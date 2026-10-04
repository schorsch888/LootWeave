//! Rust owns child startup, readiness, health, instance ownership and shutdown.
use serde_json::{json, Value};
use sha2::{Digest, Sha256};
use std::collections::{BTreeMap, BTreeSet};
use std::fs::{File, OpenOptions};
use std::io::{BufRead, BufReader, Read, Write};
use std::net::{SocketAddr, TcpStream};
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::{mpsc, Arc, Condvar, Mutex};
use std::time::{Duration, Instant};

#[cfg(windows)]
use std::os::windows::{fs::OpenOptionsExt, io::AsRawHandle, process::CommandExt};

#[cfg(windows)]
struct Job(windows_sys::Win32::Foundation::HANDLE);
// Windows kernel handles can safely be transferred; the owning runtime closes it once.
#[cfg(windows)]
unsafe impl Send for Job {}

#[cfg(windows)]
impl Job {
    fn create() -> Result<Self, &'static str> {
        use windows_sys::Win32::System::JobObjects::*;
        unsafe {
            let handle = CreateJobObjectW(std::ptr::null(), std::ptr::null());
            if handle.is_null() {
                return Err("job_creation_failed");
            }
            let job = Self(handle);
            let mut info: JOBOBJECT_EXTENDED_LIMIT_INFORMATION = std::mem::zeroed();
            info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;
            if SetInformationJobObject(
                handle,
                JobObjectExtendedLimitInformation,
                &info as *const _ as *const _,
                std::mem::size_of_val(&info) as u32,
            ) == 0
            {
                return Err("job_configuration_failed");
            }
            Ok(job)
        }
    }
    fn assign(&self, child: &Child) -> Result<(), &'static str> {
        use windows_sys::Win32::System::JobObjects::AssignProcessToJobObject;
        if unsafe { AssignProcessToJobObject(self.0, child.as_raw_handle() as _) } == 0 {
            return Err("job_assignment_failed");
        }
        Ok(())
    }
}
#[cfg(windows)]
impl Drop for Job {
    fn drop(&mut self) {
        unsafe {
            windows_sys::Win32::Foundation::CloseHandle(self.0);
        }
    }
}

const SERVICES: [&str; 5] = ["profile", "knowledge", "evaluation", "planning", "ocr"];
const START_TIMEOUT: Duration = Duration::from_secs(8);
const CONTROL_LINE_LIMIT: usize = 4096;
type OwnedChild = Arc<Mutex<Child>>;

#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub enum StartupPolicy {
    #[default]
    Eager,
    OnDemand,
}
impl StartupPolicy {
    pub fn parse(value: &str) -> Result<Self, &'static str> {
        match value {
            "eager" => Ok(Self::Eager),
            "on-demand" => Ok(Self::OnDemand),
            _ => Err("invalid_startup_policy"),
        }
    }
    fn name(self) -> &'static str {
        match self {
            Self::Eager => "eager",
            Self::OnDemand => "on-demand",
        }
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
enum ServiceState {
    Dormant,
    Starting,
    Ready,
    Failed,
    Stopping,
}
impl ServiceState {
    fn name(self) -> &'static str {
        match self {
            Self::Dormant => "dormant",
            Self::Starting => "starting",
            Self::Ready => "ready",
            Self::Failed => "failed",
            Self::Stopping => "stopping",
        }
    }
}

struct ServiceEntry {
    state: ServiceState,
    generation: u64,
    url: Option<String>,
    child: Option<OwnedChild>,
    child_generation: u64,
    dependencies: BTreeMap<String, u64>,
    error: Option<&'static str>,
    historical_only: bool,
    waiters: Vec<mpsc::Sender<Result<Value, &'static str>>>,
}
impl ServiceEntry {
    fn dormant() -> Self {
        Self {
            state: ServiceState::Dormant,
            generation: 0,
            url: None,
            child: None,
            child_generation: 0,
            dependencies: BTreeMap::new(),
            error: None,
            historical_only: false,
            waiters: Vec::new(),
        }
    }
    fn ready(&self, name: &str) -> Value {
        json!({"service": name, "state": "ready", "url": self.url, "generation": self.generation})
    }
    fn resolve(&mut self, result: Result<Value, &'static str>) {
        for waiter in self.waiters.drain(..) {
            let _ = waiter.send(result.clone());
        }
    }
    fn fail(&mut self, error: &'static str) {
        self.state = ServiceState::Failed;
        self.url = None;
        self.historical_only = false;
        self.error = Some(error);
        self.resolve(Err(error));
    }
}

struct Registry {
    services: BTreeMap<String, ServiceEntry>,
    stopping: bool,
    stopped: bool,
    // *_ready_ms top-level values are elapsed since owner creation.
    // service_ready_ms holds each successful attempt's elapsed duration;
    // service_spawn_ms holds process creation, job assignment and boot permit.
    timings: BTreeMap<String, Value>,
    #[cfg(windows)]
    job: Option<Job>,
}
impl Registry {
    fn ready_generation(&self, name: &str, generation: u64) -> bool {
        let entry = &self.services[name];
        entry.state == ServiceState::Ready
            && entry.generation == generation
            && entry
                .child
                .as_ref()
                .map(|child| {
                    entry.child_generation == generation
                        && matches!(child.lock().unwrap().try_wait(), Ok(None))
                })
                .unwrap_or(true)
    }

    fn dependencies_ready(&self, name: &str) -> bool {
        self.services[name]
            .dependencies
            .iter()
            .all(|(dependency, generation)| self.ready_generation(dependency, *generation))
    }

    fn pin_dependencies(
        &mut self,
        name: &str,
        dependencies: &BTreeMap<&str, Value>,
    ) -> Result<(), &'static str> {
        for (dependency, ready) in dependencies {
            let entry = &self.services[*dependency];
            if !ready["generation"]
                .as_u64()
                .is_some_and(|generation| self.ready_generation(dependency, generation))
                || entry.url.as_deref() != ready["url"].as_str()
            {
                return Err("service_dependency_unavailable");
            }
        }
        self.services.get_mut(name).unwrap().dependencies = dependencies
            .iter()
            .map(|(dependency, ready)| {
                (
                    dependency.to_string(),
                    ready["generation"].as_u64().unwrap(),
                )
            })
            .collect();
        Ok(())
    }

    fn invalidate_dependencies(&mut self) -> Vec<OwnedChild> {
        let invalid: Vec<_> = self
            .services
            .iter()
            .filter_map(|(name, entry)| {
                (matches!(entry.state, ServiceState::Ready | ServiceState::Starting)
                    && !self.dependencies_ready(name))
                .then(|| name.clone())
            })
            .collect();
        let mut children = Vec::new();
        for name in invalid {
            let entry = self.services.get_mut(&name).unwrap();
            let retain_history = name == "evaluation"
                && entry.state == ServiceState::Ready
                && entry.url.is_some()
                && entry.child_generation == entry.generation
                && entry
                    .child
                    .as_ref()
                    .is_some_and(|child| matches!(child.lock().unwrap().try_wait(), Ok(None)));
            if retain_history {
                // Frozen records use Evaluation's own storage and remain usable
                // without current Profile/Knowledge. Gateway restricts this URL
                // to exact frozen-history/replay routes while core stays failed.
                entry.state = ServiceState::Failed;
                entry.error = Some("service_dependency_unavailable");
                entry.historical_only = true;
                entry.resolve(Err("service_dependency_unavailable"));
                continue;
            }
            entry.fail("service_dependency_unavailable");
            if let Some(child) = entry.child.clone() {
                children.push(child);
            }
        }
        children
    }

    fn publish(&mut self, name: &str, generation: u64, url: String) -> bool {
        let dependencies_ready = self.dependencies_ready(name);
        let entry = self.services.get_mut(name).unwrap();
        if self.stopping || entry.state != ServiceState::Starting || entry.generation != generation
        {
            return false;
        }
        if !dependencies_ready {
            entry.fail("service_dependency_unavailable");
            return false;
        }
        entry.state = ServiceState::Ready;
        entry.url = Some(url);
        entry.error = None;
        entry.historical_only = false;
        entry.resolve(Ok(entry.ready(name)));
        true
    }
}

/// Readiness/dependency waits release the registry lock. Shared child handles
/// keep failed attempts and retries visible to shutdown until they are reaped.
struct Owner {
    registry: Mutex<Registry>,
    changed: Condvar,
    executable: PathBuf,
    data: PathBuf,
    token: String,
    policy: StartupPolicy,
    started: Instant,
    _lock: File,
    control_in_flight: AtomicUsize,
}

pub struct Supervisor {
    owner: Arc<Owner>,
}
impl Supervisor {
    pub fn start(
        resources: &Path,
        data: &Path,
        policy: StartupPolicy,
    ) -> Result<Self, &'static str> {
        let started = Instant::now();
        std::fs::create_dir_all(data).map_err(|_| "data_directory_unavailable")?;
        let mut options = OpenOptions::new();
        options.read(true).write(true).create(true).truncate(false);
        #[cfg(windows)]
        options.share_mode(0);
        let lock = options
            .open(data.join("instance.lock"))
            .map_err(|_| "instance_already_running")?;
        let executable = resources.join(if cfg!(windows) {
            "lootweave-sidecar.exe"
        } else {
            "lootweave-sidecar"
        });
        if !executable.is_file() {
            return Err("packaged_runtime_missing");
        }
        let verification = Instant::now();
        verify_bundle(resources)?;
        let verification_ms = verification.elapsed().as_secs_f64() * 1000.0;
        let mut bytes = [0u8; 32];
        getrandom::fill(&mut bytes).map_err(|_| "session_entropy_unavailable")?;
        let token = bytes.iter().map(|b| format!("{b:02x}")).collect();
        let services = SERVICES
            .into_iter()
            .chain(["gateway"])
            .map(|name| (name.to_string(), ServiceEntry::dormant()))
            .collect();
        let owner = Arc::new(Owner {
            registry: Mutex::new(Registry {
                services,
                stopping: false,
                stopped: false,
                timings: BTreeMap::from([
                    ("bundle_verification_ms".into(), json!(verification_ms)),
                    ("service_ready_ms".into(), json!({})),
                    ("service_spawn_ms".into(), json!({})),
                    ("service_init_ms".into(), json!({})),
                ]),
                #[cfg(windows)]
                job: Some(Job::create()?),
            }),
            changed: Condvar::new(),
            executable,
            data: data.to_path_buf(),
            token,
            policy,
            started,
            _lock: lock,
            control_in_flight: AtomicUsize::new(0),
        });
        let runtime = Self {
            owner: owner.clone(),
        };
        owner.monitor();
        if policy == StartupPolicy::Eager {
            // Preserve the prior sequential full-start cohort for A/B control.
            for name in SERVICES {
                owner.ensure(name, false, Instant::now() + START_TIMEOUT)?;
            }
        }
        owner.ensure("gateway", false, Instant::now() + START_TIMEOUT)?;
        owner.registry.lock().unwrap().timings.insert(
            "shell_ready_ms".into(),
            json!(started.elapsed().as_secs_f64() * 1000.0),
        );
        if policy == StartupPolicy::OnDemand {
            for name in ["profile", "knowledge", "evaluation"] {
                let owner = owner.clone();
                std::thread::spawn(move || {
                    // Core background phases have their own worker deadlines;
                    // each explicit gateway ensure has one overall 8s deadline.
                    if name == "evaluation" {
                        for dependency in ["profile", "knowledge"] {
                            if owner
                                .ensure(dependency, false, Instant::now() + START_TIMEOUT)
                                .is_err()
                            {
                                owner.fail_dependency(name);
                                return;
                            }
                        }
                    }
                    let _ = owner.ensure(name, false, Instant::now() + START_TIMEOUT);
                });
            }
        }
        Ok(runtime)
    }
    pub fn authorized(&self, token: &str) -> bool {
        let a = token.as_bytes();
        let b = self.owner.token.as_bytes();
        a.len() == b.len()
            && a.iter()
                .zip(b)
                .fold(0u8, |difference, (x, y)| difference | (x ^ y))
                == 0
    }
    pub fn window_url(&self) -> String {
        let registry = self.owner.registry.lock().unwrap();
        format!(
            "{}/#session={}",
            registry.services["gateway"].url.as_ref().unwrap(),
            self.owner.token
        )
    }
    pub fn readiness(&self) -> Value {
        let registry = self.owner.registry.lock().unwrap();
        json!({"url": registry.services["gateway"].url, "token": self.owner.token,
            "pids": registry.services.values().filter_map(|entry| entry.child.as_ref().map(|child| child.lock().unwrap().id())).collect::<Vec<_>>(),
            "startup_policy": self.owner.policy.name(), "timings": registry.timings})
    }
    pub fn stop(&mut self) {
        self.owner.stop();
    }
}
impl Drop for Supervisor {
    fn drop(&mut self) {
        self.stop();
    }
}

impl Owner {
    fn fail_dependency(&self, name: &str) {
        let mut registry = self.registry.lock().unwrap();
        let entry = registry.services.get_mut(name).unwrap();
        if entry.state == ServiceState::Dormant {
            entry.state = ServiceState::Failed;
            entry.error = Some("service_dependency_unavailable");
            self.changed.notify_all();
        }
    }

    fn ensure(
        self: &Arc<Self>,
        name: &str,
        retry_failed: bool,
        deadline: Instant,
    ) -> Result<Value, &'static str> {
        self.refresh();
        let (generation, previous, outcome) = {
            let mut registry = self.registry.lock().unwrap();
            if registry.stopping {
                return Err("runtime_stopping");
            }
            let entry = registry
                .services
                .get_mut(name)
                .ok_or("unsupported_service")?;
            match entry.state {
                ServiceState::Ready => return Ok(entry.ready(name)),
                ServiceState::Failed if !retry_failed => {
                    return Err(entry.error.unwrap_or("service_failed"))
                }
                ServiceState::Dormant | ServiceState::Failed => {
                    if Instant::now() >= deadline {
                        return Err("service_start_timeout");
                    }
                    entry.state = ServiceState::Starting;
                    entry.generation += 1;
                    entry.url = None;
                    entry.error = None;
                    entry.historical_only = false;
                    entry.dependencies.clear();
                    let (sender, receiver) = mpsc::channel();
                    entry.waiters.push(sender);
                    (entry.generation, entry.child.clone(), receiver)
                }
                ServiceState::Stopping => return Err("runtime_stopping"),
                ServiceState::Starting => {
                    let remaining = deadline.saturating_duration_since(Instant::now());
                    if remaining.is_zero() {
                        return Err("service_start_timeout");
                    }
                    let (sender, receiver) = mpsc::channel();
                    entry.waiters.push(sender);
                    self.changed.notify_all();
                    drop(registry);
                    // An outcome belongs to this attempt even if a new explicit
                    // retry advances the registry before this caller resumes.
                    return receiver
                        .recv_timeout(remaining)
                        .map_err(|_| "service_start_timeout")?;
                }
            }
        };
        if let Some(child) = previous {
            reap(&child);
        }
        let attempt = Instant::now();
        let result = self.launch(name, generation, retry_failed, deadline);
        let mut registry = self.registry.lock().unwrap();
        match result {
            Ok((url, startup_timings)) => {
                let expired = Instant::now() >= deadline;
                if expired || !registry.publish(name, generation, url) {
                    let entry = registry.services.get_mut(name).unwrap();
                    if entry.generation == generation && entry.state == ServiceState::Starting {
                        entry.fail("service_start_timeout");
                    }
                    let child = if entry.generation == generation {
                        entry.child.clone()
                    } else {
                        None
                    };
                    self.changed.notify_all();
                    drop(registry);
                    if let Some(child) = child {
                        reap(&child);
                    }
                    return outcome.try_recv().unwrap_or(Err(if expired {
                        "service_start_timeout"
                    } else {
                        "service_start_superseded"
                    }));
                }
                registry.timings.get_mut("service_ready_ms").unwrap()[name] =
                    json!(attempt.elapsed().as_secs_f64() * 1000.0);
                registry.timings.get_mut("service_init_ms").unwrap()[name] = startup_timings;
                if name == "gateway" {
                    registry.timings.insert(
                        "gateway_ready_ms".into(),
                        json!(self.started.elapsed().as_secs_f64() * 1000.0),
                    );
                }
                if ["gateway", "profile", "knowledge", "evaluation"]
                    .iter()
                    .all(|name| registry.services[*name].state == ServiceState::Ready)
                    && !registry.timings.contains_key("core_ready_ms")
                {
                    registry.timings.insert(
                        "core_ready_ms".into(),
                        json!(self.started.elapsed().as_secs_f64() * 1000.0),
                    );
                }
                self.changed.notify_all();
                Ok(registry.services[name].ready(name))
            }
            Err(error) => {
                let entry = registry.services.get_mut(name).unwrap();
                let child =
                    if entry.generation == generation && entry.state != ServiceState::Stopping {
                        if entry.state != ServiceState::Failed {
                            entry.fail(error);
                        }
                        entry.child.clone()
                    } else {
                        None
                    };
                self.changed.notify_all();
                drop(registry);
                if let Some(child) = child {
                    reap(&child);
                }
                outcome.try_recv().unwrap_or(Err(error))
            }
        }
    }

    fn launch(
        self: &Arc<Self>,
        name: &str,
        generation: u64,
        retry_failed: bool,
        deadline: Instant,
    ) -> Result<(String, Value), &'static str> {
        let mut dependencies = BTreeMap::new();
        if name == "evaluation" {
            dependencies.insert("profile", self.ensure("profile", retry_failed, deadline)?);
        }
        if name == "evaluation" || name == "planning" {
            dependencies.insert(
                "knowledge",
                self.ensure("knowledge", retry_failed, deadline)?,
            );
        }
        let mut command = Command::new(&self.executable);
        command
            .env("LOOTWEAVE_SESSION_TOKEN", &self.token)
            .env("PYTHONUTF8", "1")
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::null());
        if name == "gateway" {
            let registry = self.registry.lock().unwrap();
            let urls: BTreeMap<_, _> = registry
                .services
                .iter()
                .filter_map(|(name, entry)| {
                    entry.url.as_ref().map(|url| (name.clone(), url.clone()))
                })
                .collect();
            command
                .arg("--gateway")
                .arg("--parent-stdio")
                .env("LOOTWEAVE_OWNER_STDIO", "1")
                .env("LOOTWEAVE_STARTUP_POLICY", self.policy.name())
                .env(
                    "LOOTWEAVE_SERVICE_URLS",
                    serde_json::to_string(&urls).unwrap(),
                );
        } else {
            #[cfg(windows)]
            command.env("LOOTWEAVE_PARENT_JOB", "1");
            command
                .args(["--service", name, "--parent-stdio", "--data-dir"])
                .arg(&self.data);
            if let Some(knowledge) = dependencies.get("knowledge") {
                command.args(["--knowledge-url", knowledge["url"].as_str().unwrap()]);
            }
            if let Some(profile) = dependencies.get("profile") {
                command.args(["--profile-url", profile["url"].as_str().unwrap()]);
            }
        }
        #[cfg(windows)]
        command.creation_flags(0x08000000); // CREATE_NO_WINDOW
        let (stdout, gateway_stdin) = {
            // Process creation/job assignment/publication are atomic with stop.
            let mut registry = self.registry.lock().unwrap();
            if registry.stopping
                || registry.services[name].generation != generation
                || registry.services[name].state != ServiceState::Starting
            {
                return Err("runtime_stopping");
            }
            if Instant::now() >= deadline {
                return Err("service_start_timeout");
            }
            registry.pin_dependencies(name, &dependencies)?;
            let spawning = Instant::now();
            let mut child = command.spawn().map_err(|_| "service_spawn_failed")?;
            #[cfg(windows)]
            if let Err(error) = registry
                .job
                .as_ref()
                .ok_or("runtime_stopping")?
                .assign(&child)
            {
                let _ = child.kill();
                let _ = child.wait();
                return Err(error);
            }
            #[cfg(windows)]
            if name != "gateway" {
                if let Err(error) = permit_service_boot(&mut child) {
                    let _ = child.kill();
                    let _ = child.wait();
                    return Err(error);
                }
            }
            let Some(stdout) = child.stdout.take() else {
                let _ = child.kill();
                let _ = child.wait();
                return Err("readiness_pipe_unavailable");
            };
            let stdin = if name == "gateway" {
                child.stdin.take()
            } else {
                None
            };
            registry.services.get_mut(name).unwrap().child = Some(Arc::new(Mutex::new(child)));
            registry.services.get_mut(name).unwrap().child_generation = generation;
            registry.timings.get_mut("service_spawn_ms").unwrap()[name] =
                json!(spawning.elapsed().as_secs_f64() * 1000.0);
            (stdout, stdin)
        };
        let (sender, receiver) = mpsc::channel();
        if name == "gateway" {
            let stdin = gateway_stdin.ok_or("readiness_pipe_unavailable")?;
            let (responses, incoming) = mpsc::sync_channel::<Value>(16);
            let weak = Arc::downgrade(self);
            std::thread::spawn(move || {
                let mut stdin = stdin;
                loop {
                    let Some(owner) = weak.upgrade() else {
                        break;
                    };
                    if owner.registry.lock().unwrap().stopping {
                        break;
                    }
                    drop(owner);
                    match incoming.recv_timeout(Duration::from_millis(20)) {
                        Ok(response) => {
                            let Ok(line) = serde_json::to_vec(&response) else {
                                break;
                            };
                            if line.len() + 1 > CONTROL_LINE_LIMIT
                                || stdin.write_all(&line).is_err()
                                || stdin.write_all(b"\n").is_err()
                                || stdin.flush().is_err()
                            {
                                break;
                            }
                        }
                        Err(mpsc::RecvTimeoutError::Timeout) => {}
                        Err(mpsc::RecvTimeoutError::Disconnected) => break,
                    }
                }
            });
            let weak = Arc::downgrade(self);
            std::thread::spawn(move || {
                let mut reader = BufReader::new(stdout);
                let first = bounded_line(&mut reader);
                let valid = first.is_ok();
                let _ = sender.send(first);
                if valid {
                    while let Ok(line) = bounded_line(&mut reader) {
                        let Some(owner) = weak.upgrade() else {
                            break;
                        };
                        if owner.registry.lock().unwrap().stopping {
                            break;
                        }
                        owner.control(&line, &responses);
                    }
                }
                if let Some(owner) = weak.upgrade() {
                    owner.stop();
                }
            });
        } else {
            std::thread::spawn(move || {
                let _ = sender.send(bounded_line(&mut BufReader::new(stdout)));
            });
        }
        let line = receiver
            .recv_timeout(deadline.saturating_duration_since(Instant::now()))
            .map_err(|_| "service_start_timeout")??;
        let ready: Value = serde_json::from_slice(&line).map_err(|_| "service_readiness_failed")?;
        validate_ready_contract(&ready, name)?;
        let url = ready["url"]
            .as_str()
            .ok_or("service_url_missing")?
            .to_string();
        loopback_address(&url)?;
        if name != "gateway" {
            health(&url, &self.token, name, deadline)?;
        }
        if Instant::now() >= deadline {
            return Err("service_start_timeout");
        }
        Ok((url, startup_timings(&ready)))
    }

    fn status(&self) -> Value {
        self.refresh();
        let registry = self.registry.lock().unwrap();
        let services: BTreeMap<_, _> = SERVICES
            .into_iter()
            .chain(["gateway"])
            .map(|name| {
                let entry = &registry.services[name];
                let mut value =
                    json!({"state": entry.state.name(), "generation": entry.generation});
                if entry.state == ServiceState::Ready || entry.historical_only {
                    value["url"] = json!(entry.url);
                    value["pid"] =
                        json!(entry.child.as_ref().map(|child| child.lock().unwrap().id()));
                }
                if entry.historical_only {
                    value["historical_only"] = json!(true);
                }
                (name, value)
            })
            .collect();
        let core_ready = ["gateway", "profile", "knowledge", "evaluation"]
            .iter()
            .all(|name| registry.services[*name].state == ServiceState::Ready);
        json!({"services": services, "core_ready": core_ready,
            "startup_policy": self.policy.name(), "timings": registry.timings})
    }

    fn control(self: &Arc<Self>, line: &[u8], responses: &mpsc::SyncSender<Value>) {
        let Ok(request) = serde_json::from_slice::<Value>(line) else {
            return;
        };
        let Some(id) = request["id"].as_str().filter(|id| {
            !id.is_empty()
                && id.len() <= 128
                && id
                    .bytes()
                    .all(|b| b.is_ascii_alphanumeric() || b == b'-' || b == b'_')
        }) else {
            return;
        };
        let id = id.to_string();
        let error = |code| json!({"control_version": 1, "id": id, "error": code});
        if request["control_version"] != 1 {
            let _ = responses.try_send(error("incompatible_owner_control"));
            return;
        }
        match request["operation"].as_str() {
            Some("status") => {
                let _ = responses
                    .try_send(json!({"control_version": 1, "id": id, "result": self.status()}));
            }
            Some("ensure") => {
                let Some(service) = request["service"]
                    .as_str()
                    .filter(|name| SERVICES.contains(name))
                else {
                    let _ = responses.try_send(error("unsupported_service"));
                    return;
                };
                if self.control_in_flight.fetch_add(1, Ordering::Relaxed) >= 16 {
                    self.control_in_flight.fetch_sub(1, Ordering::Relaxed);
                    let _ = responses.try_send(error("owner_busy"));
                    return;
                }
                let service = service.to_string();
                let owner = self.clone();
                let responses = responses.clone();
                let deadline = Instant::now() + START_TIMEOUT;
                std::thread::spawn(move || {
                    let response = match owner.ensure(&service, true, deadline) {
                        Ok(result) => json!({"control_version": 1, "id": id, "result": result}),
                        Err(error) => json!({"control_version": 1, "id": id, "error": error}),
                    };
                    let _ = responses.try_send(response);
                    owner.control_in_flight.fetch_sub(1, Ordering::Relaxed);
                });
            }
            _ => {
                let _ = responses.try_send(error("unsupported_owner_operation"));
            }
        }
    }

    fn refresh(&self) -> bool {
        let mut registry = self.registry.lock().unwrap();
        if registry.stopping {
            return false;
        }
        for entry in registry.services.values_mut() {
            if (matches!(entry.state, ServiceState::Ready | ServiceState::Starting)
                || entry.historical_only)
                && entry.child_generation == entry.generation
                && entry
                    .child
                    .as_ref()
                    .is_some_and(|child| !matches!(child.lock().unwrap().try_wait(), Ok(None)))
            {
                entry.fail("service_exited");
            }
        }
        let children = registry.invalidate_dependencies();
        let gateway_failed = registry.services["gateway"].state == ServiceState::Failed;
        self.changed.notify_all();
        drop(registry);
        for child in children {
            reap(&child);
        }
        gateway_failed
    }

    fn monitor(self: &Arc<Self>) {
        let weak = Arc::downgrade(self);
        std::thread::spawn(move || loop {
            std::thread::sleep(Duration::from_millis(100));
            let Some(owner) = weak.upgrade() else {
                break;
            };
            if owner.registry.lock().unwrap().stopping {
                break;
            }
            if owner.refresh() {
                owner.stop();
                break;
            }
        });
    }

    fn stop(&self) {
        let mut registry = self.registry.lock().unwrap();
        if registry.stopping {
            while !registry.stopped {
                registry = self.changed.wait(registry).unwrap();
            }
            return;
        }
        registry.stopping = true;
        let mut children = Vec::new();
        for entry in registry.services.values_mut() {
            entry.state = ServiceState::Stopping;
            entry.url = None;
            entry.historical_only = false;
            entry.resolve(Err("runtime_stopping"));
            if let Some(child) = entry.child.clone() {
                child.lock().unwrap().stdin.take();
                children.push(child);
            }
        }
        self.changed.notify_all();
        drop(registry);
        let deadline = Instant::now() + Duration::from_secs(4);
        for child in &children {
            while matches!(child.lock().unwrap().try_wait(), Ok(None)) && Instant::now() < deadline
            {
                std::thread::sleep(Duration::from_millis(20));
            }
            if matches!(child.lock().unwrap().try_wait(), Ok(None)) {
                let _ = child.lock().unwrap().kill();
            }
        }
        #[cfg(windows)]
        self.registry.lock().unwrap().job.take();
        for child in &children {
            let _ = child.lock().unwrap().wait();
        }
        let mut registry = self.registry.lock().unwrap();
        for entry in registry.services.values_mut() {
            entry.child = None;
        }
        registry.stopped = true;
        self.changed.notify_all();
    }
}

fn reap(child: &OwnedChild) {
    let mut child = child.lock().unwrap();
    let _ = child.kill();
    let _ = child.wait();
}

/// Carry only declared finite durations from the worker, never arbitrary data.
fn startup_timings(ready: &Value) -> Value {
    let mut timings = json!({});
    for key in ["app_init_ms", "capability_discovery_ms"] {
        if let Some(duration) = ready["startup_timings"][key]
            .as_f64()
            .filter(|duration| duration.is_finite() && *duration >= 0.0)
        {
            timings[key] = json!(duration);
        }
    }
    timings
}

fn validate_ready_contract(ready: &Value, name: &str) -> Result<(), &'static str> {
    if ready["service"] != name || ready["contract_version"].as_u64() != Some(1) {
        return Err("incompatible_service");
    }
    if name == "gateway" && ready["control_version"].as_u64() != Some(1) {
        return Err("incompatible_owner_control");
    }
    Ok(())
}

/// Each readiness/control frame has its own byte bound and mandatory newline.
fn bounded_line(reader: &mut impl BufRead) -> Result<Vec<u8>, &'static str> {
    let mut line = Vec::new();
    loop {
        let buffer = reader.fill_buf().map_err(|_| "service_readiness_failed")?;
        if buffer.is_empty() {
            return Err("owner_control_eof");
        }
        let length = buffer
            .iter()
            .position(|byte| *byte == b'\n')
            .map(|position| position + 1)
            .unwrap_or(buffer.len());
        if line.len() + length > CONTROL_LINE_LIMIT {
            return Err("owner_control_line_too_large");
        }
        let finished = buffer[length - 1] == b'\n';
        line.extend_from_slice(&buffer[..length]);
        reader.consume(length);
        if finished {
            return Ok(line);
        }
    }
}

#[cfg(windows)]
fn permit_service_boot(child: &mut Child) -> Result<(), &'static str> {
    child
        .stdin
        .as_mut()
        .ok_or("parent_job_pipe_unavailable")?
        .write_all(b"1")
        .map_err(|_| "parent_job_handshake_failed")
}

/// Maintenance uses the same verified private bundle and preserves the single entry point.
pub fn maintenance(
    resources: &Path,
    data: &Path,
    operation: &str,
    other: &Path,
) -> Result<(), &'static str> {
    verify_bundle(resources)?;
    let mut command = Command::new(resources.join("lootweave-sidecar.exe"));
    command
        .args(["--maintenance", operation])
        .env("PYTHONUTF8", "1")
        .env_remove("LOOTWEAVE_SESSION_TOKEN")
        .stdin(Stdio::null());
    match operation {
        "backup" => {
            command
                .arg("--data-dir")
                .arg(data)
                .arg("--destination")
                .arg(other);
        }
        "restore" => {
            command
                .arg("--backup-dir")
                .arg(other)
                .arg("--destination")
                .arg(data);
        }
        _ => return Err("invalid_maintenance_operation"),
    }
    #[cfg(windows)]
    command.creation_flags(0x08000000);
    #[cfg(windows)]
    let job = Job::create()?;
    let mut child = command.spawn().map_err(|_| "maintenance_spawn_failed")?;
    #[cfg(windows)]
    if let Err(error) = job.assign(&child) {
        let _ = child.kill();
        let _ = child.wait();
        return Err(error);
    }
    let status = child.wait().map_err(|_| "maintenance_wait_failed")?;
    if status.success() {
        Ok(())
    } else {
        Err("maintenance_failed")
    }
}

#[derive(serde::Deserialize)]
struct BundleManifest {
    format_version: u32,
    publisher: String,
    platform: String,
    files: BTreeMap<String, String>,
}

/// Detect corruption and missing/unlisted runtime files before executing workers.
/// This check does not authenticate the publisher; release signing is separate.
fn verify_bundle(root: &Path) -> Result<(), &'static str> {
    let manifest_path = root.join("bundle-manifest.json");
    let metadata =
        std::fs::symlink_metadata(&manifest_path).map_err(|_| "bundle_manifest_missing")?;
    if !metadata.is_file() || metadata.file_type().is_symlink() || metadata.len() > 2 * 1024 * 1024
    {
        return Err("invalid_bundle_manifest");
    }
    let raw = std::fs::read(manifest_path).map_err(|_| "bundle_manifest_missing")?;
    let manifest: BundleManifest =
        serde_json::from_slice(&raw).map_err(|_| "invalid_bundle_manifest")?;
    if manifest.format_version != 1
        || manifest.publisher != "lootweave-build"
        || manifest.platform != "windows-x64"
        || manifest.files.is_empty()
        || manifest.files.len() > 10000
    {
        return Err("invalid_bundle_manifest");
    }
    let mut actual = BTreeSet::new();
    fn walk(
        base: &Path,
        directory: &Path,
        actual: &mut BTreeSet<String>,
    ) -> Result<(), &'static str> {
        for entry in std::fs::read_dir(directory).map_err(|_| "bundle_integrity_failed")? {
            let path = entry.map_err(|_| "bundle_integrity_failed")?.path();
            let metadata =
                std::fs::symlink_metadata(&path).map_err(|_| "bundle_integrity_failed")?;
            if metadata.file_type().is_symlink() {
                return Err("bundle_integrity_failed");
            }
            if metadata.is_dir() {
                walk(base, &path, actual)?;
            } else if metadata.is_file() {
                let relative = path
                    .strip_prefix(base)
                    .map_err(|_| "bundle_integrity_failed")?
                    .to_str()
                    .ok_or("bundle_integrity_failed")?
                    .replace('\\', "/");
                if relative != "bundle-manifest.json" {
                    actual.insert(relative);
                }
            } else {
                return Err("bundle_integrity_failed");
            }
        }
        Ok(())
    }
    walk(root, root, &mut actual)?;
    if actual != manifest.files.keys().cloned().collect::<BTreeSet<_>>() {
        return Err("bundle_integrity_failed");
    }
    for (name, expected) in manifest.files {
        if name.contains('\\')
            || name.contains(':')
            || name
                .split('/')
                .any(|part| part.is_empty() || part == "." || part == "..")
            || expected.len() != 64
            || !expected.bytes().all(|b| b.is_ascii_hexdigit())
        {
            return Err("invalid_bundle_manifest");
        }
        let path = Path::new(&name);
        if path.is_absolute() {
            return Err("invalid_bundle_manifest");
        }
        let mut file = File::open(root.join(path)).map_err(|_| "bundle_integrity_failed")?;
        let mut hash = Sha256::new();
        let mut buffer = [0u8; 65536];
        loop {
            let read = file
                .read(&mut buffer)
                .map_err(|_| "bundle_integrity_failed")?;
            if read == 0 {
                break;
            }
            hash.update(&buffer[..read]);
        }
        if format!("{:x}", hash.finalize()) != expected {
            return Err("bundle_integrity_failed");
        }
    }
    Ok(())
}

fn loopback_address(url: &str) -> Result<SocketAddr, &'static str> {
    let address = url
        .strip_prefix("http://")
        .ok_or("loopback_url_required")?
        .parse::<SocketAddr>()
        .map_err(|_| "loopback_url_required")?;
    if address.ip().to_string() != "127.0.0.1" || address.port() == 0 {
        return Err("loopback_url_required");
    }
    Ok(address)
}

fn health(url: &str, token: &str, service: &str, deadline: Instant) -> Result<(), &'static str> {
    let address = loopback_address(url)?;
    let timeout = deadline
        .saturating_duration_since(Instant::now())
        .min(Duration::from_secs(1));
    if timeout.is_zero() {
        return Err("service_start_timeout");
    }
    let mut stream =
        TcpStream::connect_timeout(&address, timeout).map_err(|_| "service_health_failed")?;
    stream
        .set_read_timeout(Some(timeout))
        .map_err(|_| "service_health_failed")?;
    stream
        .set_write_timeout(Some(timeout))
        .map_err(|_| "service_health_failed")?;
    write!(
        stream,
        "GET /v1/health HTTP/1.0\r\nHost: {address}\r\nAuthorization: Bearer {token}\r\n\r\n"
    )
    .map_err(|_| "service_health_failed")?;
    let mut response = Vec::new();
    let mut buffer = [0u8; 4096];
    loop {
        let remaining = deadline
            .saturating_duration_since(Instant::now())
            .min(Duration::from_secs(1));
        if remaining.is_zero() {
            return Err("service_start_timeout");
        }
        stream
            .set_read_timeout(Some(remaining))
            .map_err(|_| "service_health_failed")?;
        let read = stream
            .read(&mut buffer)
            .map_err(|_| "service_health_failed")?;
        if read == 0 {
            break;
        }
        if response.len() + read > 65536 {
            return Err("service_health_failed");
        }
        response.extend_from_slice(&buffer[..read]);
    }
    let response = String::from_utf8(response).map_err(|_| "service_health_failed")?;
    if !response.starts_with("HTTP/1.0 200") && !response.starts_with("HTTP/1.1 200") {
        return Err("service_health_failed");
    }
    let body = response
        .split_once("\r\n\r\n")
        .ok_or("service_health_failed")?
        .1;
    let result: Value = serde_json::from_str(body).map_err(|_| "service_health_failed")?;
    if result["service"] != service || result["contract_version"] != 1 {
        return Err("incompatible_service");
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    fn owner() -> Arc<Owner> {
        Arc::new(Owner {
            registry: Mutex::new(Registry {
                services: SERVICES
                    .into_iter()
                    .chain(["gateway"])
                    .map(|name| (name.into(), ServiceEntry::dormant()))
                    .collect(),
                stopping: false,
                stopped: false,
                timings: BTreeMap::from([
                    ("service_ready_ms".into(), json!({})),
                    ("service_spawn_ms".into(), json!({})),
                    ("service_init_ms".into(), json!({})),
                ]),
                #[cfg(windows)]
                job: Some(Job::create().unwrap()),
            }),
            changed: Condvar::new(),
            executable: std::env::temp_dir().join("lootweave-nonexistent-test-runtime.exe"),
            data: std::env::temp_dir(),
            token: "test-private-session-token".into(),
            policy: StartupPolicy::OnDemand,
            started: Instant::now(),
            _lock: File::open(std::env::current_exe().unwrap()).unwrap(),
            control_in_flight: AtomicUsize::new(0),
        })
    }

    #[test]
    fn control_lines_are_independently_bounded_and_require_newlines() {
        let mut reader = BufReader::with_capacity(2, &b"one\ntwo\n"[..]);
        assert_eq!(bounded_line(&mut reader).unwrap(), b"one\n");
        assert_eq!(bounded_line(&mut reader).unwrap(), b"two\n");
        assert_eq!(bounded_line(&mut reader), Err("owner_control_eof"));
        assert_eq!(bounded_line(&mut &b"partial"[..]), Err("owner_control_eof"));
        let mut exact = vec![b'x'; CONTROL_LINE_LIMIT - 1];
        exact.push(b'\n');
        assert_eq!(
            bounded_line(&mut exact.as_slice()).unwrap().len(),
            CONTROL_LINE_LIMIT
        );
        exact.insert(0, b'x');
        assert_eq!(
            bounded_line(&mut exact.as_slice()),
            Err("owner_control_line_too_large")
        );
    }

    #[test]
    fn status_does_not_start_services_or_expose_session_credentials() {
        let owner = owner();
        let status = owner.status();
        for name in SERVICES.into_iter().chain(["gateway"]) {
            assert_eq!(status["services"][name]["state"], "dormant");
            assert_eq!(status["services"][name]["generation"], 0);
            assert!(status["services"][name].get("url").is_none());
        }
        assert_eq!(status["core_ready"], false);
        assert_eq!(status["startup_policy"], "on-demand");
        assert!(!status.to_string().contains(&owner.token));
        owner.stop();
    }

    #[test]
    fn stale_and_post_close_readiness_cannot_publish() {
        let owner = owner();
        let mut registry = owner.registry.lock().unwrap();
        let entry = registry.services.get_mut("ocr").unwrap();
        entry.state = ServiceState::Starting;
        entry.generation = 2;
        assert!(!registry.publish("ocr", 1, "http://127.0.0.1:1234".into()));
        assert!(registry.services["ocr"].url.is_none());
        registry.stopping = true;
        assert!(!registry.publish("ocr", 2, "http://127.0.0.1:1234".into()));
        registry.stopping = false;
        assert!(registry.publish("ocr", 2, "http://127.0.0.1:1234".into()));
        drop(registry);
        owner.stop();
        assert_eq!(
            owner.ensure("ocr", true, Instant::now() + START_TIMEOUT),
            Err("runtime_stopping")
        );
    }

    #[test]
    fn concurrent_ensures_join_the_same_generation() {
        let owner = owner();
        {
            let mut registry = owner.registry.lock().unwrap();
            let entry = registry.services.get_mut("ocr").unwrap();
            entry.state = ServiceState::Starting;
            entry.generation = 7;
        }
        let barrier = Arc::new(std::sync::Barrier::new(9));
        let callers: Vec<_> = (0..8)
            .map(|_| {
                let owner = owner.clone();
                let barrier = barrier.clone();
                std::thread::spawn(move || {
                    barrier.wait();
                    owner.ensure("ocr", true, Instant::now() + START_TIMEOUT)
                })
            })
            .collect();
        barrier.wait();
        {
            let mut registry = owner.registry.lock().unwrap();
            assert!(registry.publish("ocr", 7, "http://127.0.0.1:1234".into()));
            owner.changed.notify_all();
        }
        for caller in callers {
            let result = caller.join().unwrap().unwrap();
            assert_eq!(result["generation"], 7);
            assert_eq!(result["url"], "http://127.0.0.1:1234");
        }
        assert_eq!(owner.status()["services"]["ocr"]["generation"], 7);
        owner.stop();
    }

    #[test]
    fn callers_joining_a_failed_attempt_do_not_retry_it() {
        let owner = owner();
        {
            let mut registry = owner.registry.lock().unwrap();
            let entry = registry.services.get_mut("ocr").unwrap();
            entry.state = ServiceState::Starting;
            entry.generation = 7;
        }
        let callers: Vec<_> = (0..8)
            .map(|_| {
                let owner = owner.clone();
                std::thread::spawn(move || {
                    owner.ensure("ocr", true, Instant::now() + START_TIMEOUT)
                })
            })
            .collect();
        {
            let deadline = Instant::now() + Duration::from_secs(2);
            let mut registry = owner.registry.lock().unwrap();
            while registry.services["ocr"].waiters.len() != 8 {
                let (next, timeout) = owner
                    .changed
                    .wait_timeout(registry, deadline.saturating_duration_since(Instant::now()))
                    .unwrap();
                registry = next;
                assert!(
                    !timeout.timed_out(),
                    "callers failed to join the startup generation"
                );
            }
            let entry = registry.services.get_mut("ocr").unwrap();
            entry.fail("test_failure");
            // A later explicit retry can win the registry before joiners wake.
            entry.state = ServiceState::Starting;
            entry.generation = 8;
            assert!(registry.publish("ocr", 8, "http://127.0.0.1:4321".into()));
            owner.changed.notify_all();
        }
        for caller in callers {
            assert_eq!(caller.join().unwrap(), Err("test_failure"));
        }
        assert_eq!(owner.status()["services"]["ocr"]["generation"], 8);
        owner.stop();
    }

    #[cfg(windows)]
    #[test]
    fn close_reclaims_a_child_still_starting_and_rejects_new_starts() {
        let owner = owner();
        let executable = PathBuf::from(std::env::var_os("WINDIR").unwrap())
            .join("System32/WindowsPowerShell/v1.0/powershell.exe");
        let child = Command::new(executable)
            .args([
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                "$pipe=[Console]::OpenStandardInput(); while ($pipe.ReadByte() -ne -1) {}; exit 0",
            ])
            .creation_flags(0x08000000)
            .stdin(Stdio::piped())
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .spawn()
            .unwrap();
        {
            let mut registry = owner.registry.lock().unwrap();
            registry.job.as_ref().unwrap().assign(&child).unwrap();
            let entry = registry.services.get_mut("ocr").unwrap();
            entry.state = ServiceState::Starting;
            entry.generation = 1;
            entry.child_generation = 1;
            entry.child = Some(Arc::new(Mutex::new(child)));
        }
        let caller_owner = owner.clone();
        let caller = std::thread::spawn(move || {
            caller_owner.ensure("ocr", true, Instant::now() + START_TIMEOUT)
        });
        let closed = Instant::now();
        owner.stop();
        assert_eq!(caller.join().unwrap(), Err("runtime_stopping"));
        assert!(closed.elapsed() < Duration::from_secs(3));
        assert!(owner.registry.lock().unwrap().services["ocr"]
            .child
            .is_none());
        assert_eq!(
            owner.ensure("planning", true, Instant::now() + START_TIMEOUT),
            Err("runtime_stopping")
        );
    }

    #[test]
    fn expired_attempts_and_failed_status_never_start_implicitly() {
        let owner = owner();
        assert_eq!(
            owner.ensure("ocr", true, Instant::now()),
            Err("service_start_timeout")
        );
        assert_eq!(owner.status()["services"]["ocr"]["generation"], 0);
        {
            let mut registry = owner.registry.lock().unwrap();
            let entry = registry.services.get_mut("ocr").unwrap();
            entry.state = ServiceState::Failed;
            entry.error = Some("test_failure");
            entry.generation = 1;
        }
        assert_eq!(
            owner.ensure("ocr", false, Instant::now() + START_TIMEOUT),
            Err("test_failure")
        );
        assert_eq!(owner.status()["services"]["ocr"]["generation"], 1);
        assert_eq!(
            owner.ensure("ocr", true, Instant::now() + START_TIMEOUT),
            Err("service_spawn_failed")
        );
        assert_eq!(owner.status()["services"]["ocr"]["generation"], 2);
        owner.stop();
    }

    #[test]
    fn owner_control_rejects_unknown_versions_operations_and_services() {
        let owner = owner();
        let (sender, receiver) = mpsc::sync_channel(16);
        for (request, error) in [
            (
                json!({"control_version": 2, "id": "v", "operation": "status"}),
                "incompatible_owner_control",
            ),
            (
                json!({"control_version": 1, "id": "o", "operation": "launch"}),
                "unsupported_owner_operation",
            ),
            (
                json!({"control_version": 1, "id": "s", "operation": "ensure", "service": "../external"}),
                "unsupported_service",
            ),
            (
                json!({"control_version": 1, "id": "g", "operation": "ensure", "service": "gateway"}),
                "unsupported_service",
            ),
        ] {
            owner.control(&serde_json::to_vec(&request).unwrap(), &sender);
            assert_eq!(
                receiver.recv_timeout(Duration::from_secs(1)).unwrap()["error"],
                error
            );
        }
        owner.control(
            b"{\"control_version\":1,\"id\":\"bad\\nid\",\"operation\":\"status\"}",
            &sender,
        );
        assert!(receiver.try_recv().is_err());
        owner.control(
            b"{\"control_version\":1,\"id\":\"status_1\",\"operation\":\"status\"}",
            &sender,
        );
        let status = receiver.recv_timeout(Duration::from_secs(1)).unwrap();
        assert_eq!(status["result"]["services"]["ocr"]["state"], "dormant");
        owner.stop();
    }

    #[test]
    fn startup_policy_defaults_eager_and_is_allowlisted() {
        assert_eq!(StartupPolicy::default(), StartupPolicy::Eager);
        assert_eq!(StartupPolicy::parse("eager"), Ok(StartupPolicy::Eager));
        assert_eq!(
            StartupPolicy::parse("on-demand"),
            Ok(StartupPolicy::OnDemand)
        );
        assert_eq!(
            StartupPolicy::parse("external"),
            Err("invalid_startup_policy")
        );
    }

    fn fixture_ready(owner: &Arc<Owner>, name: &str, generation: u64, port: u16) {
        let mut registry = owner.registry.lock().unwrap();
        let entry = registry.services.get_mut(name).unwrap();
        entry.state = ServiceState::Starting;
        entry.generation = generation;
        assert!(registry.publish(name, generation, format!("http://127.0.0.1:{port}")));
    }

    #[test]
    fn dependency_recovery_requires_current_generations_and_preserves_dormant_optionals() {
        let owner = owner();
        for (name, port) in [("profile", 1201), ("knowledge", 1202), ("gateway", 1203)] {
            fixture_ready(&owner, name, 1, port);
        }
        {
            let mut registry = owner.registry.lock().unwrap();
            registry
                .services
                .get_mut("evaluation")
                .unwrap()
                .dependencies = BTreeMap::from([("profile".into(), 1), ("knowledge".into(), 1)]);
            registry.services.get_mut("planning").unwrap().dependencies =
                BTreeMap::from([("knowledge".into(), 1)]);
        }
        fixture_ready(&owner, "evaluation", 1, 1204);
        fixture_ready(&owner, "planning", 1, 1205);
        {
            let mut registry = owner.registry.lock().unwrap();
            registry
                .services
                .get_mut("profile")
                .unwrap()
                .fail("service_exited");
        }
        let status = owner.status();
        assert_eq!(status["services"]["evaluation"]["state"], "failed");
        assert_eq!(status["services"]["planning"]["state"], "ready");
        assert_eq!(status["services"]["ocr"]["state"], "dormant");
        assert_eq!(status["core_ready"], false);
        fixture_ready(&owner, "profile", 2, 1211);
        assert_eq!(
            owner.ensure("evaluation", false, Instant::now() + START_TIMEOUT),
            Err("service_dependency_unavailable")
        );
        // Retry resolves the new URLs/generations before attempting process creation.
        assert_eq!(
            owner.ensure("evaluation", true, Instant::now() + START_TIMEOUT),
            Err("service_spawn_failed")
        );
        {
            let mut registry = owner.registry.lock().unwrap();
            let entry = &registry.services["evaluation"];
            assert_eq!(entry.generation, 2);
            assert_eq!(
                entry.dependencies,
                BTreeMap::from([("profile".into(), 2), ("knowledge".into(), 1)])
            );
            // Model the new validated readiness result independently of a real sidecar.
            registry.services.get_mut("evaluation").unwrap().state = ServiceState::Starting;
            assert!(registry.publish("evaluation", 2, "http://127.0.0.1:1214".into()));
        }
        assert_eq!(owner.status()["core_ready"], true);
        fixture_ready(&owner, "knowledge", 2, 1222);
        let status = owner.status();
        for name in ["evaluation", "planning"] {
            assert_eq!(status["services"][name]["state"], "failed");
            assert!(status["services"][name].get("url").is_none());
        }
        owner.stop();
    }

    #[test]
    fn changed_dependency_during_start_resolves_joiners_and_blocks_late_publication() {
        for failed in [false, true] {
            let owner = owner();
            fixture_ready(&owner, "profile", 1, 1201);
            fixture_ready(&owner, "knowledge", 1, 1202);
            let (sender, receiver) = mpsc::channel();
            {
                let mut registry = owner.registry.lock().unwrap();
                let entry = registry.services.get_mut("evaluation").unwrap();
                entry.state = ServiceState::Starting;
                entry.generation = 3;
                entry.dependencies =
                    BTreeMap::from([("profile".into(), 1), ("knowledge".into(), 1)]);
                entry.waiters.push(sender);
                let dependency = registry.services.get_mut("knowledge").unwrap();
                if failed {
                    dependency.fail("service_exited");
                } else {
                    dependency.generation = 2;
                }
                registry.invalidate_dependencies();
                assert!(!registry.publish("evaluation", 3, "http://127.0.0.1:1204".into()));
            }
            assert_eq!(
                receiver.recv_timeout(Duration::from_secs(1)).unwrap(),
                Err("service_dependency_unavailable")
            );
            assert_eq!(owner.status()["services"]["planning"]["state"], "dormant");
            owner.stop();
        }
    }

    #[test]
    fn dependencies_must_still_match_before_process_creation_or_publication() {
        let owner = owner();
        fixture_ready(&owner, "knowledge", 1, 1202);
        let old = owner.registry.lock().unwrap().services["knowledge"].ready("knowledge");
        fixture_ready(&owner, "knowledge", 2, 1212);
        let mut registry = owner.registry.lock().unwrap();
        assert_eq!(
            registry.pin_dependencies("planning", &BTreeMap::from([("knowledge", old)])),
            Err("service_dependency_unavailable")
        );
        let entry = registry.services.get_mut("planning").unwrap();
        entry.state = ServiceState::Starting;
        entry.generation = 1;
        entry.dependencies = BTreeMap::from([("knowledge".into(), 1)]);
        assert!(!registry.publish("planning", 1, "http://127.0.0.1:1205".into()));
        assert_eq!(
            registry.services["planning"].error,
            Some("service_dependency_unavailable")
        );
        drop(registry);
        owner.stop();
    }

    #[test]
    fn gateway_readiness_requires_matching_control_version() {
        let mut ready = json!({"service": "gateway", "contract_version": 1});
        assert_eq!(
            validate_ready_contract(&ready, "gateway"),
            Err("incompatible_owner_control")
        );
        ready["control_version"] = json!(2);
        assert_eq!(
            validate_ready_contract(&ready, "gateway"),
            Err("incompatible_owner_control")
        );
        ready["control_version"] = json!(1);
        assert_eq!(validate_ready_contract(&ready, "gateway"), Ok(()));
        assert_eq!(
            validate_ready_contract(
                &json!({"service": "profile", "contract_version": 1}),
                "profile"
            ),
            Ok(())
        );
    }

    #[cfg(windows)]
    #[test]
    fn core_exit_preserves_ready_history_and_reclaims_starting_dependents() {
        for state in [ServiceState::Ready, ServiceState::Starting] {
            let owner = owner();
            fixture_ready(&owner, "knowledge", 1, 1202);
            let executable = PathBuf::from(std::env::var_os("WINDIR").unwrap())
                .join("System32/WindowsPowerShell/v1.0/powershell.exe");
            let mut children = Vec::new();
            for name in ["profile", "evaluation"] {
                let child = Command::new(&executable).args([
                    "-NoProfile", "-NonInteractive", "-Command",
                    "$pipe=[Console]::OpenStandardInput(); while ($pipe.ReadByte() -ne -1) {}; exit 0",
                ]).creation_flags(0x08000000).stdin(Stdio::piped())
                    .stdout(Stdio::null()).stderr(Stdio::null()).spawn().unwrap();
                let mut registry = owner.registry.lock().unwrap();
                registry.job.as_ref().unwrap().assign(&child).unwrap();
                let entry = registry.services.get_mut(name).unwrap();
                entry.state = if name == "profile" {
                    ServiceState::Ready
                } else {
                    state
                };
                entry.generation = 1;
                entry.child_generation = 1;
                entry.url =
                    (entry.state == ServiceState::Ready).then(|| "http://127.0.0.1:1204".into());
                let child = Arc::new(Mutex::new(child));
                entry.child = Some(child.clone());
                if name == "evaluation" {
                    entry.dependencies =
                        BTreeMap::from([("profile".into(), 1), ("knowledge".into(), 1)]);
                }
                children.push(child);
            }
            let (sender, receiver) = mpsc::channel();
            owner
                .registry
                .lock()
                .unwrap()
                .services
                .get_mut("evaluation")
                .unwrap()
                .waiters
                .push(sender);
            reap(&children[0]);
            let status = owner.status();
            assert_eq!(status["services"]["evaluation"]["state"], "failed");
            assert_eq!(
                receiver.recv_timeout(Duration::from_secs(1)).unwrap(),
                Err("service_dependency_unavailable")
            );
            if state == ServiceState::Ready {
                assert!(matches!(children[1].lock().unwrap().try_wait(), Ok(None)));
                assert_eq!(status["services"]["evaluation"]["historical_only"], true);
                assert_eq!(
                    status["services"]["evaluation"]["url"],
                    "http://127.0.0.1:1204"
                );
            } else {
                assert!(matches!(
                    children[1].lock().unwrap().try_wait(),
                    Ok(Some(_))
                ));
                assert!(status["services"]["evaluation"].get("url").is_none());
                assert!(status["services"]["evaluation"]
                    .get("historical_only")
                    .is_none());
            }
            assert_eq!(status["services"]["planning"]["state"], "dormant");
            assert!(owner.registry.lock().unwrap().services["evaluation"]
                .child
                .is_some());
            owner.stop();
            assert!(matches!(
                children[1].lock().unwrap().try_wait(),
                Ok(Some(_))
            ));
        }
    }

    #[cfg(windows)]
    #[test]
    #[ignore = "Synthetic HTTP child fixture; invoked by retained-history lifecycle tests."]
    fn historical_evaluation_child_fixture() {
        if std::env::var_os("LOOTWEAVE_HISTORY_FIXTURE").as_deref()
            != Some(std::ffi::OsStr::new("1"))
        {
            return;
        }
        let mut permit = [0u8; 1];
        std::io::stdin().read_exact(&mut permit).unwrap();
        assert_eq!(permit, *b"1");
        let token = std::env::var("LOOTWEAVE_HISTORY_FIXTURE_TOKEN").unwrap();
        let listener = std::net::TcpListener::bind("127.0.0.1:0").unwrap();
        println!(
            "\nLOOTWEAVE_HISTORY_URL=http://{}",
            listener.local_addr().unwrap()
        );
        std::io::stdout().flush().unwrap();
        std::thread::spawn(|| {
            let _ = std::io::stdin().read_to_end(&mut Vec::new());
            std::process::exit(0);
        });
        for stream in listener.incoming() {
            let mut stream = stream.unwrap();
            stream
                .set_read_timeout(Some(Duration::from_secs(1)))
                .unwrap();
            let mut reader = BufReader::new(&mut stream);
            let mut request = String::new();
            reader.read_line(&mut request).unwrap();
            let mut authorized = false;
            let mut length = 0;
            loop {
                let mut line = String::new();
                reader.read_line(&mut line).unwrap();
                if line == "\r\n" || line.is_empty() {
                    break;
                }
                authorized |= line.trim() == format!("Authorization: Bearer {token}");
                if let Some(value) = line.strip_prefix("Content-Length:") {
                    length = value.trim().parse::<usize>().unwrap();
                }
            }
            assert!(length <= 1024);
            reader.read_exact(&mut vec![0u8; length]).unwrap();
            drop(reader);
            let parts: Vec<_> = request.split_whitespace().collect();
            let (status, result) = if !authorized {
                (401, json!({"error": "unauthorized"}))
            } else {
                match (parts[0], parts[1]) {
                    ("GET", "/v1/health") => {
                        (200, json!({"service": "evaluation", "contract_version": 1}))
                    }
                    ("GET", "/v1/evaluations") => {
                        (200, json!({"evaluations": [{"request_id": "frozen"}]}))
                    }
                    ("GET", "/v1/evaluations/frozen") => {
                        (200, json!({"request_id": "frozen", "fixture": true}))
                    }
                    ("POST", "/v1/evaluations/frozen/replay") => {
                        (200, json!({"identical": true, "fixture": true}))
                    }
                    _ => (404, json!({"error": "not_found"})),
                }
            };
            let body = result.to_string();
            write!(stream, "HTTP/1.0 {status} Fixture\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{body}", body.len()).unwrap();
        }
    }

    #[cfg(windows)]
    fn historical_fixture(owner: &Arc<Owner>) -> (OwnedChild, String) {
        let fixture = concat!(module_path!(), "::historical_evaluation_child_fixture")
            .split_once("::")
            .unwrap()
            .1;
        let mut child = Command::new(std::env::current_exe().unwrap())
            .args([
                "--exact",
                fixture,
                "--ignored",
                "--nocapture",
                "--test-threads=1",
            ])
            .env("LOOTWEAVE_HISTORY_FIXTURE", "1")
            .env("LOOTWEAVE_HISTORY_FIXTURE_TOKEN", &owner.token)
            .creation_flags(0x08000000)
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::null())
            .spawn()
            .unwrap();
        owner
            .registry
            .lock()
            .unwrap()
            .job
            .as_ref()
            .unwrap()
            .assign(&child)
            .unwrap();
        permit_service_boot(&mut child).unwrap();
        let stdout = child.stdout.take().unwrap();
        let child = Arc::new(Mutex::new(child));
        {
            let mut registry = owner.registry.lock().unwrap();
            let entry = registry.services.get_mut("evaluation").unwrap();
            entry.state = ServiceState::Starting;
            entry.generation = 1;
            entry.child_generation = 1;
            entry.child = Some(child.clone());
            entry.dependencies = BTreeMap::from([("profile".into(), 1), ("knowledge".into(), 1)]);
        }
        let (sender, receiver) = mpsc::channel();
        std::thread::spawn(move || {
            for line in BufReader::new(stdout).lines() {
                let line = line.unwrap();
                if let Some(url) = line.strip_prefix("LOOTWEAVE_HISTORY_URL=") {
                    let _ = sender.send(url.to_string());
                    break;
                }
            }
        });
        let url = receiver.recv_timeout(Duration::from_secs(5)).unwrap();
        health(
            &url,
            &owner.token,
            "evaluation",
            Instant::now() + START_TIMEOUT,
        )
        .unwrap();
        assert!(owner
            .registry
            .lock()
            .unwrap()
            .publish("evaluation", 1, url.clone()));
        (child, url)
    }

    #[cfg(windows)]
    fn fixture_http(url: &str, token: &str, method: &str, path: &str) -> Value {
        let address = loopback_address(url).unwrap();
        let mut stream = TcpStream::connect_timeout(&address, Duration::from_secs(1)).unwrap();
        stream
            .set_read_timeout(Some(Duration::from_secs(1)))
            .unwrap();
        let body = if method == "POST" { "{}" } else { "" };
        write!(stream, "{method} {path} HTTP/1.0\r\nHost: {address}\r\nAuthorization: Bearer {token}\r\nContent-Length: {}\r\n\r\n{body}", body.len()).unwrap();
        let mut response = String::new();
        stream.take(65536).read_to_string(&mut response).unwrap();
        assert!(response.starts_with("HTTP/1.0 200"));
        serde_json::from_str(response.split_once("\r\n\r\n").unwrap().1).unwrap()
    }

    #[cfg(windows)]
    #[test]
    fn frozen_history_survives_dependency_failure_but_not_exit_retry_or_stop() {
        for dependency in ["profile", "knowledge"] {
            for action in ["stop", "retry", "exit"] {
                let owner = owner();
                fixture_ready(&owner, "profile", 1, 1201);
                fixture_ready(&owner, "knowledge", 1, 1202);
                fixture_ready(&owner, "gateway", 1, 1203);
                let (child, url) = historical_fixture(&owner);
                owner
                    .registry
                    .lock()
                    .unwrap()
                    .services
                    .get_mut(dependency)
                    .unwrap()
                    .fail("service_exited");
                let status = owner.status();
                assert_eq!(status["core_ready"], false);
                assert_eq!(status["services"]["evaluation"]["state"], "failed");
                assert_eq!(status["services"]["evaluation"]["historical_only"], true);
                assert_eq!(status["services"]["evaluation"]["url"], url);
                assert_eq!(
                    status["services"]["evaluation"]["pid"],
                    child.lock().unwrap().id()
                );
                assert_eq!(
                    fixture_http(&url, &owner.token, "GET", "/v1/evaluations")["evaluations"][0]
                        ["request_id"],
                    "frozen"
                );
                assert_eq!(
                    fixture_http(&url, &owner.token, "GET", "/v1/evaluations/frozen")["fixture"],
                    true
                );
                assert_eq!(
                    fixture_http(&url, &owner.token, "POST", "/v1/evaluations/frozen/replay")
                        ["identical"],
                    true
                );
                assert_eq!(
                    owner.ensure("evaluation", false, Instant::now() + START_TIMEOUT),
                    Err("service_dependency_unavailable")
                );
                if action == "retry" {
                    fixture_ready(&owner, dependency, 2, 1211);
                    assert_eq!(
                        owner.ensure("evaluation", true, Instant::now() + START_TIMEOUT),
                        Err("service_spawn_failed")
                    );
                    let status = owner.status();
                    assert_eq!(status["services"]["evaluation"]["generation"], 2);
                    assert!(status["services"]["evaluation"]
                        .get("historical_only")
                        .is_none());
                    assert!(status["services"]["evaluation"].get("url").is_none());
                } else if action == "exit" {
                    reap(&child);
                    let status = owner.status();
                    assert!(status["services"]["evaluation"]
                        .get("historical_only")
                        .is_none());
                    assert!(status["services"]["evaluation"].get("url").is_none());
                }
                owner.stop();
                assert!(matches!(child.lock().unwrap().try_wait(), Ok(Some(_))));
                assert!(owner.registry.lock().unwrap().services["evaluation"]
                    .child
                    .is_none());
            }
        }
    }

    #[test]
    fn worker_timing_metadata_accepts_only_declared_nonnegative_durations() {
        let ready = json!({"startup_timings": {
            "app_init_ms": 12.5, "capability_discovery_ms": 7,
            "token": "private", "path": "private", "custom_ms": 99,
        }});
        assert_eq!(
            startup_timings(&ready),
            json!({"app_init_ms": 12.5, "capability_discovery_ms": 7.0})
        );
        assert_eq!(
            startup_timings(&json!({"startup_timings": {
                "app_init_ms": -1, "capability_discovery_ms": "private"
            }})),
            json!({})
        );
        assert_eq!(startup_timings(&json!({})), json!({}));
    }

    #[cfg(windows)]
    #[test]
    fn worker_exit_invalidates_its_route_without_respawning() {
        let owner = owner();
        let executable = PathBuf::from(std::env::var_os("WINDIR").unwrap())
            .join("System32/WindowsPowerShell/v1.0/powershell.exe");
        let child = Command::new(executable)
            .args(["-NoProfile", "-NonInteractive", "-Command", "exit 0"])
            .creation_flags(0x08000000)
            .stdin(Stdio::piped())
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .spawn()
            .unwrap();
        {
            let mut registry = owner.registry.lock().unwrap();
            registry.job.as_ref().unwrap().assign(&child).unwrap();
            let entry = registry.services.get_mut("ocr").unwrap();
            entry.state = ServiceState::Ready;
            entry.generation = 4;
            entry.child_generation = 4;
            entry.url = Some("http://127.0.0.1:1234".into());
            entry.child = Some(Arc::new(Mutex::new(child)));
        }
        owner.monitor();
        {
            let deadline = Instant::now() + Duration::from_secs(3);
            let mut registry = owner.registry.lock().unwrap();
            while registry.services["ocr"].state != ServiceState::Failed {
                let (next, timeout) = owner
                    .changed
                    .wait_timeout(registry, deadline.saturating_duration_since(Instant::now()))
                    .unwrap();
                registry = next;
                assert!(!timeout.timed_out(), "worker exit was not detected");
            }
            assert!(registry.services["ocr"].url.is_none());
            assert_eq!(registry.services["ocr"].generation, 4);
        }
        assert_eq!(
            owner.ensure("ocr", false, Instant::now() + START_TIMEOUT),
            Err("service_exited")
        );
        owner.stop();
    }

    #[test]
    fn slowly_streaming_health_reply_cannot_extend_startup_deadline() {
        let listener = std::net::TcpListener::bind("127.0.0.1:0").unwrap();
        let url = format!("http://{}", listener.local_addr().unwrap());
        let server = std::thread::spawn(move || {
            let (mut stream, _) = listener.accept().unwrap();
            let mut request = [0u8; 1024];
            let _ = stream.read(&mut request);
            for _ in 0..20 {
                if stream.write_all(b"x").is_err() {
                    break;
                }
                std::thread::sleep(Duration::from_millis(10));
            }
        });
        let started = Instant::now();
        assert!(health(
            &url,
            "fixture-token",
            "ocr",
            started + Duration::from_millis(60)
        )
        .is_err());
        assert!(started.elapsed() < Duration::from_millis(250));
        server.join().unwrap();
    }

    #[test]
    fn bundle_integrity_rejects_tampering_missing_and_extra_files() {
        let mut random = [0u8; 8];
        getrandom::fill(&mut random).unwrap();
        let name = random
            .iter()
            .map(|b| format!("{b:02x}"))
            .collect::<String>();
        let root = std::env::temp_dir().join(format!("lootweave-integrity-{name}"));
        std::fs::create_dir(&root).unwrap();
        let artifact = root.join("runtime.bin");
        std::fs::write(&artifact, b"original").unwrap();
        let hash = format!("{:x}", Sha256::digest(b"original"));
        let manifest = root.join("bundle-manifest.json");
        std::fs::write(
            &manifest,
            serde_json::to_vec(&json!({
                "format_version": 1, "publisher": "lootweave-build", "platform": "windows-x64",
                "files": {"runtime.bin": hash}
            }))
            .unwrap(),
        )
        .unwrap();
        assert!(verify_bundle(&root).is_ok());
        std::fs::write(&artifact, b"changed").unwrap();
        assert_eq!(verify_bundle(&root), Err("bundle_integrity_failed"));
        std::fs::write(&artifact, b"original").unwrap();
        let extra = root.join("unlisted.dll");
        std::fs::write(&extra, b"extra").unwrap();
        assert_eq!(verify_bundle(&root), Err("bundle_integrity_failed"));
        std::fs::remove_file(&extra).unwrap();
        std::fs::remove_file(&artifact).unwrap();
        assert_eq!(verify_bundle(&root), Err("bundle_integrity_failed"));
        std::fs::remove_file(&manifest).unwrap();
        std::fs::remove_dir(&root).unwrap();
    }

    #[cfg(windows)]
    #[test]
    #[ignore = "Child-process fixture; invoked explicitly by the Job Object test."]
    fn job_boot_child_fixture() {
        if std::env::var_os("LOOTWEAVE_JOB_BOOT_FIXTURE").as_deref()
            != Some(std::ffi::OsStr::new("1"))
        {
            return;
        }
        let mut byte = [0u8; 1];
        std::io::stdin().read_exact(&mut byte).unwrap();
        assert_eq!(byte, *b"1");
        let mut stdout = std::io::stdout().lock();
        writeln!(stdout, "\nLOOTWEAVE_JOB_BOOT_BYTE={}", byte[0]).unwrap();
        stdout.flush().unwrap();
        drop(stdout);
        // Remain alive until the assigned job is closed by the parent test.
        loop {
            std::thread::park();
        }
    }

    #[cfg(windows)]
    #[test]
    fn assigned_job_releases_boot_byte_and_reclaims_child() {
        let job = Job::create().unwrap();
        // Libtest omits the crate prefix; this works in Cargo and direct rustc tests.
        let fixture = concat!(module_path!(), "::job_boot_child_fixture")
            .split_once("::")
            .unwrap()
            .1;
        let mut child = Command::new(std::env::current_exe().unwrap())
            .args([
                "--exact",
                fixture,
                "--ignored",
                "--nocapture",
                "--test-threads=1",
            ])
            .env("LOOTWEAVE_JOB_BOOT_FIXTURE", "1")
            .creation_flags(0x08000000)
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::null())
            .spawn()
            .unwrap();
        if let Err(error) = job.assign(&child) {
            let _ = child.kill();
            let _ = child.wait();
            panic!("{error}");
        }
        let stdout = child.stdout.take().unwrap();
        let (sender, receiver) = mpsc::channel();
        let reader = std::thread::spawn(move || {
            let mut reader = BufReader::new(stdout);
            let result = loop {
                let mut line = String::new();
                match reader.read_line(&mut line) {
                    Ok(0) => break Err(std::io::Error::other("boot fixture exited before marker")),
                    Ok(_) if line.trim() == "LOOTWEAVE_JOB_BOOT_BYTE=49" => break Ok(line),
                    Ok(_) => continue, // Ignore the standard Rust test-harness preamble.
                    Err(error) => break Err(error),
                }
            };
            let _ = sender.send(result);
        });
        let permit = permit_service_boot(&mut child);
        let reply = receiver.recv_timeout(Duration::from_secs(5));
        let running_before_close = matches!(child.try_wait(), Ok(None));
        let closed_at = Instant::now();
        drop(job);
        let cleanup_deadline = closed_at + Duration::from_secs(3);
        while matches!(child.try_wait(), Ok(None)) && Instant::now() < cleanup_deadline {
            std::thread::sleep(Duration::from_millis(10));
        }
        let reclaimed = matches!(child.try_wait(), Ok(Some(_)));
        if !reclaimed {
            let _ = child.kill();
        }
        child.wait().unwrap();
        let cleanup_time = closed_at.elapsed();
        reader.join().unwrap();
        assert_eq!(permit, Ok(()));
        assert_eq!(reply.unwrap().unwrap().trim(), "LOOTWEAVE_JOB_BOOT_BYTE=49");
        assert!(running_before_close);
        assert!(
            reclaimed,
            "closing the job did not reclaim the fixture child"
        );
        assert!(cleanup_time < Duration::from_secs(3));
    }

    #[cfg(windows)]
    #[test]
    fn missing_boot_pipe_is_rejected() {
        let executable = std::path::PathBuf::from(std::env::var_os("WINDIR").unwrap())
            .join("System32/WindowsPowerShell/v1.0/powershell.exe");
        let mut child = Command::new(executable)
            .args(["-NoProfile", "-NonInteractive", "-Command", "exit 0"])
            .creation_flags(0x08000000)
            .stdin(Stdio::null())
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .spawn()
            .unwrap();
        let result = permit_service_boot(&mut child);
        child.wait().unwrap();
        assert_eq!(result, Err("parent_job_pipe_unavailable"));
    }

    #[test]
    fn external_and_ambiguous_addresses_are_rejected() {
        for value in [
            "http://localhost:1234",
            "https://127.0.0.1:1234",
            "http://127.0.0.1:0",
            "http://127.0.0.1:1234/path",
            "http://192.0.2.1:1234",
        ] {
            assert!(loopback_address(value).is_err());
        }
        assert!(loopback_address("http://127.0.0.1:1234").is_ok());
    }
}

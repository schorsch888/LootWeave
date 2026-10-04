//! Rust owns child startup, readiness, health, instance ownership and shutdown.
use serde_json::{json, Value};
use sha2::{Digest, Sha256};
use std::collections::{BTreeMap, BTreeSet};
use std::fs::{File, OpenOptions};
use std::io::{BufRead, BufReader, Read, Write};
use std::net::{SocketAddr, TcpStream};
use std::path::Path;
use std::process::{Child, Command, Stdio};
use std::sync::mpsc;
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

pub struct Supervisor {
    children: Vec<Child>,
    urls: BTreeMap<String, String>,
    token: String,
    _lock: File,
    #[cfg(windows)]
    job: Option<Job>,
}

impl Supervisor {
    pub fn start(resources: &Path, data: &Path) -> Result<Self, &'static str> {
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
        verify_bundle(resources)?;
        let mut bytes = [0u8; 32];
        getrandom::fill(&mut bytes).map_err(|_| "session_entropy_unavailable")?;
        let token = bytes.iter().map(|b| format!("{b:02x}")).collect();
        let mut runtime = Self {
            children: Vec::new(),
            urls: BTreeMap::new(),
            token,
            _lock: lock,
            #[cfg(windows)]
            job: Some(Job::create()?),
        };
        for service in [
            "profile",
            "knowledge",
            "evaluation",
            "planning",
            "ocr",
            "gateway",
        ] {
            runtime.spawn(&executable, data, service)?;
        }
        Ok(runtime)
    }

    fn spawn(&mut self, executable: &Path, data: &Path, name: &str) -> Result<(), &'static str> {
        let mut command = Command::new(executable);
        command
            .env("LOOTWEAVE_SESSION_TOKEN", &self.token)
            .env("PYTHONUTF8", "1")
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::null());
        if name == "gateway" {
            command.arg("--gateway").arg("--parent-stdio").env(
                "LOOTWEAVE_SERVICE_URLS",
                serde_json::to_string(&self.urls).unwrap(),
            );
        } else {
            #[cfg(windows)]
            command.env("LOOTWEAVE_PARENT_JOB", "1");
            command
                .args(["--service", name, "--parent-stdio", "--data-dir"])
                .arg(data);
            if name == "evaluation" || name == "planning" {
                command.args(["--knowledge-url", &self.urls["knowledge"]]);
            }
            if name == "evaluation" {
                command.args(["--profile-url", &self.urls["profile"]]);
            }
        }
        #[cfg(windows)]
        command.creation_flags(0x08000000); // CREATE_NO_WINDOW
        let mut child = command.spawn().map_err(|_| "service_spawn_failed")?;
        #[cfg(windows)]
        if let Err(error) = self.job.as_ref().unwrap().assign(&child) {
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
        let stdout = child.stdout.take().ok_or("readiness_pipe_unavailable")?;
        self.children.push(child);
        let (sender, receiver) = mpsc::channel();
        std::thread::spawn(move || {
            let mut line = String::new();
            let mut reader = BufReader::new(stdout).take(4096);
            let read = reader.read_line(&mut line);
            let _ = sender.send(read.map(|_| line));
        });
        let line = receiver
            .recv_timeout(Duration::from_secs(8))
            .map_err(|_| "service_start_timeout")?
            .map_err(|_| "service_readiness_failed")?;
        let ready: Value = serde_json::from_str(&line).map_err(|_| "service_readiness_failed")?;
        if ready["service"] != name || ready["contract_version"] != 1 {
            return Err("incompatible_service");
        }
        let url = ready["url"]
            .as_str()
            .ok_or("service_url_missing")?
            .to_string();
        if name != "gateway" {
            health(&url, &self.token, name)?;
        } else {
            loopback_address(&url)?;
        }
        self.urls.insert(name.into(), url);
        Ok(())
    }

    pub fn authorized(&self, token: &str) -> bool {
        let a = token.as_bytes();
        let b = self.token.as_bytes();
        a.len() == b.len()
            && a.iter()
                .zip(b)
                .fold(0u8, |difference, (x, y)| difference | (x ^ y))
                == 0
    }
    pub fn window_url(&self) -> String {
        format!("{}/#session={}", self.urls["gateway"], self.token)
    }
    pub fn readiness(&self) -> Value {
        json!({"url": self.urls["gateway"], "token": self.token,
               "pids": self.children.iter().map(Child::id).collect::<Vec<_>>()})
    }
    pub fn stop(&mut self) {
        for child in &mut self.children {
            child.stdin.take();
        }
        let deadline = Instant::now() + Duration::from_secs(4);
        for child in &mut self.children {
            while matches!(child.try_wait(), Ok(None)) && Instant::now() < deadline {
                std::thread::sleep(Duration::from_millis(20));
            }
            if matches!(child.try_wait(), Ok(None)) {
                let _ = child.kill();
            }
        }
        #[cfg(windows)]
        self.job.take(); // Force descendant cleanup even after service/host faults.
        for child in &mut self.children {
            let _ = child.wait();
        }
        self.children.clear();
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

impl Drop for Supervisor {
    fn drop(&mut self) {
        self.stop();
    }
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

fn health(url: &str, token: &str, service: &str) -> Result<(), &'static str> {
    let address = loopback_address(url)?;
    let mut stream = TcpStream::connect_timeout(&address, Duration::from_secs(1))
        .map_err(|_| "service_health_failed")?;
    stream
        .set_read_timeout(Some(Duration::from_secs(1)))
        .map_err(|_| "service_health_failed")?;
    stream
        .set_write_timeout(Some(Duration::from_secs(1)))
        .map_err(|_| "service_health_failed")?;
    write!(
        stream,
        "GET /v1/health HTTP/1.0\r\nHost: {address}\r\nAuthorization: Bearer {token}\r\n\r\n"
    )
    .map_err(|_| "service_health_failed")?;
    let mut response = String::new();
    stream
        .take(65536)
        .read_to_string(&mut response)
        .map_err(|_| "service_health_failed")?;
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
        assert!(reclaimed, "closing the job did not reclaim the fixture child");
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

#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

#[cfg(windows)]
mod capture;
#[cfg(windows)]
mod game_window;
#[cfg(windows)]
mod portable_webview;
mod supervisor;

use std::path::PathBuf;
use std::sync::Mutex;
use tauri::Manager;

fn option(name: &str) -> Option<PathBuf> {
    let args: Vec<String> = std::env::args().collect();
    args.windows(2)
        .find(|pair| pair[0] == name)
        .map(|pair| PathBuf::from(&pair[1]))
}

// CDP is available only for an explicitly requested hidden verification window.
// Elevated WebView2 hosts ignore environment overrides, so configure its API.
fn hidden_browser_args(hidden: bool, args: &[String]) -> Result<Option<String>, &'static str> {
    let mut flags = args
        .iter()
        .enumerate()
        .filter(|(_, arg)| *arg == "--hidden-ui-debug-port");
    let Some((index, _)) = flags.next() else {
        return Ok(None);
    };
    if !hidden || flags.next().is_some() {
        return Err("hidden_ui_debug_port_invalid");
    }
    let value = args.get(index + 1).ok_or("hidden_ui_debug_port_invalid")?;
    if value.is_empty() || !value.bytes().all(|byte| byte.is_ascii_digit()) {
        return Err("hidden_ui_debug_port_invalid");
    }
    let port = value
        .parse::<u16>()
        .map_err(|_| "hidden_ui_debug_port_invalid")?;
    if port == 0 {
        return Err("hidden_ui_debug_port_invalid");
    }
    Ok(Some(format!(
        "--disable-features=msWebOOUI,msPdfOOUI,msSmartScreenProtection \
         --autoplay-policy=no-user-gesture-required \
         --remote-debugging-port={port} --remote-debugging-address=127.0.0.1"
    )))
}

#[cfg(windows)]
#[tauri::command]
fn capture_region(
    session_token: String,
    x: i32,
    y: i32,
    width: i32,
    height: i32,
    state: tauri::State<'_, Mutex<supervisor::Supervisor>>,
) -> Result<serde_json::Value, String> {
    let state = state.lock().map_err(|_| "runtime_lock_failed")?;
    if !state.authorized(&session_token) {
        return Err("unauthorized".into());
    }
    capture::region(x, y, width, height).map_err(str::to_string)
}

#[cfg(windows)]
#[tauri::command]
fn detect_deskrawl_windows(
    session_token: String,
    state: tauri::State<'_, Mutex<supervisor::Supervisor>>,
    windows: tauri::State<'_, Mutex<game_window::Bindings>>,
) -> Result<serde_json::Value, String> {
    if !state
        .lock()
        .map_err(|_| "runtime_lock_failed")?
        .authorized(&session_token)
    {
        return Err("unauthorized".into());
    }
    windows
        .lock()
        .map_err(|_| "runtime_lock_failed")?
        .detect()
        .map_err(str::to_string)
}

#[cfg(windows)]
#[tauri::command]
fn capture_deskrawl_region(
    session_token: String,
    binding_id: String,
    x: i32,
    y: i32,
    width: i32,
    height: i32,
    state: tauri::State<'_, Mutex<supervisor::Supervisor>>,
    windows: tauri::State<'_, Mutex<game_window::Bindings>>,
) -> Result<serde_json::Value, String> {
    if !state
        .lock()
        .map_err(|_| "runtime_lock_failed")?
        .authorized(&session_token)
    {
        return Err("unauthorized".into());
    }
    windows
        .lock()
        .map_err(|_| "runtime_lock_failed")?
        .capture(&binding_id, x, y, width, height)
        .map_err(str::to_string)
}

fn configure_portable_webview(
    directory: &std::path::Path,
    data: &std::path::Path,
) -> Result<(), &'static str> {
    let runtime = directory.join("webview2");
    if !runtime.join("msedgewebview2.exe").is_file() {
        return Err("portable_webview_runtime_missing");
    }
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        // Fixed WebView2 v120+ needs AppContainer read/execute access on Windows 10.
        // Limit the grants to this package's browser files; no installation is needed.
        let system = std::env::var_os("SystemRoot")
            .map(PathBuf::from)
            .ok_or("system_directory_unavailable")?;
        let result = std::process::Command::new(system.join("System32/icacls.exe"))
            .arg(&runtime)
            .args([
                "/grant",
                "*S-1-15-2-2:(OI)(CI)(RX)",
                "/grant",
                "*S-1-15-2-1:(OI)(CI)(RX)",
                "/q",
            ])
            .creation_flags(0x08000000)
            .output()
            .map_err(|_| "portable_webview_permissions_failed")?;
        if !result.status.success() {
            return Err("portable_webview_permissions_failed");
        }
    }
    // Set before Tauri creates any threads or WebView environments.
    std::env::set_var("WEBVIEW2_BROWSER_EXECUTABLE_FOLDER", runtime);
    std::env::set_var("WEBVIEW2_USER_DATA_FOLDER", data.join("webview"));
    for variable in [
        "WEBVIEW2_WAIT_FOR_SCRIPT_DEBUGGER",
        "WEBVIEW2_PIPE_FOR_SCRIPT_DEBUGGER",
        "WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS",
    ] {
        std::env::remove_var(variable);
    }
    Ok(())
}

fn main() {
    let policy = option("--startup-policy")
        .map(|value| supervisor::StartupPolicy::parse(&value.to_string_lossy()))
        .transpose()
        .unwrap_or_else(|code| {
            eprintln!("{code}");
            std::process::exit(1);
        })
        .unwrap_or_default();
    let executable_directory = std::env::current_exe()
        .expect("executable_path_unavailable")
        .parent()
        .expect("executable_directory_unavailable")
        .to_path_buf();
    let portable = executable_directory.join("portable.json").is_file();
    let resources =
        option("--resource-dir").unwrap_or_else(|| executable_directory.join("sidecar"));
    let data = option("--data-dir").unwrap_or_else(|| {
        if portable {
            return executable_directory.join("data");
        }
        let base = std::env::var_os("LOCALAPPDATA")
            .map(PathBuf::from)
            .unwrap_or_else(std::env::temp_dir);
        base.join("LootWeave")
    });
    let backup = option("--backup-to");
    let restore = option("--restore-from");
    if backup.is_some() || restore.is_some() {
        if backup.is_some() && restore.is_some() {
            eprintln!("choose_one_maintenance_operation");
            std::process::exit(1);
        }
        let (operation, other) = if let Some(destination) = backup {
            ("backup", destination)
        } else {
            ("restore", restore.unwrap())
        };
        if let Err(code) = supervisor::maintenance(&resources, &data, operation, &other) {
            eprintln!("{code}");
            std::process::exit(1);
        }
        return;
    }
    if portable {
        if let Err(code) = configure_portable_webview(&executable_directory, &data) {
            eprintln!("{code}");
            std::process::exit(1);
        }
    }
    if std::env::args().any(|value| value == "--headless") {
        match supervisor::Supervisor::start(&resources, &data, policy) {
            Ok(mut runtime) => {
                // Readiness is parent IPC, not an application log.
                println!("{}", runtime.readiness());
                use std::io::Read;
                let mut control = Vec::new();
                let _ = std::io::stdin().read_to_end(&mut control);
                runtime.stop();
            }
            Err(code) => {
                eprintln!("{code}");
                std::process::exit(1);
            }
        }
        return;
    }
    let args: Vec<String> = std::env::args().collect();
    let hidden_ui = args.iter().any(|value| value == "--hidden-ui");
    let browser_args = hidden_browser_args(hidden_ui, &args).unwrap_or_else(|code| {
        eprintln!("{code}");
        std::process::exit(1);
    });
    if hidden_ui {
        eprintln!("lootweave_hidden_ui_v1: --hidden-ui enabled");
    }
    // Tao initializes OLE when it creates a window, after setup has begun.
    // Keep our STA initialization alive until all Tauri/WebView resources are dropped.
    #[cfg(windows)]
    let _portable_com = if portable {
        Some(
            portable_webview::StaApartment::initialize().unwrap_or_else(|code| {
                eprintln!("{code}");
                std::process::exit(1);
            }),
        )
    } else {
        None
    };
    let builder = tauri::Builder::default();
    #[cfg(windows)]
    let builder = builder
        .manage(Mutex::new(game_window::Bindings::default()))
        .invoke_handler(tauri::generate_handler![
            capture_region,
            detect_deskrawl_windows,
            capture_deskrawl_region
        ]);
    let application = builder
        .setup(move |app| {
            let runtime = supervisor::Supervisor::start(&resources, &data, policy)
                .map_err(std::io::Error::other)?;
            if hidden_ui {
                eprintln!("lootweave_hidden_ui_v1: services_ready");
            }
            let url = runtime.window_url().parse()?;
            app.manage(Mutex::new(runtime));
            if hidden_ui {
                eprintln!("lootweave_hidden_ui_v1: window_build_started");
            }
            let mut window =
                tauri::WebviewWindowBuilder::new(app, "main", tauri::WebviewUrl::External(url))
                    .data_directory(data.join("webview"))
                    .title("LootWeave")
                    .visible(!hidden_ui)
                    .focused(!hidden_ui)
                    .focusable(!hidden_ui)
                    .inner_size(1250.0, 900.0)
                    .min_inner_size(700.0, 600.0);
            if let Some(ref arguments) = browser_args {
                window = window.additional_browser_args(arguments);
            }
            #[cfg(windows)]
            if portable {
                // An explicit environment also works for elevated hosts, which
                // ignore WEBVIEW2_* variables. Its options must include the flags;
                // Wry skips environment creation and its browser args in this mode.
                let environment = portable_webview::create_environment(
                    &executable_directory.join("webview2"),
                    &data.join("webview"),
                    browser_args.as_deref(),
                )
                .map_err(std::io::Error::other)?;
                window = window.with_environment(environment);
            }
            window.build()?;
            if hidden_ui {
                eprintln!("lootweave_hidden_ui_v1: webview_ready");
            }
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("desktop_startup_failed");
    application.run(|app, event| {
        if matches!(event, tauri::RunEvent::Exit) {
            if let Some(state) = app.try_state::<Mutex<supervisor::Supervisor>>() {
                if let Ok(mut runtime) = state.lock() {
                    runtime.stop();
                }
            }
        }
    });
}

#[cfg(test)]
mod hidden_probe_tests {
    use super::hidden_browser_args;
    fn arguments(values: &[&str]) -> Vec<String> {
        values.iter().map(|value| value.to_string()).collect()
    }

    #[test]
    fn ordinary_and_unconfigured_hidden_launches_do_not_enable_cdp() {
        assert_eq!(hidden_browser_args(false, &[]), Ok(None));
        assert_eq!(hidden_browser_args(true, &[]), Ok(None));
    }

    #[test]
    fn debug_port_requires_hidden_mode_and_one_valid_numeric_value() {
        assert!(
            hidden_browser_args(false, &arguments(&["--hidden-ui-debug-port", "9222"])).is_err()
        );
        for value in [
            "",
            "0",
            "-1",
            "+9222",
            "65536",
            "NaN",
            "9222 --remote-allow-origins=*",
        ] {
            assert!(
                hidden_browser_args(true, &arguments(&["--hidden-ui-debug-port", value])).is_err()
            );
        }
        assert!(hidden_browser_args(true, &arguments(&["--hidden-ui-debug-port"])).is_err());
        assert!(hidden_browser_args(
            true,
            &arguments(&[
                "--hidden-ui-debug-port",
                "9222",
                "--hidden-ui-debug-port",
                "9223"
            ])
        )
        .is_err());
    }

    #[test]
    fn valid_ports_use_fixed_loopback_flags_and_keep_wry_defaults() {
        for port in ["1", "65535"] {
            let result = hidden_browser_args(true, &arguments(&["--hidden-ui-debug-port", port]))
                .unwrap()
                .unwrap();
            assert_eq!(result, format!("--disable-features=msWebOOUI,msPdfOOUI,msSmartScreenProtection --autoplay-policy=no-user-gesture-required --remote-debugging-port={port} --remote-debugging-address=127.0.0.1"));
        }
    }
}

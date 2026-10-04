//! Passive OS metadata and foreground region capture. No game memory or input access.
use serde::Serialize;
use serde_json::{json, Value};
use std::collections::HashMap;
use windows_sys::Win32::Foundation::*;
use windows_sys::Win32::Graphics::Gdi::ClientToScreen;
use windows_sys::Win32::System::Diagnostics::ToolHelp::*;
use windows_sys::Win32::System::Threading::*;
use windows_sys::Win32::UI::WindowsAndMessaging::*;

const EXECUTABLE: &str = "Deskrawl.exe";

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize)]
struct Bounds {
    x: i32,
    y: i32,
    width: i32,
    height: i32,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
struct Identity {
    window: usize,
    pid: u32,
    created: u64,
}

#[derive(Clone, Copy, Debug)]
struct Window {
    identity: Identity,
    bounds: Option<Bounds>,
    visible: bool,
    minimized: bool,
    foreground: bool,
}

impl Window {
    fn status(&self) -> &'static str {
        if self.minimized {
            "minimized"
        } else if !self.visible {
            "hidden"
        } else if self.bounds.is_none() {
            "window_unavailable"
        } else if !self.foreground {
            "background"
        } else {
            "ready"
        }
    }
}

struct Handle(HANDLE);
impl Drop for Handle {
    fn drop(&mut self) {
        unsafe {
            CloseHandle(self.0);
        }
    }
}

fn wide_text(value: &[u16]) -> String {
    let length = value.iter().position(|c| *c == 0).unwrap_or(value.len());
    String::from_utf16_lossy(&value[..length])
}

fn process_identity(pid: u32) -> Result<u64, &'static str> {
    unsafe {
        let raw_process = OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, 0, pid);
        if raw_process.is_null() {
            return Err("game_process_unavailable");
        }
        let process = Handle(raw_process);
        let mut path = vec![0u16; 32768];
        let mut size = path.len() as u32;
        if QueryFullProcessImageNameW(process.0, 0, path.as_mut_ptr(), &mut size) == 0 {
            return Err("game_process_unavailable");
        }
        let name = wide_text(&path[..size as usize]);
        if !name
            .rsplit(['/', '\\'])
            .next()
            .unwrap_or("")
            .eq_ignore_ascii_case(EXECUTABLE)
        {
            return Err("game_process_changed");
        }
        let mut created: FILETIME = std::mem::zeroed();
        let mut exit: FILETIME = std::mem::zeroed();
        let mut kernel: FILETIME = std::mem::zeroed();
        let mut user: FILETIME = std::mem::zeroed();
        if GetProcessTimes(process.0, &mut created, &mut exit, &mut kernel, &mut user) == 0 {
            return Err("game_process_unavailable");
        }
        Ok((created.dwHighDateTime as u64) << 32 | created.dwLowDateTime as u64)
    }
}

fn processes() -> Result<Vec<u32>, &'static str> {
    unsafe {
        // Process metadata only: never request heaps, modules or process memory.
        let raw_snapshot = CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0);
        if raw_snapshot == INVALID_HANDLE_VALUE {
            return Err("game_detection_unavailable");
        }
        let snapshot = Handle(raw_snapshot);
        let mut entry: PROCESSENTRY32W = std::mem::zeroed();
        entry.dwSize = std::mem::size_of::<PROCESSENTRY32W>() as u32;
        let mut found = Vec::new();
        let mut next = Process32FirstW(snapshot.0, &mut entry);
        while next != 0 {
            if wide_text(&entry.szExeFile).eq_ignore_ascii_case(EXECUTABLE) {
                found.push(entry.th32ProcessID);
            }
            next = Process32NextW(snapshot.0, &mut entry);
        }
        if GetLastError() != ERROR_NO_MORE_FILES {
            return Err("game_detection_unavailable");
        }
        Ok(found)
    }
}

fn inspect(identity: Identity) -> Result<Window, &'static str> {
    unsafe {
        let hwnd = identity.window as HWND;
        let mut pid = 0;
        if IsWindow(hwnd) == 0 || GetWindowThreadProcessId(hwnd, &mut pid) == 0 {
            return Err("game_window_closed");
        }
        if pid != identity.pid || process_identity(pid)? != identity.created {
            return Err("game_process_changed");
        }
        let mut rectangle: RECT = std::mem::zeroed();
        let mut origin = POINT { x: 0, y: 0 };
        let bounds = if GetClientRect(hwnd, &mut rectangle) != 0
            && ClientToScreen(hwnd, &mut origin) != 0
            && rectangle.right > 0
            && rectangle.bottom > 0
        {
            Some(Bounds {
                x: origin.x,
                y: origin.y,
                width: rectangle.right,
                height: rectangle.bottom,
            })
        } else {
            None
        };
        Ok(Window {
            identity,
            bounds,
            visible: IsWindowVisible(hwnd) != 0,
            minimized: IsIconic(hwnd) != 0,
            foreground: GetForegroundWindow() == hwnd,
        })
    }
}

struct Enumeration {
    processes: HashMap<u32, u64>,
    windows: Vec<Window>,
    overflow: bool,
}

unsafe extern "system" fn enumerate_window(hwnd: HWND, parameter: LPARAM) -> i32 {
    let context = &mut *(parameter as *mut Enumeration);
    let mut pid = 0;
    if GetWindowThreadProcessId(hwnd, &mut pid) != 0 {
        if let Some(created) = context.processes.get(&pid) {
            if context.windows.len() == 32 {
                context.overflow = true;
            } else if let Ok(window) = inspect(Identity {
                window: hwnd as usize,
                pid,
                created: *created,
            }) {
                context.windows.push(window);
            }
        }
    }
    1
}

/// Bindings are scoped to the current app session, replaced on each detection.
#[derive(Default)]
pub struct Bindings {
    windows: HashMap<String, Window>,
}

impl Bindings {
    pub fn detect(&mut self) -> Result<Value, &'static str> {
        self.windows.clear();
        let candidates = processes()?;
        let mut context = Enumeration {
            processes: HashMap::new(),
            windows: Vec::new(),
            overflow: false,
        };
        let mut unavailable = 0;
        for pid in &candidates {
            match process_identity(*pid) {
                Ok(created) => {
                    context.processes.insert(*pid, created);
                }
                Err(_) => unavailable += 1,
            }
        }
        if unsafe {
            EnumWindows(
                Some(enumerate_window),
                &mut context as *mut Enumeration as LPARAM,
            )
        } == 0
            || context.overflow
        {
            return Err("game_detection_unavailable");
        }
        let mut windows = Vec::new();
        for (index, window) in context.windows.into_iter().enumerate() {
            let mut bytes = [0u8; 16];
            getrandom::fill(&mut bytes).map_err(|_| "game_detection_unavailable")?;
            let binding_id: String = bytes.iter().map(|b| format!("{b:02x}")).collect();
            windows.push(json!({
                "binding_id": binding_id, "index": index + 1,
                "status": window.status(), "client_bounds": window.bounds,
                "can_select": window.visible && !window.minimized && window.bounds.is_some()
            }));
            self.windows.insert(binding_id, window);
        }
        let status = if candidates.is_empty() {
            "not_running"
        } else if !windows.is_empty() {
            "running"
        } else if unavailable > 0 {
            "window_unavailable"
        } else {
            "no_window"
        };
        Ok(json!({
            "game_id": "deskrawl", "executable": EXECUTABLE, "status": status,
            "process_count": candidates.len(), "unavailable_processes": unavailable,
            "windows": windows, "version_verified": false
        }))
    }

    pub fn capture(
        &self,
        binding_id: &str,
        x: i32,
        y: i32,
        width: i32,
        height: i32,
    ) -> Result<Value, &'static str> {
        let bound = *self
            .windows
            .get(binding_id)
            .ok_or("game_window_binding_expired")?;
        let before = inspect(bound.identity)?;
        let client = check_window(bound, before)?;
        let relative = Bounds {
            x,
            y,
            width,
            height,
        };
        let screen = screen_region(client, relative)?;
        let mut image = crate::capture::region(screen.x, screen.y, width, height)?;
        let after = inspect(bound.identity)?;
        check_window(before, after)?;
        let captured_at = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .map_err(|_| "capture_time_unavailable")?
            .as_millis() as u64;
        image["capture_context"] = json!({
            "format_version": 1, "game_id": "deskrawl", "executable": EXECUTABLE,
            "window_binding": binding_id, "client_bounds": client, "relative_bounds": relative,
            "verification": "foreground_before_and_after", "captured_at_ms": captured_at,
            "game_version": "unknown", "game_build": "unknown"
        });
        Ok(image)
    }
}

fn check_window(bound: Window, current: Window) -> Result<Bounds, &'static str> {
    if current.identity != bound.identity {
        return Err("game_process_changed");
    }
    if current.minimized {
        return Err("game_window_minimized");
    }
    if !current.visible {
        return Err("game_window_hidden");
    }
    if !current.foreground {
        return Err("game_window_not_foreground");
    }
    let bounds = current.bounds.ok_or("game_window_unavailable")?;
    if Some(bounds) != bound.bounds {
        return Err("game_window_changed");
    }
    Ok(bounds)
}

fn screen_region(client: Bounds, relative: Bounds) -> Result<Bounds, &'static str> {
    if relative.width <= 0
        || relative.width > 1600
        || relative.height <= 0
        || relative.height > 1200
    {
        return Err("region_size_exceeded");
    }
    if relative.x < 0
        || relative.y < 0
        || relative.x as i64 + relative.width as i64 > client.width as i64
        || relative.y as i64 + relative.height as i64 > client.height as i64
    {
        return Err("region_outside_game_window");
    }
    Ok(Bounds {
        x: client
            .x
            .checked_add(relative.x)
            .ok_or("region_outside_screen")?,
        y: client
            .y
            .checked_add(relative.y)
            .ok_or("region_outside_screen")?,
        width: relative.width,
        height: relative.height,
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    fn window() -> Window {
        Window {
            identity: Identity {
                window: 1,
                pid: 2,
                created: 3,
            },
            bounds: Some(Bounds {
                x: -1200,
                y: 40,
                width: 1000,
                height: 800,
            }),
            visible: true,
            minimized: false,
            foreground: true,
        }
    }
    #[test]
    fn process_reuse_and_window_replacement_are_rejected() {
        for identity in [
            Identity {
                window: 1,
                pid: 2,
                created: 4,
            },
            Identity {
                window: 1,
                pid: 3,
                created: 3,
            },
            Identity {
                window: 2,
                pid: 2,
                created: 3,
            },
        ] {
            let mut changed = window();
            changed.identity = identity;
            assert_eq!(check_window(window(), changed), Err("game_process_changed"));
        }
    }
    #[test]
    fn hidden_minimized_and_background_windows_cannot_capture() {
        let mut changed = window();
        changed.minimized = true;
        assert_eq!(
            check_window(window(), changed),
            Err("game_window_minimized")
        );
        changed = window();
        changed.visible = false;
        assert_eq!(check_window(window(), changed), Err("game_window_hidden"));
        changed = window();
        changed.foreground = false;
        assert_eq!(
            check_window(window(), changed),
            Err("game_window_not_foreground")
        );
    }
    #[test]
    fn moved_resized_or_unavailable_window_requires_new_binding() {
        let mut changed = window();
        changed.bounds.as_mut().unwrap().x += 1;
        assert_eq!(check_window(window(), changed), Err("game_window_changed"));
        changed = window();
        changed.bounds.as_mut().unwrap().height += 1;
        assert_eq!(check_window(window(), changed), Err("game_window_changed"));
        changed = window();
        changed.bounds = None;
        assert_eq!(
            check_window(window(), changed),
            Err("game_window_unavailable")
        );
    }
    #[test]
    fn relative_coordinates_support_negative_monitor_origins_and_reject_overflow() {
        let client = window().bounds.unwrap();
        assert_eq!(
            screen_region(
                client,
                Bounds {
                    x: 10,
                    y: 20,
                    width: 100,
                    height: 50
                }
            ),
            Ok(Bounds {
                x: -1190,
                y: 60,
                width: 100,
                height: 50
            })
        );
        for relative in [
            Bounds {
                x: -1,
                y: 0,
                width: 100,
                height: 50,
            },
            Bounds {
                x: 990,
                y: 0,
                width: 100,
                height: 50,
            },
            Bounds {
                x: 0,
                y: i32::MAX,
                width: 100,
                height: 50,
            },
        ] {
            assert_eq!(
                screen_region(client, relative),
                Err("region_outside_game_window")
            );
        }
        assert_eq!(
            screen_region(
                client,
                Bounds {
                    x: 0,
                    y: 0,
                    width: 0,
                    height: 1
                }
            ),
            Err("region_size_exceeded")
        );
        assert_eq!(
            screen_region(
                Bounds {
                    x: i32::MAX,
                    ..client
                },
                Bounds {
                    x: 1,
                    y: 0,
                    width: 1,
                    height: 1
                }
            ),
            Err("region_outside_screen")
        );
    }
    #[test]
    fn invented_bindings_never_read_pixels() {
        assert_eq!(
            Bindings::default().capture("invented", 0, 0, 100, 100),
            Err("game_window_binding_expired")
        );
    }
    #[test]
    fn passive_detection_excludes_private_metadata_and_does_not_verify_version() {
        let mut bindings = Bindings::default();
        let detection = bindings.detect().expect("OS metadata query");
        assert_eq!(detection["game_id"], "deskrawl");
        assert_eq!(detection["executable"], "Deskrawl.exe");
        assert_eq!(detection["version_verified"], false);
        assert!(
            ["not_running", "running", "no_window", "window_unavailable"]
                .contains(&detection["status"].as_str().unwrap())
        );
        for window in detection["windows"].as_array().unwrap() {
            let allowed = [
                "binding_id",
                "index",
                "status",
                "client_bounds",
                "can_select",
            ];
            assert!(window
                .as_object()
                .unwrap()
                .keys()
                .all(|key| allowed.contains(&key.as_str())));
            // Zero dimensions guarantee rejection without any screen capture.
            let error = bindings
                .capture(window["binding_id"].as_str().unwrap(), 0, 0, 0, 0)
                .expect_err("invalid dimensions cannot capture");
            assert!(error.starts_with("game_") || error == "region_size_exceeded");
        }
    }
}

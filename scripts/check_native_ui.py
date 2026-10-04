"""Measure actual WebView readiness and close only the native windows this test starts."""
from __future__ import annotations

import argparse
import ctypes
from ctypes import wintypes
import hashlib
import json
import math
import os
import queue
import re
import socket
import subprocess
import threading
import time
import uuid
from pathlib import Path

from check_desktop import CheckFailed, OwnedProcess, ROOT, expect, frozen_environment, machine


def descendants(parent):
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    class Entry(ctypes.Structure):
        _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD),
                    ("th32ProcessID", wintypes.DWORD), ("th32DefaultHeapID", ctypes.c_size_t),
                    ("th32ModuleID", wintypes.DWORD), ("cntThreads", wintypes.DWORD),
                    ("th32ParentProcessID", wintypes.DWORD), ("pcPriClassBase", wintypes.LONG),
                    ("dwFlags", wintypes.DWORD), ("szExeFile", wintypes.WCHAR * 260)]
    kernel.CreateToolhelp32Snapshot.argtypes = (wintypes.DWORD, wintypes.DWORD)
    kernel.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    kernel.Process32FirstW.argtypes = (wintypes.HANDLE, ctypes.POINTER(Entry))
    kernel.Process32NextW.argtypes = (wintypes.HANDLE, ctypes.POINTER(Entry))
    kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
    snapshot = kernel.CreateToolhelp32Snapshot(2, 0)
    expect(snapshot != ctypes.c_void_p(-1).value, "process_snapshot_unavailable")
    parents = {}
    try:
        entry = Entry()
        entry.dwSize = ctypes.sizeof(entry)
        present = kernel.Process32FirstW(snapshot, ctypes.byref(entry))
        while present:
            parents[entry.th32ProcessID] = entry.th32ParentProcessID
            present = kernel.Process32NextW(snapshot, ctypes.byref(entry))
    finally:
        kernel.CloseHandle(snapshot)
    owned = {parent}
    while True:
        expanded = owned | {pid for pid, ancestor in parents.items() if ancestor in owned}
        if expanded == owned:
            return owned - {parent}
        owned = expanded


def owned_process_state(process):
    kernel = process.kernel
    kernel.GetProcessId.argtypes = (wintypes.HANDLE,)
    kernel.GetProcessId.restype = wintypes.DWORD
    kernel.QueryFullProcessImageNameW.argtypes = (wintypes.HANDLE, wintypes.DWORD,
                                               wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD))
    kernel.QueryFullProcessImageNameW.restype = wintypes.BOOL
    image = ctypes.create_unicode_buffer(32768)
    size = wintypes.DWORD(len(image))
    known = kernel.QueryFullProcessImageNameW(process.handle, 0, image, ctypes.byref(size))
    return {"pid": kernel.GetProcessId(process.handle),
            "image_basename": Path(image.value).name if known else "query_unavailable",
            "exited": process.exited()}


def record_shutdown(folder, name, states, errors=()):
    with (folder / name).open("x", encoding="utf-8", newline="\n") as stream:
        json.dump({"scope": "This run's fixed owned process handles only; no user processes.",
                   "states": states, "errors": list(errors)}, stream, indent=2)
        stream.write("\n")


def record_startup(folder, host):
    code = host.poll()
    state = "running" if code is None else "exited"
    exit_code = code if type(code) is int and -(2**31) <= code <= 2**32 - 1 else None
    try:
        with (folder / "startup.json").open("x", encoding="utf-8", newline="\n") as stream:
            json.dump({"host_state": state, "exit_code": exit_code}, stream, indent=2)
            stream.write("\n")
    except OSError:
        pass  # Diagnostics must not change startup, timeout, or cleanup behavior.


def owned_hidden_window(pid):
    user = ctypes.WinDLL("user32", use_last_error=True)
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    user.GetWindowThreadProcessId.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.DWORD))
    user.GetWindowTextW.argtypes = (wintypes.HWND, wintypes.LPWSTR, ctypes.c_int)
    user.PostMessageW.argtypes = (wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
    user.IsWindowVisible.argtypes = (wintypes.HWND,)
    user.IsWindowVisible.restype = wintypes.BOOL
    user.GetForegroundWindow.restype = wintypes.HWND
    user.EnumWindows.argtypes = (callback_type, wintypes.LPARAM)
    windows = []
    @callback_type
    def visit(window, _):
        owner = wintypes.DWORD()
        user.GetWindowThreadProcessId(window, ctypes.byref(owner))
        if owner.value == pid:
            title = ctypes.create_unicode_buffer(256)
            user.GetWindowTextW(window, title, len(title))
            if title.value == "LootWeave":
                windows.append(window)
        return True
    user.EnumWindows(visit, 0)
    expect(len(windows) == 1, "owned_native_window_not_unique")
    expect(not user.IsWindowVisible(windows[0]), "passive_window_visible")
    expect(user.GetForegroundWindow() != windows[0], "passive_window_foreground")
    return user, windows[0]


def close_window(pid):
    user, window = owned_hidden_window(pid)
    expect(bool(user.PostMessageW(window, 0x10, 0, 0)), "owned_native_close_failed")


def free_port():
    with socket.socket() as channel:
        channel.bind(("127.0.0.1", 0))
        return channel.getsockname()[1]


def run(executable, resources, node, output, index):
    folder = output / f"run-{index:02}"
    folder.mkdir()
    port = free_port()
    env = frozen_environment()
    env["WEBVIEW2_USER_DATA_FOLDER"] = str(folder / "webview-data")
    env["WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS"] = f"--remote-debugging-port={port} --remote-debugging-address=127.0.0.1"
    start = time.perf_counter()
    error_log = (folder / "native-stderr.log").open("wb")
    host_args = [str(executable), "--resource-dir", str(resources), "--data-dir", str(folder / "state"), "--hidden-ui"]
    host = subprocess.Popen(host_args,
                            cwd=executable.parent, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                            stderr=error_log, creationflags=0x08000000)
    handles = []
    probe = None
    passed = False
    try:
        command = [str(node), str(ROOT / "scripts/probe_native_ui.mjs"), "--port", str(port),
                   "--output", str(folder)]
        command.append("--passive")
        probe_environment = dict(os.environ)
        probe_environment["NO_PROXY"] = "127.0.0.1,localhost,::1"
        probe_environment["no_proxy"] = "127.0.0.1,localhost,::1"
        probe = subprocess.Popen(command, cwd=ROOT, env=probe_environment,
                                 stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                 creationflags=0x08000000)
        messages = queue.Queue()
        def read_messages():
            for line in probe.stdout:
                try:
                    messages.put(json.loads(line))
                except ValueError:
                    messages.put({"event": "invalid"})
        threading.Thread(target=read_messages, daemon=True).start()
        message = messages.get(timeout=60)
        expect(message.get("event") == "ready", "native_readiness_failed")
        seconds = time.perf_counter() - start
        ready = message
        owned_hidden_window(host.pid)
        done = messages.get(timeout=40)
        expect(done.get("event") == "complete" and done.get("passed"), "native_flow_failed")
        probe.wait(timeout=5)
        expect(probe.returncode == 0, "native_probe_exit_failed")
        handles.append(OwnedProcess(host.pid))
        for pid in descendants(host.pid):
            try:
                handles.append(OwnedProcess(pid))
            except CheckFailed:
                pass  # A short-lived utility process may already have exited.
        expect(len(handles) >= 8, "native_process_coverage_missing")
        memory = [handle.memory() for handle in handles if not handle.exited()]
        close_window(host.pid)
        host.wait(timeout=12)
        expect(host.returncode == 0, "native_window_exit_failed")
        deadline = time.monotonic() + 8
        natural_exit = all(handle.exited(max(0, deadline - time.monotonic())) for handle in handles)
        record_shutdown(folder, "natural-exit.json", [owned_process_state(handle) for handle in handles])
        expect(natural_exit, "native_descendant_remained")
        passed = True
        return {"readiness_seconds": round(seconds, 4), "webview_version": ready["webview_version"],
                "checks": [*done["checks"], "owned_window_hidden_and_nonforeground"],
                "processes_at_idle": len(memory),
                "working_set_mib": round(sum(value[0] for value in memory) / 2**20, 2),
                "private_commit_mib": round(sum(value[1] for value in memory) / 2**20, 2)}
    finally:
        record_startup(folder, host)
        if probe and probe.poll() is None:
            probe.kill()
            probe.wait(timeout=5)
        if probe:
            probe.stdout.close()
        if host.poll() is None:
            for pid in descendants(host.pid):
                try:
                    handles.append(OwnedProcess(pid))
                except CheckFailed:
                    pass
            host.kill()
            host.wait(timeout=5)
        error_log.close()
        cleanup_states, cleanup_errors = [], []
        for handle in handles:
            try:
                if not passed and not handle.exited():
                    handle.terminate()
                    handle.exited(5)
            except CheckFailed:
                cleanup_errors.append("owned_process_termination_failed")
            finally:
                cleanup_states.append(owned_process_state(handle))
                handle.close()
        record_shutdown(folder, "cleanup.json", cleanup_states, cleanup_errors)
        expect(not cleanup_errors and all(state["exited"] for state in cleanup_states),
               "owned_cleanup_failed")


SAFE_FAILURE_CODES = frozenset({
    "process_snapshot_unavailable", "owned_native_window_not_unique", "passive_window_visible",
    "passive_window_foreground", "owned_native_close_failed", "native_readiness_failed",
    "native_flow_failed", "native_probe_exit_failed", "owned_worker_handle_unavailable",
    "native_process_coverage_missing", "native_window_exit_failed", "native_descendant_remained",
    "owned_process_termination_failed", "owned_cleanup_failed", "webview_connection_timeout",
    "native_page_missing", "native_session_not_removed", "native_session_missing",
    "native_capture_authorization_failed", "native_capture_bounds_failed",
    "native_window_detection_authorization_failed", "native_window_binding_guard_failed",
    "native_window_detection_contract_failed", "native_window_detection_status_failed",
    "native_window_capture_bounds_failed", "native_browser_error", "cdp_disconnect_failed",
    "interactive_probe_disabled", "probe_arguments_required", "probe_mode_required",
    "CheckFailed", "OSError", "ValueError", "KeyError", "Empty", "TimeoutExpired",
    "Error", "TimeoutError",
})
SAFE_PROBE_STAGES = frozenset({
    "webview_connection", "native_readiness", "native_ipc", "native_game_window_binding",
})
SAFE_CONNECTION_ERRORS = frozenset({
    "connection_refused", "connection_reset", "connection_timeout", "http_unexpected_status",
    "protocol_error", "websocket_rejected", "unknown_error",
})
SAFE_ENDPOINT_STATES = frozenset({"responded", "timeout", "connection_refused", "connection_error"})
SAFE_STARTUP_CODES = frozenset({
    "resource_directory_required", "choose_one_maintenance_operation", "packaged_runtime_missing",
    "bundle_manifest_missing", "invalid_bundle_manifest", "bundle_integrity_failed",
    "session_entropy_unavailable", "job_creation_failed", "job_configuration_failed",
    "service_spawn_failed", "job_assignment_failed", "parent_job_pipe_unavailable",
    "parent_job_handshake_failed", "service_start_timeout", "service_readiness_failed",
    "incompatible_service", "service_url_missing", "service_health_failed", "loopback_url_required",
})
SAFE_PROCESS_IMAGES = (
    "lootweave-desktop.exe", "lootweave-sidecar.exe", "msedgewebview2.exe", "conhost.exe", "WerFault.exe",
)


def _startup_diagnostics(folder):
    startup = None
    try:
        value = json.loads((folder / "startup.json").read_text(encoding="utf-8"))
        if isinstance(value, dict):
            startup = value
    except (OSError, ValueError):
        pass
    log = b""
    log_available = False
    try:
        with (folder / "native-stderr.log").open("rb") as stream:
            log = stream.read(1024 * 1024)
        log_available = True
    except OSError:
        pass
    codes = [code for code in sorted(SAFE_STARTUP_CODES) if code.encode("ascii") in log]
    windows_errors = sorted({f"0x{int(match, 16):08X}"
                             for match in re.findall(rb"0x([0-9A-Fa-f]{8})", log)})[:16]
    marker = b"lootweave_hidden_ui_v1: --hidden-ui enabled" in log if log_available else None
    state = startup.get("host_state") if startup is not None else None
    exit_code = startup.get("exit_code") if startup is not None else None
    return {
        "hidden_ui_marker": "present" if marker is True else "absent" if marker is False else "unknown",
        "desktop_startup_failed": "yes" if b"desktop_startup_failed" in log else "no" if log_available else "unknown",
        "startup_codes": codes,
        "windows_errors": windows_errors,
        "host_state": state if isinstance(state, str) and state in {"running", "exited"} else "unknown",
        "exit_code": exit_code if type(exit_code) is int and -(2**31) <= exit_code <= 2**32 - 1 else None,
    }


def _cleanup_summary(folder):
    try:
        cleanup = json.loads((folder / "cleanup.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(cleanup, dict) or not isinstance(cleanup.get("states"), list):
        return None
    counts = {name: {"total": 0, "live": 0} for name in SAFE_PROCESS_IMAGES}
    counts["unknown_owned_process"] = {"total": 0, "live": 0}
    total = live = 0
    for state in cleanup["states"]:
        if not isinstance(state, dict):
            state = {}
        image = state.get("image_basename")
        name = next((item for item in SAFE_PROCESS_IMAGES
                     if isinstance(image, str) and image.casefold() == item.casefold()),
                    "unknown_owned_process")
        exited = state.get("exited")
        total += 1
        counts[name]["total"] += 1
        if exited is False:
            live += 1
            counts[name]["live"] += 1
    errors = cleanup.get("errors")
    return {"total": total, "live": live, "images": counts,
            "error_count": len(errors) if isinstance(errors, list) else 0}


def probe_failure_summary(folder):
    try:
        probe = json.loads((folder / "probe.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(probe, dict):
        return {"stage": "unknown_stage", "failure_code": "unknown_failure", "passed": None,
                "connection_error_code": "unknown", "endpoint_state": "unknown", "http_status": None}
    stage = probe.get("stage")
    failure_code = probe.get("failure_code")
    passed = probe.get("passed")
    connection_error = probe.get("connection_error_code")
    endpoint = probe.get("loopback_endpoint")
    endpoint_state = endpoint.get("state") if isinstance(endpoint, dict) else None
    http_status = endpoint.get("http_status") if isinstance(endpoint, dict) else None
    return {
        "stage": stage if isinstance(stage, str) and stage in SAFE_PROBE_STAGES else "unknown_stage",
        "failure_code": failure_code if isinstance(failure_code, str) and failure_code in SAFE_FAILURE_CODES else "unknown_failure",
        "passed": passed if type(passed) is bool else None,
        "connection_error_code": connection_error if isinstance(connection_error, str)
        and connection_error in SAFE_CONNECTION_ERRORS else "unknown",
        "endpoint_state": endpoint_state if isinstance(endpoint_state, str)
        and endpoint_state in SAFE_ENDPOINT_STATES else "unknown",
        "http_status": http_status if type(http_status) is int and 100 <= http_status <= 599 else None,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--executable", type=Path, default=ROOT / "desktop/target/debug/lootweave-desktop.exe")
    parser.add_argument("--resources", type=Path, default=ROOT / "dist/sidecar")
    parser.add_argument("--node", type=Path, default=Path("node"))
    parser.add_argument("--cycles", type=int, default=20)
    args = parser.parse_args()
    if os.name != "nt" or not 1 <= args.cycles <= 100:
        parser.error("Requires Windows and between 1 and 100 cycles.")
    try:
        executable_bytes = args.executable.read_bytes()
    except OSError:
        parser.error("Cannot read host executable.")
    if b"lootweave_hidden_ui_v1: --hidden-ui enabled" not in executable_bytes:
        parser.error("Host executable lacks the hidden-ui verification marker; rebuild the host before running this passive check.")
    output = ROOT / ".local/native-ui-check" / uuid.uuid4().hex
    output.mkdir(parents=True)
    mode = "hidden_passive"
    report = {"scope": mode + ": fresh Windows WebView profiles and Rust hosts on this developer machine.",
              "mode": mode,
              "environment": machine(), "runs": [], "passed": False,
              "host_sha256": hashlib.sha256(executable_bytes).hexdigest(),
              "bundle_manifest_sha256": hashlib.sha256((args.resources / "bundle-manifest.json").read_bytes()).hexdigest(),
              "limitations": ["Installed WebView runtime and developer OS; not a clean-machine installer test.",
                              "Each run uses a new app/WebView profile, with warm OS caches.",
                              "No input automation is performed. Hidden WebView readiness does not validate visible rendering, painting, keyboard accessibility, or visible GUI cold-start performance; visible GUI and keyboard acceptance remain for manual review.",
                              "CDP test client startup contributes to readiness timing.",
                              "Idle memory is sampled from observed host descendants; working sets may share pages.",
                              "Native capture tests reject invalid requests without reading any desktop pixels."]}
    try:
        for index in range(1, args.cycles + 1):
            run_folder = output / f"run-{index:02}"
            result = run(args.executable.resolve(), args.resources.resolve(), args.node,
                         output, index)
            report["runs"].append(result)
            print(f"Native WebView start/close: {index}/{args.cycles}", flush=True)
        report["webview_readiness_p95_seconds"] = sorted(run["readiness_seconds"] for run in report["runs"])[math.ceil(.95 * args.cycles) - 1]
        report["max_idle_working_set_mib"] = max(run["working_set_mib"] for run in report["runs"])
        report["max_idle_private_commit_mib"] = max(run["private_commit_mib"] for run in report["runs"])
        report["passed"] = True
    except (CheckFailed, OSError, ValueError, KeyError, queue.Empty, subprocess.TimeoutExpired) as error:
        report["failure_code"] = str(error) if isinstance(error, CheckFailed) else type(error).__name__
        failure_code = report["failure_code"]
        safe_code = failure_code if failure_code in SAFE_FAILURE_CODES else "unknown_failure"
        print(f"Native WebView check failed (failure_code={safe_code}).", flush=True)
        if "run_folder" in locals():
            startup = _startup_diagnostics(run_folder)
            exit_code = str(startup["exit_code"]) if startup["exit_code"] is not None else "unknown"
            startup_codes = ",".join(startup["startup_codes"]) or "none"
            windows_errors = ",".join(startup["windows_errors"]) or "none"
            print("Native startup diagnostic: "
                  f"hidden_ui_marker={startup['hidden_ui_marker']} "
                  f"desktop_startup_failed={startup['desktop_startup_failed']} "
                  f"startup_codes={startup_codes} windows_errors={windows_errors} "
                  f"host_state={startup['host_state']} exit_code={exit_code}.", flush=True)
            cleanup = _cleanup_summary(run_folder)
            if cleanup is not None:
                image_summary = " ".join(
                    f"{name}={values['total']}/{values['live']}"
                    for name, values in cleanup["images"].items())
                print("Native cleanup diagnostic: "
                      f"owned_total={cleanup['total']} owned_live={cleanup['live']} "
                      f"cleanup_errors={cleanup['error_count']} {image_summary}.", flush=True)
            probe = probe_failure_summary(run_folder)
            if probe is not None:
                passed = str(probe["passed"]).lower() if probe["passed"] is not None else "unknown"
                print("Native probe diagnostic: "
                      f"stage={probe['stage']} failure_code={probe['failure_code']} passed={passed} "
                      f"connection_error_code={probe['connection_error_code']} "
                      f"endpoint_state={probe['endpoint_state']} "
                      f"http_status={probe['http_status'] if probe['http_status'] is not None else 'unknown'}.",
                      flush=True)
    finally:
        (output / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print("Private evidence retained.", flush=True)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

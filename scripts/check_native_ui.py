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
        probe = subprocess.Popen(command, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
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
    except OSError as error:
        parser.error(f"Cannot read host executable: {error}")
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
        print("Native WebView check failed; private probe evidence retained.", flush=True)
    finally:
        (output / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print("Evidence: " + output.relative_to(ROOT).as_posix(), flush=True)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

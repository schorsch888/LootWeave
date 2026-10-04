"""Validate the actual Windows host and frozen workers, using fictional data only.

This is a developer-machine/headless lifecycle check, not a clean-machine or
full WebView cold-start acceptance claim. No session credentials enter reports.
"""
from __future__ import annotations

import argparse
from contextlib import closing
import ctypes
from ctypes import wintypes
import hashlib
import json
import math
import os
import platform
import queue
import subprocess
import threading
import time
import uuid
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import ProxyHandler, Request, build_opener

ROOT = Path(__file__).resolve().parents[1]
import sys
sys.path.insert(0, str(ROOT))
from contracts import DomainError
from storage import acquire_instance_lock
WORKERS = ("profile", "knowledge", "evaluation", "planning", "ocr", "gateway")


class CheckFailed(Exception):
    pass


def expect(condition, code):
    if not condition:
        raise CheckFailed(code)


class OwnedProcess:
    """Keep a handle to the exact child; PID reuse cannot redirect fault tests."""
    def __init__(self, pid):
        self.kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        self.kernel.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
        self.kernel.OpenProcess.restype = wintypes.HANDLE
        self.kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
        self.kernel.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
        self.kernel.WaitForSingleObject.restype = wintypes.DWORD
        self.kernel.TerminateProcess.argtypes = (wintypes.HANDLE, wintypes.UINT)
        # SYNCHRONIZE | QUERY_INFORMATION | VM_READ | TERMINATE, owned workers only.
        self.handle = self.kernel.OpenProcess(0x100000 | 0x400 | 0x10 | 1, False, pid)
        expect(bool(self.handle), "owned_worker_handle_unavailable")

    def exited(self, timeout=0):
        return self.kernel.WaitForSingleObject(self.handle, int(timeout * 1000)) == 0

    def terminate(self):
        if not self.exited():
            expect(bool(self.kernel.TerminateProcess(self.handle, 1)), "owned_worker_fault_failed")

    def memory(self):
        class Counters(ctypes.Structure):
            _fields_ = [
                ("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
                ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t),
                ("PrivateUsage", ctypes.c_size_t),
            ]
        data = Counters()
        data.cb = ctypes.sizeof(data)
        psapi = ctypes.WinDLL("psapi", use_last_error=True)
        psapi.GetProcessMemoryInfo.argtypes = (wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD)
        expect(bool(psapi.GetProcessMemoryInfo(self.handle, ctypes.byref(data), data.cb)),
               "owned_process_memory_unavailable")
        return data.WorkingSetSize, data.PrivateUsage

    def close(self):
        if self.handle:
            self.kernel.CloseHandle(self.handle)
            self.handle = None


def frozen_environment():
    # Keep OS facilities, installed OCR language packs and user WebView data usable.
    allowed = ("SystemRoot", "WINDIR", "TEMP", "TMP", "USERPROFILE", "LOCALAPPDATA",
               "APPDATA", "PROGRAMDATA", "COMSPEC", "SystemDrive", "NUMBER_OF_PROCESSORS")
    result = {key: os.environ[key] for key in allowed if key in os.environ}
    windows = Path(os.environ["SystemRoot"])
    result["PATH"] = os.pathsep.join(str(windows / path) for path in
                                  ("System32", "", "System32/WindowsPowerShell/v1.0"))
    return result


class Desktop:
    def __init__(self, executable, resources, data):
        self.workers = []
        self.host_handle = None
        self.started = time.perf_counter()
        self.process = subprocess.Popen(
            [str(executable), "--headless", "--resource-dir", str(resources), "--data-dir", str(data)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            cwd=executable.parent, env=frozen_environment(), creationflags=0x08000000,
        )
        messages = queue.Queue(maxsize=1)
        threading.Thread(target=lambda: messages.put(self.process.stdout.readline(8193)), daemon=True).start()
        try:
            try:
                line = messages.get(timeout=50)
            except queue.Empty:
                raise CheckFailed("native_readiness_timeout") from None
            expect(0 < len(line) <= 8192, "native_readiness_missing")
            try:
                ready = json.loads(line)
            except (ValueError, UnicodeError):
                raise CheckFailed("native_readiness_invalid") from None
            parsed = urlsplit(ready.get("url", ""))
            expect(parsed.scheme == "http" and parsed.hostname == "127.0.0.1" and parsed.port
                   and not parsed.path and not parsed.query and not parsed.fragment, "native_url_invalid")
            self.url, self.token = ready["url"], ready.get("token", "")
            expect(isinstance(self.token, str) and len(self.token) == 64
                   and all(c in "0123456789abcdef" for c in self.token), "native_token_invalid")
            pids = ready.get("pids")
            expect(isinstance(pids, list) and len(pids) == 6 and len(set(pids)) == 6
                   and all(type(pid) is int and pid > 0 for pid in pids), "native_worker_set_invalid")
            for pid in pids:
                self.workers.append(OwnedProcess(pid))
            self.host_handle = OwnedProcess(self.process.pid)
            self.ready_seconds = time.perf_counter() - self.started
            self.opener = build_opener(ProxyHandler({}))
            expect(not self.call("GET", "/api/status")["degraded"], "initial_service_degraded")
        except Exception:
            self.stop()
            raise

    def call(self, method, path, body=None, authenticated=True):
        payload = None if body is None else json.dumps(body, ensure_ascii=False, allow_nan=False).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if authenticated:
            headers["Authorization"] = "Bearer " + self.token
        request = Request(self.url + path, payload, headers, method=method)
        try:
            with self.opener.open(request, timeout=5) as response:
                return json.load(response)
        except HTTPError as error:
            try:
                code = json.load(error).get("error", "")
            except (ValueError, OSError):
                code = "invalid_error_response"
            self.last_error = {"status": error.code, "code": code if isinstance(code, str)
                               and all(c in "abcdefghijklmnopqrstuvwxyz_" for c in code) else "redacted",
                               "method": method, "endpoint": path.split("/")[2:4]}
            raise

    def memory(self):
        values = [handle.memory() for handle in [self.host_handle, *self.workers]]
        return {"working_set_mib": round(sum(v[0] for v in values) / 2**20, 2),
                "private_commit_mib": round(sum(v[1] for v in values) / 2**20, 2)}

    def stop(self, forced=False):
        if self.process.poll() is None:
            if forced:
                self.process.kill()
            else:
                self.process.stdin.close()
            try:
                self.process.wait(timeout=12)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=5)
        deadline = time.monotonic() + 5
        orphaned = False
        for handle in self.workers:
            if not handle.exited(max(0, deadline - time.monotonic())):
                orphaned = True
                handle.terminate()  # Only exact children created by this check.
                handle.exited(5)
            handle.close()
        self.workers = []
        if self.host_handle:
            self.host_handle.close()
            self.host_handle = None
        self.process.stdout.close()
        self.process.stderr.close()
        expect(not orphaned, "orphan_worker_after_host_exit")


def fictional_flow(app):
    try:
        app.call("GET", "/api/status", authenticated=False)
    except HTTPError as error:
        expect(error.code == 401, "unauthenticated_status_wrong_response")
    else:
        raise CheckFailed("unauthenticated_status_accepted")
    demo = app.call("GET", "/api/demo")
    app.call("POST", "/api/profile/observations",
             {"observation_id": "demo-text", "method": "text", "raw_text": "Fictional desktop check"})
    profile = app.call("POST", "/api/profile/confirmations", {
        "request_id": "desktop-confirm", "profile_id": "desktop-fixture", "observation_id": "demo-text",
        "expected_revision": 0, "player_confirmed": True, "facts": demo["facts"],
    })
    packs = app.call("GET", "/api/knowledge/packs")["packs"]
    pack = next(p for p in packs if p["execution_policy"] == "synthetic_only")
    result = app.call("POST", "/api/evaluation/evaluations", {
        "request_id": "desktop-evaluation", "profile_id": "desktop-fixture",
        "profile_revision": profile["revision"], "pack_id": pack["pack_id"],
        "pack_version": pack["version"], "pack_hash": pack["pack_hash"], "intent": demo["intent"],
    })
    expect(result["retention"] != "discard", "fictional_core_loss_hidden")
    expect(app.call("POST", "/api/evaluation/evaluations/desktop-evaluation/replay", {})["identical"],
           "frozen_replay_mismatch")


def replay(app):
    expect(app.call("POST", "/api/evaluation/evaluations/desktop-evaluation/replay", {})["identical"],
           "persisted_replay_mismatch")


def second_instance(executable, resources, data, first):
    process = subprocess.Popen(
        [str(executable), "--headless", "--resource-dir", str(resources), "--data-dir", str(data)],
        stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        cwd=executable.parent, env=frozen_environment(), creationflags=0x08000000,
    )
    try:
        stdout, stderr = process.communicate(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        process.communicate(timeout=5)
        raise CheckFailed("second_instance_timeout") from None
    expect(process.returncode != 0 and not stdout and b"instance_already_running" in stderr,
           "second_instance_not_rejected")
    expect(not first.call("GET", "/api/status")["degraded"], "second_instance_disrupted_owner")



def cross_entry_lock(data):
    try:
        with closing(acquire_instance_lock(data)):
            raise CheckFailed("developer_entry_accepted_while_native_active")
    except DomainError as error:
        expect(error.code == "instance_already_running", "cross_entry_lock_wrong_error")


def native_maintenance(executable, resources, data, flag, other, accepted=True):
    process = subprocess.run(
        [str(executable), "--resource-dir", str(resources), "--data-dir", str(data), flag, str(other)],
        cwd=executable.parent, env=frozen_environment(), stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=40, creationflags=0x08000000,
    )
    expect((process.returncode == 0) == accepted, "native_maintenance_exit_failed")
    try:
        result = json.loads(process.stdout)
    except ValueError:
        raise CheckFailed("native_maintenance_response_invalid") from None
    if accepted:
        expect(result.get("storage_version") == 1 and result.get("files", 0) >= 3,
               "native_maintenance_files_missing")
    else:
        expect(result.get("error") == "instance_already_running", "active_backup_not_rejected")
    return result


def developer_lock_blocks_native(executable, resources, data):
    with closing(acquire_instance_lock(data)):
        process = subprocess.run(
            [str(executable), "--headless", "--resource-dir", str(resources), "--data-dir", str(data)],
            cwd=executable.parent, env=frozen_environment(), stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=10, creationflags=0x08000000,
        )
        expect(process.returncode != 0 and not process.stdout and
               b"instance_already_running" in process.stderr, "native_entry_accepted_while_developer_active")


def machine():
    import winreg
    with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                       r"HARDWARE\DESCRIPTION\System\CentralProcessor\0") as key:
        processor = winreg.QueryValueEx(key, "ProcessorNameString")[0].strip()
    return {"os": platform.platform(), "cpu": processor, "logical_processors": os.cpu_count(),
            "python_required_by_test_harness_only": platform.python_version()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--executable", type=Path, default=ROOT / "desktop/target/debug/lootweave-desktop.exe")
    parser.add_argument("--resources", type=Path, default=ROOT / "dist/sidecar")
    parser.add_argument("--cycles", type=int, default=20)
    args = parser.parse_args()
    if os.name != "nt":
        parser.error("Requires the Windows native desktop host.")
    if not 2 <= args.cycles <= 100:
        parser.error("cycles must be between 2 and 100")
    executable, resources = args.executable.resolve(), args.resources.resolve()
    if not executable.is_file() or not (resources / "bundle-manifest.json").is_file():
        parser.error("Build the native host and frozen sidecar first.")
    output = ROOT / ".local/desktop-check" / uuid.uuid4().hex
    data = output / "state"
    data.mkdir(parents=True)
    report = {"scope": "Windows developer-machine Rust host with frozen workers; headless, fictional inputs.",
              "environment": machine(), "checks": [], "passed": False,
              "host_sha256": hashlib.sha256(executable.read_bytes()).hexdigest(),
              "bundle_manifest_sha256": hashlib.sha256((resources / "bundle-manifest.json").read_bytes()).hexdigest(),
              "limitations": ["Not a clean Windows installation or installer/uninstaller test.",
                              "Readiness timing and idle memory exclude the WebView GUI.",
                              "Repeated starts include warm OS filesystem caches.",
                              "Python is absent from the child's PATH, but is present on the developer machine."]}
    samples, memories = [], []
    stage = "start_exit"
    app = None
    try:
        for index in range(args.cycles):
            app = Desktop(executable, resources, data)
            samples.append(app.ready_seconds)
            if index == 0:
                fictional_flow(app)
                second_instance(executable, resources, data, app)
                cross_entry_lock(data)
                native_maintenance(executable, resources, data, "--backup-to",
                                   output / "active-backup", accepted=False)
                report["checks"] += ["frozen_services_without_python_path", "local_api_authorization",
                                     "confirmed_snapshot_and_frozen_replay", "single_instance_ownership"]
            else:
                replay(app)
            memories.append(app.memory())
            app.stop()
            expect(app.process.returncode == 0, "normal_host_exit_failed")
            app = None
            print(f"Native start/exit: {index + 1}/{args.cycles}", flush=True)
        developer_lock_blocks_native(executable, resources, data)
        report["checks"] += ["persistent_replay_across_restart", "start_exit_without_orphan_workers",
                             "developer_and_native_share_instance_ownership", "active_backup_rejected"]
        stage = "backup_restore"
        native_maintenance(executable, resources, data, "--backup-to", output / "backup")
        native_maintenance(executable, resources, output / "restored-state", "--restore-from", output / "backup")
        app = Desktop(executable, resources, output / "restored-state")
        replay(app)
        app.stop()
        app = None
        report["checks"].append("single_exe_backup_restore_preserves_frozen_replay")
        stage = "worker_faults"
        for index, name in enumerate(WORKERS):
            app = Desktop(executable, resources, data)
            app.workers[index].terminate()
            expect(app.workers[index].exited(3), "worker_fault_not_delivered")
            if name == "gateway":
                try:
                    app.call("GET", "/api/status")
                except (URLError, ConnectionError, OSError):
                    pass
                else:
                    raise CheckFailed("gateway_fault_not_observed")
            else:
                status = app.call("GET", "/api/status")
                expect(status["degraded"] and status["services"][name]["state"] == "unavailable",
                       "worker_fault_missing_degradation")
                if name in ("profile", "knowledge"):
                    replay(app)
            app.stop()
            app = None
            print(f"Native worker fault: {name}", flush=True)
        report["checks"] += ["six_worker_fault_cleanup", "source_service_fault_keeps_frozen_replay"]
        stage = "host_fault"
        app = Desktop(executable, resources, data)
        app.stop(forced=True)
        app = None
        report["checks"].append("forced_host_exit_job_cleanup")
        app = Desktop(executable, resources, data)
        replay(app)
        app.stop()
        app = None
        report["checks"].append("restart_recovery_after_faults")
        report["passed"] = True
    except (CheckFailed, OSError, ValueError, KeyError, StopIteration, subprocess.TimeoutExpired) as error:
        report["failure_stage"] = stage
        if app and isinstance(error, HTTPError):
            report["http_error"] = app.last_error
        report["failure_code"] = str(error) if isinstance(error, CheckFailed) else type(error).__name__
        print(f"Native check failed at {stage}; private state retained.", flush=True)
    finally:
        if app:
            try:
                app.stop()
            except (CheckFailed, OSError):
                report["cleanup_failed"] = True
                report["passed"] = False
        if samples:
            report["headless_readiness"] = {
                "runs": len(samples), "seconds": [round(value, 4) for value in samples],
                "p95_seconds": round(sorted(samples)[math.ceil(.95 * len(samples)) - 1], 4),
            }
        report["headless_idle_memory"] = {
            "runs": len(memories),
            "max_working_set_mib": max((m["working_set_mib"] for m in memories), default=None),
            "max_private_commit_mib": max((m["private_commit_mib"] for m in memories), default=None),
        }
        (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print("Evidence: " + output.relative_to(ROOT).as_posix(), flush=True)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

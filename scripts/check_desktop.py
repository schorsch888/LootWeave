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
import sqlite3
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
from maintenance import CAPTURE, DATABASES, ordinary, verify
from storage import acquire_instance_lock
WORKERS = ("profile", "knowledge", "evaluation", "planning", "ocr", "gateway")
ENSURE_HTTP_TIMEOUT = 10  # Observe the owner's 8-second attempt plus loopback response delivery.


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
    def __init__(self, executable, resources, data, startup_policy=None):
        self.workers = []
        self.worker_handles = {}
        self.handles_by_pid = {}
        self.host_handle = None
        self.started = time.perf_counter()
        command = [str(executable), "--headless", "--resource-dir", str(resources), "--data-dir", str(data)]
        if startup_policy is not None:
            command += ["--startup-policy", startup_policy]
        self.process = subprocess.Popen(
            command,
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
            expect(isinstance(pids, list) and 1 <= len(pids) <= 6 and len(set(pids)) == len(pids)
                   and all(type(pid) is int and pid > 0 for pid in pids), "native_worker_set_invalid")
            for pid in pids:
                handle = OwnedProcess(pid)
                self.workers.append(handle)
                self.handles_by_pid[pid] = handle
            # Historical full-start artifacts reported exactly this ordered set.
            if len(pids) == len(WORKERS):
                self.worker_handles.update(zip(WORKERS, self.workers))
            self.host_handle = OwnedProcess(self.process.pid)
            self.ready_seconds = time.perf_counter() - self.started
            self.opener = build_opener(ProxyHandler({}))
            status = self.status()
            self.dynamic_registry = "core_ready" in status
            actual_policy = status.get("startup_policy")
            if self.dynamic_registry:
                expect(actual_policy in ("eager", "on-demand"), "native_startup_policy_invalid")
                if startup_policy is not None:
                    expect(actual_policy == startup_policy, "native_startup_policy_mismatch")
            self.expect_optional_dormant = self.dynamic_registry and actual_policy == "on-demand"
            if self.expect_optional_dormant:
                for name in ("ocr", "planning"):
                    expect(status["services"][name]["state"] == "dormant", "optional_started_before_use")
            deadline = time.monotonic() + 30
            while self.dynamic_registry and not status["core_ready"]:
                expect(time.monotonic() < deadline, "native_core_readiness_timeout")
                time.sleep(.05)
                status = self.status()
            expect(not status["degraded"], "initial_service_degraded")
            self.core_ready_seconds = time.perf_counter() - self.started
            self.phases = status.get("timings", status.get("phases", {}))
        except Exception:
            self.stop()
            raise

    def status(self):
        status = self.call("GET", "/api/status")
        for name, value in status.get("services", {}).items():
            pid = value.get("pid")
            if value.get("state") == "ready" and type(pid) is int and pid > 0:
                if pid not in self.handles_by_pid:
                    handle = OwnedProcess(pid)
                    self.handles_by_pid[pid] = handle
                    self.workers.append(handle)
                self.worker_handles[name] = self.handles_by_pid[pid]
        return status

    def ensure(self, name):
        if self.dynamic_registry:
            self.call("POST", "/api/runtime/ensure", {"service": name}, timeout=ENSURE_HTTP_TIMEOUT)
            expect(self.status()["services"][name]["state"] == "ready", "ensured_worker_not_ready")
        expect(name in self.worker_handles, "owned_worker_identity_missing")
        return self.worker_handles[name]

    def call(self, method, path, body=None, authenticated=True, timeout=5):
        payload = None if body is None else json.dumps(body, ensure_ascii=False, allow_nan=False).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if authenticated:
            headers["Authorization"] = "Bearer " + self.token
        request = Request(self.url + path, payload, headers, method=method)
        try:
            with self.opener.open(request, timeout=timeout) as response:
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
        cleanup_failed = False
        orphaned = False
        try:
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
        except Exception:
            cleanup_failed = True
            try:
                self.process.kill()
                self.process.wait(timeout=5)
            except Exception:
                pass  # Continue reclaiming each retained child even if host cleanup failed.

        def reclaim(handle):
            try:
                handle.terminate()  # This is the exact retained owned-process handle.
            except Exception:
                pass  # TerminateProcess may race an exit; the handle wait decides reclamation.
            try:
                return handle.exited(5)
            except Exception:
                return False

        deadline = time.monotonic() + 5
        for handle in self.workers:
            try:
                if not handle.exited(max(0, deadline - time.monotonic())):
                    orphaned = True
                    cleanup_failed |= not reclaim(handle)
            except Exception:
                cleanup_failed = True
                reclaim(handle)
            finally:
                try:
                    handle.close()
                except Exception:
                    cleanup_failed = True
        self.workers = []
        self.worker_handles = {}
        self.handles_by_pid = {}
        if self.host_handle:
            try:
                self.host_handle.close()
            except Exception:
                cleanup_failed = True
            finally:
                self.host_handle = None
        for stream in (self.process.stdin, self.process.stdout, self.process.stderr):
            try:
                stream.close()
            except Exception:
                cleanup_failed = True
        expect(not orphaned, "orphan_worker_after_host_exit")
        expect(not cleanup_failed, "owned_cleanup_failed")


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
    if getattr(app, "dynamic_registry", False):
        status = app.status()
        if getattr(app, "expect_optional_dormant", False):
            expect(all(status["services"][name]["state"] == "dormant" for name in ("ocr", "planning")),
                   "manual_flow_started_optional_worker")


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


def maintenance_inputs(data):
    """Snapshot the supported stored inputs before the offline native backup."""
    files = set()
    try:
        ordinary(data)
        for name in DATABASES:
            path = data / name
            if path.exists():
                ordinary(path.parent)
                expect(ordinary(path).is_file(), "native_maintenance_input_invalid")
                files.add(name)
        captures = data / "ocr"
        if captures.exists():
            ordinary(captures)
            for path in captures.iterdir():
                name = "ocr/" + path.name
                expect(CAPTURE.fullmatch(name) and ordinary(path).is_file(),
                       "native_maintenance_input_invalid")
                files.add(name)
    except DomainError:
        raise CheckFailed("native_maintenance_input_invalid") from None
    expect({"profile/profile.sqlite3", "evaluation/evaluation.sqlite3"} <= files,
           "native_maintenance_core_files_missing")
    return files


def maintenance_manifest(directory):
    try:
        manifest = verify(directory)
    except (DomainError, sqlite3.Error):
        raise CheckFailed("native_maintenance_integrity_failed") from None
    expect({"profile/profile.sqlite3", "evaluation/evaluation.sqlite3"} <= set(manifest["files"]),
           "native_maintenance_core_files_missing")
    return manifest


def native_maintenance(executable, resources, data, flag, other, accepted=True):
    if accepted:
        expect(flag in ("--backup-to", "--restore-from"), "native_maintenance_operation_invalid")
        expected = maintenance_inputs(data) if flag == "--backup-to" else maintenance_manifest(other)
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
    expect(isinstance(result, dict), "native_maintenance_response_invalid")
    if accepted:
        manifest = maintenance_manifest(other if flag == "--backup-to" else data)
        # SQLite backup can change database bytes; compare names for backup and
        # the entire verified manifest for restore, where every byte is copied.
        expect(set(manifest["files"]) == expected if flag == "--backup-to" else manifest == expected,
               "native_maintenance_files_missing")
        expect(result.get("operation") == ("backup" if flag == "--backup-to" else "restore")
               and type(result.get("storage_version")) is int and result["storage_version"] == 1
               and type(result.get("files")) is int and result["files"] == len(manifest["files"]),
               "native_maintenance_response_invalid")
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
    parser.add_argument("--startup-policy", choices=("eager", "on-demand"), default=None,
                        help="Omit for historical artifacts without this flag.")
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
    samples, core_samples, memories, phases = [], [], [], []
    stage = "start_exit"
    app = None
    try:
        for index in range(args.cycles):
            app = Desktop(executable, resources, data, args.startup_policy)
            samples.append(app.ready_seconds)
            core_samples.append(app.core_ready_seconds)
            phases.append(app.phases)
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
        app = Desktop(executable, resources, output / "restored-state", args.startup_policy)
        replay(app)
        app.stop()
        app = None
        report["checks"].append("single_exe_backup_restore_preserves_frozen_replay")
        stage = "worker_faults"
        for name in WORKERS:
            app = Desktop(executable, resources, data, args.startup_policy)
            handle = app.ensure(name) if name != "gateway" else app.worker_handles.get(name)
            expect(handle is not None, "owned_gateway_identity_missing")
            handle.terminate()
            expect(handle.exited(3), "worker_fault_not_delivered")
            if name == "gateway":
                try:
                    app.call("GET", "/api/status")
                except (URLError, ConnectionError, OSError):
                    pass
                else:
                    raise CheckFailed("gateway_fault_not_observed")
            else:
                status = app.call("GET", "/api/status")
                expect(status["degraded"] and status["services"][name]["state"] in ("unavailable", "failed"),
                       "worker_fault_missing_degradation")
                if name in ("profile", "knowledge"):
                    replay(app)
            app.stop()
            app = None
            print(f"Native worker fault: {name}", flush=True)
        report["checks"] += ["six_worker_fault_cleanup", "source_service_fault_keeps_frozen_replay"]
        stage = "host_fault"
        app = Desktop(executable, resources, data, args.startup_policy)
        app.ensure("ocr")
        app.ensure("planning")
        app.stop(forced=True)
        app = None
        report["checks"].append("forced_host_exit_job_cleanup")
        app = Desktop(executable, resources, data, args.startup_policy)
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
            report["headless_core_readiness"] = {
                "runs": len(core_samples), "seconds": [round(value, 4) for value in core_samples],
                "p50_seconds": round(sorted(core_samples)[math.ceil(.5 * len(core_samples)) - 1], 4),
                "p95_seconds": round(sorted(core_samples)[math.ceil(.95 * len(core_samples)) - 1], 4),
                "max_seconds": round(max(core_samples), 4),
            }
            report["owner_phase_counters"] = phases
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

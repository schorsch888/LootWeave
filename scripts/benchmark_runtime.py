"""Measure owned, headless runtimes with fictional inputs and warm OS caches.

No game interaction, screenshots, GUI input, or process address-space reads.
Raw reports and isolated state stay under ignored .local/runtime-benchmark.
"""
from __future__ import annotations

import argparse
import base64
import ctypes
from ctypes import wintypes
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import queue
import re
import subprocess
import struct
import sys
import threading
import time
from urllib.parse import urlsplit
from urllib.error import HTTPError
from urllib.request import ProxyHandler, Request, build_opener
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.check_desktop import CheckFailed, ENSURE_HTTP_TIMEOUT, OwnedProcess, expect, frozen_environment, machine
from contracts import digest

METRICS = ("launch_ready", "core_ready", "manual_complete", "manual_work", "catalog_response", "replay",
           "ocr_activation", "ocr_first", "ocr_first_total", "ocr_repeated", "planning_activation",
           "planning_first", "planning_first_total", "shutdown")


def percentile(values, fraction):
    """Nearest rank; empty observations have no percentile."""
    if not 0 < fraction <= 1:
        raise ValueError("percentile_fraction")
    ordered = sorted(values)
    if any(not math.isfinite(value) or value < 0 for value in ordered):
        raise ValueError("invalid_duration")
    return ordered[math.ceil(fraction * len(ordered)) - 1] if ordered else None


def summary(report):
    """Strict allowlist: raw paths, credentials, inputs and error text cannot escape."""
    cycles = report["cycles"]
    metrics = {}
    for name in METRICS:
        values = [cycle["seconds"][name] for cycle in cycles if name in cycle.get("seconds", {})]
        metrics[name] = {"samples": len(values), "p50_seconds": percentile(values, .5),
                         "p95_seconds": percentile(values, .95), "max_seconds": max(values, default=None)}
    failures = [{"cycle": cycle["cycle"], "stage": cycle.get("failure_stage", "cleanup"),
                 "category": cycle.get("failure_category", "cleanup_failed")}
                for cycle in cycles if not cycle.get("passed")]
    # Even raw category/stage strings are validated, rather than redacting paths heuristically.
    for failure in failures:
        for key in ("stage", "category"):
            if not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", failure[key]):
                failure[key] = "redacted"
    label = report.get("cohort", "unspecified")
    if not re.fullmatch(r"[a-zA-Z0-9_-]{1,48}", label):
        label = "redacted"
    return {"schema_version": 1, "cohort": label,
            "policy": report["policy"] if report["policy"] in ("legacy", "eager", "on-demand") else "redacted",
            "mode": report["mode"] if report["mode"] in ("developer", "native-headless") else "redacted",
            "runs": len(cycles), "failed_runs": len(failures), "failures": failures, "metrics": metrics,
            "cohort_completed_without_failure": len(cycles) >= 20 and not failures,
            "acceptance_passed": len(cycles) >= 20 and not failures and not any(cycle.get("ocr_skipped") for cycle in cycles),
            "cache_condition": "warm OS caches; no cold-cache procedure",
            "gui_visibility": "excluded; headless, no WebView",
            "webview_version": "not applicable to headless cohorts",
            "environment": sanitized_environment(report.get("environment", {})),
            "idle_schedule": "60 seconds at 1 Hz, first cycle only: after manual/replay before optional use, then after OCR/Planning use",
            "resource_accounting": "sum of owned working sets (shared pages may be double counted); private commit separately",
            "resource_scope": "owned host and sampled descendants; 100 ms tree discovery may miss shorter-lived helpers",
            "source_revision": report.get("source_revision") if re.fullmatch(r"[0-9a-f]{7,40}", report.get("source_revision", "")) else "unspecified",
            "identities": {name: value for name, value in report.get("identities", {}).items()
                           if name in ("runtime", "gateway", "service", "host", "bundle_manifest", "ocr_fixture", "demo_fixture", "knowledge_index")
                           and re.fullmatch(r"[0-9a-f]{64}", value)},
            "cycles": [{"cycle": cycle["cycle"], "passed": bool(cycle.get("passed")),
                        "seconds": {key: value for key, value in cycle.get("seconds", {}).items()
                                    if key in METRICS and type(value) in (int, float) and math.isfinite(value) and value >= 0},
                        "cleanup_passed": bool(cycle.get("cleanup_passed")),
                        "http_error": sanitized_http_error(cycle.get("http_error", {})),
                        "ocr_skipped": cycle.get("ocr_skipped") == "native_language_unavailable",
                        "ocr_languages": [language for language in cycle.get("ocr_languages", [])
                                          if isinstance(language, str) and re.fullmatch(r"[A-Za-z]{2,8}(?:-[A-Za-z0-9]{2,8}){0,2}", language)],
                        "input_sha256": {key: value for key, value in cycle.get("input_sha256", {}).items()
                                         if key in ("facts", "intent", "pack") and isinstance(value, str)
                                         and re.fullmatch(r"[0-9a-f]{64}", value)},
                        "resource_samples": sanitized_resources(cycle.get("resource_samples", {})),
            "phases": sanitized_phases(cycle.get("phases", {}))} for cycle in cycles]}


def sanitized_resources(value):
    allowed = {"interval_seconds", "samples", "cpu_seconds", "cpu_percent_one_logical_processor",
               "cpu_percent_machine", "max_working_set_mib", "max_private_commit_mib", "working_set_mib",
               "private_commit_mib", "sampling_failures"}
    return {name: {key: entry for key, entry in metrics.items() if key in allowed
                   and type(entry) in (int, float) and math.isfinite(entry) and entry >= 0}
            for name, metrics in value.items() if name in ("idle_after_core", "idle_after_optional", "work_peak")
            and isinstance(metrics, dict)} if isinstance(value, dict) else {}


def sanitized_http_error(value):
    if not isinstance(value, dict):
        return {}
    result = {}
    status = value.get("status")
    if type(status) is int and 400 <= status <= 599:
        result["status"] = status
    code = value.get("code")
    if isinstance(code, str) and re.fullmatch(r"[a-z][a-z0-9_]{0,63}", code):
        result["code"] = code
    return result


def sanitized_environment(value):
    result = {}
    for key in ("os_family", "os_release", "os_version", "cpu_model", "harness_python", "runtime_python"):
        text = value.get(key)
        if isinstance(text, str) and re.fullmatch(r"[A-Za-z0-9 ._()+@-]{1,160}", text):
            result[key] = text
    count = value.get("logical_processors")
    if type(count) is int and 0 < count <= 4096:
        result["logical_processors"] = count
    return result


def sanitized_phases(value):
    """Expose numeric phase counters without owner-specific labels or strings."""
    allowed = {"bundle_verification_seconds", "spawn_seconds", "ready_seconds", "startup_seconds",
               "capability_seconds", "catalog_seconds", "gateway_seconds", "profile", "knowledge",
               "evaluation", "planning", "ocr", "gateway", "generation", "seconds", "workers", "phases",
               "service_ready_ms", "service_init_ms", "shell_ready_ms", "core_ready_ms", "bundle_verification_ms",
               "gateway_ready_ms", "capability_probe_ms", "construction_ms"}
    allowed.update(("app_init_ms", "capability_discovery_ms"))
    if isinstance(value, dict):
        return {key: sanitized_phases(entry) for key, entry in value.items() if key in allowed}
    if type(value) in (int, float) and math.isfinite(value) and value >= 0:
        return value
    return None


def process_snapshot():
    """Toolhelp OS metadata only; never reads a process address space."""
    class Entry(ctypes.Structure):
        _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD),
                    ("th32ProcessID", wintypes.DWORD), ("th32DefaultHeapID", ctypes.c_size_t),
                    ("th32ModuleID", wintypes.DWORD), ("cntThreads", wintypes.DWORD),
                    ("th32ParentProcessID", wintypes.DWORD), ("pcPriClassBase", wintypes.LONG),
                    ("dwFlags", wintypes.DWORD), ("szExeFile", wintypes.WCHAR * 260)]
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateToolhelp32Snapshot.argtypes = (wintypes.DWORD, wintypes.DWORD)
    kernel.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    kernel.Process32FirstW.argtypes = (wintypes.HANDLE, ctypes.POINTER(Entry))
    kernel.Process32NextW.argtypes = (wintypes.HANDLE, ctypes.POINTER(Entry))
    kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
    snapshot = kernel.CreateToolhelp32Snapshot(2, 0)
    expect(snapshot != ctypes.c_void_p(-1).value, "process_snapshot_failed")
    result = {}
    try:
        entry = Entry()
        entry.dwSize = ctypes.sizeof(entry)
        found = kernel.Process32FirstW(snapshot, ctypes.byref(entry))
        while found:
            result[entry.th32ProcessID] = entry.th32ParentProcessID
            found = kernel.Process32NextW(snapshot, ctypes.byref(entry))
        return result
    finally:
        kernel.CloseHandle(snapshot)


class CounterProcess(OwnedProcess):
    def cpu(self):
        values = [wintypes.FILETIME() for _ in range(4)]
        self.kernel.GetProcessTimes.argtypes = (wintypes.HANDLE,) + (ctypes.POINTER(wintypes.FILETIME),) * 4
        expect(bool(self.kernel.GetProcessTimes(self.handle, *(ctypes.byref(value) for value in values))),
               "owned_cpu_counter_unavailable")
        return sum((value.dwHighDateTime << 32) + value.dwLowDateTime for value in values[2:]) / 10**7


class OwnedTree:
    """Retain exact handles; discovery/termination only follow living owned parents."""
    def __init__(self, pid, snapshot=process_snapshot, factory=CounterProcess):
        self.snapshot, self.factory = snapshot, factory
        self.handles = {pid: factory(pid)}
        self.lock = threading.Lock()
        self.finished = threading.Event()
        self.failures = []
        self.peak_working_set = self.peak_private_commit = 0
        self.thread = threading.Thread(target=self._watch, daemon=True)
        self.thread.start()

    def discover(self):
        with self.lock:
            parents = self.snapshot()
            living = {pid for pid, handle in self.handles.items() if not handle.exited()}
            while True:
                new = [pid for pid, parent in parents.items() if parent in living and pid not in self.handles]
                if not new:
                    break
                for pid in new:
                    try:
                        self.handles[pid] = self.factory(pid)
                        living.add(pid)
                    except CheckFailed:
                        # Short lived descendants can exit between snapshot and OpenProcess.
                        self.failures.append("descendant_exited_before_handle")
                        parents.pop(pid, None)

    def counters(self):
        with self.lock:
            cpu = sum(handle.cpu() for handle in self.handles.values())
            memory = []
            for handle in self.handles.values():
                if not handle.exited():
                    try:
                        memory.append(handle.memory())
                    except CheckFailed:
                        # Exit can race the counter query; a dead retained handle is still owned.
                        if not handle.exited():
                            raise
            working = sum(entry[0] for entry in memory)
            private = sum(entry[1] for entry in memory)
            self.peak_working_set = max(self.peak_working_set, working)
            self.peak_private_commit = max(self.peak_private_commit, private)
            return {"cpu_seconds": cpu, "working_set_mib": working / 2**20,
                    "private_commit_mib": private / 2**20, "retained_handles": len(self.handles)}

    def _watch(self):
        while not self.finished.is_set():
            try:
                self.discover()
                self.counters()
            except (CheckFailed, OSError):
                self.failures.append("resource_counter_failed")
            self.finished.wait(.1)

    def close(self, timeout=5):
        self.finished.set()
        self.thread.join(timeout=2)
        deadline = time.monotonic() + timeout
        clean = True
        for handle in self.handles.values():
            if not handle.exited(max(0, deadline - time.monotonic())):
                clean = False
                handle.terminate()
                handle.exited(5)
            handle.close()
        return clean


class Launch:
    def __init__(self, args, state):
        self.args, self.state = args, state
        self.process = self.tree = None
        self.started = time.perf_counter()
        self.opener = build_opener(ProxyHandler({}))

    def start(self):
        args = self.args
        if args.executable:
            command = [str(args.executable), "--headless", "--resource-dir", str(args.resources), "--data-dir", str(self.state)]
            environment = frozen_environment()
            cwd = args.executable.parent
        else:
            command = [str(args.python), "-u", str(args.runtime_root / "runtime.py"), "--no-browser", "--stdio-control", "--data-dir", str(self.state)]
            environment = {**os.environ, "PYTHONUTF8": "1"}
            cwd = args.runtime_root
        if args.policy != "legacy":
            command += ["--startup-policy", args.policy]
        self.process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                        stderr=subprocess.DEVNULL, env=environment, cwd=cwd,
                                        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        self.tree = OwnedTree(self.process.pid)
        messages = queue.Queue(maxsize=1)
        threading.Thread(target=lambda: messages.put(self.process.stdout.readline(8193)), daemon=True).start()
        try:
            line = messages.get(timeout=60)
        except queue.Empty:
            raise CheckFailed("launcher_readiness_timeout") from None
        expect(0 < len(line) <= 8192, "launcher_readiness_missing")
        ready = json.loads(line)
        parsed = urlsplit(ready.get("url", ""))
        expect(parsed.scheme == "http" and parsed.hostname == "127.0.0.1" and parsed.port
               and not parsed.path and not parsed.query and not parsed.fragment, "launcher_url_invalid")
        self.url, self.token = ready["url"], ready["token"]
        expect(isinstance(self.token, str) and 32 <= len(self.token) <= 128, "launcher_token_invalid")
        self.launch_ready = time.perf_counter() - self.started
        self.tree.discover()

    def call(self, method, path, body=None, timeout=30):
        data = None if body is None else json.dumps(body, allow_nan=False).encode()
        request = Request(self.url + path, data, {"Authorization": "Bearer " + self.token,
                                                   "Content-Type": "application/json"}, method=method)
        try:
            with self.opener.open(request, timeout=timeout) as response:
                return json.load(response)
        except HTTPError as error:
            try:
                raw = error.read(4097)
                value = json.loads(raw) if len(raw) <= 4096 else None
                code = value.get("error") if isinstance(value, dict) else None
            except (OSError, ValueError):
                code = None
            self.last_http_error = sanitized_http_error({"status": error.code, "code": code})
            raise

    def ensure(self, name):
        if self.args.policy != "legacy":
            value = self.call("POST", "/api/runtime/ensure", {"service": name}, timeout=ENSURE_HTTP_TIMEOUT)
            expect(value.get("state", "ready") == "ready", "capability_not_ready")

    def stop(self):
        if self.process is None:
            return True
        graceful = True
        if self.process.poll() is None:
            self.process.stdin.close()
            try:
                self.process.wait(timeout=12)
            except subprocess.TimeoutExpired:
                graceful = False
                self.process.kill()
                self.process.wait(timeout=5)
        clean = self.tree.close() if self.tree else False
        self.process.stdout.close()
        return graceful and clean and self.process.returncode == 0


def timed(cycle, name, action):
    start = time.perf_counter()
    try:
        return action()
    finally:
        cycle["seconds"][name] = time.perf_counter() - start


def manual(app, cycle=None):
    demo = app.call("GET", "/api/demo")
    app.call("POST", "/api/profile/observations", {"observation_id": "demo-text", "method": "text", "raw_text": "Fictional benchmark input"})
    profile = app.call("POST", "/api/profile/confirmations", {
        "request_id": "benchmark-confirm", "profile_id": "benchmark-fixture", "observation_id": "demo-text",
        "expected_revision": 0, "player_confirmed": True, "facts": demo["facts"]})
    get_packs = lambda: app.call("GET", "/api/knowledge/packs")["packs"]
    packs = timed(cycle, "catalog_response", get_packs) if cycle is not None else get_packs()
    pack = next(pack for pack in packs if pack["execution_policy"] == "synthetic_only")
    if cycle is not None:
        cycle["input_sha256"] = {"facts": digest(demo["facts"]), "intent": digest(demo["intent"]), "pack": pack["pack_hash"]}
    result = app.call("POST", "/api/evaluation/evaluations", {
        "request_id": "benchmark-evaluation", "profile_id": "benchmark-fixture", "profile_revision": profile["revision"],
        "pack_id": pack["pack_id"], "pack_version": pack["version"], "pack_hash": pack["pack_hash"], "intent": demo["intent"]})
    expect(result["retention"] != "discard", "fictional_core_loss_hidden")
    return demo["facts"]["context"]


def synthetic_bmp():
    """Original deterministic 5x7 glyph fixture; contains only fictional LEVEL 70."""
    glyphs = {"L": (16, 16, 16, 16, 16, 16, 31), "E": (31, 16, 16, 30, 16, 16, 31),
              "V": (17, 17, 17, 17, 17, 10, 4), "7": (31, 1, 2, 4, 8, 8, 8),
              "0": (14, 17, 19, 21, 25, 17, 14), " ": (0,) * 7}
    width, height, scale = 420, 100, 8
    stride = (width * 3 + 3) // 4 * 4
    pixels = bytearray(b"\xff" * (stride * height))
    for letter, character in enumerate("LEVEL 70"):
        for row, bits in enumerate(glyphs[character]):
            for column in range(5):
                if bits & (1 << (4 - column)):
                    for dy in range(scale):
                        y = 20 + row * scale + dy
                        start = (height - y - 1) * stride + (20 + letter * 6 * scale + column * scale) * 3
                        pixels[start:start + scale * 3] = b"\0" * (scale * 3)
    return (b"BM" + struct.pack("<IHHI", 54 + len(pixels), 0, 0, 54)
            + struct.pack("<IiiHHIIiiII", 40, width, height, 1, 24, 0, len(pixels), 0, 0, 0, 0) + pixels)


def idle(app):
    first = app.tree.counters()
    started = time.perf_counter()
    values = [first]
    for index in range(1, 61):
        time.sleep(max(0, started + index - time.perf_counter()))
        values.append(app.tree.counters())
    elapsed = time.perf_counter() - started
    cpu = values[-1]["cpu_seconds"] - first["cpu_seconds"]
    return {"interval_seconds": elapsed, "samples": len(values), "cpu_seconds": cpu,
            "cpu_percent_one_logical_processor": 100 * cpu / elapsed,
            "cpu_percent_machine": 100 * cpu / elapsed / (os.cpu_count() or 1),
            "max_working_set_mib": max(value["working_set_mib"] for value in values),
            "max_private_commit_mib": max(value["private_commit_mib"] for value in values)}


def run_cycle(args, output, index, fixture):
    cycle = {"cycle": index + 1, "seconds": {}, "passed": False, "resource_samples": {}}
    state = output / f"cycle-{index + 1:03d}" / "state"
    state.mkdir(parents=True)
    app = Launch(args, state)
    stage = "launch_ready"
    try:
        app.start()
        cycle["seconds"]["launch_ready"] = app.launch_ready
        stage = "core_ready"
        deadline = time.monotonic() + 30
        status = app.call("GET", "/api/status")
        while not status.get("core_ready", not status.get("degraded")):
            expect(time.monotonic() < deadline, "core_readiness_timeout")
            time.sleep(.05)
            status = app.call("GET", "/api/status")
        cycle["seconds"]["core_ready"] = time.perf_counter() - app.started
        if args.policy == "on-demand":
            expect(all(status["services"][name]["state"] == "dormant" for name in ("ocr", "planning")), "optional_started_before_use")
        stage = "manual_work"
        context = timed(cycle, stage, lambda: manual(app, cycle))
        cycle["seconds"]["manual_complete"] = time.perf_counter() - app.started
        stage = "replay"
        result = timed(cycle, stage, lambda: app.call("POST", "/api/evaluation/evaluations/benchmark-evaluation/replay", {}))
        expect(result["identical"], "frozen_replay_mismatch")
        if args.policy == "on-demand":
            status = app.call("GET", "/api/status")
            expect(all(status["services"][name]["state"] == "dormant" for name in ("ocr", "planning")), "manual_started_optional")
        if index == 0:
            stage = "idle_after_core"
            cycle["resource_samples"][stage] = idle(app)
        stage = "ocr_activation"
        optional_started = time.perf_counter()
        timed(cycle, stage, lambda: app.ensure("ocr"))
        status = app.call("GET", "/api/status")
        languages = status["services"]["ocr"].get("languages", [])
        cycle["ocr_languages"] = languages
        language = "en-US" if "en-US" in languages else languages[0] if languages else None
        if language:
            for name in ("ocr_first", "ocr_repeated"):
                stage = name
                result = timed(cycle, name, lambda: app.call("POST", "/api/ocr/regions", {
                    "observation_id": name.replace("_", "-"), "image_base64": base64.b64encode(fixture).decode(),
                    "bounds": {"x": 0, "y": 0, "width": int.from_bytes(fixture[18:22], "little", signed=True),
                               "height": abs(int.from_bytes(fixture[22:26], "little", signed=True))}, "language": language}))
                expect(not result.get("error"), "synthetic_ocr_failed")
                expect(result.get("requires_confirmation") is True, "ocr_confirmation_missing")
                expect(bool(result.get("raw_text", "").strip()), "synthetic_ocr_no_text")
                if name == "ocr_first":
                    cycle["seconds"]["ocr_first_total"] = time.perf_counter() - optional_started
        else:
            cycle["ocr_skipped"] = "native_language_unavailable"
        stage = "planning_activation"
        optional_started = time.perf_counter()
        timed(cycle, stage, lambda: app.ensure("planning"))
        stage = "planning_first"
        timed(cycle, stage, lambda: app.call("POST", "/api/planning/drop-estimates", {
            "context": context, "method": "observed_counts", "coverage": "complete", "version_unchanged": True,
            "successes": 2, "attempts": 10, "target_event": "fictional token", "attempt_unit": "fictional trial"}))
        cycle["seconds"]["planning_first_total"] = time.perf_counter() - optional_started
        if index == 0:
            stage = "idle_after_optional"
            cycle["resource_samples"][stage] = idle(app)
        status = app.call("GET", "/api/status")
        cycle["phases"] = status.get("timings", status.get("phases", {}))
        cycle["passed"] = True
    except (CheckFailed, OSError, ValueError, KeyError, StopIteration, subprocess.TimeoutExpired) as error:
        cycle["failure_stage"] = stage
        cycle["failure_category"] = str(error) if isinstance(error, CheckFailed) else type(error).__name__.lower()
        if isinstance(error, HTTPError):
            cycle["http_error"] = getattr(app, "last_http_error", {"status": error.code})
        # Preserve elapsed startup failures; never silently omit timed-out launches.
        if stage in METRICS and stage not in cycle["seconds"]:
            cycle["seconds"][stage] = time.perf_counter() - app.started
        if stage in ("ocr_activation", "ocr_first"):
            cycle["seconds"]["ocr_first_total"] = time.perf_counter() - optional_started
        if stage in ("planning_activation", "planning_first"):
            cycle["seconds"]["planning_first_total"] = time.perf_counter() - optional_started
    finally:
        start = time.perf_counter()
        try:
            cycle["cleanup_passed"] = app.stop()
        except (CheckFailed, OSError, subprocess.TimeoutExpired):
            cycle["cleanup_passed"] = False
        cycle["seconds"]["shutdown"] = time.perf_counter() - start
        cycle["passed"] = cycle["passed"] and cycle["cleanup_passed"]
        if app.tree:
            cycle["resource_samples"]["work_peak"] = {
                "working_set_mib": app.tree.peak_working_set / 2**20,
                "private_commit_mib": app.tree.peak_private_commit / 2**20,
                "sampling_failures": len(app.tree.failures)}
            if "resource_counter_failed" in app.tree.failures:
                cycle["passed"] = False
                cycle.setdefault("failure_stage", "resources")
                cycle.setdefault("failure_category", "resource_counter_failed")
    return cycle


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime-root", type=Path, default=ROOT)
    parser.add_argument("--python", type=Path, default=Path(sys.executable))
    parser.add_argument("--executable", type=Path)
    parser.add_argument("--resources", type=Path)
    parser.add_argument("--policy", choices=("legacy", "eager", "on-demand"), required=True)
    parser.add_argument("--cycles", type=int, default=20)
    parser.add_argument("--cohort", required=True, help="Public label: letters, digits, underscores or hyphens only.")
    parser.add_argument("--source-revision", default="", help="Disclosed source revision; never inferred from artifact identity.")
    args = parser.parse_args()
    if os.name != "nt":
        parser.error("Windows process resource counters are required.")
    if not 20 <= args.cycles <= 100:
        parser.error("cycles must be 20 through 100; failed launches remain in the cohort")
    if not re.fullmatch(r"[a-zA-Z0-9_-]{1,48}", args.cohort):
        parser.error("cohort must be a short public label")
    if bool(args.executable) != bool(args.resources):
        parser.error("native mode requires both executable and resources")
    args.runtime_root = args.runtime_root.resolve()
    args.python = args.python.resolve()
    if args.executable:
        args.executable, args.resources = args.executable.resolve(), args.resources.resolve()
    fixture = synthetic_bmp()
    output = ROOT / ".local/runtime-benchmark" / (args.cohort + "-" + uuid.uuid4().hex)
    output.mkdir(parents=True)
    identities = {"ocr_fixture": hashlib.sha256(fixture).hexdigest()}
    sources = {"host": args.executable, "bundle_manifest": args.resources / "bundle-manifest.json"} if args.executable else {
        name: args.runtime_root / (name + ".py") for name in ("runtime", "gateway", "service")}
    input_root = args.resources / "_internal" if args.executable else args.runtime_root
    sources.update({"demo_fixture": input_root / "fixtures/demo.json",
                    "knowledge_index": input_root / "knowledge-packs/index.json"})
    for name, path in sources.items():
        identities[name] = hashlib.sha256(path.read_bytes()).hexdigest()
    environment = {"os_family": platform.system(), "os_release": platform.release(), "os_version": platform.version(),
                   "cpu_model": machine()["cpu"], "logical_processors": os.cpu_count(), "harness_python": platform.python_version()}
    if args.executable:
        environment["runtime_python"] = json.loads((args.resources / "bundle-manifest.json").read_bytes()).get("python_version", "unknown")
    else:
        version = subprocess.run([str(args.python), "--version"], capture_output=True, text=True, timeout=5,
                                 creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        environment["runtime_python"] = (version.stdout or version.stderr).strip().removeprefix("Python ")
    report = {"schema_version": 1, "cohort": args.cohort, "policy": args.policy,
              "mode": "native-headless" if args.executable else "developer", "cycles": [],
              "source_revision": args.source_revision, "identities": identities,
              "environment": environment,
              "paths_private": {"runtime_root": str(args.runtime_root), "executable": str(args.executable),
                                "resources": str(args.resources), "python": str(args.python)}}
    print("Evidence: " + output.relative_to(ROOT).as_posix(), flush=True)
    for index in range(args.cycles):
        cycle = run_cycle(args, output, index, fixture)
        report["cycles"].append(cycle)
        (output / "report-private.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        (output / "summary-review.json").write_text(json.dumps(summary(report), indent=2) + "\n", encoding="utf-8")
        print(f"Cycle {index + 1}/{args.cycles}: {'passed' if cycle['passed'] else 'FAILED'}", flush=True)
    return 0 if summary(report)["cohort_completed_without_failure"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

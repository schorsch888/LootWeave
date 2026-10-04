"""Windows service exits must reclaim active helpers and their descendants."""
from __future__ import annotations

import base64
import contextlib
import io
import ctypes
import json
import os
import queue
import secrets
import struct
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock
from pathlib import Path

from transport import Client

ROOT = Path(__file__).resolve().parents[1]
WORKER = """import importlib.util,sys
from pathlib import Path
import services.ocr.app as ocr
ocr.ROOT=Path(sys.argv[1]).resolve()
if sys.argv[2]=='nested':
    spec=importlib.util.spec_from_file_location('test_outer_job',Path.cwd()/'process_lifecycle.py')
    outer=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(outer)
    outer.own_service_process()
import service
original_ownership=service.own_service_process
def record_ownership():
    (ocr.ROOT/'self-job-entered').write_text('entered')
    original_ownership()
service.own_service_process=record_ownership
sys.argv=['service.py','ocr','--data-dir',str(ocr.ROOT/'state'),'--parent-stdio']
(ocr.ROOT/'boot-ready').write_text('ready')
raise SystemExit(service.main())
"""


@unittest.skipUnless(os.name == "nt", "Windows process ownership requires native job objects.")
class ProcessLifecycleTests(unittest.TestCase):
    def check_exit(self, mode, *, phase="recognition", descendants=False, nested=False, gate=False, permit=b"1"):
        from ctypes import wintypes
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
        kernel.WaitForSingleObject.restype = wintypes.DWORD
        kernel.TerminateProcess.argtypes = (wintypes.HANDLE, wintypes.UINT)
        kernel.TerminateProcess.restype = wintypes.BOOL
        kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
        kernel.CloseHandle.restype = wintypes.BOOL
        base = ROOT / ".local/process-lifecycle-tests"
        base.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="owned-", dir=base) as directory:
            data = Path(directory).resolve()
            self.assertTrue(data.is_relative_to(base.resolve()))
            scripts = data / "scripts"
            scripts.mkdir()
            marker = data / "helper.pid"
            descendant_marker = data / "descendant.pid"
            quote = lambda value: "'" + str(value).replace("'", "''") + "'"
            wait_code = "$PID | Set-Content -LiteralPath " + quote(marker) + " -Encoding ASCII\n"
            if descendants:
                wait_code += (
                    "$info = New-Object System.Diagnostics.ProcessStartInfo\n"
                    "$info.FileName = (Get-Process -Id $PID).Path\n"
                    "$info.Arguments = '-NoProfile -NonInteractive -Command \"Start-Sleep -Seconds 45\"'\n"
                    "$info.UseShellExecute = $false\n"
                    "$info.CreateNoWindow = $true\n"
                    "$descendant = [System.Diagnostics.Process]::Start($info)\n"
                    "$descendant.Id | Set-Content -LiteralPath " + quote(descendant_marker) + " -Encoding ASCII\n")
            wait_code += "Start-Sleep -Seconds 45\n"
            script = "param([string]$ImagePath,[string]$Language,[switch]$Capabilities)\n"
            script += "if ($Capabilities) {\n"
            script += wait_code if phase == "startup" else "'{\"languages\":[\"en-US\"]}'\n"
            script += "exit 0\n}\n" + wait_code + "'{\"text\":\"\",\"lines\":[]}'\n"
            (scripts / "windows_ocr.ps1").write_text(script, encoding="utf-8")
            token = secrets.token_urlsafe(32)
            worker = sentinel = request_thread = None
            handles = []
            request_outcome = queue.Queue(maxsize=1)
            try:
                worker = subprocess.Popen(
                    [sys.executable, "-u", "-c", WORKER, str(data), "nested" if nested else "direct"],
                    cwd=ROOT, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                    env={**os.environ, "LOOTWEAVE_SESSION_TOKEN": token, "PYTHONUTF8": "1",
                         "LOOTWEAVE_PARENT_JOB": "1" if gate or nested else "0"},
                    creationflags=subprocess.CREATE_NO_WINDOW)
                if gate or nested:
                    boot = data / "boot-ready"
                    deadline = time.monotonic() + 6
                    while not boot.exists() and time.monotonic() < deadline:
                        time.sleep(.02)
                    self.assertTrue(boot.exists(), "controlled service did not reach bootstrap")
                    time.sleep(.2)
                    self.assertIsNone(worker.poll(), "service exited before the parent permit")
                    self.assertFalse((data / "self-job-entered").exists(),
                                     "service joined its own job before the parent assignment")
                    self.assertFalse(marker.exists(), "helper started before the parent permit")
                    if permit is None:
                        worker.stdin.close()
                    else:
                        worker.stdin.write(permit)
                        worker.stdin.flush()
                    if permit != b"1":
                        self.assertEqual(1, worker.wait(timeout=5))
                        self.assertEqual(b"", worker.stdout.read(), "unowned service published readiness")
                        self.assertEqual({"error": "service_parent_job_unavailable"},
                                         json.loads(worker.stderr.read()))
                        self.assertFalse(marker.exists(), "rejected parent permit spawned a helper")
                        self.assertFalse((data / "self-job-entered").exists())
                        return
                if phase == "recognition":
                    readiness = queue.Queue()
                    threading.Thread(target=lambda: readiness.put(worker.stdout.readline()), daemon=True).start()
                    ready = json.loads(readiness.get(timeout=8))
                    self.assertIn("url", ready, "service did not become ready")
                    health = Client(ready["url"], token, timeout=5).call("GET", "/v1/health")
                    self.assertTrue(health["available"], "controlled OCR capability probe unavailable")
                    pixels = bytes(24)
                    bmp = (b"BM" + struct.pack("<I", 54 + len(pixels)) + bytes(4) + struct.pack("<I", 54)
                           + struct.pack("<IiiHHII", 40, 3, -2, 1, 24, 0, len(pixels)) + bytes(16) + pixels)
                    body = {"observation_id": "inflight-exit", "image_base64": base64.b64encode(bmp).decode(),
                            "bounds": {"x": 0, "y": 0, "width": 3, "height": 2}, "language": "en-US"}

                    def request():
                        try:
                            result = Client(ready["url"], token, timeout=5).call("POST", "/v1/regions", body)
                            request_outcome.put({"error": result.get("error")})
                        except Exception as error:
                            # Worker exit interrupts this request; retain only a code for startup failures.
                            request_outcome.put({"error": getattr(error, "code", type(error).__name__)})

                    request_thread = threading.Thread(target=request, daemon=True)
                    request_thread.start()
                markers = [marker, descendant_marker] if descendants else [marker]
                deadline = time.monotonic() + 6
                while not all(path.exists() for path in markers) and time.monotonic() < deadline:
                    time.sleep(.02)
                started = {path.name: path.exists() for path in markers}
                if not all(started.values()):
                    outcome = request_outcome.get_nowait() if not request_outcome.empty() else "inflight"
                    self.fail(f"controlled helpers did not start: markers={started}, request={outcome}")
                for path in markers:
                    # Retain a process handle while it is live; cleanup cannot hit a recycled PID.
                    handle = kernel.OpenProcess(0x00100000 | 0x0001, False, int(path.read_text().strip()))
                    self.assertTrue(handle, "controlled helper handle unavailable")
                    handles.append(handle)
                    self.assertEqual(258, kernel.WaitForSingleObject(handle, 0), "helper not live before exit")
                sentinel = subprocess.Popen([sys.executable, "-c", "import time;time.sleep(45)"],
                                            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                            stderr=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW)
                if mode == "eof":
                    worker.stdin.close()
                else:
                    worker.terminate()
                code = worker.wait(timeout=5)
                if mode == "eof":
                    self.assertEqual(0, code, "graceful worker exit failed")
                else:
                    self.assertNotEqual(0, code, "forced worker exit was not exercised")
                for handle in handles:
                    self.assertEqual(0, kernel.WaitForSingleObject(handle, 3000),
                                     "helper or descendant survived owning service exit")
                self.assertIsNone(sentinel.poll(), "service cleanup terminated an unrelated sibling")
            finally:
                for handle in handles:
                    if kernel.WaitForSingleObject(handle, 0) == 258:
                        self.assertTrue(kernel.TerminateProcess(handle, 1), "controlled helper cleanup failed")
                    self.assertEqual(0, kernel.WaitForSingleObject(handle, 3000))
                    kernel.CloseHandle(handle)
                for process in (worker, sentinel):
                    if process:
                        if process.poll() is None:
                            process.kill()
                        process.wait(timeout=3)
                        for stream in (process.stdin, process.stdout, process.stderr):
                            if stream and not stream.closed:
                                stream.close()
                if request_thread:
                    request_thread.join(timeout=6)
                    self.assertFalse(request_thread.is_alive(), "controlled HTTP client did not stop")

    def test_parent_eof_reclaims_inflight_ocr_helper(self):
        self.check_exit("eof")

    def test_forced_worker_exit_reclaims_helper_and_descendant(self):
        self.check_exit("terminate", descendants=True)

    def test_forced_startup_exit_reclaims_capability_helper(self):
        self.check_exit("terminate", phase="startup")

    def test_ownership_failure_publishes_no_readiness_or_application(self):
        import service
        from contracts import DomainError
        for code in ("service_job_creation_failed", "service_job_configuration_failed",
                     "service_job_assignment_failed"):
            with self.subTest(code=code):
                stdout, stderr = io.StringIO(), io.StringIO()
                token = secrets.token_urlsafe(32)
                with mock.patch.object(sys, "argv", ["service.py", "ocr"]), \
                     mock.patch.dict(os.environ, {"LOOTWEAVE_SESSION_TOKEN": token, "LOOTWEAVE_PARENT_JOB": "0"}), \
                     mock.patch.object(service, "own_service_process", side_effect=DomainError(code, 503)), \
                     mock.patch.object(service, "create_app") as application, \
                     contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                    self.assertEqual(1, service.main())
                application.assert_not_called()
                self.assertEqual("", stdout.getvalue())
                self.assertEqual({"error": code}, json.loads(stderr.getvalue()))
                self.assertNotIn(token, stderr.getvalue())

    def test_parent_job_permission_precedes_service_ownership_and_helpers(self):
        self.check_exit("terminate", phase="startup", gate=True)

    def test_parent_eof_before_job_permission_spawns_no_helper(self):
        self.check_exit("terminate", phase="startup", gate=True, permit=None)

    def test_invalid_parent_job_permission_spawns_no_helper(self):
        self.check_exit("terminate", phase="startup", gate=True, permit=b"0")

    def test_nested_job_keeps_cleanup_scoped_to_the_service(self):
        self.check_exit("terminate", descendants=True, nested=True)

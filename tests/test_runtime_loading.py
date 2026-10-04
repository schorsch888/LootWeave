"""Real owner/gateway startup, generation retry and close-during-start contracts."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock
from urllib.error import HTTPError
from urllib.request import ProxyHandler, Request, build_opener

from contracts import DomainError, canonical
from runtime import Runtime
from runtime_control import StdioOwner

class RuntimeLoadingTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        directory = Path(temporary.name)
        front = directory / "ui"
        front.mkdir()
        (front / "index.html").write_text("<html>synthetic shell</html>", encoding="utf-8")
        self.runtime = Runtime(directory, front_dir=front)
        self.addCleanup(self.runtime.stop)
        self.runtime.start()
        self.opener = build_opener(ProxyHandler({}))

    def call(self, method, path, payload=None, token=None):
        request = Request(self.runtime.gateway.url + path, method=method,
                          data=None if payload is None else canonical(payload).encode(),
                          headers={"Authorization": "Bearer " + (token or self.runtime.token),
                                   "Content-Type": "application/json"})
        try:
            with self.opener.open(request, timeout=10) as response:
                return json.load(response)
        except HTTPError as error:
            raise DomainError(json.load(error)["error"], error.code) from None

    def core(self):
        self.runtime.ensure_service("evaluation")
        self.assertTrue(self.call("GET", "/api/status")["core_ready"])

    def complete_manual_flow(self):
        self.core()
        demo = self.call("GET", "/api/demo")
        self.call("POST", "/api/profile/observations", {
            "observation_id": "demo-text", "method": "text", "raw_text": "Synthetic input"})
        profile = self.call("POST", "/api/profile/confirmations", {
            "request_id": "confirm", "profile_id": "fixture", "observation_id": "demo-text",
            "expected_revision": 0, "player_confirmed": True, "facts": demo["facts"]})
        pack = next(pack for pack in self.call("GET", "/api/knowledge/packs")["packs"]
                    if pack["execution_policy"] == "synthetic_only")
        body = {"request_id": "evaluate", "profile_id": "fixture", "profile_revision": profile["revision"],
                "pack_id": pack["pack_id"], "pack_version": pack["version"],
                "pack_hash": pack["pack_hash"], "intent": demo["intent"]}
        result = self.call("POST", "/api/evaluation/evaluations", body)
        self.assertEqual(result, self.call("POST", "/api/evaluation/evaluations", body))
        replay = self.call("POST", "/api/evaluation/evaluations/evaluate/replay", {})
        self.assertTrue(replay["identical"])
        status = self.call("GET", "/api/status")
        for name in ("ocr", "planning"):
            self.assertEqual({"state": "dormant", "generation": 0}, status["services"][name])
        self.assertEqual(3, len(self.runtime.children))

    def test_manual_confirmation_evaluation_and_frozen_replay_leave_optionals_dormant(self):
        self.complete_manual_flow()

    def test_concurrent_activation_spawns_once_and_does_not_publish_private_url(self):
        self.core()
        barrier = threading.Barrier(8)
        def ensure():
            barrier.wait(timeout=3)
            return self.call("POST", "/api/runtime/ensure", {"service": "planning"})
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(lambda _: ensure(), range(8)))
        self.assertTrue(all(result == {"service": "planning", "state": "ready", "generation": 1}
                            for result in results))
        self.assertEqual(4, len(self.runtime.children))
        status = self.call("GET", "/api/status")
        self.assertEqual("dormant", status["services"]["ocr"]["state"])
        self.assertNotIn("url", status["services"]["planning"])

    def test_dead_optional_is_not_restarted_by_status_or_business_and_explicit_retry_advances(self):
        self.core()
        self.call("POST", "/api/runtime/ensure", {"service": "planning"})
        child = self.runtime.records["planning"]["process"]
        child.terminate()
        child.wait(timeout=3)
        for _ in range(2):
            status = self.call("GET", "/api/status")
            self.assertEqual("failed", status["services"]["planning"]["state"])
        with self.assertRaisesRegex(DomainError, "service_unavailable"):
            self.call("GET", "/api/planning/health")
        self.assertEqual(1, self.runtime.records["planning"]["generation"])
        restarted = self.call("POST", "/api/runtime/ensure", {"service": "planning"})
        self.assertEqual(2, restarted["generation"])
        self.assertNotEqual(child.pid, self.runtime.records["planning"]["process"].pid)
        self.assertNotIn(child, self.runtime.children)
        self.assertTrue(self.call("GET", "/api/status")["core_ready"])

    def test_knowledge_recovery_rebinds_evaluation_and_planning_and_preserves_frozen_history(self):
        self.complete_manual_flow()
        demo = self.call("GET", "/api/demo")
        self.runtime.ensure_service("planning")
        pack = next(pack for pack in self.call("GET", "/api/knowledge/packs")["packs"]
                    if pack["execution_policy"] == "synthetic_only")
        source_body = {"facts": demo["facts"], "pack_id": pack["pack_id"],
                       "pack_version": pack["version"], "pack_hash": pack["pack_hash"]}
        before = self.call("POST", "/api/planning/sources/eligibility", source_body)
        child = self.runtime.records["knowledge"]["process"]
        child.terminate()
        child.wait(timeout=3)
        status = self.call("GET", "/api/status")
        self.assertFalse(status["core_ready"])
        for name in ("evaluation", "planning"):
            self.assertEqual("failed", status["services"][name]["state"])
        self.runtime.ensure_service("evaluation")
        self.runtime.ensure_service("planning")
        self.assertTrue(self.call("GET", "/api/status")["core_ready"])
        self.assertEqual(before, self.call("POST", "/api/planning/sources/eligibility", source_body))
        new_result = self.call("POST", "/api/evaluation/evaluations", {
            "request_id": "after-recovery", "profile_id": "fixture", "profile_revision": 1,
            "pack_id": pack["pack_id"], "pack_version": pack["version"],
            "pack_hash": pack["pack_hash"], "intent": demo["intent"]})
        self.assertEqual("after-recovery", new_result["evaluation_id"])
        self.assertTrue(self.call("POST", "/api/evaluation/evaluations/evaluate/replay", {})["identical"])
        self.assertEqual("dormant", self.runtime.status()["services"]["ocr"]["state"])

    def test_dependency_exit_during_readiness_prevents_publication(self):
        self.core()
        entered, release = threading.Event(), threading.Event()
        from transport import Client
        original = Client.call
        def pause(client, *args, **kwargs):
            entered.set()
            self.assertTrue(release.wait(timeout=3))
            return original(client, *args, **kwargs)
        with mock.patch.object(Client, "call", pause):
            with ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(self.runtime.ensure_service, "planning")
                try:
                    self.assertTrue(entered.wait(timeout=3))
                    child = self.runtime.records["knowledge"]["process"]
                    child.terminate()
                    child.wait(timeout=3)
                finally:
                    release.set()
                with self.assertRaisesRegex(DomainError, "service_dependency_unavailable"):
                    future.result(timeout=3)
        self.assertEqual("failed", self.runtime.status()["services"]["planning"]["state"])

    def test_source_fault_preserves_frozen_reads_without_restarting_dependencies(self):
        self.complete_manual_flow()
        child = self.runtime.records["profile"]["process"]
        evaluation = self.runtime.records["evaluation"]["process"]
        child.terminate()
        child.wait(timeout=3)
        state = self.call("GET", "/api/status")
        self.assertFalse(state["core_ready"])
        self.assertTrue(state["services"]["evaluation"]["historical_only"])
        self.assertNotIn("url", state["services"]["evaluation"])
        self.call("GET", "/api/evaluation/evaluations")
        self.call("GET", "/api/evaluation/evaluations/evaluate")
        self.assertTrue(self.call("POST", "/api/evaluation/evaluations/evaluate/replay", {})["identical"])
        self.assertEqual(1, self.runtime.records["profile"]["generation"])
        self.assertIsNone(evaluation.poll())
        with self.assertRaisesRegex(DomainError, "service_unavailable"):
            self.call("POST", "/api/evaluation/evaluations", {})
        self.runtime.ensure_service("evaluation")
        self.assertTrue(self.call("GET", "/api/status")["core_ready"])
        self.assertNotIn("historical_only", self.runtime.records["evaluation"])

    def test_background_failure_does_not_reset_an_active_evaluation_generation(self):
        self.core()
        with self.runtime.condition:
            self.runtime.records["profile"]["state"] = "failed"
            self.runtime.records["evaluation"].update(state="starting", generation=7)
        with mock.patch.object(self.runtime, "ensure_service", side_effect=DomainError("service_start_failed", 503)):
            self.runtime.start_core()
        self.assertEqual("starting", self.runtime.records["evaluation"]["state"])
        self.assertEqual(7, self.runtime.records["evaluation"]["generation"])

    def test_health_completion_after_deadline_cannot_publish_ready(self):
        self.core()
        from transport import Client
        with mock.patch.object(Client, "call", side_effect=lambda *args, **kwargs: time.sleep(.4)):
            with self.assertRaisesRegex(DomainError, "service_start_timeout"):
                self.runtime.ensure_service("planning", deadline=time.monotonic() + .3)
        self.assertEqual("failed", self.runtime.records["planning"]["state"])

    def test_ensure_is_authenticated_and_cannot_accept_executables_or_unknown_services(self):
        for body, error in (({"service": "shell"}, "unsupported_service"),
                            ({"service": "ocr", "command": "arbitrary"}, "invalid_service_request")):
            with self.assertRaisesRegex(DomainError, error):
                self.call("POST", "/api/runtime/ensure", body)
        with self.assertRaisesRegex(DomainError, "unauthorized"):
            self.call("POST", "/api/runtime/ensure", {"service": "ocr"}, token="wrong")
        self.assertEqual("dormant", self.runtime.status()["services"]["ocr"]["state"])

    def test_joined_failed_attempt_is_shared_and_a_fresh_request_can_retry(self):
        self.core()
        command = [sys.executable, "-u", "-c", "import time; time.sleep(.3)"]
        barrier = threading.Barrier(6)
        def attempt():
            barrier.wait(timeout=3)
            try:
                self.runtime.ensure_service("planning")
            except DomainError as error:
                return error.code
        with mock.patch.object(self.runtime, "service_command", return_value=command):
            with ThreadPoolExecutor(max_workers=6) as pool:
                errors = list(pool.map(lambda _: attempt(), range(6)))
        self.assertEqual(["service_start_failed"] * 6, errors)
        self.assertEqual(1, self.runtime.records["planning"]["generation"])
        self.assertEqual(3, len(self.runtime.children))
        self.assertEqual(2, self.runtime.ensure_service("planning")["generation"])

    def test_timeout_and_close_reclaim_registered_incomplete_children(self):
        self.core()
        command = [sys.executable, "-u", "-c", "import sys; sys.stdin.buffer.read()"]
        with mock.patch.object(self.runtime, "service_command", return_value=command):
            with self.assertRaisesRegex(DomainError, "service_start_timeout"):
                self.runtime.ensure_service("planning", deadline=time.monotonic() + .2)
            self.assertEqual(3, len(self.runtime.children))
            with ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(self.runtime.ensure_service, "planning")
                deadline = time.monotonic() + 2
                while "process" not in self.runtime.records["planning"]:
                    self.assertLess(time.monotonic(), deadline)
                    time.sleep(.01)
                processes = list(self.runtime.children)
                started = time.monotonic()
                self.runtime.stop()
                self.assertLess(time.monotonic() - started, 5)
                with self.assertRaises(DomainError):
                    future.result(timeout=2)
        self.assertTrue(all(process.poll() is not None for process in processes))
        with self.assertRaisesRegex(DomainError, "service_owner_stopping"):
            self.runtime.ensure_service("ocr")


class OwnerPipeTests(unittest.TestCase):
    def test_non_draining_owner_writer_does_not_block_request_deadlines(self):
        release, entered = threading.Event(), threading.Event()
        class Source:
            def readline(self, _limit):
                release.wait(timeout=3)
                return b""
        class Destination:
            def write(self, _data):
                entered.set()
                release.wait(timeout=3)
            def flush(self):
                pass
        owner = StdioOwner(Source(), Destination())
        owner.listen(lambda: None)
        try:
            started = time.monotonic()
            with mock.patch("runtime_control.START_TIMEOUT", .1):
                with self.assertRaisesRegex(DomainError, "service_start_timeout"):
                    owner.ensure_service("ocr")
            self.assertTrue(entered.is_set())
            self.assertLess(time.monotonic() - started, 1)
        finally:
            owner.close()
            release.set()

    def test_interleaved_responses_use_ids_and_eof_rejects_pending_work(self):
        # A real duplex pipe peer exercises framing/correlation, rather than a fake call result.
        peer = subprocess.Popen([sys.executable, "-u", "-c",
            "import sys,json; a=json.loads(sys.stdin.buffer.readline()); "
            "b=json.loads(sys.stdin.buffer.readline()); "
            "[print(json.dumps(dict(control_version=1,id=m['id'],result=dict(operation=m['operation']))),"
            "flush=True) for m in (b,a)]"], stdin=subprocess.PIPE, stdout=subprocess.PIPE)
        owner = StdioOwner(peer.stdout, peer.stdin)
        closed = threading.Event()
        owner.listen(closed.set)
        try:
            with ThreadPoolExecutor(max_workers=2) as pool:
                first = pool.submit(owner.status)
                second = pool.submit(owner.ensure_service, "ocr")
                self.assertEqual({"operation": "status"}, first.result(timeout=3))
                self.assertEqual({"operation": "ensure"}, second.result(timeout=3))
            self.assertTrue(closed.wait(timeout=3))
            with self.assertRaisesRegex(DomainError, "service_owner_unavailable"):
                owner.status()
        finally:
            owner.close()
            peer.stdin.close()
            peer.wait(timeout=3)
            peer.stdout.close()

    def test_invalid_control_frame_fails_closed(self):
        import io
        for data in (b'{"control_version":2,"id":"invalid"}\n', b"x" * 4097, b"{}"):
            owner = StdioOwner(io.BytesIO(data), io.BytesIO())
            closed = threading.Event()
            owner.listen(closed.set)
            self.assertTrue(closed.wait(timeout=2))
            with self.assertRaisesRegex(DomainError, "service_owner_unavailable"):
                owner.status()


if __name__ == "__main__":
    unittest.main()

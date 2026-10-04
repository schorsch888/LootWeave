"""Boundary tests for local measurement; no games, GUI or native OCR required."""
import copy
import io
import json
import math
import os
from pathlib import Path
import struct
import subprocess
import sys
import unittest
from types import SimpleNamespace
from urllib.error import HTTPError
from unittest.mock import patch

from scripts import benchmark_runtime as benchmark


class DistributionTests(unittest.TestCase):
    def test_nearest_rank_at_small_and_twenty_sample_boundaries(self):
        self.assertIsNone(benchmark.percentile([], .95))
        self.assertEqual(1, benchmark.percentile([1, 2], .5))
        self.assertEqual(19, benchmark.percentile(range(1, 21), .95))
        self.assertEqual(3, benchmark.percentile([3], 1))
        for fraction in (0, -.5, 1.01):
            with self.assertRaises(ValueError):
                benchmark.percentile([1], fraction)
        for value in (float("nan"), float("inf"), -1):
            with self.assertRaises(ValueError):
                benchmark.percentile([value], .5)

    def test_failed_duration_remains_in_distribution_and_blocks_workflow_checks(self):
        report = {"cycles": [{"cycle": index + 1, "passed": True, "cleanup_passed": True,
                              "seconds": {"launch_ready": index + 1}} for index in range(20)],
                  "policy": "legacy", "mode": "developer", "cohort": "control-a"}
        report["cycles"][-1].update(passed=False, failure_stage="launch_ready", failure_category="timeout")
        result = benchmark.summary(report)
        self.assertEqual(20, result["runs"])
        self.assertEqual(1, result["failed_runs"])
        self.assertEqual(20, result["metrics"]["launch_ready"]["samples"])
        self.assertEqual(19, result["metrics"]["launch_ready"]["p95_seconds"])
        self.assertEqual(20, result["metrics"]["launch_ready"]["max_seconds"])
        self.assertFalse(result["workflow_checks_passed"])

    def test_missing_ocr_is_explicit_and_prevents_completed_ocr_workflow(self):
        report = {"cycles": [{"cycle": index + 1, "passed": True, "ocr_skipped": "native_language_unavailable"}
                             for index in range(20)], "policy": "legacy", "mode": "developer"}
        result = benchmark.summary(report)
        self.assertTrue(result["cohort_completed_without_failure"])
        self.assertFalse(result["workflow_checks_passed"])
        self.assertEqual(0, result["metrics"]["ocr_first"]["samples"])
        self.assertTrue(all(cycle["ocr_skipped"] for cycle in result["cycles"]))


class SanitationTests(unittest.TestCase):
    def test_private_paths_tokens_inputs_and_dynamic_labels_cannot_escape(self):
        sensitive = "PRIVATE_SENTINEL"
        report = {"cohort": sensitive + "/person", "policy": "legacy", "mode": "developer",
                  "source_revision": sensitive, "paths_private": {"python": sensitive},
                  "token": sensitive, "environment": {"user": sensitive},
                  "identities": {"host": "a" * 64, sensitive: sensitive},
                  "cycles": [{"cycle": 1, "passed": False, "token": sensitive,
                              "failure_stage": sensitive + "/path", "failure_category": sensitive + ":error",
                              "raw_text": sensitive, "seconds": {sensitive: 1, "shutdown": .1},
                              "phases": {sensitive: 1, "ocr": {"ready_seconds": .5, "token": sensitive}},
                              "resource_samples": {sensitive: {"cpu_seconds": 1},
                                                   "work_peak": {"working_set_mib": 12, "token": sensitive}}}]}
        before = copy.deepcopy(report)
        result = benchmark.summary(report)
        self.assertNotIn(sensitive, json.dumps(result))
        self.assertEqual(before, report)
        self.assertEqual(12, result["cycles"][0]["resource_samples"]["work_peak"]["working_set_mib"])
        self.assertEqual(.5, result["cycles"][0]["phases"]["ocr"]["ready_seconds"])

    def test_http_failure_records_status_code_without_private_response_details(self):
        app = benchmark.Launch(SimpleNamespace(policy="on-demand"), Path("."))
        app.url, app.token = "http://127.0.0.1:1", "PRIVATE_SESSION"
        error = HTTPError(app.url, 503, "PRIVATE_REASON", {}, io.BytesIO(
            json.dumps({"error": "service_unavailable", "details": "PRIVATE_RESPONSE"}).encode()))
        with patch.object(app.opener, "open", side_effect=error):
            with self.assertRaises(HTTPError) as raised:
                app.call("POST", "/api/ocr/regions", {})
        self.assertIs(error, raised.exception)
        self.assertEqual({"status": 503, "code": "service_unavailable"}, app.last_http_error)
        self.assertNotIn("PRIVATE", json.dumps(app.last_http_error))
        self.assertEqual({"status": 503}, benchmark.sanitized_http_error(
            {"status": 503, "code": "PRIVATE:path", "details": "PRIVATE"}))
        self.assertEqual({}, benchmark.sanitized_http_error({"status": True, "code": 15}))

    def test_oversized_or_invalid_http_error_stays_bounded_and_raises_original_failure(self):
        for payload in (b"not json", b"x" * 8192):
            app = benchmark.Launch(SimpleNamespace(policy="on-demand"), Path("."))
            app.url, app.token = "http://127.0.0.1:1", "PRIVATE_SESSION"
            response = io.BytesIO(payload)
            error = HTTPError(app.url, 500, "PRIVATE_REASON", {}, response)
            with patch.object(app.opener, "open", side_effect=error):
                with self.assertRaises(HTTPError):
                    app.call("POST", "/api/ocr/regions", {})
            self.assertEqual({"status": 500}, app.last_http_error)
            self.assertLessEqual(response.tell(), 4097)


class ObserverDeadlineTests(unittest.TestCase):
    def test_ensure_observer_has_delivery_margin_and_business_observer_is_unchanged(self):
        app = benchmark.Launch(SimpleNamespace(policy="on-demand"), Path("."))
        app.url, app.token = "http://127.0.0.1:1", "PRIVATE_SESSION"
        timeouts = []
        def open_response(request, timeout):
            timeouts.append(timeout)
            return io.BytesIO(b'{"state":"ready"}')
        with patch.object(app.opener, "open", side_effect=open_response):
            app.ensure("ocr")
            app.call("POST", "/api/ocr/regions", {})
        self.assertEqual([10, 30], timeouts)

    def test_legacy_cohort_does_not_issue_an_ensure_request(self):
        app = benchmark.Launch(SimpleNamespace(policy="legacy"), Path("."))
        with patch.object(app, "call") as call:
            app.ensure("ocr")
        call.assert_not_called()


class FakeHandle:
    def __init__(self, pid, created=None):
        self.pid, self.dead, self.closed, self.terminated = pid, False, False, False
        self.created = pid if created is None else created

    def identity(self):
        return self.pid, self.created

    def exited(self, timeout=0):
        return self.dead

    def cpu(self):
        return .1

    def memory(self):
        return 2**20, 2 * 2**20

    def terminate(self):
        self.terminated = self.dead = True

    def close(self):
        self.closed = True


class OwnershipTests(unittest.TestCase):
    @unittest.skipUnless(os.name == "nt", "Windows owned-process counters")
    def test_real_owned_test_process_counters_and_natural_exit(self):
        process = subprocess.Popen([sys.executable, "-c", "import sys; sys.stdin.buffer.read()"],
                                   stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        tree = None
        try:
            tree = benchmark.OwnedTree(process.pid)
            counters = tree.counters()
            self.assertGreater(counters["working_set_mib"], 0)
            self.assertGreater(counters["private_commit_mib"], 0)
            self.assertGreaterEqual(counters["cpu_seconds"], 0)
            process.stdin.close()
            process.wait(timeout=5)
            self.assertTrue(tree.close())
            tree = None
            self.assertEqual(0, process.returncode)
        finally:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=5)
            if process.stdin and not process.stdin.closed:
                process.stdin.close()
            if tree:
                tree.close()

    def test_only_descendants_of_living_retained_handles_are_owned(self):
        snapshot = {100: 1, 101: 100, 102: 101, 200: 1, 201: 200}
        created = {}
        def factory(pid):
            created[pid] = FakeHandle(pid)
            return created[pid]
        tree = benchmark.OwnedTree(100, snapshot=lambda: snapshot, factory=factory, clock=lambda: 1000)
        tree.finished.set()
        tree.thread.join(2)
        tree.discover()
        self.assertEqual({100, 101, 102}, set(created))
        # PID 101 has exited; a reused PID must not authorize new descendants.
        created[101].dead = True
        snapshot[103] = 101
        tree.discover()
        self.assertNotIn(103, created)
        self.assertFalse(tree.close(timeout=0))
        self.assertTrue(all(handle.closed for handle in created.values()))
        self.assertTrue(created[100].terminated)
        self.assertFalse(created[101].terminated)
        self.assertNotIn(200, created)

    def test_natural_owned_shutdown_passes_without_termination(self):
        tree = benchmark.OwnedTree(100, snapshot=lambda: {100: 1}, factory=FakeHandle, clock=lambda: 1000)
        tree.finished.set()
        tree.thread.join(2)
        handle = tree.handles[100]
        handle.dead = True
        self.assertTrue(tree.close(timeout=0))
        self.assertFalse(handle.terminated)
        self.assertTrue(handle.closed)

    def test_missing_descendant_handle_is_bounded_and_recorded(self):
        def factory(pid):
            if pid != 100:
                raise benchmark.CheckFailed("owned_worker_handle_unavailable")
            return FakeHandle(pid)
        tree = benchmark.OwnedTree(100, snapshot=lambda: {100: 1, 101: 100}, factory=factory, clock=lambda: 1000)
        tree.finished.set()
        tree.thread.join(2)
        tree.discover()
        self.assertIn("descendant_exited_before_handle", tree.failures)
        tree.handles[100].dead = True
        self.assertTrue(tree.close(timeout=0))

    def discover_once(self, parents, identities, on_open=None):
        # No watcher thread or native counters: exercise the actual admission boundary deterministically.
        tree = benchmark.OwnedTree.__new__(benchmark.OwnedTree)
        root = FakeHandle(100, 10)
        opened = {}
        def factory(pid):
            if on_open:
                on_open(tree, pid)
            actual_pid, created = identities[pid]
            opened[pid] = FakeHandle(actual_pid, created)
            return opened[pid]
        tree.snapshot, tree.factory, tree.clock = lambda: parents, factory, lambda: 50
        tree.handles, tree.created = {100: root}, {100: 10}
        import threading
        tree.lock, tree.failures = threading.Lock(), []
        tree.peak_working_set = tree.peak_private_commit = 0
        tree.discover()
        return tree, opened

    def test_valid_creation_order_admits_complete_chain_and_counters(self):
        tree, opened = self.discover_once({101: 100, 102: 101}, {101: (101, 20), 102: (102, 30)})
        self.assertEqual({100, 101, 102}, set(tree.handles))
        self.assertEqual([], tree.failures)
        self.assertTrue(all(not handle.closed for handle in opened.values()))
        self.assertEqual(3, tree.counters()["retained_handles"])

    def test_stale_parent_pid_child_born_before_current_parent_is_closed(self):
        tree, opened = self.discover_once({101: 100, 102: 101}, {101: (101, 9), 102: (102, 20)})
        self.assertEqual({100}, set(tree.handles))
        self.assertEqual({101}, set(opened))  # The rejected process cannot anchor grandchildren.
        self.assertTrue(opened[101].closed)
        self.assertFalse(opened[101].terminated)
        self.assertEqual(["descendant_identity_uncertain"], tree.failures)
        self.assertEqual(1, tree.counters()["retained_handles"])

    def test_recycled_child_pid_created_after_snapshot_is_closed(self):
        tree, opened = self.discover_once({101: 100}, {101: (101, 51)})
        self.assertNotIn(101, tree.handles)
        self.assertTrue(opened[101].closed)
        self.assertFalse(opened[101].terminated)
        self.assertEqual(["descendant_identity_uncertain"], tree.failures)

    def test_queried_pid_mismatch_closes_candidate_before_counter_use(self):
        tree, opened = self.discover_once({101: 100}, {101: (200, 20)})
        self.assertEqual({100}, set(tree.handles))
        self.assertTrue(opened[101].closed)
        self.assertFalse(opened[101].terminated)
        self.assertEqual(1, tree.counters()["retained_handles"])

    def test_parent_exit_during_open_rejects_and_closes_candidate(self):
        tree, opened = self.discover_once({101: 100}, {101: (101, 20)},
                                         on_open=lambda owner, _pid: setattr(owner.handles[100], "dead", True))
        self.assertEqual({100}, set(tree.handles))
        self.assertTrue(opened[101].closed)
        self.assertFalse(opened[101].terminated)
        self.assertEqual(["descendant_identity_uncertain"], tree.failures)


class FictionalFixtureTests(unittest.TestCase):
    def test_fixture_is_valid_original_bounded_bmp_and_deterministic(self):
        image = benchmark.synthetic_bmp()
        self.assertEqual(image, benchmark.synthetic_bmp())
        self.assertEqual(b"BM", image[:2])
        self.assertEqual(len(image), struct.unpack_from("<I", image, 2)[0])
        width, height = struct.unpack_from("<ii", image, 18)
        self.assertEqual((420, 100), (width, height))
        self.assertEqual(54 + ((width * 3 + 3) // 4 * 4) * height, len(image))
        self.assertIn(b"\0\0\0", image[54:])
        self.assertIn(b"\xff\xff\xff", image[54:])

    def test_timed_failure_is_retained(self):
        cycle = {"seconds": {}}
        def fail():
            raise benchmark.CheckFailed("synthetic_failure")
        with self.assertRaises(benchmark.CheckFailed):
            benchmark.timed(cycle, "ocr_first", fail)
        self.assertGreaterEqual(cycle["seconds"]["ocr_first"], 0)


class DynamicVerifierTests(unittest.TestCase):
    def test_late_workers_are_registered_by_service_and_old_handles_retained(self):
        from scripts import check_desktop
        app = check_desktop.Desktop.__new__(check_desktop.Desktop)
        app.workers, app.worker_handles, app.handles_by_pid = [], {}, {}
        app.dynamic_registry = True
        statuses = iter([
            {"services": {"ocr": {"state": "dormant", "generation": 0},
                          "profile": {"state": "ready", "generation": 1, "pid": 100}}},
            {"services": {"ocr": {"state": "ready", "generation": 1, "pid": 102},
                          "profile": {"state": "ready", "generation": 1, "pid": 100}}},
            {"services": {"ocr": {"state": "ready", "generation": 2, "pid": 103},
                          "profile": {"state": "ready", "generation": 1, "pid": 100}}},
        ])
        app.call = lambda *args, **kwargs: next(statuses) if args[:2] == ("GET", "/api/status") else {"state": "ready"}
        with patch.object(check_desktop, "OwnedProcess", FakeHandle):
            app.status()
            first_ocr = app.ensure("ocr")
            replacement = app.ensure("ocr")
        self.assertEqual(102, first_ocr.pid)
        self.assertEqual(103, replacement.pid)
        self.assertEqual(100, app.worker_handles["profile"].pid)
        self.assertEqual({100, 102, 103}, set(app.handles_by_pid))
        self.assertEqual(3, len(app.workers))


if __name__ == "__main__":
    unittest.main()

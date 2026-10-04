"""Process integration includes readiness, session auth, crash degradation and cleanup."""
from __future__ import annotations

import os
import tempfile
import unittest
from unittest import mock
from pathlib import Path

from contracts import DomainError
from runtime import Runtime
from transport import Client


class RuntimeTests(unittest.TestCase):
    def test_lifecycle_crash_degradation_and_no_orphan_children(self):
        with tempfile.TemporaryDirectory() as directory:
            front=Path(directory)/"ui"
            front.mkdir()
            (front/"index.html").write_text("<html><body>synthetic</body></html>")
            runtime = Runtime(Path(directory), front_dir=front)
            try:
                with mock.patch.dict(os.environ, {"LOOTWEAVE_PARENT_JOB": "1"}):
                    runtime.start()
                processes = list(runtime.children)
                client = Client(runtime.gateway.url, runtime.token)
                # Gateway API is intentionally not the service /v1 namespace.
                from urllib.request import Request, build_opener, ProxyHandler
                import json
                opener = build_opener(ProxyHandler({}))
                def status():
                    request = Request(runtime.gateway.url + "/api/status",
                                      headers={"Authorization": "Bearer " + runtime.token})
                    with opener.open(request) as response:
                        return json.load(response)
                self.assertFalse(status()["degraded"])
                processes[2].terminate()
                processes[2].wait(timeout=3)
                health = status()
                self.assertTrue(health["degraded"])
                self.assertEqual("failed", health["services"]["evaluation"]["state"])
            finally:
                runtime.stop()
            self.assertTrue(all(p.poll() is not None for p in processes))

    def test_second_instance_is_rejected_without_touching_first(self):
        with tempfile.TemporaryDirectory() as directory:
            front=Path(directory)/"ui"
            front.mkdir()
            (front/"index.html").write_text("<html><body>synthetic</body></html>")
            first, second = Runtime(Path(directory), front_dir=front), Runtime(Path(directory), front_dir=front)
            try:
                first.start()
                with self.assertRaisesRegex(DomainError, "instance_already_running"):
                    second.start()
                self.assertTrue(all(p.poll() is None for p in first.children))
            finally:
                second.stop()
                first.stop()


if __name__ == "__main__":
    unittest.main()

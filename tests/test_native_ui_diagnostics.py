"""Native verifier diagnostics must disclose only fixed stage/category values."""
from __future__ import annotations

import sys
import subprocess
import io
import json
import tempfile
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from check_native_ui import (NativeCheckFailed, cleanup_run, failure_category,
                             finish_run_failure, host_diagnostic, require_probe_message, run, safe_failure)
from check_desktop import CheckFailed


class NativeUiDiagnosticsTests(unittest.TestCase):
    def test_connection_failure_before_readiness_keeps_safe_probe_cause(self):
        with self.assertRaises(NativeCheckFailed) as caught:
            require_probe_message({"event": "complete", "passed": False,
                                   "stage": "webview_connection",
                                   "failure_code": "webview_connection_timeout",
                                   "native_rejections": ["private content"]},
                                  "ready", "webview_connection", "native_readiness_failed")
        self.assertEqual(caught.exception.diagnostic,
                         {"stage": "webview_connection", "category": "webview_connection_timeout"})

    def test_unknown_diagnostics_never_disclose_probe_values(self):
        for value in ["https://private.invalid/?token=secret", str(Path("private_location").resolve()), "a" * 64,
                      "private_dom_content", None, [], {"stage": "native_ipc"}]:
            with self.subTest(value=type(value).__name__):
                self.assertEqual(safe_failure(value, value), {"stage": "unknown", "category": "unknown"})

    def test_failed_flow_preserves_allowlisted_stage_and_timeout_class(self):
        with self.assertRaises(NativeCheckFailed) as caught:
            require_probe_message({"event": "complete", "passed": False,
                                   "stage": "native_ipc", "failure_code": "TimeoutError"},
                                  "complete", "native_flow", "native_flow_failed")
        self.assertEqual(caught.exception.diagnostic, {"stage": "native_ipc", "category": "timeout"})

    def test_malformed_message_uses_fixed_harness_failure(self):
        for message in [None, [], "private content", {"event": "invalid"},
                        {"event": "complete", "passed": "truthy"}]:
            with self.subTest(message=type(message).__name__):
                with self.assertRaises(NativeCheckFailed) as caught:
                    require_probe_message(message, "complete", "native_flow", "native_flow_failed")
                self.assertEqual(caught.exception.diagnostic,
                                 {"stage": "native_flow", "category": "native_flow_failed"})

    def test_valid_messages_leave_success_gate_intact(self):
        require_probe_message({"event": "ready"}, "ready", "webview_connection", "native_readiness_failed")
        require_probe_message({"event": "complete", "passed": True},
                              "complete", "native_flow", "native_flow_failed")

    def test_process_exceptions_disclose_only_known_class_categories(self):
        for error, expected in [(OSError("private path"), "os_error"),
                                (subprocess.TimeoutExpired("private command", 5), "timeout"),
                                (RuntimeError("private content"), "unknown")]:
            with self.subTest(error=type(error).__name__):
                self.assertEqual(failure_category(error), expected)

    def test_cleanup_failure_cannot_mask_primary_connection_failure(self):
        primary = NativeCheckFailed("webview_connection", "webview_connection_timeout")
        cleanup = {"stage": "owned_cleanup", "category": "owned_cleanup_failed"}
        with self.assertRaises(NativeCheckFailed) as caught:
            finish_run_failure(primary, cleanup, {"alive": True, "exit_code": None})
        self.assertIs(caught.exception, primary)
        self.assertEqual(caught.exception.diagnostic,
                         {"stage": "webview_connection", "category": "webview_connection_timeout"})
        self.assertEqual(caught.exception.cleanup_diagnostic, cleanup)

    def test_cleanup_failure_alone_still_fails_the_gate(self):
        with self.assertRaises(NativeCheckFailed) as caught:
            finish_run_failure(None, {"stage": "owned_cleanup", "category": "owned_cleanup_failed"},
                               {"alive": False, "exit_code": 0})
        self.assertEqual(caught.exception.diagnostic,
                         {"stage": "owned_cleanup", "category": "owned_cleanup_failed"})

    def test_job_exit_racing_termination_is_checked_by_owned_handle(self):
        host = Mock()
        host.poll.return_value = 0
        handle = Mock()
        handle.exited.side_effect = [False, True]
        handle.terminate.side_effect = CheckFailed("owned_worker_fault_failed")
        with patch("check_native_ui.owned_process_state", return_value={"exited": True}), \
             patch("check_native_ui.record_shutdown"):
            self.assertIsNone(cleanup_run(host, None, [handle], False, Path("unused"), Mock()))
        handle.exited.assert_any_call(5)
        handle.close.assert_called_once()

    def test_failed_termination_with_live_owned_child_still_fails(self):
        host = Mock()
        host.poll.return_value = 0
        handle = Mock()
        handle.exited.return_value = False
        handle.terminate.side_effect = CheckFailed("owned_worker_fault_failed")
        with patch("check_native_ui.owned_process_state", return_value={"exited": False}), \
             patch("check_native_ui.record_shutdown"):
            self.assertEqual(cleanup_run(host, None, [handle], False, Path("unused"), Mock()),
                             {"stage": "owned_cleanup", "category": "owned_cleanup_failed"})
        handle.close.assert_called_once()

    def test_cleanup_continues_reaping_after_probe_cleanup_error(self):
        probe = Mock()
        probe.poll.return_value = None
        probe.kill.side_effect = OSError("private content")
        host = Mock()
        host.poll.return_value = None
        with patch("check_native_ui.descendants", return_value=set()), \
             patch("check_native_ui.record_shutdown"):
            self.assertEqual(cleanup_run(host, probe, [], False, Path("unused"), Mock()),
                             {"stage": "owned_cleanup", "category": "owned_cleanup_failed"})
        host.kill.assert_called_once()
        host.wait.assert_called_once_with(timeout=5)

    def test_host_diagnostic_is_bounded_and_excludes_identity(self):
        host = Mock()
        for code, expected in [(None, {"alive": True, "exit_code": None}),
                               (0xC0000005, {"alive": False, "exit_code": 0xC0000005}),
                               ("private content", {"alive": False, "exit_code": None}),
                               (2**80, {"alive": False, "exit_code": None})]:
            with self.subTest(code=type(code).__name__):
                host.poll.return_value = code
                with patch("check_native_ui.host_elevation", return_value=None):
                    self.assertEqual(host_diagnostic(host), {**expected, "elevated": None})

    def test_run_keeps_primary_and_cleanup_and_uses_private_host_port_hook(self):
        host, probe = Mock(), Mock()
        host.poll.return_value = 0
        probe.stdout = io.BytesIO((json.dumps({"event": "complete", "passed": False,
                                               "stage": "webview_connection",
                                               "failure_code": "webview_connection_timeout"}) + "\n").encode())
        cleanup = {"stage": "owned_cleanup", "category": "owned_cleanup_failed"}
        with tempfile.TemporaryDirectory() as output, \
             patch("check_native_ui.frozen_environment", return_value={}), \
             patch("check_native_ui.host_elevation", return_value=True), \
             patch("check_native_ui.subprocess.Popen", side_effect=[host, probe]) as launch, \
             patch("check_native_ui.cleanup_run", side_effect=lambda *args: (args[-1].close(), cleanup)[1]):
            with self.assertRaises(NativeCheckFailed) as caught:
                run(Path("host"), Path("resources"), Path("node"), Path(output), 1)
            self.assertEqual(caught.exception.diagnostic,
                             {"stage": "webview_connection", "category": "webview_connection_timeout"})
            self.assertEqual(caught.exception.cleanup_diagnostic, cleanup)
            self.assertEqual(caught.exception.host_diagnostic, {"alive": False, "exit_code": 0, "elevated": True})
            env = launch.call_args_list[0].kwargs["env"]
            self.assertTrue(0 < int(env["LOOTWEAVE_NATIVE_VERIFY_PORT"]) <= 65535)
            self.assertFalse(any(key.startswith("WEBVIEW2_") for key in env))
            self.assertIn("--hidden-ui", launch.call_args_list[0].args[0])


if __name__ == "__main__":
    unittest.main()

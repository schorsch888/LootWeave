"""Native verifier diagnostics must disclose only fixed stage/category values."""
from __future__ import annotations

import sys
import subprocess
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from check_native_ui import NativeCheckFailed, failure_category, require_probe_message, safe_failure


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


if __name__ == "__main__":
    unittest.main()

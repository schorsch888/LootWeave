"""Native verifier diagnostics must disclose only fixed stage/category values."""
from __future__ import annotations

import sys
import subprocess
import io
import json
import shutil
import tempfile
from pathlib import Path
import unittest
from contextlib import redirect_stdout
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from check_native_ui import (NativeCheckFailed, checkpoint, cleanup_run, failure_category,
                             finish_run_failure, host_diagnostic, require_probe_message, run, safe_failure)
from check_desktop import CheckFailed


class NativeUiDiagnosticsTests(unittest.TestCase):
    def test_page_discovery_waits_for_creation_within_the_connection_deadline(self):
        node = shutil.which("node")
        if node is None:
            self.skipTest("Node.js is required for the native page discovery check")
        result = subprocess.run(
            [node, "--input-type=module"],
            cwd=Path(__file__).resolve().parents[1],
            input='''
import assert from "node:assert/strict";
import { waitForNativePage } from "./scripts/native_page.mjs";
const native = { url: () => "http://127.0.0.1:12345/" };
const blank = { url: () => "about:blank" };
let contexts = [{ pages: () => [blank] }];
const browser = { contexts: () => contexts };
const pending = waitForNativePage(browser, Date.now() + 1000);
setTimeout(() => { contexts = [{ pages: () => [blank, native] }]; }, 10);
assert.equal(await pending, native);
contexts = [];
const delayedContext = waitForNativePage(browser, Date.now() + 1000);
setTimeout(() => { contexts = [{ pages: () => [native] }]; }, 10);
assert.equal(await delayedContext, native);
contexts = [{ pages: () => [blank] }];
const deadline = Date.now() + 20;
assert.equal(await waitForNativePage(browser, deadline), undefined);
assert.ok(Date.now() >= deadline);
assert.equal(await waitForNativePage(browser, Date.now() - 1), undefined);
''',
            text=True, capture_output=True, timeout=10,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_checkpoint_discloses_only_bounded_stage_cycle_and_owned_exit_states(self):
        host, probe = Mock(), Mock()
        host.poll.return_value = 0xC0000005
        primary = NativeCheckFailed("private stage", "private credential")
        with tempfile.TemporaryDirectory() as output:
            folder = Path(output)
            for code in [None, -1, 2**32 - 1, -(2**31), 2**32, -(2**31) - 1, True, "private credential"]:
                probe.poll.return_value = code
                stream = io.StringIO()
                with redirect_stdout(stream):
                    checkpoint(folder, "private cycle", "private stage", host, probe, primary)
                state = json.loads((folder / "checkpoint.json").read_text(encoding="utf-8"))
                expected = code if type(code) is int and -(2**31) <= code < 2**32 else None
                self.assertEqual(state, {"cycle": None, "stage": "unknown",
                                        "host": {"alive": False, "exit_code": 0xC0000005},
                                        "probe": {"alive": code is None, "exit_code": expected},
                                        "primary": {"stage": "unknown", "category": "unknown"}})
                self.assertEqual(stream.getvalue(), "Native WebView checkpoint: cycle=None stage=unknown\n")
                self.assertFalse((folder / "checkpoint.tmp").exists())

    def test_primary_and_last_stage_survive_cleanup_that_abruptly_exits(self):
        host, probe = Mock(), Mock()
        host.poll.return_value = 0xC0000005
        probe.poll.return_value = 1
        probe.stdout = io.BytesIO((json.dumps({"event": "complete", "passed": False,
                                               "stage": "native_ipc", "failure_code": "TimeoutError",
                                               "private_value": "private credential"}) + "\n").encode())
        stream = io.StringIO()

        def abrupt_cleanup(*args):
            args[-1].close()
            self.assertIn("failure before cleanup: cycle=9 stage=native_ipc category=timeout", stream.getvalue())
            state = json.loads((args[-2] / "checkpoint.json").read_text(encoding="utf-8"))
            self.assertEqual(state["stage"], "owned_cleanup")
            self.assertEqual(state["primary"], {"stage": "native_ipc", "category": "timeout"})
            self.assertEqual(state["host"]["exit_code"], 0xC0000005)
            self.assertEqual(state["probe"]["exit_code"], 1)
            raise SystemExit(1)

        with tempfile.TemporaryDirectory() as output, redirect_stdout(stream), \
             patch("check_native_ui.frozen_environment", return_value={}), \
             patch("check_native_ui.HostProcess"), \
             patch("check_native_ui.host_elevation", return_value=None), \
             patch("check_native_ui.subprocess.Popen", side_effect=[host, probe]), \
             patch("check_native_ui.cleanup_run", side_effect=abrupt_cleanup) as cleanup:
            with self.assertRaises(SystemExit):
                run(Path("host"), Path("resources"), Path("node"), Path(output), 9)
        cleanup.assert_called_once()
        self.assertNotIn("private credential", stream.getvalue())

    def test_diagnostic_output_failures_do_not_prevent_owned_cleanup_or_mask_primary(self):
        host, probe = Mock(), Mock()
        host.poll.return_value = 0
        probe.poll.return_value = 1
        probe.stdout = io.BytesIO((json.dumps({"event": "complete", "passed": False,
                                               "stage": "native_flow", "failure_code": "native_browser_error"})
                                  + "\n").encode())

        def cleanup_error_log(*args):
            args[-1].close()
            return None

        with tempfile.TemporaryDirectory() as output, \
             patch("check_native_ui.frozen_environment", return_value={}), \
             patch("check_native_ui.HostProcess"), \
             patch("check_native_ui.host_elevation", return_value=None), \
             patch("check_native_ui.subprocess.Popen", side_effect=[host, probe]), \
             patch("check_native_ui.cleanup_run", side_effect=cleanup_error_log) as cleanup, \
             patch("builtins.print", side_effect=BrokenPipeError("private output error")), \
             patch.object(Path, "write_text", side_effect=OSError("private disk error")):
            with self.assertRaises(NativeCheckFailed) as caught:
                run(Path("host"), Path("resources"), Path("node"), Path(output), 1)
        cleanup.assert_called_once()
        self.assertEqual(caught.exception.diagnostic,
                         {"stage": "native_flow", "category": "native_browser_error"})

    def test_success_checkpoints_preserve_process_coverage_and_shutdown_deadlines(self):
        host, probe = Mock(), Mock()
        host.pid = 123
        host.poll.return_value = host.returncode = probe.poll.return_value = probe.returncode = 0
        probe.stdout = io.BytesIO(b'{"event":"ready","webview_version":"synthetic"}\n'
                                 b'{"event":"complete","passed":true,"checks":[]}\n')
        handles = [Mock() for _ in range(8)]
        for handle in handles:
            handle.exited.return_value = True
            handle.memory.return_value = (1, 2)
        stream = io.StringIO()
        with tempfile.TemporaryDirectory() as output, redirect_stdout(stream), \
             patch("check_native_ui.frozen_environment", return_value={}), \
             patch("check_native_ui.host_elevation", return_value=None), \
             patch("check_native_ui.subprocess.Popen", side_effect=[host, probe]), \
             patch("check_native_ui.owned_hidden_window"), patch("check_native_ui.close_window"), \
             patch("check_native_ui.descendants", return_value=handles[1:]) as discover, \
             patch("check_native_ui.HostProcess", return_value=handles[0]) as owned, \
             patch("check_native_ui.owned_process_state", return_value={"exited": True}):
            result = run(Path("host"), Path("resources"), Path("node"), Path(output), 1)
            state = json.loads((Path(output) / "run-01/checkpoint.json").read_text(encoding="utf-8"))
        owned.assert_called_once_with(host)
        discover.assert_called_once_with(handles[0], [])
        host.wait.assert_called_once_with(timeout=12)
        probe.wait.assert_called_once_with(timeout=5)
        self.assertEqual(state["stage"], "owned_cleanup")
        self.assertEqual(state["host"]["exit_code"], 0)
        self.assertEqual(state["probe"]["exit_code"], 0)
        self.assertIn("stage=native_descendant_exit", stream.getvalue())
        self.assertIn("owned_window_hidden_and_nonforeground", result["checks"])
        for handle in handles:
            handle.close.assert_called_once()
            handle.terminate.assert_not_called()
            self.assertTrue(any(call.args and 0 <= call.args[0] <= 8 for call in handle.exited.call_args_list))

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
                                (CheckFailed("owned_process_creation_time_unavailable"),
                                 "owned_process_creation_time_unavailable"),
                                (CheckFailed("owned_process_identity_unavailable"),
                                 "owned_process_identity_unavailable"),
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

    def test_cleanup_discovers_from_retained_host_and_known_handles_without_pid_reopen(self):
        host = Mock()
        host.poll.return_value = None
        root, known, discovered = Mock(), Mock(), Mock()
        handles = [root, known]
        with patch("check_native_ui.descendants", return_value=[discovered]) as discover, \
             patch("check_native_ui.OwnedProcess") as reopen, \
             patch("check_native_ui.owned_process_state", return_value={"exited": True}), \
             patch("check_native_ui.record_startup"), patch("check_native_ui.record_shutdown"):
            self.assertIsNone(cleanup_run(host, None, handles, False, Path("unused"), Mock()))
        discover.assert_called_once_with(root, [known])
        reopen.assert_not_called()
        self.assertEqual(handles, [root, known, discovered])
        host.kill.assert_called_once()
        host.wait.assert_called_once_with(timeout=5)
        for handle in handles:
            handle.close.assert_called_once()

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

    def test_run_keeps_primary_and_cleanup_and_uses_owned_debug_port_and_loopback_probe(self):
        host, probe = Mock(), Mock()
        host.poll.return_value = 0
        probe.stdout = io.BytesIO((json.dumps({"event": "complete", "passed": False,
                                               "stage": "webview_connection",
                                               "failure_code": "webview_connection_timeout"}) + "\n").encode())
        cleanup = {"stage": "owned_cleanup", "category": "owned_cleanup_failed"}
        with tempfile.TemporaryDirectory() as output, \
             patch("check_native_ui.frozen_environment", return_value={}), \
             patch("check_native_ui.HostProcess"), \
             patch("check_native_ui.host_elevation", return_value=True), \
             patch("check_native_ui.subprocess.Popen", side_effect=[host, probe]) as launch, \
             patch("check_native_ui.cleanup_run", side_effect=lambda *args: (args[-1].close(), cleanup)[1]):
            with self.assertRaises(NativeCheckFailed) as caught:
                run(Path("host"), Path("resources"), Path("node"), Path(output), 1)
            self.assertEqual(caught.exception.diagnostic,
                             {"stage": "webview_connection", "category": "webview_connection_timeout"})
            self.assertEqual(caught.exception.cleanup_diagnostic, cleanup)
            self.assertEqual(caught.exception.host_diagnostic, {"alive": False, "exit_code": 0, "elevated": True})
            host_call, probe_call = launch.call_args_list
            host_args = host_call.args[0]
            self.assertIn("--hidden-ui", host_args)
            port = host_args[host_args.index("--hidden-ui-debug-port") + 1]
            self.assertTrue(0 < int(port) <= 65535)
            self.assertFalse(any(key.startswith("WEBVIEW2_") for key in host_call.kwargs["env"]))
            self.assertNotIn("LOOTWEAVE_NATIVE_VERIFY_PORT", host_call.kwargs["env"])
            self.assertEqual(port, probe_call.args[0][probe_call.args[0].index("--port") + 1])
            self.assertEqual("127.0.0.1,localhost,::1", probe_call.kwargs["env"]["NO_PROXY"])
            self.assertEqual("127.0.0.1,localhost,::1", probe_call.kwargs["env"]["no_proxy"])


if __name__ == "__main__":
    unittest.main()

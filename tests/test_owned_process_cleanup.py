"""Retained-handle cleanup must attempt every owned child and keep orphan gates."""
from __future__ import annotations

import sys
from pathlib import Path
import subprocess
import unittest
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from check_desktop import CheckFailed, Desktop


class OwnedProcessCleanupTests(unittest.TestCase):
    def desktop(self):
        desktop = Desktop.__new__(Desktop)
        desktop.process = Mock()
        desktop.process.poll.return_value = 0
        desktop.host_handle = Mock()
        desktop.workers = [Mock(), Mock()]
        for handle in desktop.workers:
            handle.exited.return_value = True
        return desktop

    def assert_closed(self, desktop, handles, host):
        for handle in handles:
            handle.close.assert_called_once()
        host.close.assert_called_once()
        self.assertEqual([], desktop.workers)
        self.assertIsNone(desktop.host_handle)
        desktop.process.stdin.close.assert_called()
        desktop.process.stdout.close.assert_called_once()
        desktop.process.stderr.close.assert_called_once()

    def test_normal_exit_closes_all_handles_and_streams_without_termination(self):
        desktop = self.desktop()
        handles, host = list(desktop.workers), desktop.host_handle
        desktop.stop()
        self.assert_closed(desktop, handles, host)
        for handle in handles:
            handle.terminate.assert_not_called()

    def test_termination_exit_race_keeps_orphan_gate_and_closes_later_handles(self):
        desktop = self.desktop()
        handles, host = list(desktop.workers), desktop.host_handle
        handles[0].exited.side_effect = [False, True]
        handles[0].terminate.side_effect = CheckFailed("owned_worker_fault_failed")
        with self.assertRaisesRegex(CheckFailed, "orphan_worker_after_host_exit"):
            desktop.stop()
        handles[0].exited.assert_any_call(5)
        self.assert_closed(desktop, handles, host)

    def test_live_orphan_after_failed_termination_still_fails_and_continues(self):
        desktop = self.desktop()
        handles, host = list(desktop.workers), desktop.host_handle
        handles[0].exited.return_value = False
        handles[0].terminate.side_effect = OSError("unavailable")
        with self.assertRaisesRegex(CheckFailed, "orphan_worker_after_host_exit"):
            desktop.stop()
        self.assert_closed(desktop, handles, host)

    def test_child_wait_error_attempts_reclamation_and_all_closes(self):
        desktop = self.desktop()
        handles, host = list(desktop.workers), desktop.host_handle
        handles[0].exited.side_effect = [OSError("unavailable"), True]
        with self.assertRaisesRegex(CheckFailed, "owned_cleanup_failed"):
            desktop.stop()
        handles[0].terminate.assert_called_once()
        self.assert_closed(desktop, handles, host)

    def test_child_close_error_does_not_skip_remaining_handles_or_streams(self):
        desktop = self.desktop()
        handles, host = list(desktop.workers), desktop.host_handle
        handles[0].close.side_effect = OSError("unavailable")
        with self.assertRaisesRegex(CheckFailed, "owned_cleanup_failed"):
            desktop.stop()
        self.assert_closed(desktop, handles, host)

    def test_host_stop_error_does_not_skip_child_cleanup(self):
        desktop = self.desktop()
        handles, host = list(desktop.workers), desktop.host_handle
        desktop.process.poll.return_value = None
        desktop.process.stdin.close.side_effect = OSError("unavailable")
        with self.assertRaisesRegex(CheckFailed, "owned_cleanup_failed"):
            desktop.stop()
        desktop.process.kill.assert_called_once()
        desktop.process.wait.assert_called_once_with(timeout=5)
        self.assert_closed(desktop, handles, host)

    def test_host_timeout_preserves_existing_kill_wait_fallback(self):
        desktop = self.desktop()
        handles, host = list(desktop.workers), desktop.host_handle
        desktop.process.poll.return_value = None
        desktop.process.wait.side_effect = [subprocess.TimeoutExpired("owned-host", 12), 0]
        desktop.stop()
        desktop.process.kill.assert_called_once()
        self.assertEqual([12, 5], [call.kwargs["timeout"] for call in desktop.process.wait.call_args_list])
        self.assert_closed(desktop, handles, host)

    def test_host_handle_or_stream_close_errors_do_not_skip_later_streams(self):
        desktop = self.desktop()
        handles, host = list(desktop.workers), desktop.host_handle
        host.close.side_effect = OSError("unavailable")
        desktop.process.stdout.close.side_effect = OSError("unavailable")
        with self.assertRaisesRegex(CheckFailed, "owned_cleanup_failed"):
            desktop.stop()
        self.assert_closed(desktop, handles, host)


if __name__ == "__main__":
    unittest.main()

"""Synthetic ancestry/time checks; no Windows APIs, hosts or processes run."""
import unittest

from scripts.check_native_ui import select_descendants


class NativeUiOwnershipTests(unittest.TestCase):
    def test_old_orphan_with_reused_root_pid_is_excluded(self):
        parents = {20: 10, 30: 20, 40: 10}
        created = {10: 100, 20: 90, 30: 110, 40: 120}
        self.assertEqual({40}, select_descendants(parents, created, 10, 200))

    def test_old_orphan_with_reused_intermediate_pid_is_excluded(self):
        parents = {20: 10, 30: 20, 40: 30, 50: 20}
        created = {10: 100, 20: 120, 30: 110, 40: 130, 50: 140}
        self.assertEqual({20, 50}, select_descendants(parents, created, 10, 200))

    def test_valid_multigeneration_chain_is_order_independent(self):
        parents = {40: 30, 30: 20, 20: 10, 80: 99}
        created = {10: 100, 20: 110, 30: 120, 40: 130, 80: 140}
        self.assertEqual({20, 30, 40}, select_descendants(parents, created, 10, 200))

    def test_gone_child_cannot_anchor_an_unverified_descendant(self):
        parents = {20: 10, 30: 20, 40: 10}
        created = {10: 100, 30: 120, 40: 130}
        self.assertEqual({40}, select_descendants(parents, created, 10, 200))

    def test_pid_reused_after_snapshot_started_is_excluded(self):
        parents = {20: 10, 30: 20, 40: 10}
        created = {10: 100, 20: 201, 30: 205, 40: 190}
        self.assertEqual({40}, select_descendants(parents, created, 10, 200))

    def test_timestamp_boundaries_and_missing_root_fail_closed(self):
        parents = {20: 10, 30: 20, 40: 10}
        created = {10: 100, 20: 100, 30: 200, 40: 201}
        self.assertEqual({20, 30}, select_descendants(parents, created, 10, 200))
        self.assertEqual(set(), select_descendants(parents, {}, 10, 200))
        self.assertEqual(set(), select_descendants(parents, created, 10, 99))


if __name__ == "__main__":
    unittest.main()

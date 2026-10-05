"""Native maintenance verifier boundaries, with synthetic stores and a fake host."""
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from maintenance import DATABASES, backup, restore, verify
from scripts.check_desktop import CheckFailed, native_maintenance
from storage import initialize


class DesktopMaintenanceVerifierTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.data = self.root / "data"
        self.destination = self.root / "backup"
        self.executable = self.root / "synthetic-host.exe"
        self.resources = self.root / "resources"
        self.make_stores(DATABASES[:2])
        environment = patch("scripts.check_desktop.frozen_environment", return_value={})
        environment.start()
        self.addCleanup(environment.stop)

    def make_stores(self, names):
        for name in names:
            initialize(self.data / name, "CREATE TABLE IF NOT EXISTS synthetic (value TEXT);")

    def response(self, operation, count, status=0, **extra):
        body = {"operation": operation, "storage_version": 1, "files": count, **extra}
        return SimpleNamespace(returncode=status, stdout=json.dumps(body).encode(), stderr=b"")

    def call(self, flag="--backup-to", data=None, other=None, accepted=True):
        return native_maintenance(self.executable, self.resources, data or self.data,
                                  flag, other or self.destination, accepted=accepted)

    def fake_backup(self, *_args, **_kwargs):
        manifest = backup(self.data, self.destination)
        return self.response("backup", len(manifest["files"]))

    def rewrite_manifest(self, directory, manifest):
        (directory / "backup-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    def test_dormant_planning_two_core_stores_backup_and_restore(self):
        with patch("scripts.check_desktop.subprocess.run", side_effect=self.fake_backup):
            self.assertEqual(2, self.call()["files"])
        restored = self.root / "restored"

        def fake_restore(*_args, **_kwargs):
            manifest = restore(self.destination, restored)
            return self.response("restore", len(manifest["files"]))

        with patch("scripts.check_desktop.subprocess.run", side_effect=fake_restore):
            self.assertEqual(2, self.call("--restore-from", restored)["files"])
        self.assertEqual(verify(self.destination), verify(restored))
        self.assertFalse((self.data / DATABASES[2]).exists())
        self.assertFalse((restored / DATABASES[2]).exists())

    def test_eager_three_stores_are_all_required_and_preserved(self):
        self.make_stores(DATABASES[2:])
        with patch("scripts.check_desktop.subprocess.run", side_effect=self.fake_backup):
            self.assertEqual(3, self.call()["files"])
        self.assertEqual(set(DATABASES), set(verify(self.destination)["files"]))

    def test_internally_valid_backup_cannot_omit_existing_planning_database(self):
        self.make_stores(DATABASES[2:])
        image = b"BM synthetic capture evidence"
        capture = self.data / "ocr" / (hashlib.sha256(image).hexdigest() + ".bmp")
        capture.parent.mkdir()
        capture.write_bytes(image)

        def omit_planning(*_args, **_kwargs):
            manifest = backup(self.data, self.destination)
            (self.destination / DATABASES[2]).unlink()
            del manifest["files"][DATABASES[2]]
            self.rewrite_manifest(self.destination, manifest)
            # This valid three-file backup would pass the old fixed >= 3 gate.
            self.assertEqual(3, len(verify(self.destination)["files"]))
            return self.response("backup", 3)

        with patch("scripts.check_desktop.subprocess.run", side_effect=omit_planning):
            with self.assertRaisesRegex(CheckFailed, "native_maintenance_files_missing"):
                self.call()

    def test_existing_capture_cannot_be_omitted_with_its_manifest_entry(self):
        image = b"BM another synthetic capture"
        capture = self.data / "ocr" / (hashlib.sha256(image).hexdigest() + ".bmp")
        capture.parent.mkdir()
        capture.write_bytes(image)

        def omit_capture(*_args, **_kwargs):
            manifest = backup(self.data, self.destination)
            name = capture.relative_to(self.data).as_posix()
            (self.destination / name).unlink()
            del manifest["files"][name]
            self.rewrite_manifest(self.destination, manifest)
            return self.response("backup", 2)

        with patch("scripts.check_desktop.subprocess.run", side_effect=omit_capture):
            with self.assertRaisesRegex(CheckFailed, "native_maintenance_files_missing"):
                self.call()

    def test_source_requires_both_core_stores_before_native_invocation(self):
        (self.data / DATABASES[1]).unlink()
        with patch("scripts.check_desktop.subprocess.run") as run:
            with self.assertRaisesRegex(CheckFailed, "native_maintenance_core_files_missing"):
                self.call()
        run.assert_not_called()

    def test_missing_file_and_changed_hash_are_rejected(self):
        for corruption in ("missing", "changed"):
            with self.subTest(corruption=corruption):
                self.destination = self.root / corruption

                def corrupt(*_args, **_kwargs):
                    self.fake_backup()
                    path = self.destination / DATABASES[0]
                    if corruption == "missing":
                        path.unlink()
                    else:
                        with path.open("ab") as stream:
                            stream.write(b"tampering")
                    return self.response("backup", 2)

                with patch("scripts.check_desktop.subprocess.run", side_effect=corrupt):
                    with self.assertRaisesRegex(CheckFailed, "native_maintenance_integrity_failed"):
                        self.call()

    def test_reported_count_must_match_verified_manifest_exactly(self):
        def wrong_count(*_args, **_kwargs):
            self.fake_backup()
            return self.response("backup", 3)

        with patch("scripts.check_desktop.subprocess.run", side_effect=wrong_count):
            with self.assertRaisesRegex(CheckFailed, "native_maintenance_response_invalid"):
                self.call()

    def test_restore_cannot_change_verified_manifest_metadata(self):
        backup(self.data, self.destination)
        restored = self.root / "restored"

        def altered_restore(*_args, **_kwargs):
            manifest = restore(self.destination, restored)
            manifest["created_at"] = "changed"
            self.rewrite_manifest(restored, manifest)
            return self.response("restore", 2)

        with patch("scripts.check_desktop.subprocess.run", side_effect=altered_restore):
            with self.assertRaisesRegex(CheckFailed, "native_maintenance_files_missing"):
                self.call("--restore-from", restored)

    def test_active_backup_requires_ownership_rejection_without_inventory_reads(self):
        rejected = self.response("backup", 0, status=1, error="instance_already_running")
        with patch("scripts.check_desktop.subprocess.run", return_value=rejected), \
                patch("scripts.check_desktop.maintenance_inputs") as inventory:
            self.assertEqual("instance_already_running", self.call(accepted=False)["error"])
        inventory.assert_not_called()
        self.assertFalse(self.destination.exists())

    def test_other_native_error_does_not_satisfy_active_backup_check(self):
        rejected = self.response("backup", 0, status=1, error="backup_source_missing")
        with patch("scripts.check_desktop.subprocess.run", return_value=rejected):
            with self.assertRaisesRegex(CheckFailed, "active_backup_not_rejected"):
                self.call(accepted=False)


if __name__ == "__main__":
    unittest.main()

"""Offline maintenance backup/restore tests using only synthetic fixture data."""
import copy
import hashlib
import json
import shutil
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from contracts import DomainError, canonical
from maintenance import DATABASES, backup, restore, verify
from services.evaluation.app import Evaluation
from services.knowledge.app import Knowledge
from services.planning.app import Planning
from services.profile.app import Profile
from storage import acquire_instance_lock


ROOT = Path(__file__).resolve().parents[1]
DEMO = json.loads((ROOT / "fixtures/demo.json").read_text(encoding="utf-8"))


class LocalAPI:
    def __init__(self, app):
        self.app = app

    def call(self, method, path, body=None):
        return self.app.handle(method, path, body or {})


class NoOnlineServices:
    def call(self, *_args, **_kwargs):
        raise AssertionError("restore replay must use its frozen local inputs")


class MaintenanceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.data = self.root / "data"
        self.profile = Profile(self.data / "profile")
        self.knowledge = Knowledge(ROOT / "knowledge-packs")
        self.planning = Planning(self.data / "planning", LocalAPI(self.knowledge))
        self.evaluation = Evaluation(self.data / "evaluation", LocalAPI(self.profile), LocalAPI(self.knowledge))
        self.make_frozen_evaluation()

    def make_frozen_evaluation(self):
        facts = copy.deepcopy(DEMO["facts"])
        observation = {"observation_id": "demo-text", "method": "text", "raw_text": "Synthetic fixture"}
        self.profile.observe(observation)
        self.profile.confirm({"request_id": "synthetic-confirmation", "profile_id": "synthetic-profile",
                              "observation_id": observation["observation_id"], "expected_revision": 0,
                              "player_confirmed": True, "facts": facts})
        pack = next(value for value in self.knowledge.handle("GET", "/v1/packs", {})["packs"]
                    if value["execution_policy"] == "synthetic_only")
        body = {"request_id": "synthetic-evaluation", "profile_id": "synthetic-profile", "profile_revision": 1,
                "pack_id": pack["pack_id"], "pack_version": pack["version"], "pack_hash": pack["pack_hash"],
                "intent": copy.deepcopy(DEMO["intent"])}
        self.result = self.evaluation.create(body)

    def test_backup_restore_keeps_frozen_evaluation_replay_offline(self):
        backup_dir = self.root / "backup"
        restored = self.root / "restored"
        manifest = backup(self.data, backup_dir)
        self.assertEqual(set(DATABASES), set(manifest["files"]))
        restore(backup_dir, restored)
        self.assertEqual(1, verify(restored)["storage_version"])

        offline = Evaluation(restored / "evaluation", NoOnlineServices(), NoOnlineServices())
        replay = offline.replay(self.result["evaluation_id"])
        self.assertTrue(replay["identical"])
        self.assertEqual(self.result, replay["result"])

    def test_restore_refuses_existing_target_and_preserves_both_trees(self):
        backup_dir = self.root / "backup"
        backup(self.data, backup_dir)
        source_manifest = (backup_dir / "backup-manifest.json").read_bytes()
        target = self.root / "existing"
        target.mkdir()
        sentinel = target / "keep.bin"
        sentinel.write_bytes(b"pre-existing target")

        with self.assertRaisesRegex(DomainError, "backup_destination_exists"):
            restore(backup_dir, target)
        self.assertEqual(b"pre-existing target", sentinel.read_bytes())
        self.assertEqual(source_manifest, (backup_dir / "backup-manifest.json").read_bytes())

    def test_backup_refuses_an_active_instance_lock_without_changing_data(self):
        database = self.data / "profile/profile.sqlite3"
        before = database.read_bytes()
        destination = self.root / "backup"
        with closing(acquire_instance_lock(self.data)):
            with self.assertRaisesRegex(DomainError, "instance_already_running"):
                backup(self.data, destination)
        self.assertEqual(before, database.read_bytes())
        self.assertFalse(destination.exists())

    def test_unsupported_database_schema_is_rejected_without_rewriting_source_bytes(self):
        database = self.data / "profile/profile.sqlite3"
        with closing(sqlite3.connect(database)) as db:
            db.execute("PRAGMA user_version=2")
            db.commit()
        before = database.read_bytes()

        with self.assertRaisesRegex(DomainError, "incompatible_backup_storage"):
            backup(self.data, self.root / "backup")
        self.assertEqual(before, database.read_bytes())
        self.assertFalse((self.root / "backup").exists())

    def test_verify_rejects_modified_extra_and_missing_backup_content(self):
        pristine = self.root / "pristine"
        backup(self.data, pristine)

        modified = self.root / "modified"
        shutil.copytree(pristine, modified)
        with (modified / "profile/profile.sqlite3").open("ab") as stream:
            stream.write(b"changed")
        with self.assertRaisesRegex(DomainError, "backup_integrity_error"):
            verify(modified)

        extra = self.root / "extra"
        shutil.copytree(pristine, extra)
        (extra / "unexpected.txt").write_text("not part of a backup", encoding="utf-8")
        with self.assertRaisesRegex(DomainError, "backup_file_unrecognized"):
            verify(extra)

        missing = self.root / "missing"
        shutil.copytree(pristine, missing)
        (missing / "evaluation/evaluation.sqlite3").unlink()
        with self.assertRaisesRegex(DomainError, "backup_integrity_error"):
            verify(missing)

    def test_backup_copies_only_supported_databases_and_hashed_ocr_capture(self):
        capture = b"synthetic private OCR capture bytes"
        capture_name = hashlib.sha256(capture).hexdigest() + ".bmp"
        (self.data / "ocr").mkdir()
        (self.data / "ocr" / capture_name).write_bytes(capture)
        (self.data / "instance.lock").write_bytes(b"closed lock marker")
        (self.data / "WebView2/Default/Cache").mkdir(parents=True)
        (self.data / "WebView2/Default/Cache/data.bin").write_bytes(b"webview cache")
        (self.data / "user-notes.txt").write_text("synthetic unrelated user file", encoding="utf-8")

        backup_dir = self.root / "backup"
        manifest = backup(self.data, backup_dir)
        expected = {*DATABASES, "ocr/" + capture_name}
        self.assertEqual(expected, set(manifest["files"]))
        self.assertEqual(capture, (backup_dir / "ocr" / capture_name).read_bytes())
        self.assertFalse((backup_dir / "instance.lock").exists())
        self.assertFalse((backup_dir / "WebView2").exists())
        self.assertFalse((backup_dir / "user-notes.txt").exists())

    def test_backup_and_restore_reject_nested_source_and_destination_paths(self):
        with self.assertRaisesRegex(DomainError, "backup_directories_overlap"):
            backup(self.data, self.data / "nested-backup")

        backup_dir = self.root / "backup"
        backup(self.data, backup_dir)
        with self.assertRaisesRegex(DomainError, "backup_directories_overlap"):
            restore(backup_dir, backup_dir / "nested-restore")

    def test_verify_rejects_malformed_manifest_and_traversal_entries(self):
        malformed = self.root / "malformed"
        backup(self.data, malformed)
        (malformed / "backup-manifest.json").write_text("{not-json", encoding="utf-8")
        with self.assertRaisesRegex(DomainError, "invalid_json"):
            verify(malformed)

        traversal = self.root / "traversal"
        backup(self.data, traversal)
        manifest_path = traversal / "backup-manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["files"]["../outside.sqlite3"] = {"size": 1, "sha256": "0" * 64}
        manifest_path.write_text(canonical(manifest), encoding="utf-8")
        outside = self.root / "outside.sqlite3"
        outside.write_bytes(b"must remain untouched")
        with self.assertRaisesRegex(DomainError, "invalid_backup_manifest"):
            restore(traversal, self.root / "restored")
        self.assertEqual(b"must remain untouched", outside.read_bytes())
        self.assertFalse((self.root / "restored").exists())


if __name__ == "__main__":
    unittest.main()

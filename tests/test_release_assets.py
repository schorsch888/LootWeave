import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from scripts.release_assets import ReleaseError, stage_release, verify_release


COMMIT = "0123456789abcdef0123456789abcdef01234567"
OTHER = "abcdef0123456789abcdef0123456789abcdef01"


class ReleaseAssetsTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        (self.root / "desktop").mkdir()
        (self.root / "desktop/tauri.conf.json").write_text(json.dumps({"version": "0.1.0"}), encoding="utf-8")
        portable = self.root / "dist/LootWeave-portable-windows-x64.zip"
        portable.parent.mkdir(parents=True)
        with zipfile.ZipFile(portable, "w") as archive:
            archive.writestr("portable.json", json.dumps({"source_commit": COMMIT}))
            archive.writestr("LootWeave.exe", b"synthetic executable")
        installers = self.root / "desktop/target/release/bundle/nsis"
        installers.mkdir(parents=True)
        (installers / "LootWeave-setup.exe").write_bytes(b"synthetic installer")

    def tearDown(self):
        self.temporary.cleanup()

    def test_stage_then_verify(self):
        release = stage_release(self.root, COMMIT)
        self.assertEqual(release, verify_release(self.root, COMMIT))
        names = {path.name for path in release.iterdir()}
        self.assertEqual(names, {
            "LootWeave-0.1.0-portable-windows-x64.zip",
            "LootWeave-0.1.0-windows-x64-setup.exe",
            "build-manifest.json", "SHA256SUMS.txt",
        })

    def test_portable_source_commit_mismatch(self):
        archive = self.root / "dist/LootWeave-portable-windows-x64.zip"
        archive.unlink()
        with zipfile.ZipFile(archive, "w") as bundle:
            bundle.writestr("portable.json", json.dumps({"source_commit": OTHER}))
        with self.assertRaisesRegex(ReleaseError, "source commit does not match"):
            stage_release(self.root, COMMIT)

    def test_verify_rejects_different_source_commit(self):
        stage_release(self.root, COMMIT)
        with self.assertRaisesRegex(ReleaseError, "identity or schema"):
            verify_release(self.root, OTHER)

    def test_tampered_release_asset_fails_verify(self):
        release = stage_release(self.root, COMMIT)
        installer = release / "LootWeave-0.1.0-windows-x64-setup.exe"
        installer.write_bytes(b"tampered")
        with self.assertRaisesRegex(ReleaseError, "does not match manifest"):
            verify_release(self.root, COMMIT)

    def test_manifest_path_traversal_fails_verify(self):
        release = stage_release(self.root, COMMIT)
        manifest_path = release / "build-manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["files"][0]["name"] = "../outside.zip"
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        with self.assertRaisesRegex(ReleaseError, "file names or schema"):
            verify_release(self.root, COMMIT)

    def test_extra_release_file_fails_verify(self):
        release = stage_release(self.root, COMMIT)
        (release / "unexpected.txt").write_text("extra", encoding="utf-8")
        with self.assertRaisesRegex(ReleaseError, "missing, extra, or non-file"):
            verify_release(self.root, COMMIT)

    def test_existing_release_directory_is_preserved(self):
        release = self.root / "dist/release"
        release.mkdir()
        sentinel = release / "keep.txt"
        sentinel.write_text("preserve", encoding="utf-8")
        with self.assertRaisesRegex(ReleaseError, "already exists"):
            stage_release(self.root, COMMIT)
        self.assertEqual(sentinel.read_text(encoding="utf-8"), "preserve")

    def test_installer_must_be_unique(self):
        installers = self.root / "desktop/target/release/bundle/nsis"
        (installers / "second.exe").write_bytes(b"second")
        with self.assertRaisesRegex(ReleaseError, "exactly one NSIS installer"):
            stage_release(self.root, COMMIT)


if __name__ == "__main__":
    unittest.main()
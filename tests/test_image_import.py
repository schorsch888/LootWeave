"""Imported screenshot provenance never establishes game identity or capture time."""
import base64
import tempfile
import unittest
from pathlib import Path

from contracts import DomainError
from services.ocr.app import OCR
from services.profile.app import Profile
from test_window_capture import request


class ImageImportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.ocr = OCR(self.root / "ocr", command=str(self.root / "missing-command"))
        self.body = request()
        self.body.pop("capture_context")
        self.body["image_origin"] = "file"
        self.body["bounds"].update(x=0, y=0)

    def test_original_pixels_unknown_time_and_unconfirmed_source_are_preserved(self):
        result = self.ocr.recognize(self.body)
        self.assertEqual("file", result["image_origin"])
        self.assertEqual("unknown", result["source_capture_time"])
        self.assertNotIn("capture_context", result)
        self.assertTrue(result["requires_confirmation"])
        self.assertEqual("unconfirmed", result["state"])
        self.assertEqual(base64.b64decode(self.body["image_base64"]),
                         (self.root / "ocr" / (result["image_hash"] + ".bmp")).read_bytes())
        profile = Profile(self.root / "profile")
        profile.store_observation(result)
        with profile.connect() as db:
            self.assertEqual(1, db.execute("SELECT COUNT(*) FROM observations").fetchone()[0])
            self.assertEqual(0, db.execute("SELECT COUNT(*) FROM revisions").fetchone()[0])

    def test_file_cannot_claim_native_window_capture(self):
        self.body["capture_context"] = request()["capture_context"]
        with self.assertRaises(DomainError) as failure:
            self.ocr.recognize(self.body)
        self.assertEqual("image_file_capture_context_conflict", failure.exception.code)
        self.assertEqual([], list((self.root / "ocr").glob("*.bmp")))

    def test_unknown_origin_is_rejected_before_storage(self):
        self.body["image_origin"] = "unverified-provider"
        with self.assertRaises(DomainError) as failure:
            self.ocr.recognize(self.body)
        self.assertEqual("invalid_image_origin", failure.exception.code)

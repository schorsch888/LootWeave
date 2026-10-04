"""Window capture provenance stays bounded, private and unconfirmed."""
from __future__ import annotations

import base64
import copy
import json
import struct
import tempfile
import unittest
from pathlib import Path

from contracts import DomainError
from services.ocr.app import OCR
from services.profile.app import Profile


def request():
    width, height = 3, 2
    pixels = bytes(12 * height)
    bmp = (b"BM" + struct.pack("<I", 54 + len(pixels)) + bytes(4) + struct.pack("<I", 54)
           + struct.pack("<IiiHHII", 40, width, -height, 1, 24, 0, len(pixels))
           + bytes(16) + pixels)
    return {
        "observation_id": "window-observation", "image_base64": base64.b64encode(bmp).decode(),
        "bounds": {"x": -990, "y": 60, "width": width, "height": height}, "language": "en-US",
        "capture_context": {
            "format_version": 1, "game_id": "deskrawl", "executable": "Deskrawl.exe",
            "window_binding": "a" * 32,
            "client_bounds": {"x": -1000, "y": 40, "width": 1000, "height": 800},
            "relative_bounds": {"x": 10, "y": 20, "width": width, "height": height},
            "verification": "foreground_before_and_after", "captured_at_ms": 1791044209000,
            "game_version": "unknown", "game_build": "unknown",
        },
    }


class WindowCaptureTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.ocr = OCR(self.directory / "ocr", command=str(self.directory / "missing-command"))
        self.profile = Profile(self.directory / "profile")

    def test_capture_context_survives_ocr_failure_and_append_only_profile_storage(self):
        body = request()
        observed = self.ocr.recognize(body)
        self.assertEqual(observed["error"], "ocr_unavailable")
        self.assertEqual(observed["capture_context"], body["capture_context"])
        self.assertTrue(observed["requires_confirmation"])
        self.assertEqual(observed["state"], "unconfirmed")
        stored = self.profile.observe(observed)
        self.assertEqual(stored, self.profile.handle("GET", "/v1/observations/window-observation", {}))
        self.assertEqual(stored["capture_context"]["game_version"], "unknown")
        facts = json.loads((Path(__file__).resolve().parents[1] / "fixtures/demo.json").read_text())["facts"]
        for evidence in facts["evidence"]:
            if evidence["source_ref"].startswith("observation://"):
                evidence["source_ref"] = "observation://window-observation"
        # A Deskrawl window cannot establish a snapshot for the fictional demonstration game.
        with self.assertRaisesRegex(DomainError, "observation_game_conflict"):
            self.profile.confirm({"request_id": "scope-mismatch", "profile_id": "window-profile",
                                  "observation_id": "window-observation", "expected_revision": 0,
                                  "player_confirmed": True, "facts": facts})

        with self.profile.connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM revisions").fetchone()[0], 0)

    def test_legacy_screen_capture_does_not_invent_game_identity(self):
        body = request()
        del body["capture_context"]
        observed = self.ocr.recognize(body)
        self.assertNotIn("capture_context", observed)
        self.assertTrue(observed["requires_confirmation"])

    def test_claimed_version_foreign_game_private_path_and_extra_fields_are_rejected(self):
        changes = (
            {"game_id": "other-game"}, {"game_version": "1.0.0"}, {"game_build": "25690430"},
            {"executable": "private-folder/Deskrawl.exe"}, {"window_binding": "private-window"},
            {"verification": "game_verified"}, {"title": "Private game account"},
            {"format_version": True}, {"captured_at_ms": False}, {"captured_at_ms": 2**53},
        )
        for changeset in changes:
            with self.subTest(changes=changeset):
                body = request()
                body["capture_context"].update(changeset)
                with self.assertRaisesRegex(DomainError, "invalid_capture_context"):
                    self.ocr.recognize(body)
                self.assertEqual(list((self.directory / "ocr").iterdir()), [])

    def test_relative_capture_cannot_cross_window_or_disagree_with_image_bounds(self):
        bodies = []
        body = request(); body["capture_context"]["relative_bounds"]["x"] = -1; bodies.append(body)
        body = request(); body["capture_context"]["relative_bounds"]["x"] = 999; bodies.append(body)
        body = request(); body["capture_context"]["client_bounds"]["x"] += 1; bodies.append(body)
        body = request(); body["capture_context"]["relative_bounds"]["height"] += 1; bodies.append(body)
        for body in bodies:
            with self.subTest(body=body):
                with self.assertRaisesRegex(DomainError, "capture_context_bounds_mismatch"):
                    self.ocr.recognize(body)

    def test_malformed_rectangles_and_boolean_coordinates_are_rejected(self):
        changes = (
            {"client_bounds": None}, {"relative_bounds": []},
            {"relative_bounds": {"x": True, "y": 0, "width": 3, "height": 2}},
            {"client_bounds": {"x": 2**31, "y": 0, "width": 100, "height": 100}},
            {"client_bounds": {"x": 0, "y": 0, "width": 0, "height": 100}},
        )
        for changeset in changes:
            body = request(); body["capture_context"].update(changeset)
            with self.subTest(changes=changeset), self.assertRaisesRegex(DomainError, "invalid_capture_context"):
                self.ocr.recognize(body)

    def test_reusing_observation_id_cannot_rewrite_original_window_binding(self):
        observed = self.ocr.recognize(request())
        self.profile.observe(observed)
        changed = copy.deepcopy(observed)
        changed["capture_context"]["window_binding"] = "b" * 32
        with self.assertRaisesRegex(DomainError, "observation_id_conflict"):
            self.profile.observe(changed)
        self.assertEqual(self.profile.handle("GET", "/v1/observations/window-observation", {})["capture_context"],
                         observed["capture_context"])


if __name__ == "__main__":
    unittest.main()

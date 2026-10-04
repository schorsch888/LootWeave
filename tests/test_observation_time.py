"""Synthetic source-clock regressions; no image capture, OCR helper or user input."""
from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path

from contracts import DomainError, canonical, digest, timestamp_milliseconds
from services.evaluation.domain import evaluate
from services.knowledge.app import Knowledge
from services.profile.app import Profile
from services.profile.domain import build_fingerprint

ROOT = Path(__file__).resolve().parents[1]
DEMO = json.loads((ROOT / "fixtures/demo.json").read_text(encoding="utf-8"))
CAPTURE_MS = 1767225600000


def capture_observation(observation_id="demo-text", milliseconds=CAPTURE_MS):
    return {"observation_id": observation_id, "method": "ocr", "raw_text": "Synthetic source clock",
            "image_ref": "capture://" + "0" * 64,
            "capture_context": {"game_id": DEMO["facts"]["context"]["game_id"], "captured_at_ms": milliseconds}}


def confirmation(observation_id="demo-text", request_id="confirm-clock", revision=0, facts=None):
    value = copy.deepcopy(DEMO["facts"] if facts is None else facts)
    value["evidence"][0]["source_ref"] = "observation://" + observation_id
    return {"request_id": request_id, "profile_id": "demo", "observation_id": observation_id,
            "expected_revision": revision, "player_confirmed": True, "facts": value}


def seed_legacy_capture_revision(profile):
    """A v1 revision the preceding service could accept; keep its exact payload."""
    observed = capture_observation(milliseconds=CAPTURE_MS + 1000)
    profile.observe(observed)
    body = confirmation(request_id="legacy-confirm")
    facts = body["facts"]
    record = {"contract_version": 1, "profile_id": "demo", "revision": 1,
              "observation_id": observed["observation_id"], "facts": facts,
              "facts_hash": digest(facts), "build_hash": build_fingerprint(facts)}
    encoded = canonical(record)
    with profile.connect() as db:
        db.execute("INSERT INTO revisions VALUES (?,?,?)", ("demo", 1, encoded))
        db.execute("INSERT INTO confirmations VALUES (?,?,?,?)", (body["request_id"], digest(body), "demo", 1))
    return body, record, encoded


class ObservationTimeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.profile = Profile(Path(self.temp.name))

    def test_millisecond_conversion_is_exact_bounded_and_never_accepts_bool(self):
        self.assertEqual("1970-01-01T00:00:00.001000+00:00", timestamp_milliseconds(1).isoformat())
        self.assertEqual("2026-01-01T00:00:00.001000+00:00", timestamp_milliseconds(CAPTURE_MS+1).isoformat())
        self.assertEqual("9999-12-31T23:59:59.999000+00:00", timestamp_milliseconds(253402300799999).isoformat())
        for value in (True, False, None, "1767225600000", 0, -1, CAPTURE_MS+0.0,
                      253402300800000, 2**53-1, 2**53):
            with self.subTest(value=value), self.assertRaisesRegex(DomainError, "invalid_capture_time"):
                timestamp_milliseconds(value)

    def test_invalid_recorded_clock_cannot_enter_observation_storage(self):
        for value in (True, "1767225600000", -1, 253402300800000):
            observed = capture_observation(milliseconds=value)
            with self.subTest(value=value), self.assertRaisesRegex(DomainError, "invalid_capture_time"):
                self.profile.observe(observed)
        with self.profile.connect() as db:
            self.assertEqual(0, db.execute("SELECT COUNT(*) FROM observations").fetchone()[0])
        self.assertEqual("unconfirmed", self.profile.observe(capture_observation())["state"])

    def test_source_time_conflict_rejects_before_writes_and_does_not_consume_request_id(self):
        observed = capture_observation(milliseconds=CAPTURE_MS+1)
        self.profile.observe(observed)
        original = self.profile.handle("GET", "/v1/observations/demo-text", {})
        body = confirmation()
        with self.assertRaisesRegex(DomainError, "observation_time_conflict"):
            self.profile.confirm(body)
        with self.profile.connect() as db:
            self.assertEqual(0, db.execute("SELECT COUNT(*) FROM revisions").fetchone()[0])
            self.assertEqual(0, db.execute("SELECT COUNT(*) FROM confirmations").fetchone()[0])
        body["facts"]["evidence"][0]["captured_at"] = "2026-01-01T00:00:00.001Z"
        body["facts"]["captured_at"] = "2026-01-01T00:00:00.001Z"
        result = self.profile.confirm(body)
        self.assertEqual("verified", result["observation_time_status"])
        self.assertEqual(result, self.profile.confirm(body))
        self.assertEqual(body["facts"], result["facts"])
        self.assertEqual(original, self.profile.handle("GET", "/v1/observations/demo-text", {}))

    def test_timezone_equivalence_is_accepted_but_submillisecond_difference_is_not(self):
        self.profile.observe(capture_observation(milliseconds=CAPTURE_MS+1))
        body = confirmation()
        body["facts"]["evidence"][0]["captured_at"] = "2026-01-01T08:00:00.001+08:00"
        body["facts"]["captured_at"] = "2026-01-01T00:00:00.001Z"
        result = self.profile.confirm(body)
        self.assertEqual("verified", result["observation_time_status"])
        changed = copy.deepcopy(body)
        changed.update(request_id="submillisecond", expected_revision=1)
        changed["facts"]["evidence"][0]["captured_at"] = "2026-01-01T00:00:00.001001Z"
        with self.assertRaisesRegex(DomainError, "observation_time_conflict"):
            self.profile.confirm(changed)
        self.assertEqual(result, self.profile.read("demo", 1))

    def test_every_linked_record_is_checked_including_nonfirst_evidence(self):
        self.profile.observe(capture_observation())
        body = confirmation()
        second = copy.deepcopy(body["facts"]["evidence"][0])
        second.update(id="second-capture-input", captured_at="2026-01-01T00:00:00.001Z")
        body["facts"]["evidence"].append(second)
        with self.assertRaisesRegex(DomainError, "observation_time_conflict"):
            self.profile.confirm(body)
        second["captured_at"] = "2026-01-01T08:00:00+08:00"
        self.assertEqual("verified", self.profile.confirm(body)["observation_time_status"])

    def test_distinct_recorded_times_keep_sources_and_trigger_cross_time_blocking(self):
        old_body = confirmation()
        self.profile.observe(capture_observation())
        first = self.profile.confirm(old_body)
        self.profile.observe(capture_observation("later", CAPTURE_MS+1000))
        facts = copy.deepcopy(first["facts"])
        current = copy.deepcopy(facts["evidence"][0])
        current.update(id="later-input", source_ref="observation://later", captured_at="2026-01-01T00:00:01Z")
        facts["evidence"].append(current)
        facts["captured_at"] = current["captured_at"]
        body = confirmation("later", "confirm-later", 1, facts)
        # This source is still from the previous observation; do not relabel it.
        body["facts"]["evidence"][0]["source_ref"] = "observation://demo-text"
        second = self.profile.confirm(body)
        self.assertEqual("verified", second["observation_time_status"])
        self.assertEqual("observation://demo-text", second["facts"]["evidence"][0]["source_ref"])
        knowledge = Knowledge(ROOT / "knowledge-packs").handle("GET", "/v1/packs/synthetic-leveling/1.0.0", {})
        result = evaluate(second, knowledge, copy.deepcopy(DEMO["intent"]))
        self.assertIn("cross_time_snapshot", result["blockers"])
        self.assertEqual("needs_confirmation", result["retention"])
        self.assertEqual(first, self.profile.read("demo", 1))

    def test_manual_and_older_contexts_without_recorded_time_do_not_invent_a_clock(self):
        observed = {"observation_id": "demo-text", "method": "text", "raw_text": "Synthetic manual input"}
        self.profile.observe(observed)
        body = confirmation()
        first = self.profile.confirm(body)
        self.assertEqual("not_recorded", first["observation_time_status"])
        self.assertEqual(body["facts"], first["facts"])
        observed = capture_observation("older")
        del observed["capture_context"]["captured_at_ms"]
        self.profile.observe(observed)
        second = self.profile.confirm(confirmation("older", "confirm-older", 1))
        self.assertEqual("not_recorded", second["observation_time_status"])

    def test_legacy_conflict_is_reported_without_rewriting_payload_or_idempotent_history(self):
        body, original, encoded = seed_legacy_capture_revision(self.profile)
        returned = self.profile.read("demo", 1)
        self.assertEqual("conflict", returned.pop("observation_time_status"))
        self.assertEqual(original, returned)
        self.assertEqual("conflict", self.profile.confirm(body)["observation_time_status"])
        changed = copy.deepcopy(body)
        changed.update(request_id="new-confirm", expected_revision=1)
        with self.assertRaisesRegex(DomainError, "observation_time_conflict"):
            self.profile.confirm(changed)
        with self.profile.connect() as db:
            self.assertEqual(encoded, db.execute("SELECT payload FROM revisions WHERE profile_id='demo' AND revision=1").fetchone()[0])
            self.assertEqual(1, db.execute("SELECT COUNT(*) FROM revisions").fetchone()[0])

    def test_missing_original_source_is_visible_as_unavailable_and_history_stays_readable(self):
        _, original, encoded = seed_legacy_capture_revision(self.profile)
        with self.profile.connect() as db:
            db.execute("DELETE FROM observations")
        returned = self.profile.read("demo", 1)
        self.assertEqual("unavailable", returned.pop("observation_time_status"))
        self.assertEqual(original, returned)
        with self.profile.connect() as db:
            self.assertEqual(encoded, db.execute("SELECT payload FROM revisions").fetchone()[0])


if __name__ == "__main__":
    unittest.main()

"""SQLite regressions for listing and reopening confirmed profile revisions."""
from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path

from contracts import canonical, digest
from services.profile.app import Profile
from services.profile.domain import build_fingerprint

ROOT = Path(__file__).resolve().parents[1]
DEMO = json.loads((ROOT / "fixtures/demo.json").read_text(encoding="utf-8"))


class ProfileLibraryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.profile = Profile(Path(self.temp.name))

    def save_revision(self, profile_id: str, revision: int, name: str):
        facts = copy.deepcopy(DEMO["facts"])
        facts["candidate_item"]["name"] = name
        result = {
            "contract_version": 1,
            "profile_id": profile_id,
            "revision": revision,
            "observation_id": "observation-" + profile_id + str(revision),
            "facts": facts,
            "facts_hash": digest(facts),
            "build_hash": build_fingerprint(facts),
        }
        with self.profile.connect() as db:
            db.execute("INSERT INTO revisions VALUES (?,?,?)",
                       (profile_id, revision, canonical(result)))
        return result

    def test_empty_database_lists_no_profiles_after_restart(self):
        restarted = Profile(Path(self.temp.name))
        self.assertEqual({"profiles": [], "limit": 20}, restarted.handle("GET", "/v1/profiles", {}))

    def test_lists_latest_revision_per_profile_in_write_order_after_restart(self):
        self.save_revision("older", 1, "Older profile")
        self.save_revision("newer", 1, "Newer profile")
        latest = self.save_revision("older", 2, "Latest older profile")

        restarted = Profile(Path(self.temp.name))
        result = restarted.handle("GET", "/v1/profiles", {})
        self.assertEqual(["older", "newer"], [item["profile_id"] for item in result["profiles"]])
        self.assertEqual(2, result["profiles"][0]["revision"])
        self.assertEqual("Latest older profile", result["profiles"][0]["candidate_name"])
        self.assertEqual("sorcerer", result["profiles"][0]["class_id"])
        self.assertEqual("lootweave-fixture", result["profiles"][0]["game_id"])

        reopened = restarted.handle("GET", "/v1/profiles/older/revisions/2", {})
        self.assertEqual(latest["facts"], reopened["facts"])
        self.assertEqual(latest["facts_hash"], reopened["facts_hash"])
        self.assertEqual(latest["build_hash"], reopened["build_hash"])
        self.assertEqual("unavailable", reopened["observation_time_status"])

    def test_list_is_limited_to_twenty_latest_written_profiles(self):
        for index in range(21):
            self.save_revision(f"profile-{index}", 1, f"Candidate {index}")
        result = self.profile.handle("GET", "/v1/profiles", {})
        self.assertEqual(20, result["limit"])
        self.assertEqual(20, len(result["profiles"]))
        self.assertEqual("profile-20", result["profiles"][0]["profile_id"])
        self.assertNotIn("profile-0", [item["profile_id"] for item in result["profiles"]])

    def test_older_revision_inserted_later_does_not_replace_latest_revision(self):
        latest = self.save_revision("out-of-order", 2, "Saved latest")
        self.save_revision("out-of-order", 1, "Inserted later but older")

        restarted = Profile(Path(self.temp.name))
        listed = restarted.handle("GET", "/v1/profiles", {})["profiles"]
        self.assertEqual(1, len(listed))
        self.assertEqual(2, listed[0]["revision"])
        self.assertEqual("Saved latest", listed[0]["candidate_name"])
        reopened = restarted.handle("GET", "/v1/profiles/out-of-order/revisions/2", {})
        self.assertEqual(latest["facts"], reopened["facts"])
        self.assertEqual(latest["facts_hash"], reopened["facts_hash"])
        self.assertEqual(latest["build_hash"], reopened["build_hash"])


if __name__ == "__main__":
    unittest.main()

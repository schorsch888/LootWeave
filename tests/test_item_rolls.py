"""Confirmed item field differences remain useful without accepting game mechanics."""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from contracts import canonical, digest
from services.evaluation.app import Evaluation
from services.evaluation.domain import EVALUATOR_VERSION, EVALUATOR_VERSIONS, evaluate
from services.evaluation.rolls import compare_item_rolls
from services.knowledge.app import Knowledge
from services.profile.app import Profile
from services.profile.domain import snapshot
from storage import connect

ROOT = Path(__file__).resolve().parents[1]
DEMO = json.loads((ROOT / "fixtures/demo.json").read_text(encoding="utf-8"))
PACK = json.loads((ROOT / "knowledge-packs/synthetic-leveling-1.0.0.json").read_text(encoding="utf-8"))
RESEARCH = json.loads((ROOT / "knowledge-packs/deskrawl-sorcerer-leveling-0.6.0-research.json").read_text(encoding="utf-8"))


def affix(affix_id, value, unit="points", evidence_ids=None):
    return {"id": affix_id, "value": value, "unit": unit,
            "evidence_ids": ["demo-input"] if evidence_ids is None else evidence_ids}


def facts_for(current_affixes, candidate_affixes):
    facts = deepcopy(DEMO["facts"])
    facts["equipped_items"]["weapon"]["affixes"] = deepcopy(current_affixes)
    facts["candidate_item"]["affixes"] = deepcopy(candidate_affixes)
    return facts


def result_for(facts, pack=None, version=EVALUATOR_VERSION):
    snapshot(facts)
    profile = {"contract_version": 1, "profile_id": "item-rolls", "revision": 1,
               "facts": facts, "facts_hash": digest(facts)}
    pack = deepcopy(PACK if pack is None else pack)
    return evaluate(profile, {"pack": pack, "pack_hash": digest(pack)},
                    deepcopy(DEMO["intent"]), evaluator_version=version)


class ItemRollTests(unittest.TestCase):
    def test_real_research_scope_shows_confirmed_differences_without_executing_rules(self):
        facts = facts_for([affix("mana", 20)], [affix("mana", 35)])
        facts["context"] = deepcopy(RESEARCH["context"])
        facts["class_id"] = RESEARCH["class_id"]
        facts["evidence"][0]["kind"] = "manual_confirmation"
        with patch("services.evaluation.domain.resolve", side_effect=AssertionError("research rule executed")):
            result = result_for(facts, RESEARCH)
        self.assertEqual("needs_confirmation", result["retention"])
        self.assertEqual("blocked", result["comparison"]["status"])
        self.assertFalse(result["comparison"]["scope_compatible"])
        self.assertIn("game_mechanics_not_accepted", result["blockers"])
        for key in ("before", "after", "lost_mechanisms", "gained_mechanisms",
                    "missing_mechanisms", "uncertain_mechanisms"):
            self.assertEqual([], result["comparison"][key])
        rolls = result["comparison"]["item_rolls"]
        self.assertEqual("item_affixes_only", rolls["scope"])
        self.assertEqual({"instance_id": "core-staff", "name": "示例：循环法杖"}, rolls["current_item"])
        self.assertEqual({"instance_id": "vitality-staff", "name": "示例：活力法杖"}, rolls["candidate_item"])
        self.assertEqual([{"affix_id": "mana", "current_value": 20, "candidate_value": 35,
                           "current_unit": "points", "candidate_unit": "points", "delta": 15,
                           "status": "comparable", "input_evidence_ids": ["demo-input"]}], rolls["rows"])
        self.assertEqual("Confirmed item affix comparison only; no validated game recommendation or DPS.",
                         result["scope_notice"])
        self.assertTrue(rolls["limitations"])

    def test_signed_values_and_deltas_keep_the_original_units(self):
        facts = facts_for([affix("negative", -5), affix("rate", 5, "percent_points"), affix("zero", 0)],
                          [affix("negative", -2), affix("rate", 3, "percent_points"), affix("zero", 0)])
        rows = {row["affix_id"]: row for row in result_for(facts)["comparison"]["item_rolls"]["rows"]}
        self.assertEqual({"negative": 3, "rate": -2, "zero": 0},
                         {key: row["delta"] for key, row in rows.items()})
        self.assertTrue(all(row["status"] == "comparable" for row in rows.values()))
        self.assertEqual("percent_points", rows["rate"]["current_unit"])
        self.assertEqual("percent_points", rows["rate"]["candidate_unit"])

    def test_missing_affixes_are_not_zero_and_identifiers_are_not_fuzzy_matched(self):
        facts = facts_for([affix("mana", 20), affix("vitality", 0)],
                          [affix("Mana", 30), affix("cold", 0)])
        rows = compare_item_rolls(facts)["rows"]
        self.assertEqual(["Mana", "cold", "mana", "vitality"], [row["affix_id"] for row in rows])
        self.assertEqual(["added", "added", "removed", "removed"], [row["status"] for row in rows])
        self.assertTrue(all(row["delta"] is None for row in rows))
        self.assertIsNone(rows[1]["current_value"])
        self.assertIsNone(rows[1]["current_unit"])
        self.assertEqual(0, rows[1]["candidate_value"])
        self.assertEqual(0, rows[3]["current_value"])
        self.assertIsNone(rows[3]["candidate_value"])
        self.assertIsNone(rows[3]["candidate_unit"])

    def test_units_are_not_converted_or_normalized(self):
        facts = facts_for([affix("critical", 20, "percent_points"), affix("power", 5, "points")],
                          [affix("critical", 0.3, "ratio"), affix("power", 6, "Points")])
        rows = compare_item_rolls(facts)["rows"]
        self.assertEqual(["unit_mismatch", "unit_mismatch"], [row["status"] for row in rows])
        self.assertTrue(all(row["delta"] is None for row in rows))
        self.assertEqual((20, 0.3, "percent_points", "ratio"),
                         tuple(rows[0][key] for key in ("current_value", "candidate_value", "current_unit", "candidate_unit")))

    def test_only_the_candidate_slot_is_compared(self):
        facts = facts_for([affix("power", 10)], [affix("power", 20)])
        facts["equipped_items"]["head"]["affixes"] = [affix("power", 999)]
        rolls = compare_item_rolls(facts)
        self.assertEqual("core-staff", rolls["current_item"]["instance_id"])
        self.assertEqual(10, rolls["rows"][0]["current_value"])
        self.assertEqual(10, rolls["rows"][0]["delta"])
        del facts["equipped_items"]["weapon"]
        rolls = compare_item_rolls(facts)
        self.assertIsNone(rolls["current_item"])
        self.assertEqual("added", rolls["rows"][0]["status"])
        self.assertIsNone(rolls["rows"][0]["current_value"])
        self.assertIsNone(rolls["rows"][0]["delta"])
        self.assertIn("No item is confirmed", rolls["limitations"][-1])

    def test_no_recorded_affixes_produce_an_empty_comparison(self):
        facts = facts_for([], [])
        self.assertEqual([], result_for(facts)["comparison"]["item_rolls"]["rows"])
        del facts["equipped_items"]["weapon"]
        rolls = compare_item_rolls(facts)
        self.assertIsNone(rolls["current_item"])
        self.assertEqual([], rolls["rows"])

    def test_finite_inputs_cannot_create_non_finite_json_deltas(self):
        for before, after in ((-1.7e308, 1.7e308), (10**308, -(10**308))):
            with self.subTest(before=before, after=after):
                result = result_for(facts_for([affix("power", before)], [affix("power", after)]))
                row = result["comparison"]["item_rolls"]["rows"][0]
                self.assertEqual((before, after), (row["current_value"], row["candidate_value"]))
                self.assertEqual("out_of_range", row["status"])
                self.assertIsNone(row["delta"])
                self.assertEqual(result, json.loads(canonical(result)))

    def test_affix_order_and_input_source_order_do_not_change_the_fact_rows(self):
        facts = facts_for([affix("z", 2, evidence_ids=["shared", "current"]), affix("a", 1)],
                          [affix("a", 3), affix("z", 4, evidence_ids=["candidate", "shared"])])
        before = deepcopy(facts)
        expected = compare_item_rolls(facts)
        self.assertEqual(before, facts)
        self.assertEqual(["a", "z"], [row["affix_id"] for row in expected["rows"]])
        self.assertEqual(["candidate", "current", "shared"], expected["rows"][1]["input_evidence_ids"])
        for item in (facts["candidate_item"], facts["equipped_items"]["weapon"]):
            item["affixes"].reverse()
            for entry in item["affixes"]:
                entry["evidence_ids"].reverse()
        self.assertEqual(expected, compare_item_rolls(facts))

    def test_previous_versions_keep_their_original_output_shape_and_scope_notice(self):
        self.assertEqual("0.1.8", EVALUATOR_VERSION)
        self.assertEqual(("0.1.0", "0.1.1", "0.1.2", "0.1.3", "0.1.4", "0.1.5", "0.1.6", "0.1.7", "0.1.8"), EVALUATOR_VERSIONS)
        facts = facts_for([affix("mana", 20)], [affix("mana", 35)])
        facts["context"] = deepcopy(RESEARCH["context"])
        for version in EVALUATOR_VERSIONS[:EVALUATOR_VERSIONS.index("0.1.5")]:
            with self.subTest(version=version):
                result = result_for(facts, RESEARCH, version)
                self.assertNotIn("item_rolls", result["comparison"])
                self.assertEqual("Synthetic mechanism check; no validated game recommendation or DPS.", result["scope_notice"])

    def test_new_engine_inherits_previous_three_state_actor_and_requirement_behavior(self):
        archive = json.loads((ROOT / "fixtures/evaluation-0.1.3.json").read_text(encoding="utf-8"))
        for case in archive["cases"]:
            inputs = case["inputs"]
            with self.subTest(case=case["evaluation_id"]):
                # Compare the same explicitly reconfirmed synthetic facts under both engines.
                # Archived fixtures retain their original missing inventory and hashes.
                profile = deepcopy(inputs["profile"])
                profile["facts"]["inventory_items"] = []
                # Both engines compare the same newly confirmed ownership facts.
                facts = profile["facts"]
                if any(entry.get("actor", "hero") == "companion"
                       for item in (*facts["equipped_items"].values(), facts["candidate_item"])
                       for entry in item["embedded_items"]):
                    facts["companions"].append({"id": "confirmed-owner", "actor": "companion",
                                               "effects": [], "evidence_ids": facts["evidence_ids"][:]})
                    for item in (*facts["equipped_items"].values(), facts["candidate_item"]):
                        for entry in item["embedded_items"]:
                            if entry.get("actor", "hero") == "companion":
                                entry["companion_id"] = "confirmed-owner"
                profile["facts_hash"] = digest(profile["facts"])
                old = evaluate(profile, inputs["knowledge"], inputs["intent"], evaluator_version="0.1.4")
                current = evaluate(profile, inputs["knowledge"], inputs["intent"])
                self.assertEqual([], current["future_preparation"])
                del current["future_preparation"]
                del current["comparison"]["item_rolls"]
                current["pin"]["evaluator_version"] = "0.1.4"
                self.assertEqual(old, current)


class API:
    def __init__(self, app):
        self.app = app

    def call(self, method, path, body=None):
        return self.app.handle(method, path, body or {})


class ItemRollHistoryTests(unittest.TestCase):
    def test_new_fact_rows_and_previous_engine_replay_from_frozen_inputs(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            profile = Profile(root / "profile")
            knowledge = Knowledge(ROOT / "knowledge-packs")
            evaluation = Evaluation(root / "evaluation", API(profile), API(knowledge))
            facts = facts_for([affix("mana", 20, evidence_ids=["current-roll"])],
                              [affix("mana", 35, evidence_ids=["candidate-roll"])])
            for evidence_id in ("current-roll", "candidate-roll"):
                facts["evidence"].append({**deepcopy(facts["evidence"][0]), "id": evidence_id,
                                          "kind": "manual_confirmation"})
            profile.observe({"observation_id": "demo-text", "method": "text", "raw_text": "Confirmed item fields"})
            confirmed = profile.confirm({"request_id": "confirm-rolls", "profile_id": "rolls", "observation_id": "demo-text",
                                         "expected_revision": 0, "player_confirmed": True, "facts": facts})
            pack = knowledge.handle("GET", "/v1/packs/synthetic-leveling/1.0.0", {})
            body = {"request_id": "new-rolls", "profile_id": "rolls", "profile_revision": 1,
                    "pack_id": "synthetic-leveling", "pack_version": "1.0.0", "pack_hash": pack["pack_hash"],
                    "intent": deepcopy(DEMO["intent"])}
            result = evaluation.create(body)
            self.assertEqual(["candidate-roll", "current-roll"],
                             result["comparison"]["item_rolls"]["rows"][0]["input_evidence_ids"])
            old_body = {**deepcopy(body), "request_id": "old-rolls"}
            old_inputs = {"profile": deepcopy(confirmed), "knowledge": deepcopy(pack),
                          "intent": deepcopy(body["intent"]), "evaluator_version": "0.1.4"}
            old_result = {"evaluation_id": "old-rolls", **evaluate(confirmed, pack, old_inputs["intent"], evaluator_version="0.1.4")}
            self.assertNotIn("item_rolls", old_result["comparison"])
            with connect(evaluation.database) as db:
                db.execute("INSERT INTO evaluations VALUES (?,?,?,?,?)",
                           ("old-rolls", digest(old_body), canonical(old_inputs), canonical(old_result), digest(old_result)))
            changed = deepcopy(facts)
            changed["candidate_item"]["affixes"][0].update(value=99, evidence_ids=["demo-input"])
            profile.confirm({"request_id": "confirm-new-rolls", "profile_id": "rolls", "observation_id": "demo-text",
                             "expected_revision": 1, "player_confirmed": True, "facts": changed})
            evaluation.profile, evaluation.knowledge = API(None), API(None)
            for request, expected in ((body, result), (old_body, old_result)):
                self.assertEqual(expected, evaluation.create(request))
                for _ in range(10):
                    replay = evaluation.replay(request["request_id"])
                    self.assertTrue(replay["identical"])
                    self.assertEqual(expected, replay["result"])
            with connect(evaluation.database) as db:
                frozen = json.loads(db.execute("SELECT inputs FROM evaluations WHERE id=?", ("new-rolls",)).fetchone()[0])
            self.assertEqual(1, frozen["profile"]["revision"])
            self.assertEqual(35, frozen["profile"]["facts"]["candidate_item"]["affixes"][0]["value"])
            self.assertEqual(["candidate-roll"], frozen["profile"]["facts"]["candidate_item"]["affixes"][0]["evidence_ids"])
            self.assertEqual("0.1.8", frozen["evaluator_version"])


if __name__ == "__main__":
    unittest.main()

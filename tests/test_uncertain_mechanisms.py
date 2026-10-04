"""Unknown capability states cannot become definite losses, gains or absence."""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import unittest

from contracts import digest
from services.evaluation.domain import evaluate
from services.knowledge.domain import validate_pack
from services.profile.domain import snapshot

ROOT = Path(__file__).resolve().parents[1]
DEMO = json.loads((ROOT / "fixtures/demo.json").read_text(encoding="utf-8"))
PACK = json.loads((ROOT / "knowledge-packs/synthetic-leveling-1.0.0.json").read_text(encoding="utf-8"))
OR_STATES = {
    ("inactive", "inactive"): "inactive",
    ("inactive", "unknown"): "unknown",
    ("inactive", "active"): "active",
    ("unknown", "inactive"): "unknown",
    ("unknown", "unknown"): "unknown",
    ("unknown", "active"): "active",
    ("active", "inactive"): "active",
    ("active", "unknown"): "active",
    ("active", "active"): "active",
}


def inputs_for(before, after, actor="hero", case_id="three-state"):
    facts, pack, purpose = deepcopy(DEMO["facts"]), deepcopy(PACK), deepcopy(DEMO["intent"])
    original = deepcopy(facts["equipped_items"]["weapon"])
    candidate = deepcopy(facts["candidate_item"])
    for item in (original, candidate):
        item["effects"], item["embedded_items"], item["set_id"] = [], [], None
    facts["equipped_items"] = {"weapon": original}
    facts["candidate_item"] = candidate
    for key in ("talents", "paragon", "runes", "companions", "temporary_effects"):
        facts[key] = []
    for skill in facts["skills"]:
        skill["effects"] = []
    pack["pack_id"], pack["version"] = "synthetic-three-state", "1.0.0"
    pack["evidence"].append({
        "id": "fixture-three-state", "source_ref": "repo://fixtures/evaluation-0.1.3.json",
        "source_build": "fixture-1", "method": "Hand-authored fictional three-state provider specification.",
        "scope": "Synthetic source ownership and uncertainty regressions only.",
        "results": "Each provider contributes mana_loop only when its recorded condition is active.",
        "unknowns": "No actual game mechanics or recommendation is established.",
        "verification": "synthetic", "conflicts": []})
    base = deepcopy(next(rule for rule in pack["rules"] if rule["id"] == "mana-loop"))
    for phase, states, item in (("before", before, original), ("after", after, candidate)):
        for index, state in enumerate(states):
            name = f"uncertainty-{phase}-{index}"
            item["embedded_items"].append({"id": name, "actor": actor,
                                           "effects": [name], "evidence_ids": facts["evidence_ids"][:]})
            facts["conditions"][name] = state
            pack["rules"].append({**deepcopy(base), "id": name, "source_id": name,
                                  "actor": actor, "conditions": [name], "requires_skills": [],
                                  "evidence_ids": ["fixture-three-state"],
                                  "explanation": "Fictional mana_loop provider controlled by its recorded condition."})
    purpose.update(required_capabilities=["mana_loop"], future_builds=[])
    snapshot(facts)
    validate_pack(pack)
    profile = {"contract_version": 1, "profile_id": case_id, "revision": 1,
               "facts": facts, "facts_hash": digest(facts)}
    return {"profile": profile, "knowledge": {"pack": pack, "pack_hash": digest(pack)},
            "intent": purpose, "evaluator_version": "0.1.3"}


def expected_for(before, after, actor):
    prior, current = OR_STATES[tuple(before)], OR_STATES[tuple(after)]
    mechanism = {"actor": actor, "capability": "mana_loop"}
    loss = [mechanism] if (prior, current) == ("active", "inactive") else []
    gain = [mechanism] if (prior, current) == ("inactive", "active") else []
    missing = [{"actor": "hero", "capability": "mana_loop"}] if actor != "hero" or current == "inactive" else []
    uncertain = [{**mechanism, "before": prior, "after": current}] if "unknown" in (prior, current) else []
    blocked = "unknown" in (*before, *after)
    return {
        "retention": "needs_confirmation" if blocked else "keep" if "active" in after else "low_current_relevance",
        "comparison": {"status": "blocked" if blocked else "mechanism_loss" if loss or missing else
                       "mechanism_change" if gain else "no_known_change",
                       "scope_compatible": True, "lost_mechanisms": loss, "gained_mechanisms": gain,
                       "missing_mechanisms": missing, "uncertain_mechanisms": uncertain,
                       "lost_capabilities": ["mana_loop"] if loss else [],
                       "gained_capabilities": ["mana_loop"] if gain else [],
                       "missing_requirements": ["mana_loop"] if missing else []}}


def current_result(inputs):
    return evaluate(inputs["profile"], inputs["knowledge"], inputs["intent"])


class UncertainMechanismTests(unittest.TestCase):
    def assert_summary(self, result, expected):
        self.assertEqual(expected["retention"], result["retention"])
        self.assertEqual(expected["comparison"], {
            key: result["comparison"].get(key) for key in expected["comparison"]})
        self.assertEqual("0.1.4", result["pin"]["evaluator_version"])

    def test_all_provider_pairs_preserve_three_states_and_actor_ownership(self):
        for actor in ("hero", "companion"):
            for before in OR_STATES:
                for after in OR_STATES:
                    with self.subTest(actor=actor, before=before, after=after):
                        inputs = inputs_for(before, after, actor)
                        original = deepcopy(inputs)
                        result = current_result(inputs)
                        self.assert_summary(result, expected_for(before, after, actor))
                        self.assertEqual(original, inputs)
                        for row in result["comparison"]["uncertain_mechanisms"]:
                            self.assertIn("unknown", (row["before"], row["after"]))

    def test_unknown_replacement_keeps_each_original_rule_and_input_source(self):
        inputs = inputs_for(("active", "inactive"), ("unknown", "inactive"))
        result = current_result(inputs)
        self.assert_summary(result, expected_for(("active", "inactive"), ("unknown", "inactive"), "hero"))
        rows = {row["rule_id"]: row for row in result["comparison"]["after"]}
        uncertain = rows["uncertainty-after-0"]
        self.assertEqual("unknown", uncertain["state"])
        self.assertEqual([inputs["profile"]["facts"]["candidate_item"]["instance_id"] + ":uncertainty-after-0"],
                         uncertain["source_ids"])
        self.assertEqual(["fixture-three-state"], uncertain["evidence_ids"])
        self.assertEqual(["demo-input"], uncertain["input_evidence_ids"])
        self.assertIn("unknown_condition:uncertainty-after-0", result["blockers"])

    def test_rule_and_source_order_cannot_change_the_uncertain_comparison(self):
        inputs = inputs_for(("unknown", "inactive"), ("inactive", "unknown"), "companion")
        expected = current_result(inputs)
        changed = deepcopy(inputs)
        changed["knowledge"]["pack"]["rules"].reverse()
        changed["knowledge"]["pack_hash"] = digest(changed["knowledge"]["pack"])
        for item in (*changed["profile"]["facts"]["equipped_items"].values(),
                     changed["profile"]["facts"]["candidate_item"]):
            item["embedded_items"].reverse()
        changed["profile"]["facts_hash"] = digest(changed["profile"]["facts"])
        result = current_result(changed)
        self.assertEqual(expected["comparison"], result["comparison"])
        self.assertEqual(expected["blockers"], result["blockers"])
        self.assertEqual([{"actor": "companion", "capability": "mana_loop",
                           "before": "unknown", "after": "unknown"}],
                         result["comparison"].get("uncertain_mechanisms"))

    def test_incompatible_scope_cannot_invent_known_or_uncertain_mechanisms(self):
        inputs = inputs_for(("active", "inactive"), ("unknown", "inactive"))
        inputs["profile"]["facts"]["context"]["game_build"] = "different-build"
        inputs["profile"]["facts_hash"] = digest(inputs["profile"]["facts"])
        result = current_result(inputs)
        self.assertFalse(result["comparison"]["scope_compatible"])
        for key in ("before", "after", "lost_mechanisms", "gained_mechanisms",
                    "missing_mechanisms", "uncertain_mechanisms"):
            self.assertEqual([], result["comparison"].get(key))
        self.assertEqual("blocked", result["comparison"]["status"])

    def test_original_0_1_3_hashes_and_versions_survive_while_new_requests_use_corrected_states(self):
        archive = json.loads((ROOT / "fixtures/evaluation-0.1.3.json").read_text(encoding="utf-8"))
        self.assertEqual(8, len(archive["cases"]))
        for case in archive["cases"]:
            inputs = case["inputs"]
            with self.subTest(case=case["evaluation_id"]):
                old = {"evaluation_id": case["evaluation_id"],
                       **evaluate(inputs["profile"], inputs["knowledge"], inputs["intent"],
                                  evaluator_version="0.1.3")}
                self.assertEqual(case["result_hash"], digest(old))
                self.assertEqual("0.1.3", old["pin"]["evaluator_version"])
                self.assertNotIn("uncertain_mechanisms", old["comparison"])
                current = current_result(inputs)
                self.assert_summary(current, case["expected_current_result"])
                for _ in range(10):
                    self.assertEqual(current, current_result(inputs))


if __name__ == "__main__":
    unittest.main()

"""Actor-specific losses and requirements must survive complete-build comparison."""
import copy
import json
import unittest
from pathlib import Path

from services.evaluation.domain import evaluate
from services.knowledge.domain import validate_pack
from services.profile.domain import snapshot
from contracts import digest

ROOT = Path(__file__).resolve().parents[1]
ARCHIVE = json.loads((ROOT / "fixtures/evaluation-0.1.1.json").read_text(encoding="utf-8"))


def current_result(inputs):
    profile, knowledge = copy.deepcopy(inputs["profile"]), copy.deepcopy(inputs["knowledge"])
    # Reconfirm an explicitly empty synthetic inventory for the current engine.
    # The original historical inputs and result hashes are never modified.
    profile["facts"].setdefault("inventory_items", [])
    snapshot(profile["facts"])
    validate_pack(knowledge["pack"])
    profile["facts_hash"] = digest(profile["facts"])
    knowledge["pack_hash"] = digest(knowledge["pack"])
    return evaluate(profile, knowledge, copy.deepcopy(inputs["intent"]))


class ActorCapabilityTests(unittest.TestCase):
    def test_losses_transfers_and_requirements_preserve_effect_owners(self):
        for case in ARCHIVE["cases"]:
            with self.subTest(case=case["evaluation_id"]):
                result = current_result(case["inputs"])
                expected = case["expected_current_comparison"]
                actual = {key: result["comparison"].get(key) for key in expected}
                self.assertEqual(expected, actual)
                self.assertEqual([], result["blockers"])
                for key, phase in (("lost_mechanisms", "before"), ("gained_mechanisms", "after")):
                    for mechanism in actual[key]:
                        sources = [row for row in result["comparison"][phase]
                                   if row["state"] == "active" and row["actor"] == mechanism["actor"]
                                   and row["capability"] == mechanism["capability"]]
                        self.assertTrue(sources)
                        self.assertTrue(all(row["source_ids"] and row["evidence_ids"]
                                            and row["input_evidence_ids"] for row in sources))

    def test_same_owner_sources_and_equivalent_rules_do_not_duplicate_changes(self):
        case = next(case for case in ARCHIVE["cases"]
                    if case["evaluation_id"] == "legacy-same-owner-alternative-remains")
        inputs = copy.deepcopy(case["inputs"])
        facts, pack = inputs["profile"]["facts"], inputs["knowledge"]["pack"]
        facts["temporary_effects"].append({**copy.deepcopy(facts["temporary_effects"][-1]),
                                           "id": "second-hero-mana-fallback"})
        rule = next(row for row in pack["rules"] if row["id"] == "mana-loop")
        pack["rules"].append({**copy.deepcopy(rule), "id": "equivalent-mana-loop"})
        pack["rules"].reverse()
        result = current_result(inputs)
        expected = case["expected_current_comparison"]
        self.assertEqual(expected, {key: result["comparison"].get(key) for key in expected})
        for row in result["comparison"]["after"]:
            if row["capability"] == "mana_loop":
                self.assertEqual("hero", row["actor"])
                self.assertEqual("active", row["state"])
                self.assertEqual(["temporary_effects:hero-mana-fallback",
                                  "temporary_effects:second-hero-mana-fallback"], row["source_ids"])

    def test_companion_state_never_satisfies_a_hero_requirement(self):
        case = next(case for case in ARCHIVE["cases"]
                    if case["evaluation_id"] == "legacy-companion-cannot-satisfy-hero")
        for state in ("active", "inactive", "unknown"):
            inputs = copy.deepcopy(case["inputs"])
            facts, pack = inputs["profile"]["facts"], inputs["knowledge"]["pack"]
            next(row for row in pack["rules"] if row["id"] == "companion-support")["conditions"] = ["companion_ready"]
            facts["conditions"]["companion_ready"] = state
            with self.subTest(state=state):
                result = current_result(inputs)
                comparison = result["comparison"]
                self.assertEqual(["companion_support"], comparison["missing_requirements"])
                self.assertEqual([{"actor": "hero", "capability": "companion_support"}],
                                 comparison.get("missing_mechanisms"))
                self.assertEqual("blocked" if state == "unknown" else "mechanism_loss",
                                 comparison["status"])
                if state == "unknown":
                    self.assertEqual("needs_confirmation", result["retention"])
                    self.assertIn("unknown_condition:companion-support", result["blockers"])

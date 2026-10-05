"""Unknown objectives and incompatible scopes cannot establish mechanism absence."""
import copy
import json
import unittest
from pathlib import Path

from contracts import CONTEXT_KEYS, digest
from services.evaluation.domain import evaluate
from services.knowledge.domain import validate_pack
from services.profile.domain import snapshot

ROOT = Path(__file__).resolve().parents[1]
ARCHIVE = json.loads((ROOT / "fixtures/evaluation-0.1.2.json").read_text(encoding="utf-8"))


def current_result(inputs, validate_knowledge=True):
    inputs = copy.deepcopy(inputs)
    profile, knowledge = inputs["profile"], inputs["knowledge"]
    # Reconfirm an explicitly empty synthetic inventory for the current engine.
    # The original historical inputs and result hashes are never modified.
    profile["facts"].setdefault("inventory_items", [])
    snapshot(profile["facts"])
    if validate_knowledge:
        validate_pack(knowledge["pack"])
    profile["facts_hash"] = digest(profile["facts"])
    knowledge["pack_hash"] = digest(knowledge["pack"])
    return evaluate(profile, knowledge, inputs["intent"])


class RequirementTests(unittest.TestCase):
    def test_unknown_goals_block_current_future_and_low_relevance_conclusions(self):
        for case in ARCHIVE["cases"]:
            with self.subTest(case=case["evaluation_id"]):
                result = current_result(case["inputs"])
                expected = case["expected_current_result"]
                self.assertEqual(expected["retention"], result["retention"])
                self.assertEqual(expected["blockers"], result["blockers"])
                self.assertEqual(expected["comparison"],
                                 {key:result["comparison"].get(key) for key in expected["comparison"]})
                self.assertEqual(digest(case["inputs"]["intent"]), result["pin"]["intent_hash"])
                self.assertFalse(any(reason["kind"] == "low_current_relevance"
                                     for reason in result["reasons"]) if result["blockers"] else False)

    def test_incompatible_context_class_or_content_cannot_report_missing_mechanisms(self):
        base = next(case for case in ARCHIVE["cases"] if case["evaluation_id"] == "legacy-known-goal-control")["inputs"]
        for key in [*CONTEXT_KEYS, "class_id", "content_entitlements"]:
            for state in (("missing",) if key == "content_entitlements" else ("different", "unknown")):
                inputs = copy.deepcopy(base)
                facts, pack = inputs["profile"]["facts"], inputs["knowledge"]["pack"]
                if key == "class_id":
                    facts[key] = state
                elif key == "content_entitlements":
                    pack["context"][key] = ["fixture-expansion"]
                    for rule in pack["rules"]:
                        rule["context"] = copy.deepcopy(pack["context"])
                else:
                    facts["context"][key] = state
                with self.subTest(key=key, state=state):
                    result = current_result(inputs)
                    self.assertEqual("needs_confirmation", result["retention"])
                    self.assertEqual("blocked", result["comparison"]["status"])
                    self.assertEqual([], result["comparison"]["before"])
                    self.assertEqual([], result["comparison"]["after"])
                    self.assertEqual([], result["comparison"]["missing_requirements"])
                    self.assertEqual([], result["comparison"]["missing_mechanisms"])
                    self.assertIs(result["comparison"].get("scope_compatible"), False)

    def test_unknown_goal_is_pinned_immutable_and_deduplicated_for_ten_replays(self):
        inputs = copy.deepcopy(next(case for case in ARCHIVE["cases"]
                                    if case["evaluation_id"] == "legacy-mixed-known-and-unknown-goals")["inputs"])
        before = copy.deepcopy(inputs)
        expected = current_result(inputs)
        for _ in range(10):
            self.assertEqual(expected, current_result(inputs))
        self.assertEqual(before, inputs)
        self.assertEqual(["unknown_required_capability:unmapped-resource-cycle"], expected["blockers"])
        self.assertEqual(["mana_loop"], expected["comparison"]["missing_requirements"])

    def test_unsupported_upstream_scenario_cannot_resolve_rules(self):
        inputs = copy.deepcopy(next(case for case in ARCHIVE["cases"]
                                    if case["evaluation_id"] == "legacy-known-goal-control")["inputs"])
        inputs["knowledge"]["pack"]["scenario"] = "unmapped-scenario"
        result = current_result(inputs, validate_knowledge=False)
        self.assertIn("unsupported_scenario", result["blockers"])
        self.assertEqual("blocked", result["comparison"]["status"])
        self.assertEqual([], result["comparison"]["before"])
        self.assertEqual([], result["comparison"]["after"])
        self.assertEqual([], result["comparison"]["missing_requirements"])
        self.assertIs(result["comparison"].get("scope_compatible"), False)

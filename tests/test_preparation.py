"""Quoted plans use fictional local facts; these cases accept no Deskrawl rules."""
import copy
import json
import tempfile
import unittest
from pathlib import Path

from contracts import DomainError, canonical, digest
from services.evaluation.app import Evaluation
from services.evaluation.domain import evaluate
from services.knowledge.app import Knowledge
from services.profile.app import Profile
from services.profile.domain import build_fingerprint, snapshot

ROOT = Path(__file__).resolve().parents[1]
DEMO = json.loads((ROOT / "fixtures/demo.json").read_text(encoding="utf-8"))
PACK = json.loads((ROOT / "knowledge-packs/synthetic-leveling-1.0.0.json").read_text(encoding="utf-8"))


def skill_quote(facts, skill_id="fixture-fire-bolt", rank=3, *, option_id="learn-fire", cost=7):
    return {"id": option_id, "kind": "skill", "target_id": skill_id,
            "context": copy.deepcopy(facts["context"]), "class_id": facts["class_id"],
            "input": copy.deepcopy(next((s for s in facts["skills"] if s["id"] == skill_id), None)),
            "result": {"id": skill_id, "rank": rank, "actor": "hero", "effects": [],
                       "evidence_ids": ["demo-input"]},
            "requirements": {"required_level": 10, "max_rank": 5, "unlock_state": "unlocked"},
            "costs": [{"resource_id": "fixture-shard", "amount": cost}],
            "evidence_ids": ["demo-input"], "unknowns": []}


def equipment_quote(facts, *, option_id="upgrade-candidate", cost=5):
    before = copy.deepcopy(facts["candidate_item"])
    after = copy.deepcopy(before)
    after["record_kind"] = "projected_item"
    after["upgrade_state"] = {"known": True, "level": 1}
    after["socket_state"] = {"known": True, "count": 0}
    after["affixes"][0]["value"] += 3
    return {"id": option_id, "kind": "equipment", "target_id": before["instance_id"],
            "context": copy.deepcopy(facts["context"]), "class_id": facts["class_id"],
            "input": before, "result": after,
            "requirements": {"required_level": 1, "max_rank": None, "unlock_state": "unlocked"},
            "costs": [{"resource_id": "fixture-shard", "amount": cost}],
            "evidence_ids": ["demo-input"], "unknowns": []}


def prepared_case():
    facts, purpose = copy.deepcopy(DEMO["facts"]), copy.deepcopy(DEMO["intent"])
    facts["candidate_item"]["effects"] = ["fixture-fire-focus"]
    facts["owned_resources"] = {"coverage": "partial", "balances": [
        {"resource_id": "fixture-shard", "amount": 12, "evidence_ids": ["demo-input"]}]}
    facts["preparation_options"] = [skill_quote(facts), equipment_quote(facts)]
    purpose["allowed_build_changes"] = ["skills", "equipment"]
    purpose["future_builds"] = [{"skills": [s["id"] for s in facts["skills"] if s["rank"] > 0] +
        ["fixture-fire-bolt"], "conditions": copy.deepcopy(facts["conditions"]),
        "feasibility": "owned", "equipment_items": [],
        "preparation_options": ["learn-fire", "upgrade-candidate"]}]
    purpose["budget"] = {"resource_limits": [{"resource_id": "fixture-shard", "amount": 12}]}
    return facts, purpose


def run_case(facts, purpose, pack=None, version="0.1.7"):
    snapshot(facts)
    pack = copy.deepcopy(pack or PACK)
    return evaluate({"contract_version": 1, "profile_id": "quote-test", "revision": 1,
                     "facts": facts, "facts_hash": digest(facts)},
                    {"pack": pack, "pack_hash": digest(pack)}, purpose, evaluator_version=version)


class PreparationCases(unittest.TestCase):
    def setUp(self):
        self.facts, self.purpose = prepared_case()

    def result(self):
        return run_case(self.facts, self.purpose)

    def report(self):
        return self.result()["future_preparation"][0]

    def test_combined_costs_use_explicit_target_rank_without_changing_current_facts(self):
        before = digest(self.facts)
        result = self.result()
        report = result["future_preparation"][0]
        self.assertEqual("feasible", report["status"])
        self.assertEqual(3, next(s["rank"] for s in report["skill_allocations"] if s["id"] == "fixture-fire-bolt"))
        self.assertEqual({"resource_id": "fixture-shard", "cost": 12, "available": 12,
                          "budget_limit": 12, "missing": 0, "budget_excess": 0}, report["resources"][0])
        self.assertEqual("candidate", result["retention"])
        self.assertTrue(any(r["kind"] == "future_use" and r["capability"] == "fire_focus" for r in result["reasons"]))
        self.assertFalse(any(s["id"] == "fixture-fire-bolt" for s in self.facts["skills"]))
        self.assertEqual(before, digest(self.facts))
        self.assertEqual("item_instance", self.facts["candidate_item"]["record_kind"])
        self.assertFalse(any(r["capability"] == "fire_focus" and r["state"] == "active" for r in result["comparison"]["after"]))

    def test_insufficient_materials_prevent_future_use_and_show_shortfall(self):
        self.facts["owned_resources"]["balances"][0]["amount"] = 8
        result = self.result()
        report = result["future_preparation"][0]
        self.assertEqual("infeasible", report["status"])
        self.assertEqual(4, report["resources"][0]["missing"])
        self.assertFalse(any(r["kind"] == "future_use" for r in result["reasons"]))
        self.assertIn("preparation_resource_insufficient:fixture-shard", result["blockers"])

    def test_budget_changes_evaluation_even_with_sufficient_owned_materials(self):
        self.purpose["budget"]["resource_limits"][0]["amount"] = 10
        self.assertEqual("infeasible", self.report()["status"])
        self.assertEqual(2, self.report()["resources"][0]["budget_excess"])

    def test_zero_budget_is_a_real_limit(self):
        self.purpose["budget"]["resource_limits"][0]["amount"] = 0
        self.assertEqual(12, self.report()["resources"][0]["budget_excess"])

    def test_missing_and_partial_resource_records_are_unknown_not_zero(self):
        for resources in (None, {"coverage": "partial", "balances": []}, {"coverage": "unknown", "balances": []}):
            with self.subTest(resources=resources):
                facts = copy.deepcopy(self.facts)
                if resources is None:
                    del facts["owned_resources"]
                else:
                    facts["owned_resources"] = resources
                report = run_case(facts, self.purpose)["future_preparation"][0]
                self.assertEqual("unknown", report["status"])
                self.assertIsNone(report["resources"][0]["available"])

    def test_explicit_complete_empty_resources_mean_zero(self):
        self.facts["owned_resources"] = {"coverage": "complete", "balances": []}
        self.assertEqual("infeasible", self.report()["status"])
        self.assertEqual(12, self.report()["resources"][0]["missing"])

    def test_explicit_free_quotes_do_not_require_resource_inventory(self):
        del self.facts["owned_resources"]
        for option in self.facts["preparation_options"]:
            option["costs"] = []
        self.assertEqual("feasible", self.report()["status"])
        self.assertEqual([], self.report()["resources"])

    def test_unknown_cost_is_never_free(self):
        self.facts["preparation_options"][0]["costs"] = None
        self.assertEqual("unknown", self.report()["status"])
        self.assertIn("preparation_cost_unknown:learn-fire", self.report()["blockers"])

    def test_unconfirmed_fee_rows_remain_saved_but_do_not_become_known_expenses(self):
        option = self.facts["preparation_options"][0]
        option["unknowns"] = ["costs_not_confirmed"]
        self.assertEqual("unknown", self.report()["status"])
        self.assertEqual(5, self.report()["resources"][0]["cost"])
        self.assertEqual(7, option["costs"][0]["amount"])
        option["unknowns"] = []
        self.assertEqual(12, self.report()["resources"][0]["cost"])

    def test_selected_support_item_unknown_required_level_blocks_preparation(self):
        from tests.test_owned_options import combination
        facts, purpose = combination()
        facts["inventory_items"][0]["required_level"] = None
        result = run_case(facts, purpose)
        self.assertEqual("unknown", result["future_preparation"][0]["status"])
        self.assertIn("required_level_unknown:owned-robe", result["blockers"])
        self.assertFalse(any(r["kind"] == "future_use" for r in result["reasons"]))

    def test_owned_label_cannot_bypass_missing_skill_allocation(self):
        self.purpose["future_builds"][0]["preparation_options"] = ["upgrade-candidate"]
        result = self.result()
        self.assertEqual("unknown", result["future_preparation"][0]["status"])
        self.assertIn("future_skill_not_recorded:fixture-fire-bolt", result["blockers"])
        self.assertFalse(any(r["kind"] == "future_use" for r in result["reasons"]))

    def test_locked_level_and_rank_requirements_are_enforced(self):
        for patch, blocker in (({"unlock_state": "locked"}, "preparation_unlock_not_met:learn-fire"),
                               ({"required_level": 999}, "preparation_level_not_met:learn-fire"),
                               ({"max_rank": 2}, "preparation_rank_not_met:learn-fire")):
            facts = copy.deepcopy(self.facts)
            facts["preparation_options"][0]["requirements"].update(patch)
            report = run_case(facts, self.purpose)["future_preparation"][0]
            self.assertEqual("infeasible", report["status"])
            self.assertIn(blocker, report["blockers"])

    def test_unknown_requirements_are_not_satisfied(self):
        for key, value in (("unlock_state", "unknown"), ("required_level", None), ("max_rank", None)):
            facts = copy.deepcopy(self.facts)
            facts["preparation_options"][0]["requirements"][key] = value
            self.assertEqual("unknown", run_case(facts, self.purpose)["future_preparation"][0]["status"])

    def test_skill_rank_rule_uses_target_rank_and_owner(self):
        pack = copy.deepcopy(PACK)
        rule = next(r for r in pack["rules"] if r["capability"] == "fire_focus")
        rule["requires_skill_ranks"] = {"fixture-fire-bolt": 4}
        result = run_case(self.facts, self.purpose, pack)
        self.assertFalse(any(r["kind"] == "future_use" and r["capability"] == "fire_focus" for r in result["reasons"]))
        self.facts["preparation_options"][0]["result"]["rank"] = 4
        result = run_case(self.facts, self.purpose, pack)
        self.assertTrue(any(r["kind"] == "future_use" and r["capability"] == "fire_focus" for r in result["reasons"]))

    def test_confirmation_provenance_additions_do_not_invalidate_original_item_state(self):
        evidence = copy.deepcopy(self.facts["evidence"][0])
        evidence.update(id="new-confirmation", source_ref="observation://new-manual")
        self.facts["evidence"].append(evidence)
        self.facts["evidence_ids"].append(evidence["id"])
        self.facts["candidate_item"]["evidence_ids"].append(evidence["id"])
        self.facts["candidate_item"]["affixes"][0]["evidence_ids"].append(evidence["id"])
        quote = skill_quote(self.facts, self.facts["skills"][0]["id"], rank=5, option_id="improve-current", cost=0)
        self.facts["preparation_options"].append(quote)
        self.purpose["future_builds"][0]["preparation_options"].append(quote["id"])
        self.facts["skills"][0]["evidence_ids"].append(evidence["id"])
        self.assertEqual("feasible", self.report()["status"])

    def test_changed_actual_item_invalidates_old_quote(self):
        self.facts["candidate_item"]["affixes"][0]["value"] += 1
        self.assertIn("preparation_input_changed:upgrade-candidate", self.report()["blockers"])
        self.assertEqual("unknown", self.report()["status"])

    def test_changed_skill_rank_invalidates_old_quote(self):
        quote = skill_quote(self.facts, self.facts["skills"][0]["id"], rank=5, option_id="improve-current", cost=0)
        self.facts["preparation_options"].append(quote)
        self.purpose["future_builds"][0]["preparation_options"].append(quote["id"])
        self.facts["skills"][0]["rank"] += 1
        self.assertIn("preparation_input_changed:improve-current", self.report()["blockers"])

    def test_old_game_version_quote_is_not_reused(self):
        self.facts["preparation_options"][0]["context"]["game_build"] = "older"
        self.assertIn("preparation_scope_mismatch:learn-fire", self.report()["blockers"])

    def test_random_or_unrevealed_outcome_is_not_a_deterministic_projection(self):
        self.facts["preparation_options"][1]["result"]["unrevealed_properties"] = ["random roll"]
        self.assertIn("preparation_outcome_unknown:upgrade-candidate", self.report()["blockers"])
        self.assertFalse(any(r["kind"] == "future_use" for r in self.result()["reasons"]))

    def test_inventory_item_quote_cannot_equip_an_unselected_item(self):
        option = equipment_quote(self.facts)
        held = copy.deepcopy(option["input"])
        held["instance_id"], held["slot"] = "held-robe", "body"
        self.facts["inventory_items"] = [held]
        option["target_id"] = held["instance_id"]
        option["input"] = held
        option["result"].update(instance_id=held["instance_id"], slot=held["slot"])
        self.facts["preparation_options"][1] = option
        self.assertIn("preparation_item_not_selected:held-robe", self.report()["blockers"])

    def test_multiple_quotes_for_one_target_do_not_stack(self):
        another = copy.deepcopy(self.facts["preparation_options"][1])
        another["id"] = "other-upgrade"
        self.facts["preparation_options"].append(another)
        self.purpose["future_builds"][0]["preparation_options"].append(another["id"])
        self.assertIn("preparation_target_conflict:" + another["target_id"], self.report()["blockers"])
        self.assertEqual(17, self.report()["resources"][0]["cost"])
        self.assertEqual(5, self.report()["resources"][0]["missing"])
        self.assertEqual("infeasible", self.report()["status"])
        another["costs"] = None
        self.assertIn("preparation_cost_unknown:other-upgrade", self.report()["blockers"])

    def test_unknown_and_duplicate_option_references_are_handled(self):
        self.purpose["future_builds"][0]["preparation_options"].append("missing")
        self.assertIn("preparation_option_not_recorded:missing", self.report()["blockers"])
        self.purpose["future_builds"][0]["preparation_options"].append("missing")
        with self.assertRaisesRegex(DomainError, "duplicate_future_preparation"):
            self.result()

    def test_permission_is_required_for_preparation_changes(self):
        self.purpose["allowed_build_changes"] = ["skills"]
        self.assertIn("future_build_change_not_permitted", self.report()["blockers"])
        self.assertEqual("infeasible", self.report()["status"])

    def test_skill_removal_needs_explicit_quote_and_cost(self):
        removed = self.facts["skills"][0]
        self.purpose["future_builds"][0]["skills"].remove(removed["id"])
        self.assertIn("future_skill_removal_not_recorded:" + removed["id"], self.report()["blockers"])
        option = skill_quote(self.facts, removed["id"], rank=0, option_id="remove-current", cost=0)
        self.facts["preparation_options"].append(option)
        self.purpose["future_builds"][0]["preparation_options"].append(option["id"])
        self.assertEqual("feasible", self.report()["status"])
        self.assertFalse(any(s["id"] == removed["id"] for s in self.report()["skill_allocations"]))

    def test_companion_learning_does_not_assume_hero_unlock_and_level(self):
        self.facts["preparation_options"][0]["result"]["actor"] = "companion"
        self.assertIn("preparation_companion_requirements_unknown:learn-fire", self.report()["blockers"])

    def test_exact_integer_sum_overflow_is_reported_without_rounded_cost(self):
        for option in self.facts["preparation_options"]:
            option["costs"][0]["amount"] = 2**53 - 1
        report = self.report()
        self.assertIsNone(report["resources"][0]["cost"])
        self.assertIn("preparation_cost_out_of_range:fixture-shard", report["blockers"])

    def test_resource_evidence_conflict_prevents_feasible_result(self):
        self.facts["evidence"][0]["conflicts"] = ["different count"]
        self.assertEqual("unknown", self.report()["status"])
        self.assertIn("preparation_evidence_unconfirmed:demo-input", self.report()["blockers"])

    def test_preparation_does_not_change_current_build_identity(self):
        original = build_fingerprint(self.facts)
        self.facts["owned_resources"]["balances"][0]["amount"] += 1
        self.facts["preparation_options"][0]["result"]["rank"] += 1
        self.assertEqual(original, build_fingerprint(self.facts))

    def test_budget_shape_is_never_silently_ignored(self):
        for budget, code in (({"gold": 3}, "unsupported_budget_fields"),
            ({"resource_limits": {}}, "resource_budget_required"),
            ({"resource_limits": [{"resource_id": "fixture-shard", "amount": -1}]}, "resource_amount_required")):
            purpose = copy.deepcopy(self.purpose)
            purpose["budget"] = budget
            with self.subTest(budget=budget), self.assertRaisesRegex(DomainError, code):
                run_case(self.facts, purpose)

    def test_profile_rejects_forged_projection_and_invalid_resource_counts(self):
        for bad in (-1, True, 0.5, 2**53, None):
            facts = copy.deepcopy(self.facts)
            facts["owned_resources"]["balances"][0]["amount"] = bad
            with self.subTest(bad=bad), self.assertRaisesRegex(DomainError, "resource_amount_required"):
                snapshot(facts)
        self.facts["preparation_options"][1]["result"]["record_kind"] = "item_instance"
        with self.assertRaisesRegex(DomainError, "projected_item_required"):
            snapshot(self.facts)

    def test_quote_cannot_change_item_identity_or_actor(self):
        facts = copy.deepcopy(self.facts)
        facts["preparation_options"][1]["result"]["slot"] = "body"
        with self.assertRaisesRegex(DomainError, "preparation_item_identity_conflict"):
            snapshot(facts)
        facts = copy.deepcopy(self.facts)
        quote = skill_quote(facts, facts["skills"][0]["id"])
        quote["result"]["actor"] = "companion"
        facts["preparation_options"] = [quote]
        with self.assertRaisesRegex(DomainError, "preparation_skill_owner_conflict"):
            snapshot(facts)

    def test_real_research_pack_can_show_recorded_costs_without_executing_mechanics(self):
        pack = json.loads((ROOT / "knowledge-packs/deskrawl-sorcerer-leveling-0.6.0-research.json").read_text(encoding="utf-8"))
        self.facts["context"] = copy.deepcopy(pack["context"])
        for option in self.facts["preparation_options"]:
            option["context"] = copy.deepcopy(pack["context"])
        result = run_case(self.facts, self.purpose, pack)
        self.assertEqual("feasible", result["future_preparation"][0]["status"])
        self.assertEqual("needs_confirmation", result["retention"])
        self.assertIn("game_mechanics_not_accepted", result["blockers"])
        self.assertEqual([], result["comparison"]["after"])
        self.assertEqual([], result["reasons"])

    def test_old_engine_retains_old_future_skill_behavior(self):
        result = run_case(self.facts, self.purpose, version="0.1.6")
        self.assertNotIn("future_preparation", result)
        self.assertTrue(any(r["kind"] == "future_use" for r in result["reasons"]))


class PreparationPersistence(unittest.TestCase):
    def test_cached_old_budget_is_returned_without_new_schema_or_live_sources(self):
        from storage import connect
        facts, purpose = prepared_case()
        purpose["budget"] = {"historical_untyped_gold": 99}
        old = {"evaluation_id": "old-budget", **run_case(facts, purpose, version="0.1.6")}
        body = {"request_id": "old-budget", "profile_id": "quote-test", "profile_revision": 1,
                "pack_id": PACK["pack_id"], "pack_version": PACK["version"], "pack_hash": digest(PACK), "intent": purpose}
        class Unavailable:
            def call(self, *args): raise AssertionError("live dependency used")
        with tempfile.TemporaryDirectory() as temp:
            service = Evaluation(Path(temp), Unavailable(), Unavailable())
            inputs = {"profile": {"contract_version": 1, "profile_id": "quote-test", "revision": 1,
                      "facts": facts, "facts_hash": digest(facts)},
                      "knowledge": {"pack": PACK, "pack_hash": digest(PACK)}, "intent": purpose,
                      "evaluator_version": "0.1.6"}
            with connect(service.database) as db:
                db.execute("INSERT INTO evaluations VALUES (?,?,?,?,?)", ("old-budget", digest(body),
                           canonical(inputs), canonical(old), digest(old)))
            self.assertEqual(old, service.create(body))
            self.assertEqual(old, service.replay("old-budget")["result"])


    def test_new_revision_and_plan_result_survive_service_restart_and_frozen_replay(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)
            facts, purpose = prepared_case()
            profile = Profile(path)
            profile.observe({"observation_id": "demo-text", "method": "text", "raw_text": "Fictional quote"})
            saved = profile.confirm({"request_id": "quote-confirm", "profile_id": "quote-test",
                "observation_id": "demo-text", "expected_revision": 0, "player_confirmed": True, "facts": facts})
            class API:
                def __init__(self, app): self.app = app
                def call(self, method, route, body=None):
                    if self.app is None: raise AssertionError("live source service used")
                    return self.app.handle(method, route, body or {})
            knowledge = Knowledge(ROOT / "knowledge-packs")
            evaluation = Evaluation(path, API(profile), API(knowledge))
            result = evaluation.create({"request_id": "quoted-result", "profile_id": "quote-test",
                "profile_revision": saved["revision"], "pack_id": PACK["pack_id"],
                "pack_version": PACK["version"], "pack_hash": digest(PACK), "intent": purpose})
            restarted = Profile(path)
            self.assertEqual(saved, restarted.read("quote-test", 1))
            evaluation = Evaluation(path, API(None), API(None))
            self.assertEqual(result, evaluation.read("quoted-result"))
            for _ in range(10):
                self.assertEqual(result, evaluation.replay("quoted-result")["result"])
            self.assertEqual("0.1.8", result["pin"]["evaluator_version"])


if __name__ == "__main__":
    unittest.main()

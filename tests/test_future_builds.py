"""Complete future builds use only explicitly confirmed fictional preparation facts."""
import copy
import json
import tempfile
import unittest
from pathlib import Path

from contracts import DomainError, digest
from services.evaluation.app import Evaluation
from services.evaluation.domain import EVALUATOR_VERSION, intent, resolve
from services.evaluation.preparation import SOURCE_GROUPS
from services.knowledge.app import Knowledge
from services.profile.app import Profile
from services.profile.domain import build_fingerprint, snapshot
from tests.test_preparation import PACK, ROOT, prepared_case, run_case


def source_quote(facts, kind, target_id, result, *, option_id=None, cost=1, companion_id=None):
    group = SOURCE_GROUPS[kind]
    option = {"id": option_id or "prepare-" + kind, "kind": kind, "target_id": target_id,
              "context": copy.deepcopy(facts["context"]), "class_id": facts["class_id"],
              "input": copy.deepcopy(next((entry for entry in facts[group] if entry["id"] == target_id), None)),
              "result": copy.deepcopy(result), "costs": [{"resource_id": "fixture-shard", "amount": cost}],
              "requirements": {"required_level": 1, "max_rank": 5 if kind in ("skill", "talent", "paragon") else None,
                               "unlock_state": "unlocked"},
              "evidence_ids": ["demo-input"], "unknowns": []}
    if companion_id is not None:
        option["requirements"]["companion_id"] = companion_id
    return option


def full_case():
    """Reusable oracle: all six groups + equipment cost 24; resource/survival/set losses remain visible."""
    facts, purpose = prepared_case()
    companion = facts["companions"][0]
    companion.update(level=12, companion_id=companion["id"])
    removed_talent = copy.deepcopy(facts["talents"][0])
    removed_talent.update(rank=0, effects=[])
    removed_paragon = copy.deepcopy(facts["paragon"][0])
    removed_paragon.update(rank=0, effects=[])
    adjusted_companion = copy.deepcopy(companion)
    adjusted_companion["rank"] = 3
    temporary = {"id": "fixture-buff-focus", "rank": 1, "actor": "hero",
                 "effects": ["fixture-temporary-focus"], "evidence_ids": ["demo-input"]}
    quotes = [
        source_quote(facts, "talent", removed_talent["id"], removed_talent, cost=2),
        source_quote(facts, "paragon", removed_paragon["id"], removed_paragon, cost=3),
        source_quote(facts, "rune", "fixture-rune-b", None, cost=1),
        source_quote(facts, "companion", companion["id"], adjusted_companion, cost=4,
                     companion_id=companion["id"]),
        source_quote(facts, "temporary_effect", temporary["id"], temporary, cost=2),
    ]
    quotes[3]["requirements"]["required_level"] = 10
    facts["preparation_options"].extend(quotes)
    facts["owned_resources"]["balances"][0]["amount"] = 24
    future = purpose["future_builds"][0]
    future.update(talents=[], paragon=[], runes=["fixture-rune-a"],
                  companions=[companion["id"]], temporary_effects=[temporary["id"]])
    future["conditions"]["buff_active"] = "active"
    future["preparation_options"].extend(quote["id"] for quote in quotes)
    purpose["allowed_build_changes"] = [*SOURCE_GROUPS.values(), "equipment"]
    purpose["required_capabilities"] = ["mana_loop", "archive_shield", "resource_efficiency", "survival", "frost_cycle"]
    purpose["budget"]["resource_limits"][0]["amount"] = 24
    return facts, purpose


def full_result(facts, purpose, pack=None):
    return run_case(facts, purpose, pack, version="0.1.8")


class CompleteFutureBuildCases(unittest.TestCase):
    def setUp(self):
        self.facts, self.purpose = full_case()

    def result(self):
        return full_result(self.facts, self.purpose)

    def report(self):
        return self.result()["future_preparation"][0]

    def test_six_groups_share_costs_but_payable_plan_still_loses_required_dependencies(self):
        before_hash, build_hash = digest(self.facts), build_fingerprint(self.facts)
        result = self.result()
        report = result["future_preparation"][0]
        self.assertEqual("0.1.8", EVALUATOR_VERSION)
        self.assertEqual("feasible", report["status"])
        self.assertEqual("future_plan", report["projection_kind"])
        self.assertEqual(set(SOURCE_GROUPS.values()), set(report["build_sources"]))
        self.assertEqual({"resource_id": "fixture-shard", "cost": 24, "available": 24,
                          "budget_limit": 24, "missing": 0, "budget_excess": 0}, report["resources"][0])
        self.assertEqual(7, len(report["options"]))
        self.assertEqual([], report["build_sources"]["talents"])
        self.assertEqual([], report["build_sources"]["paragon"])
        self.assertEqual(["fixture-rune-a"], [entry["id"] for entry in report["build_sources"]["runes"]])
        self.assertEqual(3, report["build_sources"]["companions"][0]["rank"])
        self.assertEqual(12, report["build_sources"]["companions"][0]["level"])
        self.assertEqual("fixture-companion", report["build_sources"]["companions"][0]["companion_id"])
        self.assertIsNone(next(option for option in report["options"] if option["kind"] == "rune")["projected_result"])
        comparison = report["comparison"]
        self.assertEqual("mechanism_loss", comparison["status"])
        self.assertEqual(result["comparison"]["before"], comparison["before"])
        for capability in ("resource_efficiency", "survival", "frost_cycle", "mana_loop", "archive_shield"):
            self.assertIn(capability, comparison["lost_capabilities"])
            self.assertIn(capability, comparison["missing_requirements"])
        self.assertTrue({"fire_focus", "temporary_focus"}.issubset(comparison["gained_capabilities"]))
        self.assertTrue(any(reason["kind"] == "future_use" and reason["capability"] == "fire_focus"
                            and "survival" in reason["future_comparison"]["missing_requirements"]
                            for reason in result["reasons"]))
        self.assertFalse(any(row["capability"] == "fire_focus" and row["state"] == "active"
                             for row in result["comparison"]["after"]))
        self.assertEqual(before_hash, digest(self.facts))
        self.assertEqual(build_hash, build_fingerprint(self.facts))
        self.assertEqual("item_instance", self.facts["candidate_item"]["record_kind"])
        self.assertEqual("projected_item", report["equipped_items"]["weapon"]["record_kind"])

    def test_each_deletion_requires_a_selected_confirmed_quote(self):
        for kind, group in (("talent", "talents"), ("paragon", "paragon"), ("rune", "runes")):
            facts, purpose = full_case()
            quote = next(option for option in facts["preparation_options"] if option["kind"] == kind)
            purpose["future_builds"][0]["preparation_options"].remove(quote["id"])
            report = full_result(facts, purpose)["future_preparation"][0]
            with self.subTest(kind=kind):
                self.assertEqual("unknown", report["status"])
                self.assertIn("future_source_removal_not_recorded:" + group + ":" + quote["target_id"], report["blockers"])
                self.assertTrue(any(entry["id"] == quote["target_id"] for entry in report["build_sources"][group]))

    def test_added_unrecorded_source_needs_quote_even_with_owned_label(self):
        self.purpose["future_builds"][0]["runes"].append("never-recorded")
        report = self.report()
        self.assertEqual("unknown", report["status"])
        self.assertIn("future_source_not_recorded:runes:never-recorded", report["blockers"])
        self.assertFalse(any(entry["id"] == "never-recorded" for entry in report["build_sources"]["runes"]))

    def test_omitted_groups_inherit_actual_selection_and_empty_lists_request_clearing(self):
        facts, purpose = prepared_case()
        report = full_result(facts, purpose)["future_preparation"][0]
        self.assertEqual("feasible", report["status"])
        for group in ("talents", "paragon", "runes", "companions", "temporary_effects"):
            self.assertEqual(facts[group], report["build_sources"][group])
        purpose["future_builds"][0]["runes"] = []
        purpose["allowed_build_changes"].append("runes")
        report = full_result(facts, purpose)["future_preparation"][0]
        self.assertEqual("unknown", report["status"])
        self.assertIn("future_source_removal_not_recorded:runes:fixture-rune-a", report["blockers"])

    def test_quote_result_must_match_target_selection(self):
        self.purpose["future_builds"][0]["talents"] = [self.facts["talents"][0]["id"]]
        report = self.report()
        self.assertIn("preparation_source_selection_conflict:prepare-talent", report["blockers"])
        self.assertEqual(1, report["build_sources"]["talents"][0]["rank"])

    def test_each_changed_group_requires_permission(self):
        for group in SOURCE_GROUPS.values():
            facts, purpose = full_case()
            purpose["allowed_build_changes"].remove(group)
            report = full_result(facts, purpose)["future_preparation"][0]
            with self.subTest(group=group):
                self.assertEqual("infeasible", report["status"])
                self.assertIn("future_build_change_not_permitted", report["blockers"])

    def test_stale_input_is_not_applied_to_the_future_copy(self):
        self.facts["talents"][0]["rank"] = 2
        report = self.report()
        self.assertIn("preparation_input_changed:prepare-talent", report["blockers"])
        self.assertEqual(2, report["build_sources"]["talents"][0]["rank"])
        self.assertEqual("unknown", report["status"])

    def test_unselected_quote_does_not_change_sources_or_charge_resources(self):
        temporary = {"id": "unselected-effect", "effects": ["fixture-vitality-support"],
                     "actor": "hero", "evidence_ids": ["demo-input"]}
        self.facts["preparation_options"].append(source_quote(self.facts, "temporary_effect", temporary["id"], temporary, cost=99, option_id="unused"))
        report = self.report()
        self.assertEqual(24, report["resources"][0]["cost"])
        self.assertFalse(any(entry["id"] == "unselected-effect" for entry in report["build_sources"]["temporary_effects"]))

    def test_unknown_cost_is_not_free_and_resource_shortfall_uses_all_groups(self):
        self.facts["owned_resources"]["balances"][0]["amount"] = 20
        self.assertEqual(4, self.report()["resources"][0]["missing"])
        self.assertEqual("infeasible", self.report()["status"])
        self.facts["owned_resources"]["balances"][0]["amount"] = 24
        next(option for option in self.facts["preparation_options"] if option["kind"] == "paragon")["costs"] = None
        report = self.report()
        self.assertEqual("unknown", report["status"])
        self.assertIn("preparation_cost_unknown:prepare-paragon", report["blockers"])
        self.assertEqual(21, report["resources"][0]["cost"])

    def test_unconfirmed_outcome_stale_input_and_missing_removal_cannot_prove_future_changes(self):
        for fault in ("outcome", "stale", "missing-removal", "evidence-conflict"):
            facts, purpose = full_case()
            if fault == "outcome":
                facts["preparation_options"][0]["unknowns"] = ["outcome_not_confirmed"]
            elif fault == "stale":
                facts["talents"][0]["rank"] = 2
            elif fault == "missing-removal":
                purpose["future_builds"][0]["preparation_options"].remove("prepare-rune")
            else:
                facts["evidence"][0]["conflicts"] = ["different expected result"]
            result = full_result(facts, purpose)
            comparison = result["future_preparation"][0]["comparison"]
            with self.subTest(fault=fault):
                self.assertEqual("blocked", comparison["status"])
                self.assertTrue(comparison["blockers"])
                for key in ("after", "lost_capabilities", "gained_capabilities", "missing_requirements",
                            "lost_mechanisms", "gained_mechanisms", "missing_mechanisms", "uncertain_mechanisms"):
                    self.assertEqual([], comparison[key])
                self.assertFalse(any(reason["kind"] == "future_use" for reason in result["reasons"]))
                self.assertTrue(result["future_preparation"][0]["build_sources"])

    def test_current_input_and_pack_faults_block_each_plan_without_changing_preparation_costs(self):
        for fault, code in (("unreviewed", "input_unknown:build_not_reviewed"),
                            ("pack-conflict", "conflicting_evidence"),
                            ("current-time", "cross_time_snapshot"),
                            ("current-effect", "unknown_effect:unverified-current-effect")):
            facts, purpose = full_case()
            pack = copy.deepcopy(PACK)
            if fault == "unreviewed":
                facts["unknowns"].append("build_not_reviewed")
            elif fault == "pack-conflict":
                pack["evidence"][0]["conflicts"].append("contradictory rule")
            elif fault == "current-time":
                old = copy.deepcopy(facts["evidence"][0])
                old.update(id="old-current-item", captured_at="2000-01-01T00:00:00Z")
                facts["evidence"].append(old)
                facts["equipped_items"]["weapon"]["evidence_ids"] = [old["id"]]
            else:
                facts["equipped_items"]["weapon"]["effects"].append("unverified-current-effect")
            purpose["future_builds"].append(copy.deepcopy(purpose["future_builds"][0]))
            result = full_result(facts, purpose, pack)
            with self.subTest(fault=fault):
                for report in result["future_preparation"]:
                    self.assertEqual("feasible", report["status"])
                    self.assertEqual(24, report["resources"][0]["cost"])
                    comparison = report["comparison"]
                    self.assertIn(code, comparison["blockers"])
                    self.assertEqual("blocked", comparison["status"])
                    for key in ("after", "lost_capabilities", "gained_capabilities", "missing_requirements",
                                "lost_mechanisms", "gained_mechanisms", "missing_mechanisms", "uncertain_mechanisms"):
                        self.assertEqual([], comparison[key])
                self.assertFalse(any(reason["kind"] == "future_use" for reason in result["reasons"]))

    def test_rejected_future_projection_cannot_emit_an_independently_resolved_future_use(self):
        quote = next(option for option in self.facts["preparation_options"] if option["kind"] == "equipment")
        quote["result"]["effects"].append("unverified-future-effect")
        result = self.result()
        report = result["future_preparation"][0]
        self.assertEqual("feasible", report["status"])
        self.assertIn("unknown_effect:unverified-future-effect", report["comparison"]["blockers"])
        self.assertEqual([], report["comparison"]["after"])
        self.assertFalse(any(reason["kind"] == "future_use" for reason in result["reasons"]))

    def test_new_projected_embedded_source_is_attributed_to_the_candidate_future_use(self):
        facts, purpose = prepared_case()
        quote = next(option for option in facts["preparation_options"] if option["kind"] == "equipment")
        quote["result"]["socket_state"] = {"known": True, "count": 1}
        quote["result"]["embedded_items"] = [{"id": "planned-focus-gem", "actor": "hero",
            "effects": ["fixture-temporary-focus"], "evidence_ids": ["demo-input"]}]
        purpose["future_builds"][0]["conditions"]["buff_active"] = "active"
        before = digest(facts)
        result = full_result(facts, purpose)
        report = result["future_preparation"][0]
        self.assertEqual("feasible", report["status"])
        reason = next(row for row in result["reasons"]
                      if row["kind"] == "future_use" and row["capability"] == "temporary_focus")
        self.assertIn(facts["candidate_item"]["instance_id"] + ":planned-focus-gem", reason["source_ids"])
        self.assertEqual("hero", reason["actor"])
        self.assertEqual(report["comparison"], reason["future_comparison"])
        self.assertEqual([], facts["candidate_item"]["embedded_items"])
        self.assertEqual(before, digest(facts))
        quote["unknowns"] = ["outcome_not_confirmed"]
        self.assertFalse(any(row["kind"] == "future_use" and row["capability"] == "temporary_focus"
                             for row in full_result(facts, purpose)["reasons"]))

    def test_one_unreliable_future_plan_never_changes_another_plans_comparison(self):
        extra = {"id": "unverified-buff", "actor": "hero", "effects": ["unverified-future-effect"],
                 "evidence_ids": ["demo-input"]}
        quote = source_quote(self.facts, "temporary_effect", extra["id"], extra, option_id="unverified-plan", cost=0)
        self.facts["preparation_options"].append(quote)
        good = copy.deepcopy(self.purpose["future_builds"][0])
        bad = copy.deepcopy(good)
        bad["temporary_effects"].append(extra["id"])
        bad["preparation_options"].append(quote["id"])
        expected = self.report()["comparison"]
        for plans in ([bad, good], [good, bad]):
            purpose = copy.deepcopy(self.purpose)
            purpose["future_builds"] = plans
            result = full_result(self.facts, purpose)
            good_index = plans.index(good)
            with self.subTest(good_index=good_index):
                self.assertEqual(expected, result["future_preparation"][good_index]["comparison"])
                self.assertEqual([], result["future_preparation"][1-good_index]["comparison"]["after"])
                self.assertTrue(any(reason["kind"] == "future_use" and reason["future_build_index"] == good_index
                                    for reason in result["reasons"]))
                self.assertFalse(any(reason["kind"] == "future_use" and reason["future_build_index"] != good_index
                                     for reason in result["reasons"]))

    def test_cost_uncertainty_preserves_confirmed_conditional_projection_but_no_future_use(self):
        self.facts["preparation_options"][0]["costs"] = None
        result = self.result()
        report = result["future_preparation"][0]
        self.assertEqual("unknown", report["status"])
        self.assertEqual("blocked", report["comparison"]["status"])
        self.assertTrue(report["comparison"]["after"])
        self.assertIn("fire_focus", report["comparison"]["gained_capabilities"])
        self.assertIn("survival", report["comparison"]["missing_requirements"])
        self.assertFalse(any(reason["kind"] == "future_use" for reason in result["reasons"]))

    def test_unknown_requirements_and_rank_caps_apply_to_talent_and_paragon(self):
        for kind in ("talent", "paragon"):
            facts, purpose = full_case()
            quote = next(option for option in facts["preparation_options"] if option["kind"] == kind)
            quote["result"] = copy.deepcopy(quote["input"])
            quote["result"]["rank"] = 6
            group = SOURCE_GROUPS[kind]
            purpose["future_builds"][0][group] = [quote["target_id"]]
            report = full_result(facts, purpose)["future_preparation"][0]
            with self.subTest(kind=kind):
                self.assertEqual("infeasible", report["status"])
                self.assertIn("preparation_rank_not_met:" + quote["id"], report["blockers"])
                quote["requirements"]["max_rank"] = None
                self.assertEqual("unknown", full_result(facts, purpose)["future_preparation"][0]["status"])

    def test_current_companion_level_is_used_not_hero_or_projected_level(self):
        quote = next(option for option in self.facts["preparation_options"] if option["kind"] == "companion")
        self.facts["companions"][0]["level"] = 2
        quote["input"]["level"] = 2
        quote["result"]["level"] = 99
        report = self.report()
        self.assertEqual("infeasible", report["status"])
        self.assertIn("preparation_level_not_met:prepare-companion", report["blockers"])
        del self.facts["companions"][0]["level"]
        del quote["input"]["level"]
        report = self.report()
        self.assertEqual("unknown", report["status"])
        self.assertIn("preparation_companion_requirements_unknown:prepare-companion", report["blockers"])

    def test_companion_identity_is_its_source_id_even_when_optional_owner_field_was_omitted(self):
        del self.facts["companions"][0]["companion_id"]
        quote = next(option for option in self.facts["preparation_options"] if option["kind"] == "companion")
        del quote["input"]["companion_id"]
        self.assertEqual("feasible", self.report()["status"])

    def test_companion_quote_cannot_borrow_another_companions_level(self):
        other = copy.deepcopy(self.facts["companions"][0])
        other.update(id="other-companion", companion_id="other-companion", level=99)
        self.facts["companions"].append(other)
        quote = next(option for option in self.facts["preparation_options"] if option["kind"] == "companion")
        quote["requirements"]["companion_id"] = other["id"]
        report = self.report()
        self.assertEqual("unknown", report["status"])
        self.assertIn("preparation_companion_requirements_unknown:prepare-companion", report["blockers"])

    def test_unowned_companion_quote_is_unknown_even_with_a_high_projected_level(self):
        proposed = {"id": "new-companion", "actor": "companion", "level": 99,
                    "effects": ["fixture-companion-support"], "evidence_ids": ["demo-input"]}
        quote = source_quote(self.facts, "companion", proposed["id"], proposed,
                             option_id="recruit", cost=0, companion_id=proposed["id"])
        self.facts["preparation_options"].append(quote)
        self.purpose["future_builds"][0]["preparation_options"].append(quote["id"])
        self.purpose["future_builds"][0]["companions"].append(proposed["id"])
        report = self.report()
        self.assertEqual("unknown", report["status"])
        self.assertIn("preparation_companion_not_recorded:recruit", report["blockers"])

    def test_companion_learning_has_explicit_owner_and_cannot_satisfy_hero_dependency(self):
        facts, purpose = prepared_case()
        companion = facts["companions"][0]
        companion["level"] = 12
        quote = facts["preparation_options"][0]
        quote["result"].update(actor="companion", companion_id=companion["id"])
        quote["requirements"]["companion_id"] = companion["id"]
        result = full_result(facts, purpose)
        self.assertEqual("feasible", result["future_preparation"][0]["status"])
        fire = next(row for row in result["future_preparation"][0]["comparison"]["after"] if row["capability"] == "fire_focus")
        self.assertEqual("inactive", fire["state"])
        self.assertFalse(any(reason["kind"] == "future_use" and reason["capability"] == "fire_focus" for reason in result["reasons"]))
        del quote["result"]["companion_id"]
        self.assertEqual("unknown", full_result(facts, purpose)["future_preparation"][0]["status"])

    def test_removing_companion_does_not_silently_remove_attached_sources(self):
        owner = self.facts["companions"][0]["id"]
        attached = {"id": "companion-buff", "actor": "companion", "companion_id": owner,
                    "effects": ["fixture-companion-support"], "evidence_ids": ["demo-input"]}
        self.facts["temporary_effects"].append(attached)
        self.purpose["future_builds"][0]["temporary_effects"].append(attached["id"])
        quote = next(option for option in self.facts["preparation_options"] if option["kind"] == "companion")
        quote["result"] = None
        self.purpose["future_builds"][0]["companions"] = []
        report = self.report()
        self.assertEqual("unknown", report["status"])
        self.assertIn("preparation_companion_not_selected:companion-buff", report["blockers"])
        self.assertEqual([], report["comparison"]["after"])

    def test_unknown_goal_and_unknown_condition_are_not_reported_as_known_absence(self):
        self.purpose["required_capabilities"].extend(["temporary_focus", "unverified-goal"])
        self.purpose["future_builds"][0]["conditions"]["buff_active"] = "unknown"
        comparison = self.report()["comparison"]
        self.assertIn("unknown_required_capability:unverified-goal", comparison["blockers"])
        self.assertNotIn("temporary_focus", comparison["missing_requirements"])
        self.assertNotIn("unverified-goal", comparison["missing_requirements"])
        self.assertTrue(any(row["capability"] == "temporary_focus" and row["after"] == "unknown"
                            for row in comparison["uncertain_mechanisms"]))

    def test_real_deskrawl_research_can_price_plan_but_cannot_execute_rules(self):
        pack = json.loads((ROOT / "knowledge-packs/deskrawl-sorcerer-leveling-0.6.0-research.json").read_text(encoding="utf-8"))
        self.facts["context"] = copy.deepcopy(pack["context"])
        for option in self.facts["preparation_options"]:
            option["context"] = copy.deepcopy(pack["context"])
        result = full_result(self.facts, self.purpose, pack)
        report = result["future_preparation"][0]
        self.assertEqual("feasible", report["status"])
        self.assertEqual("blocked", report["comparison"]["status"])
        self.assertEqual([], report["comparison"]["before"])
        self.assertEqual([], report["comparison"]["after"])
        self.assertIn("game_mechanics_not_accepted", report["comparison"]["blockers"])
        self.assertEqual([], result["reasons"])

    def test_profile_rejects_null_ranked_result_double_null_and_identity_or_owner_forgery(self):
        for kind, patch, code in (
            ("talent", {"result": None}, "preparation_source_required"),
            ("rune", {"input": None, "result": None}, "preparation_source_required"),
            ("temporary_effect", {"result": {"id": "forged", "effects": [], "evidence_ids": ["demo-input"]}}, "preparation_source_required"),
            ("companion", {"result": {"id": "fixture-companion", "actor": "hero", "effects": [], "evidence_ids": ["demo-input"]}}, "preparation_source_owner_conflict"),
        ):
            facts, _ = full_case()
            next(option for option in facts["preparation_options"] if option["kind"] == kind).update(patch)
            with self.subTest(kind=kind), self.assertRaisesRegex(DomainError, code):
                snapshot(facts)
        self.facts["companions"][0]["level"] = True
        with self.assertRaisesRegex(DomainError, "source_level_required"):
            snapshot(self.facts)

    def test_quote_cannot_transfer_source_between_companions(self):
        quote = next(option for option in self.facts["preparation_options"] if option["kind"] == "companion")
        quote["result"]["companion_id"] = "other-companion"
        with self.assertRaisesRegex(DomainError, "preparation_source_owner_conflict"):
            snapshot(self.facts)

    def test_new_intent_fields_are_validated_and_old_engines_cannot_silently_ignore_them(self):
        facts, purpose = prepared_case()
        for group in ("talents", "paragon", "runes", "companions", "temporary_effects"):
            bad = copy.deepcopy(purpose)
            bad["future_builds"][0][group] = ["same", "same"]
            with self.subTest(group=group), self.assertRaisesRegex(DomainError, "duplicate_future_source"):
                full_result(facts, bad)
            with self.assertRaisesRegex(DomainError, "unsupported_future_build_fields"):
                intent(bad, "0.1.7")
        with self.assertRaisesRegex(DomainError, "unsupported_preparation_kind"):
            run_case(self.facts, self.purpose, version="0.1.7")

    def test_old_engine_keeps_old_report_shape_and_companion_unknown_behavior(self):
        facts, purpose = prepared_case()
        quote = facts["preparation_options"][0]
        quote["result"].update(actor="companion", companion_id=facts["companions"][0]["id"])
        facts["companions"][0]["level"] = 99
        quote["requirements"]["companion_id"] = facts["companions"][0]["id"]
        report = run_case(facts, purpose)["future_preparation"][0]
        self.assertIn("preparation_companion_requirements_unknown:learn-fire", report["blockers"])
        self.assertNotIn("comparison", report)
        self.assertNotIn("build_sources", report)
        self.assertNotIn("projection_kind", report)


class CompanionResolverCases(unittest.TestCase):
    def test_rune_set_and_skill_requirements_cannot_pool_different_companions(self):
        facts, _ = prepared_case()
        first = facts["companions"][0]["id"]
        second = copy.deepcopy(facts["companions"][0])
        second["id"] = "other-companion"
        facts["companions"].append(second)
        pack = copy.deepcopy(PACK)
        frost = next(rule for rule in pack["rules"] if rule["capability"] == "frost_cycle")
        frost["actor"] = "companion"
        for rune, owner in zip(facts["runes"], (first, second["id"])):
            rune.update(actor="companion", companion_id=owner)
        facts["skills"][0].update(actor="companion", companion_id=first)
        self.assertEqual("inactive", next(row for row in resolve(facts, pack) if row["capability"] == "frost_cycle")["state"])
        facts["runes"][1]["companion_id"] = first
        self.assertEqual("active", next(row for row in resolve(facts, pack) if row["capability"] == "frost_cycle")["state"])
        facts["skills"][0]["companion_id"] = second["id"]
        self.assertEqual("inactive", next(row for row in resolve(facts, pack) if row["capability"] == "frost_cycle")["state"])


class CompleteFuturePersistence(unittest.TestCase):
    def test_full_plan_survives_sqlite_restart_and_frozen_offline_replay(self):
        class API:
            def __init__(self, app):
                self.app = app
            def call(self, method, path, body=None):
                if self.app is None:
                    raise AssertionError("frozen replay used a live dependency")
                return self.app.handle(method, path, body or {})
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary)
            facts, purpose = full_case()
            facts["evidence"][0]["source_ref"] = "observation://full-text"
            profile = Profile(path)
            profile.observe({"observation_id": "full-text", "method": "text", "raw_text": "Confirmed fictional complete future plan"})
            saved = profile.confirm({"request_id": "full-confirm", "profile_id": "full-build",
                "observation_id": "full-text", "expected_revision": 0, "player_confirmed": True, "facts": facts})
            evaluator = Evaluation(path, API(profile), API(Knowledge(ROOT / "knowledge-packs")))
            request = {"request_id": "full-evaluation", "profile_id": "full-build", "profile_revision": saved["revision"],
                       "pack_id": PACK["pack_id"], "pack_version": PACK["version"], "pack_hash": digest(PACK), "intent": purpose}
            result = evaluator.create(request)
            self.assertEqual("feasible", result["future_preparation"][0]["status"])
            self.assertIn("survival", result["future_preparation"][0]["comparison"]["missing_requirements"])
            changed = copy.deepcopy(facts)
            changed["companions"][0]["level"] = 3
            changed["talents"][0]["rank"] = 2
            profile.confirm({"request_id": "new-full-confirm", "profile_id": "full-build", "observation_id": "full-text",
                             "expected_revision": 1, "player_confirmed": True, "facts": changed})
            self.assertEqual(saved, Profile(path).read("full-build", 1))
            evaluator = Evaluation(path, API(None), API(None))
            self.assertEqual(result, evaluator.create(request))
            self.assertEqual(result, evaluator.read("full-evaluation"))
            for _ in range(10):
                self.assertEqual(result, evaluator.replay("full-evaluation")["result"])
            self.assertEqual("0.1.8", result["pin"]["evaluator_version"])


if __name__ == "__main__":
    unittest.main()

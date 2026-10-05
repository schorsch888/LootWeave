"""Synthetic regressions for public contracts, ownership, conditions and replacement."""
from __future__ import annotations

import copy
import json
import sqlite3
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from contracts import CONTEXT_KEYS, DomainError, digest, parse_json
from services.evaluation.domain import evaluate
from services.knowledge.app import Knowledge
from services.knowledge.domain import validate_pack
from services.profile.app import Profile
from services.profile.domain import snapshot
from storage import connect, initialize

ROOT = Path(__file__).resolve().parents[1]
DEMO = json.loads((ROOT / "fixtures/demo.json").read_text(encoding="utf-8"))
PACK = json.loads((ROOT / "knowledge-packs/synthetic-leveling-1.0.0.json").read_text(encoding="utf-8"))


def run_evaluation(facts=None, pack=None, intent=None):
    facts, pack = copy.deepcopy(facts or DEMO["facts"]), copy.deepcopy(pack or PACK)
    snapshot(facts)
    validate_pack(pack)
    record = {"contract_version": 1, "profile_id": "demo", "revision": 1,
              "facts": facts, "facts_hash": digest(facts)}
    return evaluate(record, {"pack": pack, "pack_hash": digest(pack)},
                    copy.deepcopy(intent or DEMO["intent"]))


class ProfileTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.profile = Profile(Path(self.temp.name))
        self.observation = {"observation_id": "demo-text", "method": "text", "raw_text": "Synthetic"}
        self.profile.observe(self.observation)
        self.body = {"request_id": "confirm-1", "profile_id": "demo", "observation_id": "demo-text",
                     "expected_revision": 0, "player_confirmed": True,
                     "facts": copy.deepcopy(DEMO["facts"])}

    def test_observation_is_unconfirmed_and_cannot_create_a_revision(self):
        self.assertEqual("unconfirmed", self.profile.observe(self.observation)["state"])
        with self.assertRaisesRegex(DomainError, "revision_not_found"):
            self.profile.read("demo", 1)

    def test_confirmation_is_idempotent(self):
        first = self.profile.confirm(self.body)
        self.assertEqual(first, self.profile.confirm(self.body))
        self.assertEqual(1, first["revision"])

    def test_same_request_id_cannot_change_facts(self):
        self.profile.confirm(self.body)
        self.body["facts"]["character_level"] += 1
        with self.assertRaisesRegex(DomainError, "idempotency_conflict"):
            self.profile.confirm(self.body)

    def test_stale_revision_does_not_overwrite(self):
        first = self.profile.confirm(self.body)
        self.body["request_id"] = "confirm-2"
        with self.assertRaisesRegex(DomainError, "revision_conflict"):
            self.profile.confirm(self.body)
        self.assertEqual(first, self.profile.read("demo", 1))

    def test_revisions_remain_replayable(self):
        first = self.profile.confirm(self.body)
        self.body.update(request_id="confirm-2", expected_revision=1)
        self.body["facts"]["character_level"] = 16
        second = self.profile.confirm(self.body)
        self.assertEqual(2, second["revision"])
        self.assertEqual(first, self.profile.read("demo", 1))

    def test_concurrent_confirmations_have_one_winner(self):
        bodies = [copy.deepcopy(self.body) for _ in range(2)]
        bodies[1]["request_id"] = "confirm-race"
        def attempt(body):
            try:
                return self.profile.confirm(body)["revision"]
            except DomainError as error:
                return error.code
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(attempt, bodies))
        self.assertCountEqual([1, "revision_conflict"], results)

    def test_confirmation_requires_explicit_player_action(self):
        self.body["player_confirmed"] = False
        with self.assertRaisesRegex(DomainError, "player_confirmation_required"):
            self.profile.confirm(self.body)

    def test_observation_requires_identity(self):
        self.body["observation_id"] = "missing"
        with self.assertRaisesRegex(DomainError, "observation_not_found"):
            self.profile.confirm(self.body)

    def test_confirmation_requires_link_to_original_observation(self):
        self.body["facts"]["evidence"][0]["source_ref"] = "manual://unrelated"
        with self.assertRaisesRegex(DomainError, "observation_evidence_required"):
            self.profile.confirm(self.body)

    def test_original_text_is_immutable(self):
        changed = {**self.observation, "raw_text": "Changed"}
        with self.assertRaisesRegex(DomainError, "observation_id_conflict"):
            self.profile.observe(changed)


class DomainCases(unittest.TestCase):
    def setUp(self):
        self.facts, self.pack = copy.deepcopy(DEMO["facts"]), copy.deepcopy(PACK)

    def run_case(self):
        return run_evaluation(self.facts, self.pack)

    def test_stat_gain_exposes_lost_core_and_set(self):
        result = self.run_case()
        self.assertEqual("keep", result["retention"])
        self.assertEqual("mechanism_loss", result["comparison"]["status"])
        self.assertEqual(["archive_shield", "cold_focus", "mana_loop"],
                         result["comparison"]["lost_capabilities"])
        self.assertEqual(["vitality_support"], result["comparison"]["gained_capabilities"])
        self.assertNotIn("dps", result)
        self.assertNotIn("score", result)

    def test_panel_is_not_added_to_equipment_or_talents(self):
        first = self.run_case()
        self.facts["observed_panel"][0]["value"] = 999999
        second = self.run_case()
        self.assertEqual(first["comparison"], second["comparison"])
        self.assertEqual("observations_only", second["panel_policy"])

    def test_unique_temporary_source_is_not_counted_twice(self):
        self.facts["candidate_item"]["effects"].append("fixture-temporary-focus")
        self.facts["temporary_effects"] = [{"id": "temp", "effects": ["fixture-temporary-focus"],
                                          "evidence_ids": ["demo-input"]}]
        self.facts["conditions"]["buff_active"] = "active"
        after = self.run_case()["comparison"]["after"]
        matching = [r for r in after if r["capability"] == "temporary_focus"]
        self.assertEqual(1, len(matching))
        self.assertEqual(2, len(matching[0]["source_ids"]))

    def test_temporary_condition_cannot_be_assumed_active(self):
        self.facts["candidate_item"]["effects"].append("fixture-temporary-focus")
        del self.facts["conditions"]["buff_active"]
        result = self.run_case()
        self.assertEqual("needs_confirmation", result["retention"])
        self.assertIn("unknown_condition:temporary-focus", result["blockers"])

    def test_companion_effect_does_not_apply_to_hero(self):
        self.facts["candidate_item"]["effects"] = ["fixture-companion-support"]
        result = self.run_case()
        rule = next(r for r in result["comparison"]["after"] if r["rule_id"] == "companion-support")
        self.assertNotIn("vitality-staff", rule["source_ids"])
        self.assertEqual("low_current_relevance", result["retention"])

    def test_embedded_effect_defaults_to_hero_and_retains_source_provenance(self):
        candidate = self.facts["candidate_item"]
        candidate["effects"] = []
        candidate["embedded_items"] = [{"id": "socketed", "effects": ["fixture-vitality-support"],
                                         "evidence_ids": ["demo-input"]}]
        result = self.run_case()
        rule = next(row for row in result["comparison"]["after"] if row["rule_id"] == "vitality-support")
        self.assertEqual("active", rule["state"])
        self.assertEqual([candidate["instance_id"] + ":socketed"], rule["source_ids"])
        self.assertEqual(["demo-input"], rule["input_evidence_ids"])
        self.assertEqual("keep", result["retention"])

    def test_rune_thresholds_count_only_matching_effect_owners(self):
        for rule_actor in ("hero", "companion"):
            for owners in ((None, None), ("hero", "companion"), ("companion", "companion")):
                facts, pack = copy.deepcopy(DEMO["facts"]), copy.deepcopy(PACK)
                rule = next(row for row in pack["rules"] if row["id"] == "frost-two")
                rule["actor"], rule["requires_skills"] = rule_actor, []
                for rune, owner in zip(facts["runes"], owners):
                    if owner is not None:
                        rune["actor"] = owner
                        if owner == "companion":
                            rune["companion_id"] = facts["companions"][0]["id"]
                expected_ids = sorted(rune["id"] for rune in facts["runes"]
                                      if rune.get("actor", "hero") == rule_actor)
                with self.subTest(rule_actor=rule_actor, owners=owners):
                    result = run_evaluation(facts, pack)
                    for phase in ("before", "after"):
                        resolved = next(row for row in result["comparison"][phase] if row["rule_id"] == "frost-two")
                        self.assertEqual("active" if len(expected_ids) >= 2 else "inactive", resolved["state"])
                        self.assertEqual(expected_ids, resolved["source_ids"])

    def test_hero_equipment_cannot_activate_a_companion_owned_set(self):
        next(rule for rule in self.pack["rules"] if rule["id"] == "archive-two")["actor"] = "companion"
        result = self.run_case()
        for phase in ("before", "after"):
            rule = next(row for row in result["comparison"][phase] if row["rule_id"] == "archive-two")
            self.assertEqual("inactive", rule["state"])
            self.assertEqual([], rule["source_ids"])

    def test_required_skills_must_belong_to_the_effect_owner(self):
        for skill_actor in ("hero", "companion"):
            facts = copy.deepcopy(DEMO["facts"])
            facts["skills"][0]["actor"] = skill_actor
            if skill_actor == "companion":
                facts["skills"][0]["companion_id"] = facts["companions"][0]["id"]
            pack = copy.deepcopy(PACK)
            companion = next(rule for rule in pack["rules"] if rule["id"] == "companion-support")
            companion["requires_skills"] = ["fixture-cold-bolt"]
            with self.subTest(skill_actor=skill_actor):
                rows = {row["rule_id"]: row for row in run_evaluation(facts, pack)["comparison"]["before"]}
                self.assertEqual("active" if skill_actor == "hero" else "inactive", rows["cold-focus"]["state"])
                self.assertEqual("active" if skill_actor == "companion" else "inactive", rows["companion-support"]["state"])

    def test_unknown_inventory_is_not_empty_inventory(self):
        self.facts["inventory_coverage"] = "unknown"
        result = self.run_case()
        self.assertEqual("needs_confirmation", result["retention"])
        self.assertIn("inventory_not_fully_scanned", result["blockers"])

    def test_equipping_and_retaining_have_separate_constraints(self):
        self.facts["candidate_item"]["required_level"] = 70
        result = self.run_case()
        self.assertEqual("keep", result["retention"])
        self.assertEqual("blocked", result["comparison"]["status"])
        self.assertEqual(["required_level_not_met"], result["comparison"]["equip_blockers"])

    def test_current_skill_selection_controls_relevance(self):
        self.facts["candidate_item"]["effects"] = ["fixture-cold-focus"]
        self.facts["skills"][0]["id"] = "fixture-fire-bolt"
        self.assertEqual("low_current_relevance", self.run_case()["retention"])

    def test_future_build_is_explicit_and_explained(self):
        self.facts["candidate_item"]["effects"] = ["fixture-fire-focus"]
        purpose = copy.deepcopy(DEMO["intent"])
        from tests.test_preparation import skill_quote
        quote = skill_quote(self.facts, rank=2, cost=0)
        removal = skill_quote(self.facts, self.facts["skills"][0]["id"], rank=0, option_id="remove-cold", cost=0)
        self.facts["preparation_options"] = [quote, removal]
        purpose["future_builds"] = [{"skills": ["fixture-fire-bolt"], "conditions": copy.deepcopy(self.facts["conditions"]),
                                    "feasibility": "hypothetical", "preparation_options": [quote["id"], removal["id"]]}]
        result = run_evaluation(self.facts, self.pack, purpose)
        self.assertEqual("candidate", result["retention"])
        self.assertEqual("hypothetical", result["reasons"][0]["feasibility"])

    def test_forbidden_future_change_requires_confirmation(self):
        purpose = copy.deepcopy(DEMO["intent"])
        purpose["allowed_build_changes"] = []
        purpose["future_builds"] = [{"skills": ["fixture-fire-bolt"], "conditions": {},
                                    "feasibility": "owned"}]
        self.assertIn("future_build_change_not_permitted",
                      run_evaluation(self.facts, self.pack, purpose)["blockers"])

    def test_rule_and_input_provenance_are_retained(self):
        result = self.run_case()
        self.assertTrue(all(r["evidence_ids"] == ["fixture-spec"] for r in result["reasons"]))
        self.assertTrue(all(r["input_evidence_ids"] == ["demo-input"] for r in result["reasons"]))
        self.assertEqual("1.0.0", result["pin"]["pack_version"])
        self.assertEqual(1, result["pin"]["intent_revision"])

    def test_deterministic_locked_input_ten_replays(self):
        expected = self.run_case()
        for _ in range(10):
            self.assertEqual(expected, self.run_case())

    def test_same_instant_different_timezone_is_consistent(self):
        self.facts["evidence"][0]["captured_at"] = "2026-01-01T08:00:00+08:00"
        self.assertNotIn("cross_time_snapshot", self.run_case()["blockers"])


def add_domain_case(name, mutation, check):
    def test(self):
        mutation(self.facts, self.pack)
        check(self, self.run_case())
    test.__name__ = "test_" + name
    setattr(DomainCases, test.__name__, test)


for context_key in CONTEXT_KEYS:
    for variant in ("different", "unknown"):
        def mutate(facts, _pack, key=context_key, value=variant):
            facts["context"][key] = value
        def check(test, result, key=context_key):
            test.assertEqual("needs_confirmation", result["retention"])
            test.assertEqual([], result["comparison"]["after"])
            test.assertIn("incompatible_context:" + key, result["blockers"])
        add_domain_case("context_" + context_key + "_" + variant, mutate, check)

for condition, effect, capability in (
    ("hero_cast", "fixture-mana-loop", "mana_loop"),
    ("mana_starved", "fixture-resource-efficiency", "resource_efficiency"),
    ("survival_required", "fixture-survival", "survival"),
    ("buff_active", "fixture-temporary-focus", "temporary_focus"),
    ("target_frozen", "fixture-frozen-bonus", "frozen_bonus"),
):
    for state in ("active", "inactive", "unknown"):
        def mutate(facts, _pack, key=condition, source=effect, value=state):
            facts["candidate_item"]["effects"] = [source]
            facts["conditions"][key] = value
        def check(test, result, expected=state, cap=capability):
            matching = next(r for r in result["comparison"]["after"] if r["capability"] == cap)
            test.assertEqual(expected, matching["state"])
            if expected == "unknown":
                test.assertEqual("needs_confirmation", result["retention"])
            elif expected == "active":
                test.assertEqual("keep", result["retention"])
            else:
                test.assertEqual("low_current_relevance", result["retention"])
        add_domain_case("condition_" + condition + "_" + state, mutate, check)

for index, capture_time in enumerate((
    "2026-01-01T00:00:01Z", "2026-01-01T00:01:00Z", "2026-01-01T01:00:00Z",
    "2026-01-02T00:00:00Z", "2025-12-31T23:59:59Z", "2025-12-31T23:00:00Z",
    "2025-12-30T00:00:00Z", "2026-01-01T00:00:00.001Z",
    "2026-01-01T00:00:00+01:00", "2026-01-01T00:00:00-01:00")):
    def mutate(facts, _pack, value=capture_time):
        facts["evidence"][0]["captured_at"] = value
    def check(test, result):
        test.assertEqual("needs_confirmation", result["retention"])
        test.assertIn("cross_time_snapshot", result["blockers"])
    add_domain_case("cross_time_" + str(index + 1), mutate, check)

for index in range(10):
    def mutate(facts, _pack, value=index):
        facts["candidate_item"]["affixes"][0]["value"] = 65 + value * 100
        facts["conditions"]["mana_starved"] = "active" if value % 2 else "inactive"
        facts["conditions"]["survival_required"] = "active" if value < 5 else "inactive"
    def check(test, result):
        test.assertEqual("mechanism_loss", result["comparison"]["status"])
        test.assertIn("archive_shield", result["comparison"]["lost_capabilities"])
        test.assertIn("mana_loop", result["comparison"]["lost_capabilities"])
    add_domain_case("replacement_stat_gain_core_loss_" + str(index + 1), mutate, check)

for field, value, expected in (
    ("unknowns", ["unmapped effect"], "item_unknown:unmapped effect"),
    ("unrevealed_properties", ["hidden affix"], "unrevealed_properties:vitality-staff"),
    ("required_level", None, "required_level_unknown:vitality-staff"),
    ("effects", ["unmapped"], "unknown_effect:unmapped"),
    ("set_id", "unmapped", "unknown_set:unmapped"),
    ("upgrade_state", {"known": False}, "item_modifications_unknown:vitality-staff"),
    ("socket_state", {"known": False}, "item_modifications_unknown:vitality-staff"),
):
    def mutate(facts, _pack, key=field, item_value=value):
        facts["candidate_item"][key] = item_value
    def check(test, result, blocker=expected):
        test.assertEqual("needs_confirmation", result["retention"])
        test.assertIn(blocker, result["blockers"])
    add_domain_case("unknown_item_" + field, mutate, check)

for game in ("diablo2_lod", "diablo2_resurrected", "diablo3", "diablo4"):
    def mutate(facts, _pack, game_id=game):
        facts["context"]["game_id"] = game_id
    def check(test, result):
        test.assertEqual([], result["comparison"]["after"])
        test.assertEqual("needs_confirmation", result["retention"])
    add_domain_case("cross_game_" + game, mutate, check)


class ValidationTests(unittest.TestCase):
    def test_nonfinite_and_duplicate_json_are_rejected(self):
        for raw in ('{"a":NaN}', '{"a":Infinity}', '{"a":1,"a":2}'):
            with self.subTest(raw=raw), self.assertRaises(DomainError):
                parse_json(raw)

    def test_template_cannot_be_an_owned_instance(self):
        facts = copy.deepcopy(DEMO["facts"])
        facts["candidate_item"]["record_kind"] = "item_template"
        with self.assertRaisesRegex(DomainError, "actual_item_instance_required"):
            snapshot(facts)

    def test_input_provenance_cannot_be_fabricated_by_unknown_ref(self):
        facts = copy.deepcopy(DEMO["facts"])
        facts["skills"][0]["evidence_ids"] = ["missing"]
        with self.assertRaisesRegex(DomainError, "fact_evidence_required"):
            snapshot(facts)

    def test_unconfirmed_input_does_not_become_fact(self):
        facts = copy.deepcopy(DEMO["facts"])
        facts["evidence"][0]["verification"] = "unconfirmed"
        with self.assertRaisesRegex(DomainError, "unconfirmed_fact"):
            snapshot(facts)

    def test_bool_and_nan_are_not_actual_rolls(self):
        for value in (True, float("nan"), float("inf")):
            facts = copy.deepcopy(DEMO["facts"])
            facts["candidate_item"]["affixes"][0]["value"] = value
            with self.subTest(value=value), self.assertRaisesRegex(DomainError, "actual_roll_and_unit_required"):
                snapshot(facts)

    def test_synthetic_rules_cannot_be_relabelled_as_real_game(self):
        pack = copy.deepcopy(PACK)
        pack["context"]["game_id"] = "deskrawl"
        with self.assertRaisesRegex(DomainError, "synthetic_scope_required"):
            validate_pack(pack)

    def test_each_rule_requires_evidence_and_scope(self):
        for key, value, error in (("evidence_ids", [], "rule_evidence_required"),
                                  ("context", {}, "rule_scope_mismatch"),
                                  ("actor", None, "effect_owner_required")):
            pack = copy.deepcopy(PACK)
            pack["rules"][0][key] = value
            with self.subTest(key=key), self.assertRaisesRegex(DomainError, error):
                validate_pack(pack)

    def test_future_storage_cannot_be_opened_by_old_code(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "profile.sqlite3"
            with connect(database) as db:
                db.execute("PRAGMA user_version=2")
            with self.assertRaisesRegex(DomainError, "incompatible_storage"):
                Profile(Path(directory))
            with connect(database) as db:
                self.assertEqual(2, db.execute("PRAGMA user_version").fetchone()[0])

    def test_existing_unknown_schema_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "profile.sqlite3"
            with connect(database) as db:
                db.execute("CREATE TABLE old_schema(value)")
            with self.assertRaisesRegex(DomainError, "unrecognized_storage"):
                Profile(Path(directory))

    def test_bundled_pack_files_and_index_are_verified(self):
        knowledge = Knowledge(ROOT / "knowledge-packs")
        self.assertEqual(7, len(knowledge.handle("GET", "/v1/packs", None)["packs"]))

    def test_research_pack_executes_no_game_rule(self):
        pack = json.loads((ROOT / "knowledge-packs/deskrawl-sorcerer-leveling-0.1.0-research.json").read_text())
        facts = copy.deepcopy(DEMO["facts"])
        facts["context"] = copy.deepcopy(pack["context"])
        result = run_evaluation(facts, pack)
        self.assertEqual([], result["comparison"]["before"])
        self.assertIn("game_mechanics_not_accepted", result["blockers"])

    def test_research_pack_cannot_contain_executable_rules(self):
        pack = json.loads((ROOT / "knowledge-packs/deskrawl-sorcerer-leveling-0.3.0-research.json").read_text())
        pack["rules"] = copy.deepcopy(PACK["rules"])
        with self.assertRaisesRegex(DomainError, "research_rules_not_executable"):
            validate_pack(pack)

    def test_research_policy_blocks_rules_even_from_invalid_upstream_data(self):
        pack = json.loads((ROOT / "knowledge-packs/deskrawl-sorcerer-leveling-0.3.0-research.json").read_text())
        facts = copy.deepcopy(DEMO["facts"])
        facts["context"] = copy.deepcopy(pack["context"])
        snapshot(facts)
        pack["rules"] = copy.deepcopy(PACK["rules"])
        pack["known_affixes"] = copy.deepcopy(PACK["known_affixes"])
        for rule in pack["rules"]:
            rule["context"] = copy.deepcopy(pack["context"])
        profile = {"contract_version": 1, "profile_id": "research", "revision": 1,
                   "facts": facts, "facts_hash": digest(facts)}
        result = evaluate(profile, {"pack": pack, "pack_hash": digest(pack)}, copy.deepcopy(DEMO["intent"]))
        self.assertIn("game_mechanics_not_accepted", result["blockers"])
        self.assertEqual("needs_confirmation", result["retention"])
        self.assertEqual([], result["comparison"]["before"])
        self.assertEqual([], result["comparison"]["after"])
        self.assertEqual([], result["reasons"])

    def test_new_research_pack_preserves_original_version_bytes(self):
        import hashlib
        original = ROOT / "knowledge-packs/deskrawl-sorcerer-leveling-0.1.0-research.json"
        self.assertEqual("3b396c8940c3f0bfd6f84d6652c1dbb4aea478a23af7ed7b8c3f42c828958fd0",
                         hashlib.sha256(original.read_bytes()).hexdigest())
        prior = ROOT / "knowledge-packs/deskrawl-sorcerer-leveling-0.2.0-research.json"
        self.assertEqual("8a9eab9aae84fab275aca716e3643aaeec75c6a02e78fd392c3ba3f382c0eb2c",
                         hashlib.sha256(prior.read_bytes()).hexdigest())
        knowledge = Knowledge(ROOT / "knowledge-packs")
        old = knowledge.handle("GET", "/v1/packs/deskrawl-sorcerer-leveling/0.1.0-research", None)
        new = knowledge.handle("GET", "/v1/packs/deskrawl-sorcerer-leveling/0.2.0-research", None)
        self.assertNotEqual(old["pack_hash"], new["pack_hash"])
        self.assertEqual(1, len(old["pack"]["evidence"]))
        self.assertEqual(2, len(new["pack"]["evidence"]))
        self.assertEqual("research_only", new["pack"]["execution_policy"])

    def test_changed_pack_bytes_are_rejected_by_bundled_index(self):
        import shutil
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "packs"
            shutil.copytree(ROOT / "knowledge-packs", target)
            path = target / "deskrawl-sorcerer-leveling-0.2.0-research.json"
            path.write_bytes(path.read_bytes() + b" ")
            with self.assertRaisesRegex(DomainError, "pack_file_integrity_error"):
                Knowledge(target)


if __name__ == "__main__":
    unittest.main()

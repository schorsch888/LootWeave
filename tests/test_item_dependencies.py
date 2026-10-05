from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from contracts import DomainError
from services.knowledge.app import Knowledge
from services.knowledge.domain import validate_pack

ROOT = Path(__file__).resolve().parents[1]
PACK_ID = "deskrawl-sorcerer-leveling"
VERSION = "0.7.0-research"


class ItemDependencyTests(unittest.TestCase):
    def setUp(self):
        self.knowledge = Knowledge(ROOT / "knowledge-packs")
        self.pack_result = self.knowledge.handle("GET", f"/v1/packs/{PACK_ID}/{VERSION}", {})
        self.pack = self.pack_result["pack"]
        self.request = {
            "pack_id": PACK_ID,
            "pack_version": VERSION,
            "pack_hash": self.pack_result["pack_hash"],
            "context": copy.deepcopy(self.pack["context"]),
            "class_id": self.pack["class_id"],
            "template_id": "LegendaryStaff1",
        }

    def query(self, request=None):
        return self.knowledge.handle("POST", "/v1/item-dependencies", self.request if request is None else request)

    def test_real_frostwyrm_static_association_matches_registration_research(self):
        result = self.query()
        dependency = result["dependency"]
        registration = json.loads(
            (ROOT / "research/deskrawl-frostwyrm-code-registration.json").read_text(encoding="utf-8"))
        objects = {item["object_id"]: item for item in registration["objects"]}
        source_links = {(item["source_id"], item["field"]): item["target_id"]
                        for item in registration["links"]}
        self.assertEqual(("LegendaryStaff1", "Staff of the Frostwyrm"),
                         (dependency["template_id"], dependency["template_name"]))
        self.assertEqual(("SorcererBasicAttack2", "Ice Shards"),
                         (dependency["ability_id"], dependency["ability_name"]))
        self.assertEqual("resources.assets:4972", dependency["template_object_id"])
        self.assertEqual("resources.assets:4793", dependency["effect_object_id"])
        self.assertEqual("sharedassets0.assets:59839", dependency["ability_object_id"])
        for dto_key in ("template_object_id", "effect_object_id", "ability_object_id"):
            object_id = dependency[dto_key]
            expected_name = dependency["template_id"] if dto_key != "ability_object_id" else dependency["ability_id"]
            self.assertEqual(expected_name, objects[object_id]["name"])
        self.assertEqual([("resources.assets:4972", "equipment_effect", "resources.assets:4793"),
                          ("resources.assets:4793", "affected_ability", "sharedassets0.assets:59839")],
                         [(x["source_id"], x["relation"], x["target_id"]) for x in dependency["object_links"]])
        self.assertEqual("resources.assets:4793", source_links[(dependency["template_object_id"],
                                                                  "$.EquipmentEffects[0]")])
        self.assertEqual("sharedassets0.assets:59839", source_links[(dependency["effect_object_id"],
                                                                      "$.Ability")])
        self.assertEqual("item_template_dependency", result["record_kind"])
        self.assertEqual("reviewed_static_only", result["scope"])
        self.assertFalse(result["mechanics_accepted"])
        self.assertEqual({"deskrawl-frostwyrm-native-review", "deskrawl-frostwyrm-registration-review"},
                         {item["id"] for item in result["evidence"]})

    def test_catalog_advertises_only_versioned_dependency_templates(self):
        catalog = self.knowledge.handle("GET", "/v1/packs", {})["packs"]
        listed = next(item for item in catalog if item["version"] == VERSION)
        self.assertEqual([{"template_id": "LegendaryStaff1", "label": "Staff of the Frostwyrm"}],
                         listed["dependency_templates"])
        old = next(item for item in catalog if item["version"] == "0.6.0-research")
        self.assertNotIn("dependency_templates", old)

    def test_scope_hash_version_and_template_are_strictly_pinned(self):
        for change, code in (
            (lambda b: b.update(pack_hash="0" * 64), "pack_hash_conflict"),
            (lambda b: b.update(pack_version="latest"), "pack_version_not_found"),
            (lambda b: b.update(context={**b["context"], "game_build": "wrong"}), "dependency_scope_mismatch"),
            (lambda b: b.update(context={**b["context"], "mode": "offline"}), "dependency_scope_mismatch"),
            (lambda b: b.update(context={**b["context"], "content_entitlements": ["other"]}),
             "dependency_scope_mismatch"),
            (lambda b: b.update(class_id="barbarian"), "dependency_scope_mismatch"),
            (lambda b: b.update(template_id="UnknownStaff"), "dependency_template_not_found"),
        ):
            request = copy.deepcopy(self.request)
            change(request)
            with self.subTest(code=code), self.assertRaisesRegex(DomainError, code):
                self.query(request)

    def test_result_mutation_does_not_change_cached_knowledge(self):
        before = self.knowledge.handle("GET", f"/v1/packs/{PACK_ID}/{VERSION}", {})
        result = self.query()
        result["dependency"]["object_links"].clear()
        result["evidence"].clear()
        self.assertEqual(before, self.knowledge.handle("GET", f"/v1/packs/{PACK_ID}/{VERSION}", {}))

    def test_pack_validator_rejects_duplicate_dangling_or_accepted_dependency_graphs(self):
        mutations = (
            (lambda p: p["item_dependencies"].append(copy.deepcopy(p["item_dependencies"][0])),
             "duplicate_item_dependency"),
            (lambda p: p["item_dependencies"][0]["evidence_ids"].append("unlinked-evidence"),
             "dependency_evidence_required"),
            (lambda p: p["item_dependencies"][0]["object_links"].pop(), "invalid_dependency_links"),
            (lambda p: p["item_dependencies"][0].update(status="accepted"), "dependency_data_unavailable"),
            (lambda p: p["item_dependencies"][0].update(mechanics_accepted=True), "invalid_item_dependency"),
            (lambda p: (p.update(context={**p["context"], "game_id": "lootweave-fixture"}),
                        p.update(execution_policy="synthetic_only")), "dependency_data_unavailable"),
        )
        for mutate, code in mutations:
            candidate = copy.deepcopy(self.pack)
            mutate(candidate)
            with self.subTest(code=code), self.assertRaisesRegex(DomainError, code):
                validate_pack(candidate)

    def test_research_pack_still_has_no_executable_rules(self):
        self.assertEqual("research_only", self.pack["execution_policy"])
        self.assertEqual([], self.pack["rules"])


if __name__ == "__main__":
    unittest.main()

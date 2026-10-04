"""Fictional metadata/PE linkage checks; no game bytes or execution."""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import struct
import unittest

from contracts import digest
from scripts.validate_deskrawl_frostwyrm import (
    check_metadata_slots, check_native, check_native_module_methods, pe_layout,
)
from services.knowledge.app import Knowledge
from services.knowledge.domain import validate_pack
from test_metadata_slots import metadata_fixture
from test_research_evidence import native_fixture

ROOT = Path(__file__).resolve().parents[1]


def module_fixture():
    data, metadata, locations = metadata_fixture(with_image=True)
    binary, evidence = native_fixture()
    base = evidence["native_image_base"]
    name = b"Assembly-CSharp.dll\0"
    binary[0x280:0x280 + len(name)] = name
    struct.pack_into("<QqQ", binary, 0x240, base + 0x1080, 4, base + 0x10C0)
    binary[0x220] = 0xC3
    first = evidence["native_methods"][0]
    first["name"] = "FixtureEffect.apply"
    evidence["native_methods"].append({
        "name": "FixtureEffect.remove", "rva": 0x1020, "offset": 0x220,
        "length": 1, "sha256": hashlib.sha256(binary[0x220:0x221]).hexdigest(),
    })
    evidence["native_review"][0]["method"] = first["name"]
    struct.pack_into("<4Q", binary, 0x2C0, 0, 0, base + 0x1010, base + 0x1020)
    evidence["metadata_method_slots"] = metadata
    evidence["native_module_methods"] = {
        "source_ref": "game://GameAssembly.dll", "pointer_size": 8,
        "module_name": "Assembly-CSharp.dll", "module_rva": 0x1040,
        "module_name_rva": 0x1080, "method_pointer_count": 4, "method_pointers_rva": 0x10C0,
        "methods": [
            {"method_index": 2, "token": 0x06000003, "pointer_index": 2, "native_method": "FixtureEffect.apply"},
            {"method_index": 3, "token": 0x06000004, "pointer_index": 3, "native_method": "FixtureEffect.remove"},
        ],
    }
    return binary, evidence, data, metadata, locations


def module_check(binary, evidence):
    base, sections = pe_layout(binary)
    return check_native_module_methods(binary, sections, base, evidence)


class NativeModuleTests(unittest.TestCase):
    def test_image_ownership_tokens_pointers_and_hashed_bodies_form_one_chain(self):
        binary, evidence, data, metadata, _ = module_fixture()
        self.assertEqual({"metadata_image_checks": 1, "metadata_type_checks": 2,
                          "metadata_method_checks": 4, "metadata_vtable_target_checks": 2},
                         check_metadata_slots(data, metadata))
        self.assertEqual(2, module_check(binary, evidence))
        self.assertEqual(2, check_native(binary, evidence))

    def test_false_image_identity_member_range_or_layout_claims_fail(self):
        _, _, data, metadata, locations = module_fixture()
        for key, value in (("image_index", True), ("image_index", 1), ("name", "Other.dll"),
                           ("assembly_index", 1), ("type_start", 1), ("type_count", 1)):
            altered = copy.deepcopy(metadata)
            altered["image"][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                check_metadata_slots(data, altered)
        for offset, format_, value in (
                (8 + 20 * 12 + 4, "<I", 35),
                (locations["images"] + 4, "<i", -1),
                (locations["images"] + 8, "<H", 256)):
            altered = bytearray(data)
            struct.pack_into(format_, altered, offset, value)
            with self.subTest(offset=offset), self.assertRaises(ValueError):
                check_metadata_slots(altered, metadata)
        altered = bytearray(data)
        struct.pack_into("<I", altered, locations["images"] + 10, 1)
        narrowed = copy.deepcopy(metadata)
        narrowed["image"]["type_count"] = 1
        with self.assertRaisesRegex(ValueError, "metadata_type_outside_image"):
            check_metadata_slots(altered, narrowed)

    def test_module_prefix_name_and_full_table_ranges_are_checked(self):
        binary, evidence, _, _, _ = module_fixture()
        for offset, format_, value in ((0x240, "<Q", 0), (0x248, "<q", -1), (0x250, "<Q", 0),
                                       (0x280, "<B", ord("X")), (0x293, "<B", ord("X"))):
            altered = bytearray(binary)
            struct.pack_into(format_, altered, offset, value)
            with self.subTest(offset=offset), self.assertRaises(ValueError):
                module_check(altered, evidence)
        for key, value in (("pointer_size", 4), ("module_rva", 0x10F0),
                           ("module_name_rva", 0x1081), ("method_pointer_count", 5),
                           ("method_pointers_rva", 0x10C1), ("source_ref", "game://Other.dll")):
            altered = copy.deepcopy(evidence)
            altered["native_module_methods"][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                module_check(binary, altered)
        altered = bytearray(binary)
        struct.pack_into("<q", altered, 0x248, 1000)
        claimed = copy.deepcopy(evidence)
        claimed["native_module_methods"]["method_pointer_count"] = 1000
        with self.assertRaisesRegex(ValueError, "unmapped_native_range"):
            module_check(altered, claimed)

    def test_wrong_or_null_targets_and_token_index_claims_fail(self):
        binary, evidence, _, _, _ = module_fixture()
        for target in (0, evidence["native_image_base"] + 0x1020, evidence["native_image_base"] + 0x1011):
            altered = bytearray(binary)
            struct.pack_into("<Q", altered, 0x2D0, target)
            with self.subTest(target=target), self.assertRaisesRegex(ValueError, "native_module_method_target"):
                module_check(altered, evidence)
        for key, value in (("method_index", True), ("method_index", 0), ("token", 0x06000004),
                           ("pointer_index", 3), ("native_method", "FixtureEffect.remove")):
            altered = copy.deepcopy(evidence)
            altered["native_module_methods"]["methods"][0][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                module_check(binary, altered)
        altered = copy.deepcopy(evidence)
        del altered["native_methods"][0]
        with self.assertRaisesRegex(ValueError, "native_module_target_missing"):
            module_check(binary, altered)

    def test_bindings_cannot_be_omitted_duplicated_or_outside_the_table(self):
        binary, evidence, _, _, _ = module_fixture()
        for entries, error in (
                ([], "native_module_methods_missing"),
                (evidence["native_module_methods"]["methods"][:1], "native_module_bindings_incomplete"),
                ([evidence["native_module_methods"]["methods"][0]] * 2, "duplicate_native_module_method")):
            altered = copy.deepcopy(evidence)
            altered["native_module_methods"]["methods"] = entries
            with self.subTest(error=error), self.assertRaisesRegex(ValueError, error):
                module_check(binary, altered)
        altered = bytearray(binary)
        struct.pack_into("<q", altered, 0x248, 3)
        claimed = copy.deepcopy(evidence)
        claimed["native_module_methods"]["method_pointer_count"] = 3
        with self.assertRaisesRegex(ValueError, "native_module_pointer_outside_table"):
            module_check(altered, claimed)

    def test_native_module_requires_the_same_validated_metadata_image(self):
        binary, evidence, data, metadata, _ = module_fixture()
        altered = copy.deepcopy(evidence)
        del altered["metadata_method_slots"]["image"]
        with self.assertRaisesRegex(ValueError, "native_module_metadata_image_required"):
            module_check(binary, altered)
        altered = copy.deepcopy(evidence)
        altered["metadata_method_slots"]["image"]["name"] = "Other.dll"
        with self.assertRaisesRegex(ValueError, "native_module_image"):
            module_check(binary, altered)
        # A claim cannot remove a concrete method from the pointer coverage contract.
        altered = copy.deepcopy(metadata)
        altered["types"][1]["methods"][0]["vtable_method_definition"] = False
        with self.assertRaisesRegex(ValueError, "metadata_vtable_policy_required"):
            check_metadata_slots(data, altered)

    def test_new_research_pack_pins_the_record_and_keeps_prior_bytes(self):
        path = ROOT / "knowledge-packs/deskrawl-sorcerer-leveling-0.5.0-research.json"
        pack = json.loads(path.read_text(encoding="utf-8"))
        validate_pack(pack)
        self.assertEqual("research_only", pack["execution_policy"])
        self.assertEqual([], pack["rules"])
        knowledge = Knowledge(ROOT / "knowledge-packs")
        loaded = knowledge.handle("GET", "/v1/packs/deskrawl-sorcerer-leveling/0.5.0-research", {})
        self.assertEqual(digest(pack), loaded["pack_hash"])
        record = json.loads((ROOT / "research/deskrawl-frostwyrm-module-pointers.json").read_text(encoding="utf-8"))
        self.assertEqual("not_performed", record["online_validation"])
        self.assertEqual("research_only", record["candidate_mechanism"]["execution_status"])
        prior = ROOT / record["previous_record"]["source_ref"].removeprefix("repo://")
        self.assertEqual(hashlib.sha256(prior.read_bytes()).hexdigest(), record["previous_record"]["sha256"])
        self.assertEqual("026d7b9ed22753aa09ae2d41ac40ca3f2daac2fe1380a6f3ca1180d8c9fdd0b8",
                         hashlib.sha256((ROOT / "knowledge-packs/deskrawl-sorcerer-leveling-0.4.0-research.json").read_bytes()).hexdigest())


if __name__ == "__main__":
    unittest.main()

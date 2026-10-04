"""Fictional metadata guards; original game bytes are never bundled or executed."""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import struct
import unittest

from contracts import DomainError, digest
from scripts.validate_deskrawl_frostwyrm import check_metadata_slots
from services.knowledge.app import Knowledge
from services.knowledge.domain import validate_pack

ROOT = Path(__file__).resolve().parents[1]


def metadata_fixture(with_image=False):
    data = bytearray(380)
    struct.pack_into("<II", data, 0, 0xFAB11BAF, 39)
    def section(index, payload, count):
        offset = len(data)
        data.extend(payload)
        struct.pack_into("<III", data, 8 + index * 12, offset, len(payload), count)
        return offset
    names = b"\0FixtureBase\0FixtureEffect\0apply\0remove\0"
    if with_image:
        names += b"Assembly-CSharp.dll\0"
    strings = section(2, names, 5)
    method_table = section(5, bytes(4 * 30), 4)
    section(10, bytes(65536 * 10), 65536)
    section(14, bytes(256 * 16), 256)
    vtables = section(17, bytes(16 * 4), 16)
    section(18, bytes(6), 1)
    type_table = section(19, bytes(256 * 76), 256)
    types = []
    for index, name in enumerate(("FixtureBase", "FixtureEffect")):
        position = type_table + index * 76
        struct.pack_into("<II", data, position, names.index(name.encode()), 0)
        struct.pack_into("<I", data, position + 24, index * 2)
        struct.pack_into("<I", data, position + 44, index * 8)
        struct.pack_into("<8H", data, position + 52, 2, 0, 0, 0, 0, 8, 0, 0)
        methods = []
        for delta, method_name in enumerate(("apply", "remove")):
            method_index, slot = index * 2 + delta, 4 + delta
            method = {"method_index": method_index, "name": method_name, "declaring_type_index": index,
                      "token": 0x06000001 + method_index, "flags": 0x446 if index == 0 else 0x46,
                      "implementation_flags": 0, "slot": slot, "parameter_count": 1,
                      "vtable_method_definition": index == 1}
            base = method_table + method_index * 30
            struct.pack_into("<IH", data, base, names.index(method_name.encode()), index)
            struct.pack_into("<I4H", data, base + 18, method["token"], method["flags"], 0, slot, 1)
            struct.pack_into("<I", data, vtables + (index * 8 + slot) * 4,
                             1 if index == 0 else 0x60000000 | (method_index << 1) | 1)
            methods.append(method)
        types.append({"type_index": index, "name": name, "namespace": "", "method_start": index * 2,
                      "method_count": 2, "vtable_start": index * 8, "vtable_count": 8, "methods": methods})
    spec = {"metadata_version": 39, "types": types}
    locations = {"strings": strings, "methods": method_table, "vtables": vtables, "types": type_table}
    if with_image:
        image = section(20, bytes(36), 1)
        struct.pack_into("<IiHI", data, image, names.index(b"Assembly-CSharp.dll"), 0, 0, 2)
        section(21, bytes(1), 1)
        spec["image"] = {"image_index": 0, "name": "Assembly-CSharp.dll",
                         "assembly_index": 0, "type_start": 0, "type_count": 2}
        locations["images"] = image
    return data, spec, locations


class MetadataSlotTests(unittest.TestCase):
    def test_base_declarations_and_concrete_targets_are_separate_checks(self):
        data, spec, _ = metadata_fixture()
        self.assertEqual({"metadata_type_checks": 2, "metadata_method_checks": 4,
                          "metadata_vtable_target_checks": 2}, check_metadata_slots(data, spec))

    def test_version_width_stride_bounds_and_overlap_are_rejected(self):
        data, spec, locations = metadata_fixture()
        mutations = [
            (0, "<I", 0, "unsupported_metadata_layout"),
            (4, "<I", 38, "unsupported_metadata_layout"),
            (8 + 2 * 12, "<I", len(data) + 1, "metadata_section_outside_file"),
            (8 + 19 * 12 + 8, "<I", 255, "unsupported_metadata_index_widths"),
            (8 + 5 * 12 + 4, "<I", 119, "metadata_table_stride"),
            (8 + 5 * 12, "<I", locations["strings"], "metadata_sections_overlap"),
            (locations["types"] + 24, "<I", 4, "metadata_type_members_outside_table"),
            (locations["types"] + 44, "<I", 16, "metadata_type_members_outside_table"),
        ]
        for offset, format_, value, error in mutations:
            with self.subTest(error=error):
                altered = bytearray(data)
                struct.pack_into(format_, altered, offset, value)
                with self.assertRaisesRegex(ValueError, error):
                    check_metadata_slots(altered, spec)
        with self.assertRaisesRegex(ValueError, "truncated_metadata_header"):
            check_metadata_slots(data[:379], spec)

    def test_false_owner_name_token_slot_or_signature_claims_fail(self):
        data, spec, _ = metadata_fixture()
        for key, value in (("name", "other"), ("declaring_type_index", 1), ("token", 0x06000099),
                           ("flags", 0x46), ("implementation_flags", 1), ("slot", 5),
                           ("parameter_count", 0), ("method_index", 2), ("method_index", True),
                           ("vtable_method_definition", 1)):
            with self.subTest(key=key, value=value):
                altered = copy.deepcopy(spec)
                altered["types"][0]["methods"][0][key] = value
                with self.assertRaises(ValueError):
                    check_metadata_slots(data, altered)
        for key, value in (("type_index", True), ("name", "other"), ("namespace", "other"),
                           ("method_start", 1), ("vtable_count", 9)):
            with self.subTest(type_key=key):
                altered = copy.deepcopy(spec)
                altered["types"][0][key] = value
                with self.assertRaises(ValueError):
                    check_metadata_slots(data, altered)
        for duplicate in ("type", "method"):
            altered = copy.deepcopy(spec)
            if duplicate == "type":
                altered["types"].append(copy.deepcopy(altered["types"][0]))
            else:
                altered["types"][0]["methods"].append(copy.deepcopy(altered["types"][0]["methods"][0]))
            with self.subTest(duplicate=duplicate), self.assertRaisesRegex(ValueError, "duplicate_metadata"):
                check_metadata_slots(data, altered)

    def test_concrete_vtable_entries_cannot_target_another_method_or_metadata_kind(self):
        data, spec, locations = metadata_fixture()
        altered_spec = copy.deepcopy(spec)
        altered_spec["types"][1]["methods"][0]["vtable_method_definition"] = False
        with self.assertRaisesRegex(ValueError, "metadata_vtable_policy_required"):
            check_metadata_slots(data, altered_spec)
        target = locations["vtables"] + (8 + 4) * 4
        for encoded, error in ((0x60000007, "metadata_vtable_target"),
                               (0xC0000005, "metadata_vtable_not_method_definition"),
                               (1, "metadata_vtable_not_method_definition")):
            altered = bytearray(data)
            struct.pack_into("<I", altered, target, encoded)
            with self.subTest(encoded=encoded), self.assertRaisesRegex(ValueError, error):
                check_metadata_slots(altered, spec)

    def test_string_offsets_and_termination_stay_inside_the_string_section(self):
        data, spec, locations = metadata_fixture()
        altered = bytearray(data)
        struct.pack_into("<I", altered, locations["types"], 0xFFFFFFFF)
        with self.assertRaisesRegex(ValueError, "metadata_string_outside_section"):
            check_metadata_slots(altered, spec)
        altered = bytearray(data)
        # The last selected name reaches the string boundary; no later table supplies its terminator.
        names_size = struct.unpack_from("<I", altered, 8 + 2 * 12 + 4)[0]
        altered[locations["strings"] + names_size - 1] = ord("x")
        with self.assertRaisesRegex(ValueError, "metadata_string_unterminated"):
            check_metadata_slots(altered, spec)

    def test_all_research_versions_remain_explicit_and_quarantined(self):
        knowledge = Knowledge(ROOT / "knowledge-packs")
        rows = knowledge.handle("GET", "/v1/packs", None)["packs"]
        self.assertEqual(["0.1.0-research", "0.2.0-research", "0.3.0-research", "0.4.0-research", "0.5.0-research", "0.6.0-research"],
                         sorted(row["version"] for row in rows if row["pack_id"] == "deskrawl-sorcerer-leveling"))
        for version in ("0.1.0", "0.2.0", "0.3.0", "0.4.0"):
            result = knowledge.handle("GET", f"/v1/packs/deskrawl-sorcerer-leveling/{version}-research", None)
            self.assertEqual(digest(result["pack"]), result["pack_hash"])
            self.assertEqual([], result["pack"]["rules"])
            self.assertEqual("research_only", result["pack"]["execution_policy"])
            altered = copy.deepcopy(result["pack"])
            altered["rules"] = [{}]
            with self.assertRaisesRegex(DomainError, "research_rules_not_executable"):
                validate_pack(altered)
        prior = ROOT / "knowledge-packs/deskrawl-sorcerer-leveling-0.3.0-research.json"
        self.assertEqual("592e372204e60d5c5bf853b3131151ff980a9c2987c364a70520debd074c15d5",
                         hashlib.sha256(prior.read_bytes()).hexdigest())


if __name__ == "__main__":
    unittest.main()

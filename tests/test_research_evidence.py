"""Portable identity regressions; synthetic PE bytes never execute game code."""
from __future__ import annotations

import copy
import hashlib
import json
import struct
import tempfile
import unittest
from pathlib import Path

from scripts.validate_deskrawl_frostwyrm import (
    check_graph, check_native, pe_layout, pe_offset, read_objects, validate,
)

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = json.loads((ROOT / "research/deskrawl-frostwyrm.json").read_text(encoding="utf-8"))


def graph_fixture():
    records = {
        spec["object_id"]: {
            "object_id": spec["object_id"], "class_name": spec["class_name"], "name": spec["name"],
            "expected_byte_size": spec["byte_size"], "consumed_bytes": spec["byte_size"],
            "validation": {flag: True for flag in (
                "full_byte_count", "builtin_header_matches", "strict_parser_success")},
            "data": copy.deepcopy(spec["fields"]), "references": [],
        }
        for spec in EVIDENCE["objects"]
    }
    for link in EVIDENCE["links"]:
        records[link["source_id"]]["references"].append({
            "field": link["field"], "raw": copy.deepcopy(link["raw"]), "target_id": link["target_id"],
            "resolved": True, "target_parsed": True, "target_parse_failed": False,
        })
    for spec in EVIDENCE["managed_effects"]:
        records[spec["object_id"]]["data"]["references"] = {
            "version": spec["registry_version"],
            "RefIds": [{"rid": spec["rid"], "type": copy.deepcopy(spec["type"]), "data": copy.deepcopy(spec["fields"])}],
        }
    return records


def native_fixture():
    binary = bytearray(0x400)
    binary[:2] = b"MZ"
    struct.pack_into("<I", binary, 0x3C, 0x80)
    binary[0x80:0x84] = b"PE\0\0"
    struct.pack_into("<HH", binary, 0x84, 0x8664, 1)
    struct.pack_into("<H", binary, 0x94, 0xF0)
    struct.pack_into("<H", binary, 0x98, 0x20B)
    struct.pack_into("<Q", binary, 0xB0, 0x180000000)
    struct.pack_into("<8sIIII", binary, 0x188, b".text\0\0\0", 0x100, 0x1000, 0x200, 0x200)
    binary[0x210:0x214] = b"\x31\xc0\xc3\x90"
    evidence = {
        "native_image_base": 0x180000000,
        "native_methods": [{"name": "fixture", "rva": 0x1010, "offset": 0x210, "length": 4,
                            "sha256": hashlib.sha256(binary[0x210:0x214]).hexdigest()}],
        "native_review": [{"method": "fixture", "rvas": [0x1010]}],
    }
    return binary, evidence


class SourceEvidenceTests(unittest.TestCase):
    def test_incomplete_parse_or_mistyped_field_fails(self):
        records = graph_fixture()
        check_graph(EVIDENCE, records)
        key = "resources.assets:4793"
        for flag in ("full_byte_count", "builtin_header_matches", "strict_parser_success"):
            altered = copy.deepcopy(records)
            del altered[key]["validation"][flag]
            with self.subTest(flag=flag), self.assertRaisesRegex(ValueError, "object_validation"):
                check_graph(EVIDENCE, altered)
        for field, value, error in (
                ("consumed_bytes", 67, "object_consumption"),
                ("class_name", "ItemData", "object_class")):
            altered = copy.deepcopy(records)
            altered[key][field] = value
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, error):
                check_graph(EVIDENCE, altered)
        altered = copy.deepcopy(records)
        altered[key]["data"]["Deflects"] = True
        with self.assertRaisesRegex(ValueError, "object_field"):
            check_graph(EVIDENCE, altered)

    def test_pointer_target_and_resolution_are_not_name_matches(self):
        records = graph_fixture()
        key = "resources.assets:4972"
        for field, value, error in (
                ("target_id", "resources.assets:4972", "reference_target"),
                ("raw", {"m_FileID": 2, "m_PathID": 4793}, "reference_raw"),
                ("resolved", False, "reference_unverified"),
                ("target_parsed", False, "reference_unverified"),
                ("target_parse_failed", True, "reference_unverified")):
            altered = copy.deepcopy(records)
            altered[key]["references"][0][field] = value
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, error):
                check_graph(EVIDENCE, altered)
        altered = copy.deepcopy(records)
        altered[key]["references"].append(copy.deepcopy(altered[key]["references"][0]))
        with self.assertRaisesRegex(ValueError, "reference_not_unique"):
            check_graph(EVIDENCE, altered)

    def test_managed_registry_identity_cannot_be_ambiguous(self):
        records = graph_fixture()
        key = "sharedassets0.assets:59839"
        for change, error in (
                ("version", "managed_registry_version"),
                ("duplicate", "managed_effect_not_unique"),
                ("type", "managed_effect_type"),
                ("field", "managed_effect_field")):
            altered = copy.deepcopy(records)
            registry = altered[key]["data"]["references"]
            if change == "version":
                registry["version"] = 1
            elif change == "duplicate":
                registry["RefIds"].append(copy.deepcopy(registry["RefIds"][0]))
            elif change == "type":
                registry["RefIds"][0]["type"]["class"] = "DamageEffect"
            else:
                registry["RefIds"][0]["data"]["RehitInterval"] = 1.0
            with self.subTest(change=change), self.assertRaisesRegex(ValueError, error):
                check_graph(EVIDENCE, altered)

    def test_duplicate_and_missing_selected_records_are_rejected(self):
        records = graph_fixture()
        wanted = set(records)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "objects.jsonl"
            rows = list(records.values())
            for values, error in ((rows[:-1], "selected_objects_missing"),
                                  (rows + [rows[0]], "duplicate_selected_object")):
                path.write_text("\n".join(json.dumps(row) for row in values), encoding="utf-8")
                with self.subTest(error=error), self.assertRaisesRegex(ValueError, error):
                    read_objects(path, wanted)

    def test_native_bytes_mapping_and_review_addresses_remain_pinned(self):
        binary, evidence = native_fixture()
        self.assertEqual(1, check_native(binary, evidence))
        corrupted = bytearray(binary)
        corrupted[0x211] ^= 1
        with self.assertRaisesRegex(ValueError, "native_method_hash"):
            check_native(corrupted, evidence)
        for key, value, error in (
                ("offset", 0x211, "native_pe_mapping"),
                ("length", 0x200, "unmapped_native_range")):
            altered = copy.deepcopy(evidence)
            altered["native_methods"][0][key] = value
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, error):
                check_native(binary, altered)
        altered = copy.deepcopy(evidence)
        altered["native_review"][0]["rvas"] = [0x1014]
        with self.assertRaisesRegex(ValueError, "review_address_outside_method"):
            check_native(binary, altered)

    def test_pe_rejects_wrong_architecture_and_unbacked_addresses(self):
        binary, _evidence = native_fixture()
        _base, sections = pe_layout(binary)
        for rva, length, error in (
                (0x10FF, 2, "unmapped_native_range"),
                (0x1100, 1, "unmapped_native_range"),
                (True, 1, "invalid_native_range"),
                (0x1010, 0, "invalid_native_range")):
            with self.subTest(rva=rva, length=length), self.assertRaisesRegex(ValueError, error):
                pe_offset(len(binary), sections, rva, length)
        with self.assertRaisesRegex(ValueError, "truncated_native_range"):
            pe_offset(0x210, sections, 0x1010, 4)
        altered = bytearray(binary)
        struct.pack_into("<H", altered, 0x84, 0x14C)
        with self.assertRaisesRegex(ValueError, "invalid_x64_pe"):
            pe_layout(altered)
        with self.assertRaisesRegex(ValueError, "invalid_pe"):
            pe_layout(binary[:40])

    def test_required_source_identity_cannot_be_omitted(self):
        for missing in ("game://Deskrawl_Data/resources.assets",
                        "repo://data/extracted/deskrawl/25690430/objects.jsonl"):
            altered = copy.deepcopy(EVIDENCE)
            altered["sources"] = [source for source in altered["sources"] if source["path"] != missing]
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                (root / "manifest.json").write_text(json.dumps({"build_id": "25690430"}), encoding="utf-8")
                with self.subTest(missing=missing), self.assertRaisesRegex(ValueError, "^source_identity_missing$"):
                    validate(altered, root / "missing-game", root)

    def test_extraction_build_mismatch_fails_before_using_sources(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "manifest.json").write_text(json.dumps({"build_id": "different"}), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "extraction_build_mismatch"):
                validate(EVIDENCE, root / "missing-game", root)

    def test_native_relative_calls_and_backward_tail_jumps(self):
        for kind, target_rva in (("call", 0x1020), ("tail_jump", 0x1000)):
            binary, evidence = native_fixture()
            source = evidence["native_methods"][0]
            source["length"] = 5
            target_offset = 0x200 + target_rva - 0x1000
            binary[target_offset:target_offset + 4] = b"\x31\xc0\xc3\x90"
            binary[0x210] = 0xE8 if kind == "call" else 0xE9
            struct.pack_into("<i", binary, 0x211, target_rva - 0x1015)
            source["sha256"] = hashlib.sha256(binary[0x210:0x215]).hexdigest()
            evidence["native_methods"].append({
                "name": "target", "rva": target_rva, "offset": target_offset, "length": 4,
                "sha256": hashlib.sha256(binary[target_offset:target_offset + 4]).hexdigest()})
            evidence["native_links"] = [{
                "source_method": "fixture", "instruction_rva": 0x1010, "kind": kind, "target_method": "target"}]
            with self.subTest(kind=kind):
                self.assertEqual(2, check_native(binary, evidence))

    def test_native_link_tampering_fails_even_with_matching_method_hashes(self):
        binary, evidence = native_fixture()
        source = evidence["native_methods"][0]
        source["length"] = 5
        binary[0x210] = 0xE8
        struct.pack_into("<i", binary, 0x211, 0x1020 - 0x1015)
        binary[0x220:0x224] = b"\x31\xc0\xc3\x90"
        source["sha256"] = hashlib.sha256(binary[0x210:0x215]).hexdigest()
        evidence["native_methods"].append({
            "name": "target", "rva": 0x1020, "offset": 0x220, "length": 4,
            "sha256": hashlib.sha256(binary[0x220:0x224]).hexdigest()})
        evidence["native_links"] = [{
            "source_method": "fixture", "instruction_rva": 0x1010, "kind": "call", "target_method": "target"}]
        for change, error in (
                ("target", "native_link_target"), ("opcode", "native_link_opcode"),
                ("range", "native_link_outside_method"), ("duplicate", "duplicate_native_link"),
                ("method", "native_link_method_missing")):
            data, spec = bytearray(binary), copy.deepcopy(evidence)
            if change == "target":
                struct.pack_into("<i", data, 0x211, 0x1021 - 0x1015)
            elif change == "opcode":
                data[0x210] = 0x90
            elif change == "range":
                spec["native_links"][0]["instruction_rva"] += 1
            elif change == "duplicate":
                spec["native_links"].append(copy.deepcopy(spec["native_links"][0]))
            else:
                spec["native_links"][0]["target_method"] = "missing"
            spec["native_methods"][0]["sha256"] = hashlib.sha256(data[0x210:0x215]).hexdigest()
            with self.subTest(change=change), self.assertRaisesRegex(ValueError, error):
                check_native(data, spec)

    def test_exception_directory_independently_pins_native_bounds(self):
        binary, evidence = native_fixture()
        struct.pack_into("<I", binary, 0x98 + 108, 4)
        struct.pack_into("<II", binary, 0x98 + 136, 0x1080, 12)
        struct.pack_into("<III", binary, 0x280, 0x1010, 0x1014, 0x1090)
        evidence["native_methods"][0].update(bounds_source="pe_exception_directory", unwind_info_rva=0x1090)
        self.assertEqual(1, check_native(binary, evidence))
        for field, value in ((0x284, 0x1015), (0x288, 0x1094)):
            data = bytearray(binary)
            struct.pack_into("<I", data, field, value)
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, "native_unwind_bounds"):
                check_native(data, evidence)

    def test_missing_or_ambiguous_exception_directory_is_rejected(self):
        binary, evidence = native_fixture()
        evidence["native_methods"][0].update(bounds_source="pe_exception_directory", unwind_info_rva=0x1090)
        with self.assertRaisesRegex(ValueError, "exception_directory_missing"):
            check_native(binary, evidence)
        struct.pack_into("<I", binary, 0x98 + 108, 4)
        struct.pack_into("<II", binary, 0x98 + 136, 0x1080, 13)
        with self.assertRaisesRegex(ValueError, "invalid_exception_directory"):
            check_native(binary, evidence)
        struct.pack_into("<II", binary, 0x98 + 136, 0x1080, 24)
        struct.pack_into("<III", binary, 0x280, 0x1010, 0x1014, 0x1090)
        struct.pack_into("<III", binary, 0x28C, 0x1010, 0x1014, 0x1090)
        with self.assertRaisesRegex(ValueError, "native_unwind_entry_not_unique"):
            check_native(binary, evidence)

    def test_previous_research_record_identity_cannot_be_replaced(self):
        evidence = json.loads((ROOT / "research/deskrawl-frostwyrm-lifecycle.json").read_text(encoding="utf-8"))
        evidence["previous_record"]["sha256"] = "0" * 64
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "manifest.json").write_text(json.dumps({"build_id": "25690430"}), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "previous_record_identity"):
                validate(evidence, root / "missing-game", root)



if __name__ == "__main__":
    unittest.main()

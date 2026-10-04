"""Fictional registration/metadata linkage regressions; no game code executes."""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import struct
import unittest

from contracts import digest
from scripts.validate_deskrawl_frostwyrm import (
    check_metadata_slots, check_native, check_native_code_registration, pe_layout,
)
from services.knowledge.app import Knowledge
from services.knowledge.domain import validate_pack
from test_native_module import module_fixture

ROOT = Path(__file__).resolve().parents[1]


def registration_fixture():
    binary, evidence, data, metadata, locations = module_fixture()
    binary.extend(bytes(0x400))
    struct.pack_into("<8sIIII", binary, 0x188, b".text\0\0\0", 0x600, 0x1000, 0x600, 0x200)
    strings_offset, strings_size, strings_count = struct.unpack_from("<III", data, 8 + 2 * 12)
    names = bytes(data[strings_offset:strings_offset + strings_size]) + b"Other.dll\0"
    struct.pack_into("<III", data, 8 + 2 * 12, len(data), len(names), strings_count + 1)
    data.extend(names)
    images = bytes(data[locations["images"]:locations["images"] + 36]) + bytes(36)
    images_offset = len(data)
    struct.pack_into("<III", data, 8 + 20 * 12, images_offset, len(images), 2)
    data.extend(images)
    struct.pack_into("<IiHI", data, images_offset + 36, names.index(b"Other.dll"), 1, 2, 254)
    struct.pack_into("<III", data, 8 + 21 * 12, len(data), 2, 2)
    data.extend(bytes(2))
    metadata["image"]["image_count"] = 2
    base = evidence["native_image_base"]
    binary[0x4C0:0x4CA] = b"Other.dll\0"
    struct.pack_into("<QqQ", binary, 0x4E0, base + 0x12C0, 1, base + 0x10C0)
    # Metadata order is Assembly-CSharp, Other; the native array reverses it.
    struct.pack_into("<2Q", binary, 0x390, base + 0x12E0, base + 0x1040)
    struct.pack_into("<qQ", binary, 0x300 + 120, 2, base + 0x1190)
    rva = 0x12A1
    binary[0x4A0:0x4B0] = b"\x90\x48\x8d\x0d" + struct.pack("<i", 0x1100 - rva - 7) + bytes([0x90] * 7) + b"\xc3"
    struct.pack_into("<I", binary, 0x104, 4)
    struct.pack_into("<II", binary, 0x120, 0x13C0, 12)
    struct.pack_into("<III", binary, 0x5C0, 0x12A0, 0x12B0, 0x13E0)
    evidence["native_methods"].append({
        "name": "registration-reference", "rva": 0x12A0, "offset": 0x4A0, "length": 16,
        "sha256": hashlib.sha256(binary[0x4A0:0x4B0]).hexdigest(),
        "bounds_source": "pe_exception_directory", "unwind_info_rva": 0x13E0,
    })
    evidence["native_code_registration"] = {
        "source_ref": "game://GameAssembly.dll", "pointer_size": 8, "layout_size": 136,
        "registration_rva": 0x1100, "sha256": hashlib.sha256(binary[0x300:0x388]).hexdigest(),
        "code_gen_modules_count": 2, "code_gen_module_pointers_rva": 0x1190, "selected_module_index": 1,
        "address_reference": {"source_method": "registration-reference", "instruction_rva": rva, "kind": "lea_rcx_rip"},
    }
    return binary, evidence, data, metadata


def registration_check(binary, evidence):
    base, sections = pe_layout(binary)
    return check_native_code_registration(binary, sections, base, evidence)


def pin_registration(binary, evidence):
    evidence["native_code_registration"]["sha256"] = hashlib.sha256(binary[0x300:0x388]).hexdigest()


def pin_reference(binary, evidence):
    evidence["native_methods"][-1]["sha256"] = hashlib.sha256(binary[0x4A0:0x4B0]).hexdigest()


class NativeRegistrationTests(unittest.TestCase):
    def test_registered_module_order_is_independent_of_metadata_order(self):
        binary, evidence, data, metadata = registration_fixture()
        self.assertNotEqual(metadata["image"]["image_index"], evidence["native_code_registration"]["selected_module_index"])
        self.assertEqual({"metadata_image_count_checks": 1, "metadata_image_checks": 1, "metadata_type_checks": 2,
                          "metadata_method_checks": 4, "metadata_vtable_target_checks": 2},
                         check_metadata_slots(data, metadata))
        self.assertEqual(1, registration_check(binary, evidence))
        self.assertEqual(3, check_native(binary, evidence))

    def test_registration_requires_the_recorded_profile_and_module_identity(self):
        binary, evidence, _, _ = registration_fixture()
        for key, value in (("source_ref", "game://Other.dll"), ("pointer_size", 4),
                           ("layout_size", 128), ("layout_size", True), ("registration_rva", True),
                           ("registration_rva", 0x15A0)):
            altered = copy.deepcopy(evidence)
            altered["native_code_registration"][key] = value
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                registration_check(binary, altered)
        for section in ("native_module_methods", "metadata_method_slots"):
            altered = copy.deepcopy(evidence)
            del altered[section]
            with self.subTest(section=section), self.assertRaises(ValueError):
                registration_check(binary, altered)
        altered = copy.deepcopy(evidence)
        del altered["metadata_method_slots"]["image"]["image_count"]
        with self.assertRaisesRegex(ValueError, "native_registration_module_identity_required"):
            registration_check(binary, altered)

    def test_registration_hash_counts_and_array_pointer_are_verified(self):
        binary, evidence, _, _ = registration_fixture()
        changed = bytearray(binary)
        changed[0x300] ^= 1
        with self.assertRaisesRegex(ValueError, "native_registration_hash"):
            registration_check(changed, evidence)
        for count in (0, -1, 1000):
            changed, claimed = bytearray(binary), copy.deepcopy(evidence)
            struct.pack_into("<q", changed, 0x378, count)
            claimed["native_code_registration"]["code_gen_modules_count"] = count
            claimed["metadata_method_slots"]["image"]["image_count"] = count
            pin_registration(changed, claimed)
            with self.subTest(count=count), self.assertRaises(ValueError):
                registration_check(changed, claimed)
        for key, value, error in (("code_gen_modules_count", True, "native_registration_module_count"),
                                  ("code_gen_modules_count", 3, "native_registration_module_count"),
                                  ("code_gen_module_pointers_rva", 0x1198, "native_registration_table_pointer")):
            altered = copy.deepcopy(evidence)
            altered["native_code_registration"][key] = value
            with self.subTest(key=key, value=value), self.assertRaisesRegex(ValueError, error):
                registration_check(binary, altered)
        changed, claimed = bytearray(binary), copy.deepcopy(evidence)
        struct.pack_into("<Q", changed, 0x380, 0)
        pin_registration(changed, claimed)
        with self.assertRaisesRegex(ValueError, "native_registration_table_pointer"):
            registration_check(changed, claimed)

    def test_selected_entry_and_full_array_bounds_cannot_be_substituted(self):
        binary, evidence, _, _ = registration_fixture()
        for index in (True, 0, -1, 2, 1.0):
            altered = copy.deepcopy(evidence)
            altered["native_code_registration"]["selected_module_index"] = index
            with self.subTest(index=index), self.assertRaises(ValueError):
                registration_check(binary, altered)
        changed = bytearray(binary)
        struct.pack_into("<Q", changed, 0x398, evidence["native_image_base"] + 0x1010)
        with self.assertRaisesRegex(ValueError, "native_registration_module_target"):
            registration_check(changed, evidence)
        changed, claimed = bytearray(binary), copy.deepcopy(evidence)
        struct.pack_into("<Q", changed, 0x380, evidence["native_image_base"] + 0x15F8)
        claimed["native_code_registration"]["code_gen_module_pointers_rva"] = 0x15F8
        pin_registration(changed, claimed)
        with self.assertRaisesRegex(ValueError, "unmapped_native_range"):
            registration_check(changed, claimed)

    def test_address_reference_is_bounded_hashed_and_targets_the_registration(self):
        binary, evidence, _, _ = registration_fixture()
        for offset, value, error in ((0x4A2, 0x89, "native_registration_reference_opcode"),
                                      (0x4A4, 0, "native_registration_reference_target")):
            changed, claimed = bytearray(binary), copy.deepcopy(evidence)
            changed[offset] = value
            pin_reference(changed, claimed)
            with self.subTest(offset=offset), self.assertRaisesRegex(ValueError, error):
                check_native(changed, claimed)
        changed = bytearray(binary)
        changed[0x4A2] ^= 1
        with self.assertRaisesRegex(ValueError, "native_method_hash"):
            check_native(changed, evidence)
        for key, value, error in (("source_method", "missing", "native_registration_reference_method_missing"),
                                  ("source_method", "FixtureEffect.apply", "native_registration_reference_bounds_required"),
                                  ("kind", "call", "unsupported_native_registration_reference"),
                                  ("instruction_rva", 0x129F, "native_registration_reference_outside_method"),
                                  ("instruction_rva", 0x12AA, "native_registration_reference_outside_method")):
            altered = copy.deepcopy(evidence)
            altered["native_code_registration"]["address_reference"][key] = value
            with self.subTest(key=key, value=value), self.assertRaisesRegex(ValueError, error):
                check_native(binary, altered)
        altered = copy.deepcopy(evidence)
        altered["native_methods"][-1]["unwind_info_rva"] += 1
        with self.assertRaisesRegex(ValueError, "native_unwind_bounds"):
            check_native(binary, altered)

    def test_metadata_image_count_is_read_from_the_original_table(self):
        binary, evidence, data, metadata = registration_fixture()
        for value in (True, 1, 3):
            altered = copy.deepcopy(metadata)
            altered["image"]["image_count"] = value
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "metadata_image_count"):
                check_metadata_slots(data, altered)
        altered = copy.deepcopy(evidence)
        altered["metadata_method_slots"]["image"]["image_count"] = 3
        with self.assertRaisesRegex(ValueError, "native_registration_metadata_image_count"):
            registration_check(binary, altered)

    def test_published_research_version_pins_history_without_execution(self):
        path = ROOT / "knowledge-packs/deskrawl-sorcerer-leveling-0.6.0-research.json"
        pack = json.loads(path.read_text(encoding="utf-8"))
        validate_pack(pack)
        self.assertEqual("research_only", pack["execution_policy"])
        self.assertEqual([], pack["rules"])
        loaded = Knowledge(ROOT / "knowledge-packs").handle(
            "GET", "/v1/packs/deskrawl-sorcerer-leveling/0.6.0-research", {})
        self.assertEqual(digest(pack), loaded["pack_hash"])
        record = json.loads((ROOT / "research/deskrawl-frostwyrm-code-registration.json").read_text(encoding="utf-8"))
        self.assertEqual("not_performed", record["online_validation"])
        self.assertEqual("research_only", record["candidate_mechanism"]["execution_status"])
        prior = ROOT / record["previous_record"]["source_ref"].removeprefix("repo://")
        self.assertEqual(hashlib.sha256(prior.read_bytes()).hexdigest(), record["previous_record"]["sha256"])
        self.assertEqual("6928b8f21945d15bdf5fc76624f06d868f1dc591b04c62624fb89fa843dd9607",
                         hashlib.sha256((ROOT / "knowledge-packs/deskrawl-sorcerer-leveling-0.5.0-research.json").read_bytes()).hexdigest())
        self.assertEqual(3, record["metadata_method_slots"]["image"]["image_index"])
        self.assertEqual(6, record["native_code_registration"]["selected_module_index"])


if __name__ == "__main__":
    unittest.main()

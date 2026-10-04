"""Verify reviewed Frostwyrm source identity and links; never execute game code."""
from __future__ import annotations

import argparse
import hashlib
import json
import mmap
import os
import re
import struct
from pathlib import Path

if __package__:
    from .deskrawl_paths import REPO_ROOT, repo_path, resolve_source, safe_error
else:
    from deskrawl_paths import REPO_ROOT, repo_path, resolve_source, safe_error


def check(condition, label):
    if not condition:
        raise ValueError(label)


def expect(actual, expected, label):
    # Distinguish a boolean, integer and float; Python equality alone does not.
    options = {"sort_keys": True, "allow_nan": False, "separators": (",", ":")}
    check(json.dumps(actual, **options) == json.dumps(expected, **options), label)


def sha256(path):
    result = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(chunk)
    return result.hexdigest()


def read_objects(path, wanted):
    records = {}
    with path.open(encoding="utf-8") as stream:
        for line in stream:
            record = json.loads(line)
            key = record["object_id"]
            if key in wanted:
                check(key not in records, "duplicate_selected_object:" + key)
                records[key] = record
    check(set(records) == wanted, "selected_objects_missing")
    return records


def check_graph(evidence, records):
    for spec in evidence["objects"]:
        key = spec["object_id"]
        record = records[key]
        expect(record["class_name"], spec["class_name"], "object_class:" + key)
        expect(record["name"], spec["name"], "object_identity:" + key)
        expect(record["expected_byte_size"], spec["byte_size"], "object_size:" + key)
        expect(record["consumed_bytes"], spec["byte_size"], "object_consumption:" + key)
        for flag in ("full_byte_count", "builtin_header_matches", "strict_parser_success"):
            check(record.get("validation", {}).get(flag) is True, "object_validation:" + key)
        for field, value in spec["fields"].items():
            expect(record["data"][field], value, "object_field:" + key + ":" + field)
    for spec in evidence["links"]:
        matches = [r for r in records[spec["source_id"]]["references"] if r["field"] == spec["field"]]
        check(len(matches) == 1, "reference_not_unique:" + spec["field"])
        reference = matches[0]
        expect(reference["raw"], spec["raw"], "reference_raw:" + spec["field"])
        expect(reference["target_id"], spec["target_id"], "reference_target:" + spec["field"])
        check(reference.get("resolved") is True and reference.get("target_parsed") is True
              and reference.get("target_parse_failed") is False, "reference_unverified:" + spec["field"])
        check(spec["target_id"] in records, "reference_target_missing")
    for spec in evidence["managed_effects"]:
        registry = records[spec["object_id"]]["data"]["references"]
        expect(registry["version"], spec["registry_version"], "managed_registry_version")
        matches = [r for r in registry["RefIds"] if r["rid"] == spec["rid"]]
        check(len(matches) == 1, "managed_effect_not_unique")
        effect = matches[0]
        expect(effect["type"], spec["type"], "managed_effect_type")
        for field, value in spec["fields"].items():
            expect(effect["data"][field], value, "managed_effect_field:" + field)


def pe_layout(binary):
    check(len(binary) >= 64 and binary[:2] == b"MZ", "invalid_pe")
    pe = struct.unpack_from("<I", binary, 0x3C)[0]
    check(pe + 24 <= len(binary) and binary[pe:pe + 4] == b"PE\0\0", "invalid_pe")
    machine, count = struct.unpack_from("<HH", binary, pe + 4)
    optional_size = struct.unpack_from("<H", binary, pe + 20)[0]
    table = pe + 24 + optional_size
    check(machine == 0x8664 and optional_size >= 32 and count > 0
          and table + count * 40 <= len(binary), "invalid_x64_pe")
    check(struct.unpack_from("<H", binary, pe + 24)[0] == 0x20B, "invalid_x64_pe")
    image_base = struct.unpack_from("<Q", binary, pe + 48)[0]
    sections = [struct.unpack_from("<8sIIII", binary, table + i * 40) for i in range(count)]
    return image_base, sections


def pe_offset(binary_size, sections, rva, length):
    check(type(rva) is int and type(length) is int and rva >= 0 and length > 0, "invalid_native_range")
    matches = [s for s in sections if s[2] <= rva and rva + length <= s[2] + min(s[1], s[3])]
    check(len(matches) == 1, "unmapped_native_range")
    section = matches[0]
    offset = rva - section[2] + section[4]
    check(offset >= 0 and offset + length <= binary_size, "truncated_native_range")
    return offset


def unwind_bounds(binary, sections, rva):
    """Read the x64 RUNTIME_FUNCTION entry; endpoints are image-relative."""
    pe = struct.unpack_from("<I", binary, 0x3C)[0]
    optional_size = struct.unpack_from("<H", binary, pe + 20)[0]
    check(optional_size >= 144 and struct.unpack_from("<I", binary, pe + 24 + 108)[0] >= 4,
          "exception_directory_missing")
    table_rva, table_size = struct.unpack_from("<II", binary, pe + 24 + 112 + 3 * 8)
    check(table_size > 0 and table_size % 12 == 0, "invalid_exception_directory")
    offset = pe_offset(len(binary), sections, table_rva, table_size)
    matches = [
        entry for entry in struct.iter_unpack("<III", binary[offset:offset + table_size])
        if entry[0] <= rva < entry[1]
    ]
    check(len(matches) == 1, "native_unwind_entry_not_unique")
    return matches[0]


def check_native_links(binary, sections, methods, links):
    seen = set()
    for link in links:
        check(link["source_method"] in methods and link["target_method"] in methods, "native_link_method_missing")
        source, target = methods[link["source_method"]], methods[link["target_method"]]
        rva = link["instruction_rva"]
        check(type(rva) is int and source["rva"] <= rva and rva + 5 <= source["rva"] + source["length"],
              "native_link_outside_method")
        check((source["name"], rva) not in seen, "duplicate_native_link")
        seen.add((source["name"], rva))
        check(link["kind"] in ("call", "tail_jump"), "unsupported_native_link")
        offset = pe_offset(len(binary), sections, rva, 5)
        opcode = 0xE8 if link["kind"] == "call" else 0xE9
        check(binary[offset] == opcode, "native_link_opcode")
        destination = rva + 5 + struct.unpack_from("<i", binary, offset + 1)[0]
        expect(destination, target["rva"], "native_link_target")
    return len(seen)


def check_native_module_methods(binary, sections, image_base, evidence):
    """Selected x64 module prefix/token pointers; no registration or dispatch claim."""
    spec = evidence["native_module_methods"]
    expect(spec["source_ref"], "game://GameAssembly.dll", "native_module_source_required")
    expect(spec["pointer_size"], 8, "unsupported_native_module_layout")
    slots = evidence.get("metadata_method_slots", {})
    check("image" in slots, "native_module_metadata_image_required")
    expect(spec["module_name"], slots["image"]["name"], "native_module_image")
    offset = pe_offset(len(binary), sections, spec["module_rva"], 24)
    name_pointer, count, table_pointer = struct.unpack_from("<QqQ", binary, offset)
    expect(name_pointer, image_base + spec["module_name_rva"], "native_module_name_pointer")
    expect(count, spec["method_pointer_count"], "native_module_method_count")
    check(count > 0, "native_module_method_count")
    expect(table_pointer, image_base + spec["method_pointers_rva"], "native_module_table_pointer")
    name = spec["module_name"].encode("utf-8") + b"\0"
    name_offset = pe_offset(len(binary), sections, spec["module_name_rva"], len(name))
    check(binary[name_offset:name_offset + len(name)] == name, "native_module_name")
    table_offset = pe_offset(len(binary), sections, spec["method_pointers_rva"], count * 8)
    concrete = {method["method_index"]: (type_["name"] + "." + method["name"], method["token"])
                for type_ in slots["types"] for method in type_["methods"]
                if method["vtable_method_definition"]}
    native = {method["name"]: method for method in evidence["native_methods"]}
    check(isinstance(spec["methods"], list) and bool(spec["methods"]), "native_module_methods_missing")
    seen = set()
    for method in spec["methods"]:
        index = method["method_index"]
        check(type(index) is int and index in concrete, "native_module_method_not_concrete")
        check(index not in seen, "duplicate_native_module_method")
        seen.add(index)
        name, token = concrete[index]
        expect(method["native_method"], name, "native_module_method_name")
        expect(method["token"], token, "native_module_method_token")
        check(type(token) is int and token >> 24 == 6 and token & 0xFFFFFF,
              "native_module_method_token")
        pointer_index = (token & 0xFFFFFF) - 1
        expect(method["pointer_index"], pointer_index, "native_module_pointer_index")
        check(pointer_index < count, "native_module_pointer_outside_table")
        check(name in native, "native_module_target_missing")
        pointer = struct.unpack_from("<Q", binary, table_offset + pointer_index * 8)[0]
        expect(pointer, image_base + native[name]["rva"], "native_module_method_target")
    check(seen == set(concrete), "native_module_bindings_incomplete")
    return len(seen)



def check_native_code_registration(binary, sections, image_base, evidence):
    """Selected v39 x64 registration tail and address reference; no execution claim."""
    spec = evidence["native_code_registration"]
    expect(spec["source_ref"], "game://GameAssembly.dll", "native_registration_source_required")
    expect(spec["pointer_size"], 8, "unsupported_native_registration_layout")
    expect(spec["layout_size"], 136, "unsupported_native_registration_layout")
    slots = evidence.get("metadata_method_slots", {})
    expect(slots.get("metadata_version"), 39, "unsupported_native_registration_layout")
    image = slots.get("image", {})
    check("image_count" in image and "native_module_methods" in evidence,
          "native_registration_module_identity_required")
    offset = pe_offset(len(binary), sections, spec["registration_rva"], 136)
    check(hashlib.sha256(binary[offset:offset + 136]).hexdigest() == spec["sha256"],
          "native_registration_hash")
    count, table_pointer = struct.unpack_from("<qQ", binary, offset + 120)
    expect(count, spec["code_gen_modules_count"], "native_registration_module_count")
    expect(count, image["image_count"], "native_registration_metadata_image_count")
    check(count > 0, "native_registration_module_count")
    expect(table_pointer, image_base + spec["code_gen_module_pointers_rva"],
           "native_registration_table_pointer")
    table = pe_offset(len(binary), sections, spec["code_gen_module_pointers_rva"], count * 8)
    # The selected module's array index is independent of its metadata image index.
    index = spec["selected_module_index"]
    check(type(index) is int and 0 <= index < count, "native_registration_module_outside_table")
    pointer = struct.unpack_from("<Q", binary, table + index * 8)[0]
    expect(pointer, image_base + evidence["native_module_methods"]["module_rva"],
           "native_registration_module_target")
    reference = spec["address_reference"]
    expect(reference["kind"], "lea_rcx_rip", "unsupported_native_registration_reference")
    methods = {method["name"]: method for method in evidence["native_methods"]}
    check(reference["source_method"] in methods, "native_registration_reference_method_missing")
    method = methods[reference["source_method"]]
    expect(method.get("bounds_source"), "pe_exception_directory", "native_registration_reference_bounds_required")
    rva = reference["instruction_rva"]
    check(type(rva) is int and method["rva"] <= rva and rva + 7 <= method["rva"] + method["length"],
          "native_registration_reference_outside_method")
    instruction = pe_offset(len(binary), sections, rva, 7)
    check(binary[instruction:instruction + 3] == b"\x48\x8d\x0d", "native_registration_reference_opcode")
    target = rva + 7 + struct.unpack_from("<i", binary, instruction + 3)[0]
    expect(target, spec["registration_rva"], "native_registration_reference_target")
    return 1


def check_native(binary, evidence):
    image_base, sections = pe_layout(binary)
    expect(image_base, evidence["native_image_base"], "native_image_base")
    methods = {m["name"]: m for m in evidence["native_methods"]}
    check(len(methods) == len(evidence["native_methods"]) and bool(methods), "duplicate_or_missing_native_method")
    for name, spec in methods.items():
        offset = pe_offset(len(binary), sections, spec["rva"], spec["length"])
        expect(offset, spec["offset"], "native_pe_mapping:" + name)
        check(hashlib.sha256(binary[offset:offset + spec["length"]]).hexdigest() == spec["sha256"],
              "native_method_hash:" + name)
        if "bounds_source" in spec:
            expect(spec["bounds_source"], "pe_exception_directory", "unsupported_native_bounds")
            expect(unwind_bounds(binary, sections, spec["rva"]),
                   (spec["rva"], spec["rva"] + spec["length"], spec["unwind_info_rva"]),
                   "native_unwind_bounds:" + name)
    check_native_links(binary, sections, methods, evidence.get("native_links", []))
    if "native_module_methods" in evidence:
        check_native_module_methods(binary, sections, image_base, evidence)
    if "native_code_registration" in evidence:
        check_native_code_registration(binary, sections, image_base, evidence)
    for review in evidence["native_review"]:
        spec = methods[review["method"]]
        check(all(type(rva) is int and spec["rva"] <= rva < spec["rva"] + spec["length"]
                  for rva in review["rvas"]), "review_address_outside_method")
    return len(methods)


def check_metadata_slots(data, spec):
    """Selected v39 method slots; not a general metadata or runtime-dispatch reader."""
    check(len(data) >= 380, "truncated_metadata_header")
    expect(struct.unpack_from("<II", data), (0xFAB11BAF, 39), "unsupported_metadata_layout")
    expect(spec["metadata_version"], 39, "unsupported_metadata_layout")
    sections = [struct.unpack_from("<III", data, 8 + index * 12) for index in range(31)]
    selected_sections = (2, 5, 10, 14, 17, 18, 19) + ((20, 21) if "image" in spec else ())
    for index in selected_sections:
        offset, size, count = sections[index]
        check(380 <= offset <= offset + size <= len(data), "metadata_section_outside_file")
        check(count > 0 and size > 0, "metadata_section_empty")
    ranges = sorted((sections[index][0], sections[index][0] + sections[index][1])
                    for index in selected_sections)
    check(all(left[1] <= right[0] for left, right in zip(ranges, ranges[1:])),
          "metadata_sections_overlap")
    strings, methods, vtables, types = (sections[index] for index in (2, 5, 17, 19))
    # This recorded build has 16-bit type/generic indices and 32-bit parameter indices.
    check(255 < types[2] <= 65535 and 255 < sections[14][2] <= 65535
          and sections[10][2] > 65535 and sections[18][1] == sections[18][2] * 6,
          "unsupported_metadata_index_widths")
    for section, stride in ((methods, 30), (types, 76), (vtables, 4),
                            (sections[10], 10), (sections[14], 16)):
        check(section[1] == section[2] * stride, "metadata_table_stride")

    def name(index):
        check(0 <= index < strings[1], "metadata_string_outside_section")
        start = strings[0] + index
        end = data.find(b"\0", start, strings[0] + strings[1])
        check(end >= start, "metadata_string_unterminated")
        return data[start:end].decode("utf-8")

    image_checks = {}
    if "image" in spec:
        image = spec["image"]
        images = sections[20]
        check(images[1] == images[2] * 36, "metadata_image_stride")
        if "image_count" in image:
            expect(images[2], image["image_count"], "metadata_image_count")
            image_checks["metadata_image_count_checks"] = 1
        index = image["image_index"]
        check(type(index) is int and 0 <= index < images[2], "metadata_image_outside_table")
        name_index, assembly_index, first_type, type_count = struct.unpack_from(
            "<IiHI", data, images[0] + index * 36)
        expect(name(name_index), image["name"], "metadata_image_name")
        check(0 <= assembly_index < sections[21][2] and first_type + type_count <= types[2],
              "metadata_image_members_outside_table")
        for key, actual in (("assembly_index", assembly_index), ("type_start", first_type),
                            ("type_count", type_count)):
            expect(actual, image[key], "metadata_image_" + key)
        check(all(first_type <= type_["type_index"] < first_type + type_count for type_ in spec["types"]),
              "metadata_type_outside_image")
        image_checks["metadata_image_checks"] = 1

    type_ids, method_ids, target_count = set(), set(), 0
    check(isinstance(spec["types"], list) and bool(spec["types"]), "metadata_types_missing")
    for expected in spec["types"]:
        index = expected["type_index"]
        check(type(index) is int and 0 <= index < types[2], "metadata_type_outside_table")
        check(index not in type_ids, "duplicate_metadata_type")
        type_ids.add(index)
        position = types[0] + index * 76
        name_index, namespace_index = struct.unpack_from("<II", data, position)
        expect(name(name_index), expected["name"], "metadata_type_name")
        expect(name(namespace_index), expected["namespace"], "metadata_type_namespace")
        first_method = struct.unpack_from("<I", data, position + 24)[0]
        first_slot = struct.unpack_from("<I", data, position + 44)[0]
        counts = struct.unpack_from("<8H", data, position + 52)
        method_count, slot_count = counts[0], counts[5]
        check(first_method + method_count <= methods[2] and first_slot + slot_count <= vtables[2],
              "metadata_type_members_outside_table")
        for key, actual in (("method_start", first_method), ("method_count", method_count),
                            ("vtable_start", first_slot), ("vtable_count", slot_count)):
            expect(actual, expected[key], "metadata_type_" + key)
        check(isinstance(expected["methods"], list) and bool(expected["methods"]), "metadata_methods_missing")
        for method in expected["methods"]:
            method_index = method["method_index"]
            check(type(method_index) is int and first_method <= method_index < first_method + method_count,
                  "metadata_method_outside_declaring_type")
            check(method_index not in method_ids, "duplicate_metadata_method")
            method_ids.add(method_index)
            base = methods[0] + method_index * 30
            expect(name(struct.unpack_from("<I", data, base)[0]), method["name"], "metadata_method_name")
            declaring_type = struct.unpack_from("<H", data, base + 4)[0]
            expect(declaring_type, index, "metadata_method_owner")
            expect(declaring_type, method["declaring_type_index"], "metadata_method_owner")
            token, flags, iflags, slot, parameters = struct.unpack_from("<I4H", data, base + 18)
            for key, actual in (("token", token), ("flags", flags), ("implementation_flags", iflags),
                                ("slot", slot), ("parameter_count", parameters)):
                expect(actual, method[key], "metadata_method_" + key)
            check(flags & 0x40 and slot < slot_count, "metadata_method_not_virtual")
            expect(method["vtable_method_definition"], not bool(flags & 0x400), "metadata_vtable_policy_required")
            if method["vtable_method_definition"]:
                encoded = struct.unpack_from("<I", data, vtables[0] + (first_slot + slot) * 4)[0]
                check(encoded >> 29 == 3, "metadata_vtable_not_method_definition")
                expect((encoded & 0x1FFFFFFF) >> 1, method_index, "metadata_vtable_target")
                target_count += 1
    return {**image_checks, "metadata_type_checks": len(type_ids), "metadata_method_checks": len(method_ids),
            "metadata_vtable_target_checks": target_count}


def validate(evidence, game, source_root):
    expect(evidence["schema_version"], 1, "incompatible_evidence_schema")
    expect(evidence["status"], "reviewed_static_native_only", "not_static_review")
    expect(evidence["online_validation"], "not_performed", "online_status_requires_separate_review")
    expect(evidence["candidate_mechanism"]["execution_status"], "research_only", "candidate_not_quarantined")
    expect(evidence["context"]["game_id"], "deskrawl", "incompatible_game")
    expect(evidence["context"]["mode"], "online", "incompatible_mode")
    expect(evidence["context"]["game_build"], evidence["build_id"], "evidence_build_mismatch")
    expect(evidence["class_id"], "sorcerer", "incompatible_class")
    expect(evidence["scenario"], "leveling", "incompatible_scenario")
    manifest = json.loads((source_root / "manifest.json").read_text(encoding="utf-8"))
    expect(manifest["build_id"], evidence["build_id"], "extraction_build_mismatch")
    if "previous_record" in evidence:
        previous = evidence["previous_record"]
        check(previous["source_ref"].startswith("repo://"), "logical_previous_record_required")
        path = resolve_source(previous["source_ref"])
        check(sha256(path) == previous["sha256"], "previous_record_identity")
        prior = json.loads(path.read_text(encoding="utf-8"))
        expect(prior["context"], evidence["context"], "previous_record_scope_mismatch")
    refs = {s["path"] for s in evidence["sources"]}
    check(len(refs) == len(evidence["sources"]), "duplicate_source_identity")
    required = {
        "game://GameAssembly.dll", "game://Deskrawl_Data/resources.assets",
        "game://Deskrawl_Data/sharedassets0.assets",
        "game://Deskrawl_Data/il2cpp_data/Metadata/global-metadata.dat",
        "repo://data/extracted/deskrawl/" + evidence["build_id"] + "/objects.jsonl",
        "repo://.tools/cpp2il/deskrawl-" + evidence["build_id"] + "-addresses/Assembly-CSharp.dll",
    } | {s["source_ref"] for s in evidence["field_layouts"] + evidence["enums"]}
    check(required.issubset(refs), "source_identity_missing")
    for source in evidence["sources"]:
        label = source["path"]
        check(label.startswith(("game://", "repo://")), "logical_source_required")
        path = (source_root / "objects.jsonl" if label ==
                "repo://data/extracted/deskrawl/" + evidence["build_id"] + "/objects.jsonl"
                else resolve_source(label, game=game))
        check(sha256(path) == source["sha256"], "source_hash:" + label)
        if label.startswith("game://"):
            matches = [s for s in manifest["source_files"] if s["path"] == label]
            check(len(matches) == 1, "extraction_source_not_unique")
            expect(matches[0]["sha256"], source["sha256"], "extraction_source_identity:" + label)
    wanted = {o["object_id"] for o in evidence["objects"]}
    check(len(wanted) == len(evidence["objects"]) and bool(wanted), "duplicate_or_missing_object_spec")
    check_graph(evidence, read_objects(source_root / "objects.jsonl", wanted))
    for spec in evidence["field_layouts"]:
        check(spec["source_ref"] in refs, "field_source_identity_missing")
        text = resolve_source(spec["source_ref"], game=game).read_text(encoding="utf-8")
        pattern = (r"(?:public|private)\s+([^;\n]+?)\s+" + re.escape(spec["field"])
                   + r";\s*//Field offset:\s*(0x[\dA-Fa-f]+)")
        matches = list(re.finditer(pattern, text))
        check(len(matches) == 1, "field_layout_not_unique:" + spec["field"])
        expect(matches[0][1], spec["field_type"], "field_type:" + spec["field"])
        expect(int(matches[0][2], 16), spec["offset"], "field_offset:" + spec["field"])
    for spec in evidence["enums"]:
        check(spec["source_ref"] in refs, "enum_source_identity_missing")
        text = resolve_source(spec["source_ref"], game=game).read_text(encoding="utf-8")
        matches = re.findall(r"\b" + re.escape(spec["name"]) + r"\s*=\s*(-?\d+)\s*,", text)
        check(len(matches) == 1, "enum_value_not_unique")
        expect(int(matches[0]), spec["value"], "enum_value:" + spec["name"])
    binary_path = resolve_source("game://GameAssembly.dll", game=game)
    with binary_path.open("rb") as stream, mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ) as binary:
        native_count = check_native(binary, evidence)
    metadata_checks = {}
    if "metadata_method_slots" in evidence:
        slots = evidence["metadata_method_slots"]
        check(slots["source_ref"] in refs, "metadata_source_identity_missing")
        metadata_path = resolve_source(slots["source_ref"], game=game)
        with metadata_path.open("rb") as stream, mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ) as data:
            metadata_checks = check_metadata_slots(data, slots)
    if "native_module_methods" in evidence:
        metadata_checks["native_module_method_checks"] = len(evidence["native_module_methods"]["methods"])
    if "native_code_registration" in evidence:
        metadata_checks.update(native_code_registration_checks=1, native_registered_module_checks=1,
                               native_registration_address_reference_checks=1)
    return {
        **metadata_checks,
        "build_id": evidence["build_id"], "source_hash_checks": len(refs),
        "strict_object_checks": len(wanted), "resolved_link_checks": len(evidence["links"]),
        "managed_effect_checks": len(evidence["managed_effects"]), "field_layout_checks": len(evidence["field_layouts"]),
        "enum_checks": len(evidence["enums"]), "native_method_hash_and_pe_mapping_checks": native_count,
        "direct_native_link_checks": len(evidence.get("native_links", [])),
        "pe_exception_bound_checks": sum("bounds_source" in method for method in evidence["native_methods"]),
        "previous_record_checks": int("previous_record" in evidence),
        "status": "pass_static_source_and_evidence_identity", "online_validated": False, "m1_accepted": False,
        "limits": "Checks reviewed identities, declarations and links. Does not perform a new semantic review or online experiment."
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--game", type=Path, default=os.environ.get("DESKRAWL_GAME_DIR"))
    parser.add_argument("--source-root", type=Path, default=REPO_ROOT / "data/extracted/deskrawl/25690430")
    parser.add_argument("--evidence", type=Path, default=REPO_ROOT / "research/deskrawl-frostwyrm.json")
    args = parser.parse_args()
    if args.game is None:
        parser.error("Provide --game or DESKRAWL_GAME_DIR.")
    try:
        evidence = json.loads(repo_path(args.evidence).read_text(encoding="utf-8"))
        result = validate(evidence, args.game, repo_path(args.source_root))
    except (OSError, ValueError, KeyError, TypeError, struct.error) as error:
        print(json.dumps({"status": "fail", "error": safe_error(error)}, ensure_ascii=False))
        return 1
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

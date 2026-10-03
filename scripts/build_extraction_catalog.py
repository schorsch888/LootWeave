#!/usr/bin/env python3
"""Build a human-readable catalog from successfully exported Deskrawl objects.

This is a deterministic projection of static extraction output. It does not read
save data, infer equipped state, or assign item scores.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any
from deskrawl_paths import REPO_ROOT, repo_path, source_label


BUILD_ID = "25690430"
OBJECT_CLASSES = (
    "ItemData",
    "HeroData",
    "AbilityData",
    "TalentData",
    "RuneData",
    "RuneSetData",
    "GemData",
)

# Exact Unity field -> enum type correspondences from enums.json.
ENUM_FIELDS = {
    "Type": "ItemType",
    "Rarity": "ItemRarity",
    "UsableClasses": "HeroClass",
}

# Only search the localization tables appropriate to each definition class.
LOCALIZATION_TABLES = {
    "ItemData": ("Equipments", "Items"),
    "HeroData": ("UI",),
    "AbilityData": ("Abilities",),
    "TalentData": ("Talents",),
    "RuneData": ("Equipments", "Items"),
    "RuneSetData": ("Equipments", "Items"),
    "GemData": ("Equipments", "Items"),
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8-sig") as stream:
        return json.load(stream)


def load_localization(path: Path) -> dict[str, dict[str, str]]:
    """Return exact Key -> Simplified Chinese text maps for requested tables."""
    tables: dict[str, dict[str, str]] = {}
    for table_name in sorted({name for names in LOCALIZATION_TABLES.values() for name in names}):
        table_path = path / f"{table_name}.json"
        document = read_json(table_path)
        headers = document.get("headers", [])
        rows = document.get("rows", [])
        key_index = headers.index("Key") if "Key" in headers else 0
        chinese_index = headers.index("Chinese (Simplified)") if "Chinese (Simplified)" in headers else None
        if chinese_index is None:
            raise ValueError(f"No Simplified Chinese column in {table_path}")

        entries: dict[str, str] = {}
        for row in rows:
            if not isinstance(row, list) or max(key_index, chinese_index) >= len(row):
                continue
            key, text = row[key_index], row[chinese_index]
            if isinstance(key, str) and key and isinstance(text, str) and text:
                entries[key] = text
        tables[table_name] = entries
    return tables


def enum_value(enum_document: dict[str, Any], enum_name: str, raw: Any) -> dict[str, Any]:
    enum = enum_document.get("enums", {}).get(enum_name)
    result = {"raw": raw, "enum": enum_name, "name": None}
    if enum is None or not isinstance(raw, int):
        result["enum"] = enum_name if enum is not None else None
        return result

    members = enum.get("members", {})
    if not enum.get("flags", False):
        result["name"] = next((name for name, value in members.items() if value == raw), None)
        return result

    result["is_flags"] = True
    aliases = [name for name, value in members.items() if value == raw]
    result["named_aliases"] = aliases
    if raw == 0:
        result["names"] = aliases[:1] or ["None"]
        result["unknown_bits"] = 0
        return result

    # Decode only distinct positive single-bit members. Composite aliases such
    # as All are retained separately and never consumed as ordinary flags.
    remaining = raw
    names: list[str] = []
    if raw >= 0:
        for name, value in members.items():
            if value > 0 and value & (value - 1) == 0 and remaining & value:
                names.append(name)
                remaining &= ~value
    result["names"] = names
    result["unknown_bits"] = remaining
    return result


def exact_localized_value(
    class_name: str,
    data: dict[str, Any],
    record_name: Any,
    localization: dict[str, dict[str, str]],
    *,
    description: bool = False,
) -> tuple[str | None, dict[str, Any]]:
    tables = LOCALIZATION_TABLES.get(class_name, ())
    explicit_fields = ("AbilityName", "HeroName")
    name_keys: list[str] = []
    if isinstance(record_name, str) and record_name:
        name_keys.append(record_name)
    for field in explicit_fields:
        value = data.get(field)
        if isinstance(value, str) and value and value not in name_keys:
            name_keys.append(value)
    value = data.get("m_Name")
    if isinstance(value, str) and value and value not in name_keys:
        name_keys.append(value)

    matches: list[dict[str, str]] = []
    description_keys: list[str] = []
    if description:
        for field in ("DescriptionKey", "AbilityDescriptionKey"):
            value = data.get(field)
            if isinstance(value, str) and value and value not in description_keys:
                description_keys.append(value)
        description_keys.extend(f"{base_key}.Desc" for base_key in name_keys)
    for table_name in tables:
        entries = localization.get(table_name, {})
        if description:
            # Deskrawl's localization tables store descriptions under exact
            # `<definition key>.Desc` keys; explicit description-key fields are
            # also accepted only when they exactly exist in the selected table.
            key_candidates = description_keys
        else:
            key_candidates = name_keys
        for key in key_candidates:
            text = entries.get(key)
            if text:
                matches.append({"table": table_name, "key": key, "text": text})

    unique_values = {match["text"] for match in matches}
    if len(unique_values) == 1:
        selected = matches[0]
        return selected["text"], {
            "status": "matched_exact_key",
            "table": selected["table"],
            "key": selected["key"],
        }
    if len(unique_values) > 1:
        return None, {"status": "ambiguous_exact_matches", "keys": matches}
    return None, {"status": "not_found", "keys_tried": name_keys}


def successful_record(record: dict[str, Any]) -> bool:
    if not isinstance(record.get("data"), dict) or record.get("error"):
        return False
    validation = record.get("validation")
    if not isinstance(validation, dict):
        return False
    return validation.get("full_byte_count") is True and validation.get("builtin_header_matches") is True


def build_catalog(source_root: Path, output_path: Path, batch_status: str) -> dict[str, Any]:
    objects_path = source_root / "objects.jsonl"
    enums_path = source_root / "enums.json"
    manifest_path = source_root / "manifest.json"
    errors_path = source_root / "parse-errors.json"
    localization_path = source_root / "localization"
    enums = read_json(enums_path)
    manifest = read_json(manifest_path)
    parse_errors = read_json(errors_path)
    if str(enums.get("build_id")) != BUILD_ID:
        raise ValueError(f"Expected build {BUILD_ID}, found {enums.get('build_id')!r}")
    if str(manifest.get("build_id")) != BUILD_ID:
        raise ValueError(f"Expected manifest build {BUILD_ID}, found {manifest.get('build_id')!r}")
    if not isinstance(parse_errors, list):
        raise ValueError(f"Expected parse-errors array in {errors_path}")
    localization = load_localization(localization_path)

    input_paths = [objects_path, enums_path, manifest_path, errors_path]
    input_paths.extend(localization_path / f"{name}.json" for name in sorted(localization))
    input_manifest = [
        {
            "path": source_label(path),
            "bytes": path.stat().st_size,
            "sha256": sha256(path),
        }
        for path in input_paths
    ]

    entries: list[dict[str, Any]] = []
    class_counts: Counter[str] = Counter()
    skipped = 0
    with objects_path.open("r", encoding="utf-8-sig") as stream:
        for line_number, line in enumerate(stream, start=1):
            if not line.strip():
                continue
            record = json.loads(line)
            class_name = record.get("class_name")
            if class_name not in OBJECT_CLASSES:
                continue
            if not successful_record(record):
                skipped += 1
                continue

            data = record["data"]
            record_name = record.get("name")
            name = record_name if isinstance(record_name, str) else data.get("m_Name")
            if not isinstance(name, str):
                name = None

            localized_name, name_match = exact_localized_value(
                class_name, data, record_name, localization
            )
            localized_description, description_match = exact_localized_value(
                class_name, data, record_name, localization, description=True
            )

            decoded_enums: dict[str, Any] = {}
            if class_name == "ItemData":
                for field, enum_name in ENUM_FIELDS.items():
                    if field in data:
                        decoded_enums[field] = enum_value(enums, enum_name, data[field])

            flag_decodings: dict[str, Any] = {}
            if class_name == "ItemData" and "UsableClasses" in data:
                flag_decodings["UsableClasses"] = enum_value(
                    enums, "HeroClass", data["UsableClasses"]
                )

            entry = {
                "object_id": record.get("object_id"),
                "class": class_name,
                "name": name,
                "localized_name_zh_cn": localized_name,
                "localized_name_match": name_match,
                "description_zh_cn": localized_description,
                "description_match": description_match,
                "enums": decoded_enums,
                "flags": flag_decodings,
                "source": {
                    "file": record.get("source_file"),
                    "path_id": record.get("path_id"),
                    "line": line_number,
                },
            }
            entries.append(entry)
            class_counts[class_name] += 1

    entries.sort(key=lambda entry: (entry["class"], entry["name"] or "", entry["object_id"] or ""))
    manifest_coverage = manifest.get("class_coverage", {})
    failed_counts = Counter(
        error.get("class_name") for error in parse_errors
        if isinstance(error, dict) and error.get("class_name") in OBJECT_CLASSES
    )
    successful_counts = {class_name: class_counts.get(class_name, 0) for class_name in OBJECT_CLASSES}
    expected_or_discovered = {
        class_name: {
            "selected_expected": manifest_coverage.get(class_name, {}).get("selected"),
            "discovered_successful": successful_counts[class_name],
        }
        for class_name in OBJECT_CLASSES
    }
    failed_by_class = {class_name: failed_counts.get(class_name, 0) for class_name in OBJECT_CLASSES}
    incomplete_classes = [class_name for class_name, count in failed_by_class.items() if count > 0]
    ability_failures = failed_by_class.get("AbilityData", 0)
    ability_successes = successful_counts.get("AbilityData", 0)

    return {
        "schema_version": 1,
        "game": "Deskrawl",
        "build_id": BUILD_ID,
        "research_date": "2026-10-03",
        "batch_status": batch_status,
        "catalog_scope": list(OBJECT_CLASSES),
        "input_sha256": input_manifest,
        "counts": {
            "objects": len(entries),
            "by_class": {class_name: class_counts.get(class_name, 0) for class_name in OBJECT_CLASSES},
            "skipped_failed_exports_in_scope": skipped,
            "skipped_failed_exports_in_scope_semantics": "Failed exports recorded only in parse-errors.json are not in objects.jsonl and are not counted as skipped lines here.",
            "localization": {
                "matched_names": sum(entry["localized_name_zh_cn"] is not None for entry in entries),
                "matched_descriptions": sum(entry["description_zh_cn"] is not None for entry in entries),
                "unmatched_names": sum(entry["localized_name_zh_cn"] is None for entry in entries),
                "unmatched_descriptions": sum(entry["description_zh_cn"] is None for entry in entries),
            },
        },
        "coverage": {
            "expected_or_discovered_by_class": expected_or_discovered,
            "successful_by_class": successful_counts,
            "failed_definitions_by_class": failed_by_class,
            "failed_counts_match_manifest": {
                class_name: failed_by_class[class_name] == manifest_coverage.get(class_name, {}).get("failed")
                for class_name in OBJECT_CLASSES
            },
            "complete_for_requested_classes": not incomplete_classes,
            "incomplete_classes": incomplete_classes,
            "core_skill_catalog_complete": ability_failures == 0 and ability_successes > 0,
            "core_skill_completeness_note": (
                f"AbilityData has {ability_successes} successful definitions and {ability_failures} failed definitions; "
                + ("core skills are incomplete." if ability_failures or ability_successes == 0 else "no AbilityData parse failures were recorded.")
            ),
        },
        "notes": [
            "Only successfully exported object records with passing full_byte_count and builtin_header_matches validation are included.",
            "Localization uses exact keys from class-specific tables; absent and ambiguous matches are null. No fuzzy matching or guessed display text is used.",
            "Only ItemData.Type, ItemData.Rarity, and ItemData.UsableClasses are decoded from enums.json; UsableClasses is a HeroClass bitmask and unknown bits are retained. Other fields are left untyped.",
            "Class coverage combines manifest.json expected selections and parse-errors.json failures; objects.jsonl contains successful exports only.",
            "This is static definition data; it does not imply anything is currently equipped, active, unlocked, or owned by the player.",
            "No scores, keep/sell recommendations, or active-state inferences are calculated.",
        ],
        "objects": entries,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source-root", type=Path,
        default=Path("data/extracted/deskrawl") / BUILD_ID,
        help="Build extraction directory (default: data/extracted/deskrawl/25690430)",
    )
    parser.add_argument(
        "--output", type=Path,
        default=Path("data/extracted/deskrawl") / BUILD_ID / "catalog.json",
        help="Output catalog path",
    )
    parser.add_argument(
        "--batch-status", choices=("intermediate", "final"), default="intermediate",
        help="Mark whether the source extraction batch is final",
    )
    args = parser.parse_args()
    args.source_root = repo_path(args.source_root)
    args.output = repo_path(args.output)
    catalog = build_catalog(args.source_root, args.output, args.batch_status)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8", newline="\n") as stream:
        json.dump(catalog, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    print(json.dumps(catalog["counts"], ensure_ascii=False, sort_keys=True))
    print(f"Wrote {source_label(args.output)}")


if __name__ == "__main__":
    main()

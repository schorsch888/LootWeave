"""Confirmed facts are separate from observations and inferred results."""
from __future__ import annotations

from contracts import context, identifier, number, object_value, require, strings, timestamp, timestamp_milliseconds


def evidence_refs(value: dict, known: set[str]) -> None:
    refs = strings(value.get("evidence_ids"), "fact_evidence_required")
    require(bool(refs) and all(x in known for x in refs), "fact_evidence_required")


def source(value: dict, known: set[str]) -> None:
    object_value(value)
    identifier(value.get("id"))
    effects = strings(value.get("effects"), "source_effects_required")
    require(len(effects) == len(set(effects)), "duplicate_source_effect")
    require(value.get("actor", "hero") in ("hero", "companion"), "invalid_effect_owner")
    evidence_refs(value, known)


def item(value: dict, known: set[str]) -> None:
    object_value(value)
    require(value.get("record_kind") == "item_instance", "actual_item_instance_required")
    identifier(value.get("instance_id"))
    identifier(value.get("slot"))
    evidence_refs(value, known)
    require("required_level" in value and (value["required_level"] is None or
            (type(value["required_level"]) is int and value["required_level"] >= 1)),
            "invalid_required_level")
    effects = strings(value.get("effects"), "item_effects_required")
    require(len(effects) == len(set(effects)), "duplicate_source_effect")
    strings(value.get("unrevealed_properties"))
    strings(value.get("unknowns"))
    require(isinstance(value.get("affixes"), list) and
            isinstance(value.get("embedded_items"), list), "item_fields_required")
    for key in ("upgrade_state", "socket_state"):
        object_value(value.get(key))
        require(type(value[key].get("known")) is bool, "item_state_required")
    if value.get("set_id") is not None:
        identifier(value["set_id"])
    if value.get("class_id") is not None:
        identifier(value["class_id"])
    for entry in value["embedded_items"]:
        source(entry, known)
    affix_ids = set()
    for affix in value["affixes"]:
        object_value(affix)
        affix_id = identifier(affix.get("id"))
        require(affix_id not in affix_ids, "duplicate_affix_id")
        affix_ids.add(affix_id)
        require(number(affix.get("value")) and isinstance(affix.get("unit"), str)
                and 0 < len(affix["unit"]) <= 40, "actual_roll_and_unit_required")
        evidence_refs(affix, known)


def snapshot(value: dict) -> dict:
    value = object_value(value)
    context(value.get("context"))
    identifier(value.get("class_id"))
    require(type(value.get("character_level")) is int and value["character_level"] > 0,
            "character_level_required")
    timestamp(value.get("captured_at"))
    require(isinstance(value.get("evidence"), list) and value["evidence"], "evidence_required")
    known: set[str] = set()
    for record in value["evidence"]:
        object_value(record)
        evidence_id = identifier(record.get("id"))
        require(evidence_id not in known, "duplicate_evidence_id")
        known.add(evidence_id)
        require(record.get("verification") == "confirmed", "unconfirmed_fact")
        require(record.get("kind") in ("manual_confirmation", "synthetic", "ocr_confirmation"),
                "unsupported_input_method")
        require(isinstance(record.get("source_ref"), str) and 0 < len(record["source_ref"]) <= 500,
                "evidence_source_required")
        timestamp(record.get("captured_at"))
    for key in ("skills", "talents", "paragon", "runes", "companions", "temporary_effects",
                "observed_panel"):
        require(isinstance(value.get(key), list), "build_fields_required")
    strings(value.get("unknowns"))
    object_value(value.get("account_unlocks"))
    object_value(value.get("conditions"))
    require(all(x in ("active", "inactive", "unknown") for x in value["conditions"].values()),
            "invalid_condition_state")
    require(value.get("inventory_coverage") in ("complete", "partial", "unknown"),
            "inventory_coverage_required")
    evidence_refs(value, known)
    equipped = object_value(value.get("equipped_items"))
    for slot, entry in equipped.items():
        identifier(slot)
        item(entry, known)
        require(entry["slot"] == slot, "equipment_slot_mismatch")
    item(value.get("candidate_item"), known)
    instances = [x["instance_id"] for x in equipped.values()]
    instances.append(value["candidate_item"]["instance_id"])
    if "inventory_items" in value:
        require(isinstance(value["inventory_items"], list), "inventory_items_required")
        for entry in value["inventory_items"]:
            item(entry, known)
            instances.append(entry["instance_id"])
    require(len(instances) == len(set(instances)), "duplicate_item_instance")
    for key in ("skills", "talents", "paragon", "runes", "companions", "temporary_effects"):
        ids = set()
        for entry in value[key]:
            source(entry, known)
            require(entry["id"] not in ids, "duplicate_build_source")
            ids.add(entry["id"])
            if key in ("skills", "talents", "paragon"):
                require(type(entry.get("rank")) is int and entry["rank"] >= 0, "source_rank_required")
                require(entry["rank"] != 0 or not entry["effects"], "unallocated_source_has_effects")
            if key == "runes" and entry.get("set_id") is not None:
                identifier(entry["set_id"])
    for entry in value["observed_panel"]:
        object_value(entry)
        identifier(entry.get("stat"))
        require(number(entry.get("value")) and isinstance(entry.get("unit"), str),
                "panel_provenance_required")
        strings(entry.get("source_ids"), "panel_provenance_required")
        evidence_refs(entry, known)
    return value


def build_fingerprint(facts: dict) -> str:
    """Trial identity excludes capture provenance and an unequipped candidate.

    Actual equipment, ranks, conditions and temporary sources stay in the identity.
    Level range and observed XP bonuses are separate Planning scope fields.
    """
    from contracts import digest
    def intrinsic(value):
        if isinstance(value, dict):
            return {key: intrinsic(item) for key, item in value.items()
                    if key not in ("evidence", "evidence_ids", "captured_at", "source_ref")}
        if isinstance(value, list):
            return [intrinsic(item) for item in value]
        return value
    keys = ("context", "class_id", "skills", "talents", "paragon", "account_unlocks",
            "equipped_items", "runes", "companions", "temporary_effects", "conditions")
    return digest(intrinsic({key: facts[key] for key in keys}))


def observation_capture_time(observation: dict):
    capture = observation.get("capture_context")
    if capture is None:
        return None
    require(isinstance(capture, dict), "invalid_capture_context")
    if "captured_at_ms" not in capture:
        return None
    return timestamp_milliseconds(capture["captured_at_ms"])


def observation_time_status(observation: dict, facts: dict) -> str:
    captured = observation_capture_time(observation)
    if captured is None:
        return "not_recorded"
    ref = "observation://" + observation["observation_id"]
    linked = [entry for entry in facts["evidence"] if entry["source_ref"] == ref]
    return ("verified" if linked and all(timestamp(entry["captured_at"]) == captured for entry in linked)
            else "conflict")


def ensure_observation_binding(observation: dict, facts: dict) -> None:
    capture = observation.get("capture_context")
    if capture is not None:
        require(isinstance(capture, dict)
                and capture.get("game_id") == facts["context"]["game_id"],
                "observation_game_conflict")
    require(observation_time_status(observation, facts) != "conflict", "observation_time_conflict")

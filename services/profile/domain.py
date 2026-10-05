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
    if "level" in value:
        require(type(value["level"]) is int and 1 <= value["level"] < 2**53,
                "source_level_required")
    if "companion_id" in value:
        identifier(value["companion_id"])
    evidence_refs(value, known)


def item(value: dict, known: set[str], *, record_kind="item_instance") -> None:
    object_value(value)
    require(value.get("record_kind") == record_kind,
            "actual_item_instance_required" if record_kind == "item_instance" else "projected_item_required")
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


def resource_costs(value) -> None:
    require(value is None or isinstance(value, list), "preparation_costs_required")
    if value is None:
        return
    ids = set()
    for entry in value:
        object_value(entry)
        resource_id = identifier(entry.get("resource_id"))
        require(resource_id not in ids, "duplicate_resource_cost")
        ids.add(resource_id)
        require(type(entry.get("amount")) is int and 0 <= entry["amount"] < 2**53,
                "resource_amount_required")


def preparation_facts(value: dict, known: set[str]) -> None:
    """Player-confirmed quotes are facts about a plan, never executed changes."""
    if "owned_resources" in value:
        resources = object_value(value["owned_resources"])
        require(resources.get("coverage") in ("complete", "partial", "unknown"),
                "resource_coverage_required")
        require(isinstance(resources.get("balances"), list), "resource_balances_required")
        ids = set()
        for entry in resources["balances"]:
            object_value(entry)
            resource_id = identifier(entry.get("resource_id"))
            require(resource_id not in ids, "duplicate_resource_balance")
            ids.add(resource_id)
            require(type(entry.get("amount")) is int and 0 <= entry["amount"] < 2**53,
                    "resource_amount_required")
            evidence_refs(entry, known)
    if "preparation_options" not in value:
        return
    require(isinstance(value["preparation_options"], list), "preparation_options_required")
    ids = set()
    for option in value["preparation_options"]:
        object_value(option)
        option_id = identifier(option.get("id"))
        require(option_id not in ids, "duplicate_preparation_option")
        ids.add(option_id)
        require(option.get("kind") in ("equipment", "skill", "talent", "paragon", "rune", "companion", "temporary_effect"),
                "preparation_kind_required")
        context(option.get("context"))
        identifier(option.get("class_id"))
        target_id = identifier(option.get("target_id"))
        evidence_refs(option, known)
        strings(option.get("unknowns"), "preparation_unknowns_required")
        require("costs" in option, "preparation_costs_required")
        resource_costs(option["costs"])
        requirements = object_value(option.get("requirements"))
        require(requirements.get("unlock_state") in ("unlocked", "locked", "unknown"),
                "preparation_unlock_required")
        for key in ("required_level", "max_rank"):
            require(key in requirements and (requirements[key] is None or
                    (type(requirements[key]) is int and 1 <= requirements[key] < 2**53)),
                    "preparation_requirements_required")
        if "companion_id" in requirements:
            identifier(requirements["companion_id"])
        require("input" in option, "preparation_input_required")
        if option["kind"] == "equipment":
            item(option["input"], known)
            item(option.get("result"), known, record_kind="projected_item")
            before, after = option["input"], option["result"]
            require(before["instance_id"] == target_id == after["instance_id"]
                    and before["slot"] == after["slot"]
                    and before.get("class_id") == after.get("class_id"),
                    "preparation_item_identity_conflict")
            for key, count in (("upgrade_state", "level"), ("socket_state", "count")):
                state = after[key]
                require(not state["known"] or (type(state.get(count)) is int and
                        0 <= state[count] < 2**53), "projected_item_state_required")
            require(not after["socket_state"]["known"] or
                    len(after["embedded_items"]) <= after["socket_state"]["count"],
                    "projected_socket_capacity_exceeded")
        else:
            before, after = option["input"], option.get("result")
            ranked = option["kind"] in ("skill", "talent", "paragon")
            code = "preparation_skill_required" if option["kind"] == "skill" else "preparation_source_required"
            require("result" in option and (ranked or before is not None or after is not None), code)
            for entry in (before, after):
                if entry is None:
                    continue
                source(entry, known)
                require(entry["id"] == target_id, code)
                if ranked:
                    require(type(entry.get("rank")) is int and entry["rank"] >= 0, code)
                if option["kind"] == "rune" and entry.get("set_id") is not None:
                    identifier(entry["set_id"])
                if option["kind"] == "companion":
                    require(entry.get("actor", "companion") == "companion", "preparation_source_owner_conflict")
                if option["kind"] == "companion" and entry.get("companion_id") is not None:
                    require(entry["companion_id"] == target_id, "preparation_source_owner_conflict")
            if ranked:
                require(after is not None and type(after.get("rank")) is int
                        and 0 <= after["rank"] < 2**53, code)
                require(after["rank"] != 0 or not after["effects"], "unallocated_source_has_effects")
            default_actor = "companion" if option["kind"] == "companion" else "hero"
            require(before is None or after is None or
                    before.get("actor", default_actor) == after.get("actor", default_actor),
                    "preparation_skill_owner_conflict" if option["kind"] == "skill" else
                    "preparation_source_owner_conflict")
            owner_default = target_id if option["kind"] == "companion" else None
            require(before is None or after is None or
                    before.get("companion_id", owner_default) == after.get("companion_id", owner_default),
                    "preparation_source_owner_conflict")


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
        require(record.get("kind") in ("manual_confirmation", "synthetic", "ocr_confirmation", "external_api_confirmation", "live_api_confirmation"),
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
            if key == "companions" and entry.get("companion_id") is not None:
                require(entry["companion_id"] == entry["id"], "source_companion_identity_conflict")
            if key == "runes" and entry.get("set_id") is not None:
                identifier(entry["set_id"])
    for entry in value["observed_panel"]:
        object_value(entry)
        identifier(entry.get("stat"))
        require(number(entry.get("value")) and isinstance(entry.get("unit"), str),
                "panel_provenance_required")
        strings(entry.get("source_ids"), "panel_provenance_required")
        evidence_refs(entry, known)
    preparation_facts(value, known)
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
    if observation.get("method") in ("external_api", "live_api"):
        require(observation.get("declared_context") == facts["context"], "observation_context_conflict")
        require(observation.get("declared_class") == facts["class_id"], "observation_class_conflict")
        require(timestamp(facts["captured_at"]) == observation_capture_time(observation),
                "observation_time_conflict")

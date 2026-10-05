"""Local live observations, with independent schemas and explicit confirmation."""
from __future__ import annotations

from collections import Counter
from copy import deepcopy
from datetime import datetime, timezone

from contracts import CONTEXT_KEYS, canonical, context, digest, identifier, require, timestamp
from services.profile.live_reports import reports
from services.profile.live_schema import ALLOCATIONS, BUILD_SOURCE, INTEGER, ITEM, KEY, NUMBER, OVERVIEW, TEXT, array, decode, enum, mapping, obj, string

ADAPTER = "lootweave-live-v1"
SCHEMA = "lootweave-live/1"
SLOTS = {"weapon", "head", "shoulders", "body", "hands", "waist", "legs", "feet", "ring1", "ring2", "neck"}
CONTAINERS = ("equipment", "inventory", "storage", "carriage")
MAX_SAMPLE_BYTES = 4 * 1024 * 1024


def stable_id(prefix, value):
    return prefix + "-" + digest(value)[:32]


def content_hash(observation):
    names = ("declared_context", "declared_class", "character", "items", "coverage", "equipped_slots",
             "abilities", "talents", "paragon", "runes", "companions", "temporary_effects", "observed_panel", "overview", "warnings", "telemetry")
    return digest({name: observation[name] for name in names if name in observation})


def capture_time(value, now=None):
    sampled = timestamp(value)
    now = now or datetime.now(timezone.utc)
    require(-30 <= (now - sampled).total_seconds() <= 120, "live_source_stale")
    return sampled


def item_record(value, raw, producer, mode):
    blocked = []
    if value["record_kind"] != "equipment" or value["slot"] not in SLOTS | {"ring"}:
        blocked.append("not_equipment")
    if not value["instance_id"]:
        blocked.append("instance_unavailable")
    if value["settlement"] == "pending":
        blocked.append("settlement_pending")
    elif mode == "online" and value["settlement"] != "settled":
        blocked.append("settlement_unverified")
    if "affixes" not in raw:
        blocked.append("affixes_unavailable")
    affixes, seen = [], set()
    for entry in value["affixes"]:
        if not entry["id"] or entry["id"] in seen or entry["value"] is None:
            blocked.append("affix_unverified")
            continue
        seen.add(entry["id"])
        quality = entry["roll"]["quality"]
        require(quality is None or 0 <= quality <= 1, "live_sample_invalid")
        affixes.append({**entry, "id": "live." + entry["id"], "name": entry["name"] or entry["id"],
                        "unit": entry["unit"] or "unverified"})
    require(value["required_level"] is None or value["required_level"] > 0, "live_sample_invalid")
    embedded = sources(value["embedded_items"])
    require(value["sockets"] is None or len(embedded) <= value["sockets"], "live_sample_invalid")
    require(value["sockets_used"] is None or len(embedded) <= value["sockets_used"], "live_sample_invalid")
    require(value["sockets"] is None or value["sockets_used"] is None
            or value["sockets_used"] <= value["sockets"], "live_sample_invalid")
    result = {name: value[name] for name in ("name", "template_id", "slot", "container", "index", "page", "rarity",
              "required_level", "upgrade_level", "sockets", "sockets_used", "item_level", "armor", "weapon", "effect_description")}
    result.update({"id": stable_id("live", [producer, value["instance_id"] or [value["container"], value["page"], value["index"]]]),
                   "affixes": affixes, "blocked": blocked, "embedded_items": embedded,
                   **{name: value[name] for name in ("locked", "ancient", "black_mist")}})
    return result


def sources(rows, require_rank=False):
    require(all(row["id"] and (not require_rank or row["rank"] is not None) for row in rows), "live_sample_invalid")
    require(len({row["id"] for row in rows}) == len(rows), "live_allocation_conflict")
    result = []
    for row in rows:
        require(row["level"] is None or row["level"] > 0, "live_sample_invalid")
        identity = "live." + row["id"]
        result.append({"id": identity, "name": row["name"],
                       **{name: row[name] for name in ("rank", "level") if row[name] is not None},
                       **({"actor": row["actor"]} if row["actor"] else {}),
                       **({"set_id": "live." + row["set_id"]} if row["set_id"] else {}),
                       **({"companion_id": "live." + row["companion_id"]} if row["companion_id"] else {})})
    return result


def normalize_sample(document, now=None):
    require(isinstance(document, dict) and document.get("schema") == SCHEMA, "live_schema_unsupported")
    require(len(canonical(document).encode("utf-8")) <= MAX_SAMPLE_BYTES, "live_sample_too_large")
    producer = identifier(document.get("producer_id"))
    class_id = identifier(document.get("class_id"))
    supplied_context = context(document.get("context"))
    require(len(supplied_context["content_entitlements"]) <= 64, "live_sample_too_large")
    declared = {name: supplied_context[name] for name in CONTEXT_KEYS}
    declared["content_entitlements"] = decode(supplied_context["content_entitlements"], array(KEY, 64))
    sampled = capture_time(document.get("captured_at"), now)
    captured_at = sampled.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    character = decode(document.get("character"), obj(name=TEXT, level=INTEGER, gold=INTEGER))
    require(character["level"] is not None and character["level"] > 0, "live_character_required")
    raw_items = document.get("items")
    require(isinstance(raw_items, list), "live_sample_invalid")
    values = decode(raw_items, array(ITEM, 2000))
    items = [item_record(value, raw, producer, declared["mode"]) for value, raw in zip(values, raw_items)
             if value["ownership"] == "held"]
    require(all(value["container"] in CONTAINERS for value in items), "live_sample_invalid")
    duplicates = {identity for identity, amount in Counter(row["id"] for row in items).items() if amount > 1}
    equipped = [row["slot"] for row in items if row["container"] == "equipment"]
    duplicate_slots = {slot for slot, amount in Counter(equipped).items() if amount > 1}
    for row in items:
        if row["id"] in duplicates or row["container"] == "equipment" and row["slot"] in duplicate_slots:
            row["blocked"].append("duplicate_instance")
    known_slots = decode(document.get("equipped_slots"), array(KEY, 20))
    require(set(known_slots) <= SLOTS, "live_sample_invalid")
    unread = {row["slot"] for row in items if row["container"] == "equipment" and row["blocked"]}
    data = decode(document.get("overview"), OVERVIEW)
    data["panel"]["kind"] = "source_estimate"
    for container in CONTAINERS[1:]:
        data["capacity"].setdefault(container, decode(None, OVERVIEW[1]["capacity"][1]))
    data["carriage"]["pickup_rarities"] = data["carriage"]["pickup_rarities"] or None
    materials = data["materials"]
    require(all(row["id"] for row in materials), "live_sample_invalid")
    require(len({row["id"] for row in materials}) == len(materials), "live_material_conflict")
    for row in materials:
        row["id"] = "live." + row["id"]
        row["importable"] = row["amount"] is not None
    preview_count = sum(len(row["items"]) for row in data["forecast"]["waves"]) + sum(len(row["contents"]) for row in data["chests"])
    require(preview_count <= 2000, "live_sample_too_large")
    allocations = {}
    for name in ("abilities", "talents"):
        source = decode(document.get(name), ALLOCATIONS)
        require(all(row["id"] and row["rank"] is not None for row in source), "live_sample_invalid")
        require(len({row["id"] for row in source}) == len(source), "live_allocation_conflict")
        allocations[name] = [{"id": "live." + row["id"], "rank": row["rank"]} for row in source]
        data[name] = source
    build_sources = {name: sources(decode(document.get(name), array(BUILD_SOURCE, 512)), name == "paragon")
                     for name in ("paragon", "runes", "companions", "temporary_effects")}
    for row in build_sources["companions"]:
        require(row.get("companion_id", row["id"]) == row["id"], "live_sample_invalid")
    observed_panel = decode(document.get("observed_panel"), array(obj(stat=KEY, value=NUMBER, unit=string(40),
                                                                    source_ids=array(KEY, 128)), 256))
    require(all(row["stat"] and row["value"] is not None and row["unit"] for row in observed_panel), "live_sample_invalid")
    coverage = decode(document.get("coverage"), mapping(enum("complete", "partial", "unknown"), 4))
    report_coverage = decode(document.get("report_coverage"), mapping(enum("complete", "partial", "unknown"), 5))
    result = {"schema": SCHEMA, "producer_id": producer, "context": deepcopy(declared), "class_id": class_id,
            "captured_at": captured_at, "character": {**character, "class_id": class_id},
            "items": items, "coverage": {name: "enabled" if coverage.get(name) == "complete" else "partial"
                                         if coverage.get(name) == "partial" else "unavailable" for name in CONTAINERS},
            "equipped_slots": [slot for slot in known_slots if slot not in unread], **allocations, **build_sources,
            "observed_panel": observed_panel, "overview": data,
            "telemetry": reports(document.get("reports"), sampled.timestamp(), producer, report_coverage)}
    result["semantic_hash"] = content_hash({**result, "declared_context": result["context"], "declared_class": class_id,
                                           "warnings": ["game_identity_producer_declared", "source_fields_require_review", "mechanics_unverified",
                                                        "inventory_partial", "build_sources_incomplete"]})
    result["sample_hash"] = digest(result)
    return result


def observation(sample, observation_id, declared_context, class_id, now=None):
    identifier(observation_id)
    context(declared_context)
    require(sample["context"] == declared_context, "live_context_mismatch")
    require(sample["class_id"] == class_id, "live_class_mismatch")
    sampled = capture_time(sample["captured_at"], now)
    delta = sampled - datetime(1970, 1, 1, tzinfo=timezone.utc)
    milliseconds = delta.days * 86400000 + delta.seconds * 1000 + delta.microseconds // 1000
    result = {"observation_id": observation_id, "method": "live_api", "state": "unconfirmed",
              "raw_text": f"LootWeave local API: {len(sample['items'])} held records; source time {sample['captured_at']}.",
              "capture_context": {"game_id": declared_context["game_id"], "captured_at_ms": milliseconds},
              "declared_context": deepcopy(declared_context), "declared_class": class_id,
              "source": {"adapter": ADAPTER, "schema": SCHEMA, "response_hash": sample["sample_hash"],
                         "game_identity": "producer_declared", "captured_at": sample["captured_at"],
                         "producer_id": sample["producer_id"]},
              **{name: deepcopy(sample[name]) for name in ("character", "items", "coverage", "equipped_slots", "abilities", "talents", "paragon", "runes", "companions", "temporary_effects", "observed_panel", "overview", "telemetry")},
              "warnings": ["game_identity_producer_declared", "source_fields_require_review", "mechanics_unverified",
                           "inventory_partial", "build_sources_incomplete"]}
    result["build_sources"] = {name: result[name] for name in ("paragon", "runes", "companions", "temporary_effects")}
    result["source"]["content_hash"] = sample["semantic_hash"]
    return result

def draft(observation, candidate_id, target_slot=None):
    require(observation.get("method") == "live_api"
            and observation.get("source", {}).get("adapter") in (ADAPTER,), "live_observation_required")
    candidate = next((row for row in observation["items"] if row["id"] == candidate_id), None)
    require(candidate is not None and not candidate["blocked"] and candidate["container"] != "equipment",
            "live_candidate_required")
    if candidate["slot"] == "ring":
        require(target_slot in ("ring1", "ring2"), "live_ring_slot_required")
    else:
        require(target_slot in (None, candidate["slot"]), "live_target_slot_conflict")
    evidence_id = stable_id("live-input", observation["observation_id"])
    refs = [evidence_id]

    def convert(row):
        unknowns = ["effects_not_reviewed", "affix_units_unverified", "effect_mechanics_unverified"]
        if any(row[name] is None for name in ("locked", "ancient", "black_mist")):
            unknowns.append("item_flags_not_observed")
        unrevealed = []
        if row["black_mist"]:
            unrevealed.append("black_mist_properties")
        if row["sockets_used"] is None or row["sockets_used"] > len(row["embedded_items"]):
            unrevealed.append("embedded_items_not_observed")
        return {
            "record_kind": "item_instance", "instance_id": row["id"], "name": row["name"],
            "slot": row["slot"], "required_level": row["required_level"], "effects": [],
            "affixes": [{**{key: affix[key] for key in ("id", "name", "value", "unit")}, "evidence_ids": refs}
                        for affix in row["affixes"]],
            "evidence_ids": refs, "unknowns": unknowns, "unrevealed_properties": unrevealed,
            "embedded_items": [{**entry, "effects": [], "evidence_ids": refs} for entry in row["embedded_items"]],
            "upgrade_state": {"known": row["upgrade_level"] is not None, **({"level": row["upgrade_level"]}
                              if row["upgrade_level"] is not None else {})},
            "socket_state": {"known": row["sockets"] is not None, **({"count": row["sockets"]}
                             if row["sockets"] is not None else {})},
            "live_source": {key: row[key] for key in ("template_id", "container", "index", "page", "rarity",
                                                         "locked", "ancient", "black_mist")},
        }

    equipped, inventory = {}, []
    for row in observation["items"]:
        if row["blocked"] or row["id"] == candidate_id:
            continue
        if row["container"] == "equipment":
            equipped[row["slot"]] = convert(row)
        else:
            inventory.append(convert(row))
    chosen = convert(candidate)
    if target_slot:
        chosen["slot"] = target_slot
    captured_at = observation["source"]["captured_at"]
    sources = lambda key: [{**entry, "effects": [], "evidence_ids": refs} for entry in observation[key]]
    unknowns = list(observation["warnings"]) + ["build_not_reviewed"]
    if chosen["slot"] not in observation["equipped_slots"]:
        unknowns.append("current_slot_not_reviewed")
    gold = observation["character"]["gold"]
    resources = [] if gold is None else [{"resource_id": "gold", "amount": gold, "evidence_ids": refs}]
    resources.extend({"resource_id": entry["id"], "amount": entry["amount"], "evidence_ids": refs}
                     for entry in observation.get("overview", {}).get("materials", []) if entry["importable"])
    return {
        "context": deepcopy(observation["declared_context"]), "class_id": observation["declared_class"],
        "character_level": observation["character"]["level"], "captured_at": captured_at,
        "evidence": [{"id": evidence_id, "kind": "live_api_confirmation",
                      "source_ref": "observation://" + observation["observation_id"],
                      "captured_at": captured_at, "verification": "confirmed", "conflicts": []}],
        "evidence_ids": refs, "equipped_items": equipped, "candidate_item": chosen, "inventory_items": inventory,
        "skills": sources("abilities"), "talents": sources("talents"), "paragon": sources("paragon"), "runes": sources("runes"),
        "companions": sources("companions"), "temporary_effects": sources("temporary_effects"),
        "observed_panel": [{**row, "evidence_ids": refs} for row in observation["observed_panel"]], "conditions": {}, "account_unlocks": {},
        "inventory_coverage": "partial", "unknowns": unknowns,
        "owned_resources": {"coverage": "partial", "balances": resources},
    }

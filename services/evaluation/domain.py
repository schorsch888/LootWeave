"""Three-state, source-aware mechanism comparisons; no DPS or universal weights."""
from __future__ import annotations

from copy import deepcopy

from contracts import CONTEXT_KEYS, digest, identifier, object_value, require, strings, timestamp
from services.evaluation.rolls import compare_item_rolls
from services.evaluation.preparation import (
    FUTURE_SOURCE_FIELDS, prepare_full_future, prepare_future,
    validate_full_future_intent, validate_preparation_intent,
)

EVALUATOR_VERSION = "0.1.8"
EVALUATOR_VERSIONS = ("0.1.0", "0.1.1", "0.1.2", "0.1.3", "0.1.4", "0.1.5", "0.1.6", "0.1.7", EVALUATOR_VERSION)


def intent(value: dict, evaluator_version=EVALUATOR_VERSION) -> dict:
    value = object_value(value)
    require(type(value.get("revision")) is int and value["revision"] > 0, "intent_revision_required")
    require(value.get("scenario") == "leveling", "unsupported_scenario")
    strings(value.get("required_capabilities"))
    strings(value.get("allowed_build_changes"))
    require(isinstance(value.get("future_builds"), list), "future_builds_required")
    for build in value["future_builds"]:
        object_value(build)
        if evaluator_version != "0.1.8":
            require(not (FUTURE_SOURCE_FIELDS & build.keys()), "unsupported_future_build_fields")
        require(isinstance(build.get("skills"), list), "future_skills_required")
        require(all(isinstance(x, str) for x in build["skills"]), "future_skills_required")
        states = object_value(build.get("conditions"))
        require(all(x in ("active", "inactive", "unknown") for x in states.values()),
                "invalid_condition_state")
        require(build.get("feasibility") in ("owned", "obtainable", "hypothetical"),
                "future_feasibility_required")
        if evaluator_version in ("0.1.6", "0.1.7", "0.1.8"):
            refs = strings(build.get("equipment_items", []), "future_equipment_required")
            for ref in refs:
                identifier(ref)
            require(len(refs) == len(set(refs)), "duplicate_future_equipment")
    object_value(value.get("budget"))
    if evaluator_version == "0.1.7":
        validate_preparation_intent(value)
    elif evaluator_version == "0.1.8":
        validate_full_future_intent(value)
    return value


def all_sources(facts: dict, evaluator_version=EVALUATOR_VERSION) -> list[dict]:
    result = []
    for slot, item in sorted(facts["equipped_items"].items()):
        result.append({"id": item["instance_id"], "effects": item["effects"], "actor": "hero",
                       "evidence_ids": item["evidence_ids"], "kind": "equipment"})
        for entry in item["embedded_items"]:
            embedded = {**entry, "id": item["instance_id"] + ":" + entry["id"], "kind": "embedded"}
            if evaluator_version != "0.1.0":
                embedded["actor"] = entry.get("actor", "hero")
            result.append(embedded)
    for key in ("skills", "talents", "paragon", "runes", "companions", "temporary_effects"):
        for entry in facts[key]:
            source = {**entry, "id": key + ":" + entry["id"], "kind": key,
                      "actor": entry.get("actor", "companion" if key == "companions" else "hero")}
            if evaluator_version == "0.1.8" and key == "companions":
                source["companion_id"] = entry.get("companion_id", entry["id"])
            result.append(source)
    return result


def condition_state(states: list[str]) -> str:
    if "inactive" in states:
        return "inactive"
    return "unknown" if "unknown" in states else "active"


def resolve(facts: dict, pack: dict, evaluator_version=EVALUATOR_VERSION) -> list[dict]:
    if evaluator_version == "0.1.8":
        return resolve_full_future(facts, pack)
    sources = all_sources(facts, evaluator_version)
    result = []
    for rule in sorted(pack["rules"], key=lambda x: x["id"]):
        # Version 0.1.0 keeps its historical ownership behavior for frozen replay.
        skills = {entry["id"] for entry in facts["skills"] if entry["rank"] > 0
                  and (evaluator_version == "0.1.0" or entry.get("actor", "hero") == rule["actor"])}
        if rule["source_kind"] == "effect":
            matching = [x for x in sources if rule["source_id"] in x["effects"]
                        and x["actor"] == rule["actor"]]
        else:
            items = (list(facts["equipped_items"].values()) if rule["source_kind"] == "equipment_set"
                     else facts["runes"])
            matching = [{"id": x.get("instance_id", x.get("id")),
                         "evidence_ids": x["evidence_ids"]}
                        for x in items if x.get("set_id") == rule["source_id"]
                        and (evaluator_version == "0.1.0" or
                             ("hero" if rule["source_kind"] == "equipment_set" else
                              x.get("actor", "hero")) == rule["actor"])]
        present = len(matching) >= rule.get("min_count", 1)
        required_skills = set(rule.get("requires_skills", []))
        states = [facts["conditions"].get(key, "unknown") for key in rule["conditions"]]
        rank_requirements = rule.get("requires_skill_ranks", {}) if evaluator_version == "0.1.7" else {}
        ranks = {entry["id"]: entry["rank"] for entry in facts["skills"]
                 if entry.get("actor", "hero") == rule["actor"]}
        ranks_met = all(ranks.get(skill_id, 0) >= rank for skill_id, rank in rank_requirements.items())
        if not present or not required_skills.issubset(skills) or not ranks_met:
            state = "inactive"
        else:
            state = condition_state(states)
        # Unique capabilities retain every provenance source without double-counting.
        result.append({"rule_id": rule["id"], "capability": rule["capability"], "state": state,
                       "actor": rule["actor"], "source_ids": sorted(x["id"] for x in matching),
                       "input_evidence_ids": sorted({e for x in matching for e in x["evidence_ids"]}),
                       "evidence_ids": rule["evidence_ids"], "explanation": rule["explanation"]})
    return result


def capability_states(rows: list[dict]) -> dict[tuple[str, str], str]:
    """Any active provider establishes presence; unknown alone cannot establish absence."""
    providers = {}
    for row in rows:
        providers.setdefault((row["actor"], row["capability"]), set()).add(row["state"])
    return {key: "active" if "active" in states else "unknown" if "unknown" in states else "inactive"
            for key, states in providers.items()}


def item_blockers(items: list[dict], pack: dict) -> list[str]:
    blockers = []
    for item in items:
        if item["required_level"] is None:
            blockers.append("required_level_unknown:" + item["instance_id"])
        if item["unrevealed_properties"]:
            blockers.append("unrevealed_properties:" + item["instance_id"])
        blockers.extend("item_unknown:" + x for x in item["unknowns"])
        if not all(item[key]["known"] for key in ("upgrade_state", "socket_state")):
            blockers.append("item_modifications_unknown:" + item["instance_id"])
        for affix in item["affixes"]:
            if pack["known_affixes"].get(affix["id"]) != affix["unit"]:
                blockers.append("unknown_affix_or_unit:" + affix["id"])
    return blockers


def source_blockers(facts: dict, pack: dict, evaluator_version: str) -> list[str]:
    known_effects = {rule["source_id"] for rule in pack["rules"] if rule["source_kind"] == "effect"}
    known_sets = {rule["source_id"] for rule in pack["rules"] if rule["source_kind"] != "effect"}
    blockers = ["unknown_effect:" + effect for entry in all_sources(facts, evaluator_version)
                for effect in entry["effects"] if effect not in known_effects]
    blockers.extend("unknown_set:" + entry["set_id"]
                    for entry in [*facts["equipped_items"].values(), *facts["runes"]]
                    if entry.get("set_id") and entry["set_id"] not in known_sets)
    if evaluator_version == "0.1.8":
        companions = {entry["id"] for entry in facts["companions"]
                      if entry.get("actor", "companion") == "companion"}
        for entry in all_sources(facts, evaluator_version):
            owner = entry.get("companion_id")
            if entry["kind"] == "companions" and owner != entry["id"].removeprefix("companions:"):
                blockers.append("source_owner_conflict:" + entry["id"])
            if entry["actor"] == "companion":
                if not owner:
                    blockers.append("companion_owner_unknown:" + entry["id"])
                elif owner not in companions:
                    blockers.append("companion_owner_not_selected:" + entry["id"])
            elif owner is not None:
                blockers.append("source_owner_conflict:" + entry["id"])
    return blockers


def future_equipment(facts: dict, refs: list[str], *, strict=False) -> tuple[list[dict], list[str]]:
    """Only recorded instances can support a future combination; none activate implicitly."""
    owned = {item["instance_id"]: item for item in
             [*facts["equipped_items"].values(), *facts.get("inventory_items", [])]}
    selected, blockers, slots = [], [], set()
    for ref in refs:
        item = owned.get(ref)
        if item is None:
            blockers.append("future_item_not_owned:" + ref)
            continue
        slot = item["slot"]
        if slot == facts["candidate_item"]["slot"]:
            blockers.append("future_candidate_slot_conflict:" + slot)
        if slot in slots:
            blockers.append("future_equipment_slot_conflict:" + slot)
        slots.add(slot)
        if strict and item["required_level"] is None:
            blockers.append("required_level_unknown:" + ref)
        if item["required_level"] is not None and item["required_level"] > facts["character_level"]:
            blockers.append("future_required_level_not_met:" + ref)
        if item.get("class_id") not in (None, facts["class_id"]):
            blockers.append("future_item_class_incompatible:" + ref)
        selected.append(item)
    return selected, blockers


def evaluate(profile: dict, knowledge: dict, purpose: dict, *, evaluator_version=EVALUATOR_VERSION) -> dict:
    require(evaluator_version in EVALUATOR_VERSIONS, "evaluator_version_unavailable", 409)
    require(profile.get("contract_version") == 1, "incompatible_profile_contract")
    facts, pack = profile["facts"], knowledge["pack"]
    require(profile.get("facts_hash") == digest(facts), "profile_integrity_error", 409)
    require(knowledge.get("pack_hash") == digest(pack), "pack_integrity_error", 409)
    require(pack.get("contract_version") == 1, "incompatible_pack_contract")
    if evaluator_version != "0.1.8":
        require(all(option.get("kind") in ("equipment", "skill")
                    for option in facts.get("preparation_options", [])), "unsupported_preparation_kind")
    purpose = intent(purpose, evaluator_version)
    strict_requirements = evaluator_version in ("0.1.3", "0.1.4", "0.1.5", "0.1.6", "0.1.7", "0.1.8")
    uncertainty_aware = evaluator_version in ("0.1.4", "0.1.5", "0.1.6", "0.1.7", "0.1.8")
    owned_equipment = evaluator_version in ("0.1.6", "0.1.7", "0.1.8")
    preparation_aware = evaluator_version in ("0.1.7", "0.1.8")
    full_future = evaluator_version == "0.1.8"
    pin = {"context": facts["context"], "profile_id": profile["profile_id"],
           "profile_revision": profile["revision"], "facts_hash": profile["facts_hash"],
           "item_instance_id": facts["candidate_item"]["instance_id"],
           "intent_revision": purpose["revision"], "intent_hash": digest(purpose),
           "pack_id": pack["pack_id"], "pack_version": pack["version"],
           "pack_hash": knowledge["pack_hash"], "evaluator_version": evaluator_version}
    blockers = []
    for key in CONTEXT_KEYS:
        if facts["context"][key].lower() in ("unknown", "unconfirmed"):
            blockers.append("unknown_context:" + key)
        if facts["context"][key] != pack["context"][key]:
            blockers.append("incompatible_context:" + key)
    if not set(pack["context"]["content_entitlements"]).issubset(facts["context"]["content_entitlements"]):
        blockers.append("missing_content_entitlement")
    if facts["class_id"] != pack["class_id"]:
        blockers.append("unsupported_class")
    if purpose["scenario"] != pack["scenario"]:
        blockers.append("unsupported_scenario")
    if pack["execution_policy"] != "synthetic_only" or facts["context"]["game_id"] != "lootweave-fixture":
        blockers.append("game_mechanics_not_accepted")
    blockers.extend("input_unknown:" + x for x in facts["unknowns"])
    if facts["inventory_coverage"] != "complete":
        blockers.append("inventory_not_fully_scanned")
    if owned_equipment and "inventory_items" not in facts:
        blockers.append("inventory_not_recorded")
    capture = timestamp(facts["captured_at"])
    if any(timestamp(e["captured_at"]) != capture for e in facts["evidence"]):
        blockers.append("cross_time_snapshot")
    if any(e.get("conflicts") for e in facts["evidence"]) or any(e.get("conflicts") for e in pack["evidence"]):
        blockers.append("conflicting_evidence")
    blockers.extend(item_blockers([*facts["equipped_items"].values(), facts["candidate_item"]], pack))
    known_skills = {skill for rule in pack["rules"] for skill in rule.get("requires_skills", [])}
    if preparation_aware:
        known_skills.update(skill for rule in pack["rules"] for skill in rule.get("requires_skill_ranks", {}))
    if pack["execution_policy"] == "synthetic_only":
        blockers.extend("unknown_skill:" + entry["id"] for entry in facts["skills"]
                        if entry["rank"] > 0 and entry["id"] not in known_skills)
    before_facts = deepcopy(facts)
    after_facts = deepcopy(facts)
    candidate = facts["candidate_item"]
    after_facts["equipped_items"][candidate["slot"]] = candidate
    for configured in (before_facts, after_facts):
        blockers.extend(source_blockers(configured, pack, evaluator_version))
    # Incompatible scopes must never execute a rule, even for an explanation.
    scoped = not any(x.startswith(("incompatible_context:", "unknown_context:")) or
                     x in ("unsupported_class", "missing_content_entitlement", "game_mechanics_not_accepted")
                     for x in blockers)
    if strict_requirements and "unsupported_scenario" in blockers:
        scoped = False
    if owned_equipment and candidate.get("class_id") not in (None, facts["class_id"]):
        blockers.append("candidate_class_incompatible")
        scoped = False
    before = resolve(before_facts, pack, evaluator_version) if scoped else []
    after = resolve(after_facts, pack, evaluator_version) if scoped else []
    for result in before + after:
        if result["state"] == "unknown":
            blockers.append("unknown_condition:" + result["rule_id"])
    # Engines through 0.1.1 aggregate names; later engines preserve the actor.
    actor_aware = evaluator_version in ("0.1.2", "0.1.3", "0.1.4", "0.1.5", "0.1.6", "0.1.7", "0.1.8")
    active_before = {(r["actor"] if actor_aware else None, r["capability"])
                     for r in before if r["state"] == "active"}
    active_after = {(r["actor"] if actor_aware else None, r["capability"])
                    for r in after if r["state"] == "active"}
    candidate_sources = {candidate["instance_id"], *(
        candidate["instance_id"] + ":" + x["id"] for x in candidate["embedded_items"])}
    candidate_rules = [r for r in after if candidate_sources.intersection(r["source_ids"])]
    relevant = [r for r in candidate_rules if r["state"] == "active"]
    future_reasons = []
    future_preparation, prepared_builds = [], {}
    # Every plan shares the actual current-input reliability, never another plan's blockers.
    current_plan_blockers = []
    if full_future:
        current_plan_blockers = [code for code in blockers
            if code.startswith(("unknown_context:", "incompatible_context:", "input_unknown:", "unknown_skill:"))
            or code in ("unsupported_class", "missing_content_entitlement", "game_mechanics_not_accepted",
                        "unsupported_scenario", "candidate_class_incompatible", "cross_time_snapshot", "conflicting_evidence")]
        current_plan_blockers.extend(item_blockers(list(before_facts["equipped_items"].values()), pack))
        current_plan_blockers.extend(source_blockers(before_facts, pack, "0.1.8"))
    if preparation_aware:
        for index, future in enumerate(purpose["future_builds"]):
            refs = future.get("equipment_items", [])
            selected, plan_blockers = future_equipment(facts, refs, strict=True)
            configured = deepcopy(after_facts)
            for item in selected:
                configured["equipped_items"][item["slot"]] = deepcopy(item)
            current_skills = {entry["id"] for entry in facts["skills"] if entry["rank"] > 0}
            if ((set(future["skills"]) != current_skills and "skills" not in purpose["allowed_build_changes"])
                    or (refs and "equipment" not in purpose["allowed_build_changes"])):
                plan_blockers.append("future_build_change_not_permitted")
            prepare = prepare_full_future if full_future else prepare_future
            modified, report = prepare(facts, configured, future, purpose, index, plan_blockers)
            if full_future:
                report["comparison"] = compare_future_plan(
                    before, modified, pack, purpose, scoped, report["blockers"], current_plan_blockers)
                blockers.extend(report["comparison"]["blockers"])
            prepared_builds[index] = (modified, report, selected)
            future_preparation.append(report)
            blockers.extend(report["blockers"])
    if scoped:
        for index, future in enumerate(purpose["future_builds"]):
            if preparation_aware:
                modified, report, selected = prepared_builds[index]
                if report["status"] != "feasible":
                    continue
                blockers.extend(item_blockers(list(modified["equipped_items"].values()), pack))
                blockers.extend(source_blockers(modified, pack, evaluator_version))
            else:
                refs = future.get("equipment_items", []) if owned_equipment else []
                current_skills = {entry["id"] for entry in facts["skills"] if entry["rank"] > 0}
                changes = set()
                if not owned_equipment or set(future["skills"]) != current_skills:
                    changes.add("skills")
                if refs:
                    changes.add("equipment")
                if not changes.issubset(purpose["allowed_build_changes"]):
                    blockers.append("future_build_change_not_permitted")
                    continue
                modified = deepcopy(after_facts)
                if owned_equipment:
                    selected, selection_blockers = future_equipment(facts, refs)
                    blockers.extend(selection_blockers)
                    if selection_blockers:
                        continue
                    for item in selected:
                        modified["equipped_items"][item["slot"]] = deepcopy(item)
                    allocated = {entry["id"]: entry for entry in facts["skills"] if entry["rank"] > 0}
                    modified["skills"] = [deepcopy(allocated[x]) if x in allocated else
                                          {"id": x, "rank": 1, "effects": [], "evidence_ids": facts["evidence_ids"]}
                                          for x in future["skills"]]
                    blockers.extend(item_blockers(selected, pack))
                    blockers.extend(source_blockers(modified, pack, evaluator_version))
                else:
                    modified["skills"] = [{"id": x, "rank": 1, "effects": [], "evidence_ids": facts["evidence_ids"]}
                                          for x in future["skills"]]
            modified["conditions"] = future["conditions"]
            blockers.extend("unknown_future_skill:" + x for x in future["skills"] if x not in known_skills)
            future_rows = report["comparison"]["after"] if full_future else resolve(modified, pack, evaluator_version)
            future_candidate_sources = candidate_sources
            if full_future:
                projected = modified["equipped_items"][candidate["slot"]]
                future_candidate_sources = {projected["instance_id"], *(
                    projected["instance_id"] + ":" + entry["id"] for entry in projected["embedded_items"])}
            for rule in future_rows:
                if future_candidate_sources.intersection(rule["source_ids"]) and rule["state"] == "unknown":
                    blockers.append("unknown_future_condition:" + rule["rule_id"])
                if future_candidate_sources.intersection(rule["source_ids"]) and rule["state"] == "active":
                    reason = {**rule, "future_build_index": index, "feasibility": future["feasibility"]}
                    if owned_equipment:
                        reason["future_equipment"] = [{key: item[key] for key in ("instance_id", "slot", "name")
                                                      if key in item} for item in sorted(selected, key=lambda x: x["instance_id"])]
                        reason["input_evidence_ids"] = sorted(set(reason["input_evidence_ids"]) |
                            {ref for item in selected for ref in item["evidence_ids"]})
                    if preparation_aware:
                        reason["input_evidence_ids"] = sorted(set(reason["input_evidence_ids"]) |
                                                             set(report["input_evidence_ids"]))
                        reason["preparation_status"] = report["status"]
                        if full_future:
                            reason["future_comparison"] = deepcopy(report["comparison"])
                    future_reasons.append(reason)
    equip_blockers = []
    if candidate["required_level"] is not None and candidate["required_level"] > facts["character_level"]:
        equip_blockers.append("required_level_not_met")
    if candidate.get("class_id") not in (None, facts["class_id"]):
        equip_blockers.append("item_class_incompatible")
    lost_mechanisms, gained_mechanisms = sorted(active_before - active_after), sorted(active_after - active_before)
    if uncertainty_aware:
        states_before, states_after = capability_states(before), capability_states(after)
        lost_mechanisms = sorted(key for key in states_before
                                 if states_before[key] == "active" and states_after.get(key, "inactive") == "inactive")
        gained_mechanisms = sorted(key for key in states_after
                                   if states_after[key] == "active" and states_before.get(key, "inactive") == "inactive")
        uncertain_mechanisms = [
            {"actor": actor, "capability": capability,
             "before": states_before.get((actor, capability), "inactive"),
             "after": states_after.get((actor, capability), "inactive")}
            for actor, capability in sorted(states_before.keys() | states_after.keys())
            if "unknown" in (states_before.get((actor, capability), "inactive"),
                             states_after.get((actor, capability), "inactive"))]
    required_capabilities = set(purpose["required_capabilities"])
    if strict_requirements:
        if scoped:
            known_capabilities = {rule["capability"] for rule in pack["rules"]}
            blockers.extend("unknown_required_capability:" + capability
                            for capability in sorted(required_capabilities - known_capabilities))
            required_capabilities &= known_capabilities
        else:
            # An incompatible pack cannot establish which mechanisms this build lacks.
            required_capabilities.clear()
    required = {("hero" if actor_aware else None, capability) for capability in required_capabilities}
    missing_mechanisms = sorted(required - active_after)
    if uncertainty_aware:
        missing_mechanisms = sorted(key for key in required if states_after.get(key, "inactive") == "inactive")
    losses = sorted({capability for _, capability in lost_mechanisms})
    gains = sorted({capability for _, capability in gained_mechanisms})
    missing = [capability for _, capability in missing_mechanisms]
    blockers = sorted(set(blockers))
    verdict = ("needs_confirmation" if blockers else "keep" if relevant else
               "candidate" if future_reasons else "low_current_relevance")
    status = ("blocked" if blockers or equip_blockers else
              "mechanism_loss" if losses or missing else
              "mechanism_change" if gains else "no_known_change")
    reasons = [{"kind": "current_use", **r} for r in relevant] + [
        {"kind": "future_use", **r} for r in future_reasons]
    if not reasons and not blockers:
        reasons.append({"kind": "low_current_relevance", "explanation":
                        "No known current or selected future use; other uses remain possible.",
                        "input_evidence_ids": candidate["evidence_ids"], "evidence_ids": []})
    comparison = {"status": status, "lost_capabilities": losses, "gained_capabilities": gains,
                  "missing_requirements": missing, "equip_blockers": equip_blockers,
                  "before": before, "after": after}
    if strict_requirements:
        comparison["scope_compatible"] = scoped
    if uncertainty_aware:
        comparison["uncertain_mechanisms"] = uncertain_mechanisms
    if actor_aware:
        for key, mechanisms in (("lost_mechanisms", lost_mechanisms),
                                ("gained_mechanisms", gained_mechanisms),
                                ("missing_mechanisms", missing_mechanisms)):
            comparison[key] = [{"actor": actor, "capability": capability} for actor, capability in mechanisms]
    scope_notice = "Synthetic mechanism check; no validated game recommendation or DPS."
    if evaluator_version in ("0.1.5", "0.1.6", "0.1.7", "0.1.8"):
        comparison["item_rolls"] = compare_item_rolls(facts)
        if not scoped:
            scope_notice = "Confirmed item affix comparison only; no validated game recommendation or DPS."
    result = {"contract_version": 1, "pin": pin, "retention": verdict,
            "comparison": comparison,
            "reasons": reasons, "blockers": blockers, "panel_policy": "observations_only",
            "scope_notice": scope_notice,
            "limitations": pack["unknowns"]}
    if preparation_aware:
        result["future_preparation"] = future_preparation
    return result


def resolve_full_future(facts: dict, pack: dict) -> list[dict]:
    """Evaluate each companion's providers and dependencies in its own ownership scope."""
    sources = all_sources(facts, "0.1.8")
    companions = {entry["id"] for entry in facts["companions"]
                  if entry.get("actor", "companion") == "companion"}
    rows = []
    for rule in sorted(pack["rules"], key=lambda entry: entry["id"]):
        if rule["source_kind"] == "effect":
            matching = [entry for entry in sources if rule["source_id"] in entry["effects"]
                        and entry["actor"] == rule["actor"]]
        else:
            equipment = rule["source_kind"] == "equipment_set"
            items = list(facts["equipped_items"].values()) if equipment else facts["runes"]
            matching = [{"id": entry.get("instance_id", entry.get("id")),
                         "evidence_ids": entry["evidence_ids"],
                         "companion_id": entry.get("companion_id")}
                        for entry in items if entry.get("set_id") == rule["source_id"]
                        and ("hero" if equipment else entry.get("actor", "hero")) == rule["actor"]]
        providers = {}
        if rule["actor"] == "hero":
            providers[None] = matching
        else:
            for entry in matching:
                providers.setdefault(entry.get("companion_id"), []).append(entry)
        provider_states = []
        for owner, entries in providers.items():
            if rule["actor"] == "companion" and owner not in companions:
                provider_states.append("unknown")
                continue
            skills = {entry["id"]: entry["rank"] for entry in facts["skills"]
                      if entry.get("actor", "hero") == rule["actor"] and entry["rank"] > 0
                      and (rule["actor"] == "hero" or entry.get("companion_id") == owner)}
            present = len(entries) >= rule.get("min_count", 1)
            skills_met = set(rule.get("requires_skills", [])).issubset(skills)
            ranks_met = all(skills.get(ref, 0) >= rank
                            for ref, rank in rule.get("requires_skill_ranks", {}).items())
            if not present or not skills_met or not ranks_met:
                provider_states.append("inactive")
            else:
                provider_states.append(condition_state([
                    facts["conditions"].get(key, "unknown") for key in rule["conditions"]]))
        state = ("active" if "active" in provider_states else
                 "unknown" if "unknown" in provider_states else "inactive")
        rows.append({"rule_id": rule["id"], "capability": rule["capability"], "state": state,
                     "actor": rule["actor"], "source_ids": sorted(entry["id"] for entry in matching),
                     "input_evidence_ids": sorted({ref for entry in matching for ref in entry["evidence_ids"]}),
                     "evidence_ids": rule["evidence_ids"], "explanation": rule["explanation"]})
    return rows


def compare_future_plan(before: list[dict], configured: dict, pack: dict, purpose: dict,
                        scoped: bool, preparation_blockers: list[str], current_blockers: list[str]) -> dict:
    """A payable plan is compared separately against the actual current build."""
    blockers = [*preparation_blockers, *current_blockers]
    blockers.extend(item_blockers(list(configured["equipped_items"].values()), pack))
    blockers.extend(source_blockers(configured, pack, "0.1.8"))
    known_skills = {ref for rule in pack["rules"] for ref in rule.get("requires_skills", [])}
    known_skills.update(ref for rule in pack["rules"] for ref in rule.get("requires_skill_ranks", {}))
    blockers.extend("unknown_future_skill:" + entry["id"] for entry in configured["skills"]
                    if entry["rank"] > 0 and entry["id"] not in known_skills)
    # Payment uncertainty does not erase a separately confirmed hypothetical outcome.
    # An unconfirmed/stale/partial source projection cannot establish either gain or loss.
    cost_codes = ("preparation_cost_unknown:", "preparation_cost_out_of_range:",
                  "preparation_resource_unknown:", "preparation_resource_insufficient:",
                  "preparation_budget_exceeded:")
    projection_reliable = scoped and all(code.startswith(cost_codes) or
        (code.startswith("preparation_unknown:") and code.endswith(":costs_not_confirmed"))
        for code in blockers)
    after = resolve(configured, pack, "0.1.8") if projection_reliable else []
    blockers.extend("unknown_future_condition:" + entry["rule_id"] for entry in after
                    if entry["state"] == "unknown")
    known_capabilities = {rule["capability"] for rule in pack["rules"]}
    required = set(purpose["required_capabilities"])
    if scoped:
        blockers.extend("unknown_required_capability:" + ref for ref in sorted(required - known_capabilities))
        required &= known_capabilities
    else:
        required.clear()
    states_before, states_after = capability_states(before), capability_states(after)
    lost = sorted(key for key in states_before if states_before[key] == "active"
                  and states_after.get(key, "inactive") == "inactive")
    gained = sorted(key for key in states_after if states_after[key] == "active"
                    and states_before.get(key, "inactive") == "inactive")
    missing = sorted(("hero", ref) for ref in required
                     if states_after.get(("hero", ref), "inactive") == "inactive")
    uncertain = [{"actor": actor, "capability": capability,
                  "before": states_before.get((actor, capability), "inactive"),
                  "after": states_after.get((actor, capability), "inactive")}
                 for actor, capability in sorted(states_before.keys() | states_after.keys())
                 if "unknown" in (states_before.get((actor, capability), "inactive"),
                                  states_after.get((actor, capability), "inactive"))]
    if not projection_reliable:
        lost, gained, missing, uncertain = [], [], [], []
    equip_blockers = []
    for entry in configured["equipped_items"].values():
        if entry["required_level"] is not None and entry["required_level"] > configured["character_level"]:
            equip_blockers.append("future_required_level_not_met:" + entry["instance_id"])
        if entry.get("class_id") not in (None, configured["class_id"]):
            equip_blockers.append("future_item_class_incompatible:" + entry["instance_id"])
    blockers = sorted(set(blockers))
    return {"status": "blocked" if blockers or equip_blockers else
            "mechanism_loss" if lost or missing else "mechanism_change" if gained else "no_known_change",
            "scope_compatible": scoped, "before": deepcopy(before), "after": after,
            "lost_capabilities": sorted({capability for _, capability in lost}),
            "gained_capabilities": sorted({capability for _, capability in gained}),
            "missing_requirements": [capability for _, capability in missing],
            "lost_mechanisms": [{"actor": actor, "capability": capability} for actor, capability in lost],
            "gained_mechanisms": [{"actor": actor, "capability": capability} for actor, capability in gained],
            "missing_mechanisms": [{"actor": actor, "capability": capability} for actor, capability in missing],
            "uncertain_mechanisms": uncertain, "equip_blockers": sorted(set(equip_blockers)),
            "blockers": blockers}

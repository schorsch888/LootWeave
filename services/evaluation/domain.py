"""Three-state, source-aware mechanism comparisons; no DPS or universal weights."""
from __future__ import annotations

from copy import deepcopy

from contracts import CONTEXT_KEYS, digest, object_value, require, strings, timestamp

EVALUATOR_VERSION = "0.1.4"
EVALUATOR_VERSIONS = ("0.1.0", "0.1.1", "0.1.2", "0.1.3", EVALUATOR_VERSION)


def intent(value: dict) -> dict:
    value = object_value(value)
    require(type(value.get("revision")) is int and value["revision"] > 0, "intent_revision_required")
    require(value.get("scenario") == "leveling", "unsupported_scenario")
    strings(value.get("required_capabilities"))
    strings(value.get("allowed_build_changes"))
    require(isinstance(value.get("future_builds"), list), "future_builds_required")
    for build in value["future_builds"]:
        object_value(build)
        require(isinstance(build.get("skills"), list), "future_skills_required")
        require(all(isinstance(x, str) for x in build["skills"]), "future_skills_required")
        states = object_value(build.get("conditions"))
        require(all(x in ("active", "inactive", "unknown") for x in states.values()),
                "invalid_condition_state")
        require(build.get("feasibility") in ("owned", "obtainable", "hypothetical"),
                "future_feasibility_required")
    object_value(value.get("budget"))
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
            result.append({**entry, "id": key + ":" + entry["id"], "kind": key,
                           "actor": entry.get("actor", "companion" if key == "companions" else "hero")})
    return result


def condition_state(states: list[str]) -> str:
    if "inactive" in states:
        return "inactive"
    return "unknown" if "unknown" in states else "active"


def resolve(facts: dict, pack: dict, evaluator_version=EVALUATOR_VERSION) -> list[dict]:
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
        if not present or not required_skills.issubset(skills):
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


def evaluate(profile: dict, knowledge: dict, purpose: dict, *, evaluator_version=EVALUATOR_VERSION) -> dict:
    require(evaluator_version in EVALUATOR_VERSIONS, "evaluator_version_unavailable", 409)
    require(profile.get("contract_version") == 1, "incompatible_profile_contract")
    facts, pack = profile["facts"], knowledge["pack"]
    require(profile.get("facts_hash") == digest(facts), "profile_integrity_error", 409)
    require(knowledge.get("pack_hash") == digest(pack), "pack_integrity_error", 409)
    require(pack.get("contract_version") == 1, "incompatible_pack_contract")
    purpose = intent(purpose)
    strict_requirements = evaluator_version in ("0.1.3", "0.1.4")
    uncertainty_aware = evaluator_version == "0.1.4"
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
    capture = timestamp(facts["captured_at"])
    if any(timestamp(e["captured_at"]) != capture for e in facts["evidence"]):
        blockers.append("cross_time_snapshot")
    if any(e.get("conflicts") for e in facts["evidence"]) or any(e.get("conflicts") for e in pack["evidence"]):
        blockers.append("conflicting_evidence")
    for item in [*facts["equipped_items"].values(), facts["candidate_item"]]:
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
    known_skills = {skill for rule in pack["rules"] for skill in rule.get("requires_skills", [])}
    if pack["execution_policy"] == "synthetic_only":
        blockers.extend("unknown_skill:" + entry["id"] for entry in facts["skills"]
                        if entry["rank"] > 0 and entry["id"] not in known_skills)
    before_facts = deepcopy(facts)
    after_facts = deepcopy(facts)
    candidate = facts["candidate_item"]
    after_facts["equipped_items"][candidate["slot"]] = candidate
    known_effects = {r["source_id"] for r in pack["rules"] if r["source_kind"] == "effect"}
    known_sets = {r["source_id"] for r in pack["rules"] if r["source_kind"] != "effect"}
    for configured in (before_facts, after_facts):
        for entry in all_sources(configured, evaluator_version):
            blockers.extend("unknown_effect:" + effect for effect in entry["effects"] if effect not in known_effects)
        for entry in [*configured["equipped_items"].values(), *configured["runes"]]:
            if entry.get("set_id") and entry["set_id"] not in known_sets:
                blockers.append("unknown_set:" + entry["set_id"])
    # Incompatible scopes must never execute a rule, even for an explanation.
    scoped = not any(x.startswith(("incompatible_context:", "unknown_context:")) or
                     x in ("unsupported_class", "missing_content_entitlement", "game_mechanics_not_accepted")
                     for x in blockers)
    if strict_requirements and "unsupported_scenario" in blockers:
        scoped = False
    before = resolve(before_facts, pack, evaluator_version) if scoped else []
    after = resolve(after_facts, pack, evaluator_version) if scoped else []
    for result in before + after:
        if result["state"] == "unknown":
            blockers.append("unknown_condition:" + result["rule_id"])
    # Engines through 0.1.1 aggregate names; later engines preserve the actor.
    actor_aware = evaluator_version in ("0.1.2", "0.1.3", "0.1.4")
    active_before = {(r["actor"] if actor_aware else None, r["capability"])
                     for r in before if r["state"] == "active"}
    active_after = {(r["actor"] if actor_aware else None, r["capability"])
                    for r in after if r["state"] == "active"}
    candidate_sources = {candidate["instance_id"], *(
        candidate["instance_id"] + ":" + x["id"] for x in candidate["embedded_items"])}
    candidate_rules = [r for r in after if candidate_sources.intersection(r["source_ids"])]
    relevant = [r for r in candidate_rules if r["state"] == "active"]
    future_reasons = []
    if scoped:
        for index, future in enumerate(purpose["future_builds"]):
            if "skills" not in purpose["allowed_build_changes"]:
                blockers.append("future_build_change_not_permitted")
                continue
            modified = deepcopy(after_facts)
            modified["skills"] = [{"id": x, "rank": 1, "effects": [], "evidence_ids": facts["evidence_ids"]}
                                  for x in future["skills"]]
            modified["conditions"] = future["conditions"]
            blockers.extend("unknown_future_skill:" + x for x in future["skills"] if x not in known_skills)
            for rule in resolve(modified, pack, evaluator_version):
                if candidate_sources.intersection(rule["source_ids"]) and rule["state"] == "unknown":
                    blockers.append("unknown_future_condition:" + rule["rule_id"])
                if candidate_sources.intersection(rule["source_ids"]) and rule["state"] == "active":
                    future_reasons.append({**rule, "future_build_index": index,
                                           "feasibility": future["feasibility"]})
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
    return {"contract_version": 1, "pin": pin, "retention": verdict,
            "comparison": comparison,
            "reasons": reasons, "blockers": blockers, "panel_policy": "observations_only",
            "scope_notice": "Synthetic mechanism check; no validated game recommendation or DPS.",
            "limitations": pack["unknowns"]}

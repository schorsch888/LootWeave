"""Feasibility from confirmed local quotes; no inferred recipes or game execution."""
from __future__ import annotations

from copy import deepcopy

from contracts import CONTEXT_KEYS, identifier, object_value, require, strings, timestamp

MAX_AMOUNT = 2**53 - 1


def validate_preparation_intent(purpose: dict) -> None:
    budget = purpose["budget"]
    require(set(budget).issubset({"resource_limits"}), "unsupported_budget_fields")
    limits = budget.get("resource_limits", [])
    require(isinstance(limits, list), "resource_budget_required")
    ids = set()
    for entry in limits:
        object_value(entry)
        resource_id = identifier(entry.get("resource_id"))
        require(resource_id not in ids, "duplicate_resource_budget")
        ids.add(resource_id)
        require(type(entry.get("amount")) is int and 0 <= entry["amount"] <= MAX_AMOUNT,
                "resource_amount_required")
    for build in purpose["future_builds"]:
        refs = strings(build.get("preparation_options", []), "future_preparation_required")
        for ref in refs:
            identifier(ref)
        require(len(refs) == len(set(refs)), "duplicate_future_preparation")
        require(len(build["skills"]) == len(set(build["skills"])), "duplicate_future_skill")
        for skill_id in build["skills"]:
            identifier(skill_id)


def intrinsic(value):
    """Confirmation can add provenance without changing an item's actual state."""
    if isinstance(value, dict):
        return {key: intrinsic(entry) for key, entry in value.items()
                if key not in ("evidence", "evidence_ids", "captured_at", "source_ref")}
    if isinstance(value, list):
        return [intrinsic(entry) for entry in value]
    return value


def prepare_future(facts: dict, configured: dict, future: dict, purpose: dict,
                   index: int, initial_blockers: list[str]) -> tuple[dict, dict]:
    """Apply projections only inside this plan, retaining the actual current build."""
    configured = deepcopy(configured)
    blockers = list(initial_blockers)
    impossible = set()
    input_refs = set()
    evidence = {entry["id"]: entry for entry in facts["evidence"]}
    capture = timestamp(facts["captured_at"])

    def block(code, *, infeasible=False):
        blockers.append(code)
        if infeasible:
            impossible.add(code)

    def use_refs(refs):
        input_refs.update(refs)
        for ref in refs:
            entry = evidence.get(ref)
            if (entry is None or entry.get("verification") != "confirmed" or
                    entry.get("conflicts") or timestamp(entry["captured_at"]) != capture):
                block("preparation_evidence_unconfirmed:" + ref)

    for key in CONTEXT_KEYS:
        if facts["context"][key].lower() in ("unknown", "unconfirmed"):
            block("unknown_context:" + key)
    use_refs(facts["evidence_ids"])
    candidate = configured["equipped_items"][facts["candidate_item"]["slot"]]
    if candidate["required_level"] is None:
        block("required_level_unknown:" + candidate["instance_id"])
    elif candidate["required_level"] > facts["character_level"]:
        block("future_required_level_not_met:" + candidate["instance_id"], infeasible=True)
    if candidate.get("class_id") not in (None, facts["class_id"]):
        block("future_item_class_incompatible:" + candidate["instance_id"], infeasible=True)
    use_refs(candidate["evidence_ids"])

    options = {option["id"]: option for option in facts.get("preparation_options", [])}
    selected = []
    targets = set()
    total_costs = {}
    current_skills = {entry["id"]: entry for entry in facts["skills"]}
    proposed_skills = {skill_id: deepcopy(current_skills[skill_id])
                       for skill_id in future["skills"]
                       if skill_id in current_skills and current_skills[skill_id]["rank"] > 0}
    skill_options = set()
    for ref in future.get("preparation_options", []):
        option = options.get(ref)
        if option is None:
            block("preparation_option_not_recorded:" + ref)
            continue
        selected.append({**{key: option[key] for key in ("id", "kind", "target_id")},
                         "projected_result": deepcopy(option["result"])})
        use_refs(option["evidence_ids"])
        if option["context"] != facts["context"] or option["class_id"] != facts["class_id"]:
            block("preparation_scope_mismatch:" + ref)
        for unknown in option["unknowns"]:
            block("preparation_unknown:" + ref + ":" + unknown)
        if option["costs"] is None or "costs_not_confirmed" in option["unknowns"]:
            block("preparation_cost_unknown:" + ref)
        else:
            for cost in option["costs"]:
                resource_id = cost["resource_id"]
                total_costs[resource_id] = total_costs.get(resource_id, 0) + cost["amount"]
        target = (option["kind"], option["target_id"])
        if target in targets:
            block("preparation_target_conflict:" + option["target_id"])
            continue
        targets.add(target)
        change = "skills" if option["kind"] == "skill" else "equipment"
        if change not in purpose["allowed_build_changes"]:
            block("future_build_change_not_permitted", infeasible=True)
        requirements = option["requirements"]
        if requirements["unlock_state"] == "unknown":
            block("preparation_unlock_unknown:" + ref)
        elif requirements["unlock_state"] == "locked":
            block("preparation_unlock_not_met:" + ref, infeasible=True)
        if requirements["required_level"] is None:
            block("preparation_level_unknown:" + ref)
        elif requirements["required_level"] > facts["character_level"]:
            block("preparation_level_not_met:" + ref, infeasible=True)
        result = deepcopy(option["result"])
        if option["kind"] == "skill":
            skill_options.add(option["target_id"])
            if intrinsic(option["input"]) != intrinsic(current_skills.get(option["target_id"])):
                block("preparation_input_changed:" + ref)
            positive = result["rank"] > 0
            if positive != (option["target_id"] in future["skills"]):
                block("preparation_skill_selection_conflict:" + ref)
            if positive:
                if requirements["max_rank"] is None:
                    block("preparation_rank_limit_unknown:" + ref)
                elif result["rank"] > requirements["max_rank"]:
                    block("preparation_rank_not_met:" + ref, infeasible=True)
                # Companion skill learning needs companion-specific level/unlock facts.
                if result.get("actor", "hero") != "hero":
                    block("preparation_companion_requirements_unknown:" + ref)
                proposed_skills[option["target_id"]] = result
            else:
                proposed_skills.pop(option["target_id"], None)
            use_refs(result["evidence_ids"])
        else:
            active = next((item for item in configured["equipped_items"].values()
                           if item["instance_id"] == option["target_id"]), None)
            if active is None:
                block("preparation_item_not_selected:" + option["target_id"])
            elif intrinsic(option["input"]) != intrinsic(active):
                block("preparation_input_changed:" + ref)
            else:
                configured["equipped_items"][active["slot"]] = result
            if result["required_level"] is None:
                block("required_level_unknown:" + result["instance_id"])
            elif result["required_level"] > facts["character_level"]:
                block("future_required_level_not_met:" + result["instance_id"], infeasible=True)
            if result["unrevealed_properties"] or result["unknowns"]:
                block("preparation_outcome_unknown:" + ref)
            if not all(result[key]["known"] for key in ("upgrade_state", "socket_state")):
                block("preparation_outcome_unknown:" + ref)
            use_refs(result["evidence_ids"])
            for entry in [*result["affixes"], *result["embedded_items"]]:
                use_refs(entry["evidence_ids"])

    for skill_id in future["skills"]:
        if skill_id not in proposed_skills:
            block("future_skill_not_recorded:" + skill_id)
    for skill_id, skill in current_skills.items():
        if skill["rank"] > 0 and skill_id not in future["skills"] and skill_id not in skill_options:
            block("future_skill_removal_not_recorded:" + skill_id)
    configured["skills"] = [proposed_skills[skill_id] for skill_id in sorted(proposed_skills)]
    for source in configured["skills"]:
        use_refs(source["evidence_ids"])
    for item in configured["equipped_items"].values():
        use_refs(item["evidence_ids"])
    configured["conditions"] = deepcopy(future["conditions"])

    resources = facts.get("owned_resources")
    balances = {row["resource_id"]: row for row in resources["balances"]} if resources else {}
    limits = {row["resource_id"]: row["amount"] for row in purpose["budget"].get("resource_limits", [])}
    rows = []
    for resource_id, cost in sorted(total_costs.items()):
        balance = balances.get(resource_id)
        available = balance["amount"] if balance else 0 if resources and resources["coverage"] == "complete" else None
        if balance:
            use_refs(balance["evidence_ids"])
        elif available == 0:
            use_refs(facts["evidence_ids"])
        limit = limits.get(resource_id)
        if cost > MAX_AMOUNT:
            block("preparation_cost_out_of_range:" + resource_id)
            rows.append({"resource_id": resource_id, "cost": None, "available": available,
                         "budget_limit": limit, "missing": None, "budget_excess": None})
            continue
        missing = None if available is None else max(0, cost - available)
        excess = None if limit is None else max(0, cost - limit)
        if cost and available is None:
            block("preparation_resource_unknown:" + resource_id)
        if missing:
            block("preparation_resource_insufficient:" + resource_id, infeasible=True)
        if excess:
            block("preparation_budget_exceeded:" + resource_id, infeasible=True)
        rows.append({"resource_id": resource_id, "cost": cost, "available": available,
                     "budget_limit": limit, "missing": missing, "budget_excess": excess})
    blockers = sorted(set(blockers))
    # Known failed conditions dominate uncertainty, while all reasons remain visible.
    infeasible = bool(impossible) or "future_build_change_not_permitted" in blockers or any(code.startswith(("future_required_level_not_met:",
        "future_item_class_incompatible:", "future_equipment_slot_conflict:",
        "future_candidate_slot_conflict:")) for code in blockers)
    report = {"future_build_index": index,
              "status": "infeasible" if infeasible else "unknown" if blockers else "feasible",
              "declared_feasibility": future["feasibility"], "blockers": blockers,
              "options": sorted(selected, key=lambda option: option["id"]),
              "skill_allocations": deepcopy(configured["skills"]), "resources": rows,
              "input_evidence_ids": sorted(input_refs)}
    return configured, report

"""Research and synthetic specifications cannot become accepted game mechanics."""
from __future__ import annotations

from contracts import context, identifier, object_value, require, strings


def validate_pack(pack: dict) -> dict:
    object_value(pack)
    require(pack.get("contract_version") == 1, "incompatible_pack_contract")
    identifier(pack.get("pack_id"))
    identifier(pack.get("version"))
    scope = context(pack.get("context"))
    require(pack.get("execution_policy") in ("synthetic_only", "research_only"), "unaccepted_execution_policy")
    require(pack["execution_policy"] != "synthetic_only" or scope["game_id"] == "lootweave-fixture",
            "synthetic_scope_required")
    identifier(pack.get("class_id"))
    require(pack.get("scenario") == "leveling", "unsupported_pack_scenario")
    evidence = pack.get("evidence")
    require(isinstance(evidence, list) and bool(evidence), "rule_evidence_required")
    evidence_ids = set()
    for entry in evidence:
        object_value(entry)
        identifier(entry.get("id"))
        require(entry["id"] not in evidence_ids, "duplicate_rule_evidence")
        evidence_ids.add(entry["id"])
        require(all(isinstance(entry.get(key), str) and bool(entry[key]) for key in
                    ("source_ref", "source_build", "method", "scope", "results", "unknowns")),
                "evidence_record_incomplete")
        require(entry.get("verification") in ("synthetic", "historical_research"),
                "evidence_verification_required")
        strings(entry.get("conflicts"))
    require(isinstance(pack.get("rules"), list), "pack_rules_required")
    require(pack["execution_policy"] != "research_only" or not pack["rules"], "research_rules_not_executable")
    ids = set()
    for rule in pack["rules"]:
        object_value(rule)
        identifier(rule.get("id"))
        require(rule["id"] not in ids, "duplicate_rule_id")
        ids.add(rule["id"])
        require(rule.get("operation") == "capability", "unsupported_rule_operation")
        require(rule.get("source_kind") in ("effect", "equipment_set", "rune_set"), "invalid_rule_source")
        refs = strings(rule.get("evidence_ids"), "rule_evidence_required")
        require(bool(refs) and all(x in evidence_ids for x in refs), "rule_evidence_required")
        require(rule.get("context") == scope, "rule_scope_mismatch")
        strings(rule.get("conditions"), "invalid_rule_conditions")
        strings(rule.get("requires_skills"), "rule_skills_required")
        require(rule.get("actor") in ("hero", "companion"), "effect_owner_required")
        require(rule.get("stacking") in ("unique", "source") and rule.get("unit") == "capability",
                "rule_semantics_required")
        require(isinstance(rule.get("explanation"), str) and bool(rule["explanation"]),
                "rule_explanation_required")
        identifier(rule.get("source_id"))
        identifier(rule.get("capability"))
        if rule["source_kind"] != "effect":
            require(type(rule.get("min_count")) is int and rule["min_count"] > 0,
                    "invalid_set_threshold")
    affixes = object_value(pack.get("known_affixes"))
    require(all(isinstance(x, str) and bool(x) for x in affixes.values()), "affix_units_required")
    for source in pack.get("acquisition_sources", []):
        object_value(source)
        identifier(source.get("source_id"))
        identifier(source.get("target_event"))
        require(type(source.get("min_level")) is int and source["min_level"] >= 1,
                "source_level_required")
        strings(source.get("conditions"))
        strings(source.get("entitlements"))
        refs = strings(source.get("evidence_ids"))
        require(bool(refs) and all(x in evidence_ids for x in refs), "source_evidence_required")
    strings(pack.get("unknowns"), "pack_unknowns_required")
    return pack

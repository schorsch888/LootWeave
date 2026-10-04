"""Measured outcomes and versioned prerequisites; client weights are not probabilities."""
from __future__ import annotations

import math
from statistics import NormalDist

from contracts import CONTEXT_KEYS, context, digest, number, object_value, require, strings

SUPPORTED_TRIAL_GAMES = ("deskrawl", "lootweave-fixture")
MAX_EXACT_INTEGER = 2**53 - 1


def trial_scope(value):
    value = object_value(value)
    game = context(value.get("context"))
    require(game["game_id"] in SUPPORTED_TRIAL_GAMES, "unsupported_planning_game")
    require(all(game[key].lower() not in ("unknown", "unconfirmed") for key in CONTEXT_KEYS),
            "confirmed_trial_context_required")
    for key in ("class_id", "build_hash", "bonuses_hash", "objective"):
        require(isinstance(value.get(key), str) and bool(value[key]), "trial_scope_required")
    require(value.get("xp_kind") in ("character", "paragon"), "xp_kind_required")
    minimum_level = 0 if value["xp_kind"] == "paragon" else 1
    require(type(value.get("level_start")) is int and type(value.get("level_end")) is int
            and minimum_level <= value["level_start"] <= value["level_end"], "level_range_required")
    return value


def trial(value):
    value = object_value(value)
    trial_scope(value.get("scope"))
    for key in ("trial_id", "map_id", "difficulty_id"):
        require(isinstance(value.get(key), str) and bool(value[key]), "trial_identity_required")
    require(value.get("access") in ("active", "inactive", "unknown"), "trial_access_required")
    require(type(value.get("xp_gain")) is int and value["xp_gain"] >= 0, "actual_xp_required")
    require(number(value.get("complete_elapsed_seconds")) and value["complete_elapsed_seconds"] > 0,
            "complete_elapsed_time_required")
    require(value.get("method") in ("cumulative_xp", "bar_difference"), "xp_measurement_method_required")
    require(type(value.get("bonuses_unchanged")) is bool and type(value.get("build_unchanged")) is bool,
            "trial_consistency_required")
    require(type(value.get("xp_transition")) is bool and
            type(value.get("level_thresholds_verified")) is bool, "xp_transition_state_required")
    refs = strings(value.get("evidence_ids"))
    require(bool(refs), "trial_evidence_required")
    unknowns = []
    if value["xp_gain"] > MAX_EXACT_INTEGER or value["scope"]["level_end"] > MAX_EXACT_INTEGER:
        unknowns.append("trial_measurement_out_of_range")
    elif not math.isfinite(value["xp_gain"] * 60 / value["complete_elapsed_seconds"]):
        unknowns.append("trial_measurement_out_of_range")
    if value["access"] != "active":
        unknowns.append("route_access_not_confirmed")
    if not value["bonuses_unchanged"] or not value["build_unchanged"]:
        unknowns.append("trial_settings_changed")
    if value["xp_transition"]:
        unknowns.append("character_paragon_transition")
    if value["method"] == "bar_difference" and value["scope"]["level_start"] != value["scope"]["level_end"] \
            and not value["level_thresholds_verified"]:
        unknowns.append("unverified_level_thresholds")
    return {**value, "measurement_status": "uncertain" if unknowns else "confirmed", "unknowns": unknowns}


def compare_routes(scope, candidates, trials):
    trial_scope(scope)
    require(scope["level_end"] <= MAX_EXACT_INTEGER, "level_range_required")
    require(isinstance(candidates, list) and isinstance(trials, list), "routes_and_trials_required")
    routes = {}
    for candidate in candidates:
        object_value(candidate)
        require(candidate.get("access") in ("active", "inactive", "unknown"), "route_access_required")
        require(all(isinstance(candidate.get(key), str) and candidate[key] for key in
                    ("map_id", "difficulty_id")), "route_identity_required")
        key = (candidate["map_id"], candidate["difficulty_id"])
        require(key not in routes, "duplicate_route_candidate")
        routes[key] = {**candidate, "trial_count": 0, "xp_total": 0, "time_total": 0.0, "rates": []}
    excluded = []
    for value in trials:
        measured = trial(value)
        key = (measured["map_id"], measured["difficulty_id"])
        if measured["scope"] != scope or measured["measurement_status"] != "confirmed" or key not in routes \
                or routes[key]["access"] != "active":
            excluded.append({"trial_id": measured["trial_id"], "reason":
                             "incomparable_scope" if measured["scope"] != scope else
                             "uncertain_measurement_or_access", "unknowns": measured["unknowns"]})
            continue
        route = routes[key]
        route["trial_count"] += 1
        route["xp_total"] += measured["xp_gain"]
        route["time_total"] += measured["complete_elapsed_seconds"]
        route["rates"].append(measured["xp_gain"] * 60 / measured["complete_elapsed_seconds"])
    result = []
    for route in routes.values():
        rates = route.pop("rates")
        count = route["trial_count"]
        aggregate_known = route["xp_total"] <= MAX_EXACT_INTEGER and number(route["time_total"])
        rate = route["xp_total"] * 60 / route["time_total"] if count and aggregate_known else None
        aggregate_known = aggregate_known and (rate is None or math.isfinite(rate))
        route["unknowns"] = [] if aggregate_known else ["aggregate_trial_measurement_out_of_range"]
        if not aggregate_known:
            rate = None
            if route["xp_total"] > MAX_EXACT_INTEGER:
                route["xp_total"] = None
            if not number(route["time_total"]):
                route["time_total"] = None
        route.update(xp_per_minute=rate, minimum_trial_rate=min(rates) if rates else None,
                     maximum_trial_rate=max(rates) if rates else None,
                     status="inaccessible" if route["access"] == "inactive" else
                     "needs_confirmation" if route["access"] == "unknown" or not aggregate_known else
                     "measured" if count else "trial_candidate",
                     observation="single_trial" if count == 1 else "multiple_trials" if count else "unmeasured")
        result.append(route)
    measured = sorted((r for r in result if r["status"] == "measured"),
                      key=lambda r: (-r["xp_per_minute"], r["map_id"], r["difficulty_id"]))
    best = measured[0] if measured else None
    retest = any(r["trial_count"] == 1 or (r["minimum_trial_rate"] < r["maximum_trial_rate"] * .75)
                 for r in measured)
    if len(measured) > 1 and measured[0]["xp_per_minute"] > 0:
        retest = retest or measured[1]["xp_per_minute"] >= measured[0]["xp_per_minute"] * .9
    return {"scope": scope, "scope_hash": digest(scope), "routes": result, "excluded_trials": excluded,
            "best_measured_candidate": None if best is None else
            {"map_id": best["map_id"], "difficulty_id": best["difficulty_id"]},
            "retest_recommended": retest, "method": "total actual XP / total complete elapsed time",
            "retest_policy": "One trial, >25% trial-rate range, or top measured rates within 10%; heuristic.",
            "limitations": ["Untested routes are unranked.", "This does not establish a global optimum."]}


def eligibility(facts, pack):
    game = context(facts.get("context"))
    require(type(facts.get("character_level")) is int and facts["character_level"] > 0, "character_level_required")
    states = object_value(facts.get("conditions"))
    require(all(x in ("active", "inactive", "unknown") for x in states.values()), "invalid_condition_state")
    scope_ok = all(game[key] == pack["context"][key] for key in CONTEXT_KEYS)
    scope_ok = scope_ok and facts.get("class_id") == pack["class_id"]
    accepted = pack["execution_policy"] == "synthetic_only" and game["game_id"] == "lootweave-fixture"
    sources = []
    for source in pack.get("acquisition_sources", []):
        if not scope_ok or not accepted:
            state = "unknown"
        elif source["min_level"] > facts["character_level"] or \
                not set(source["entitlements"]).issubset(game["content_entitlements"]):
            state = "inactive"
        else:
            prerequisites = [states.get(x, "unknown") for x in source["conditions"]]
            state = "inactive" if "inactive" in prerequisites else "unknown" if "unknown" in prerequisites else "active"
        sources.append({**source, "eligibility": state})
    return {"sources": sources, "scope_accepted": scope_ok and accepted,
            "notice": "Eligibility is separate from rarity, usefulness and reacquisition cost.",
            "unknowns": [] if scope_ok and accepted else ["Source rules are not accepted for this scope."]}


def drop_estimate(value):
    value = object_value(value)
    game = context(value.get("context"))
    require(all(game[key].lower() not in ("unknown", "unconfirmed") for key in CONTEXT_KEYS),
            "sample_version_required")
    require(value.get("method") == "observed_counts", "weights_are_not_probabilities")
    require(value.get("coverage") == "complete", "unrecorded_attempts_are_not_failures")
    require(value.get("version_unchanged") is True, "stale_version_sample")
    require(type(value.get("attempts")) is int and 0 < value["attempts"] <= MAX_EXACT_INTEGER and
            type(value.get("successes")) is int and 0 <= value["successes"] <= value["attempts"],
            "invalid_sample_counts")
    for key in ("target_event", "attempt_unit"):
        require(isinstance(value.get(key), str) and bool(value[key]), "sampling_definition_required")
    n, k = value["attempts"], value["successes"]
    p = k / n
    z = NormalDist().inv_cdf(.975)
    denominator = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denominator
    radius = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denominator
    return {"context": game, "target_event": value["target_event"], "attempt_unit": value["attempt_unit"],
            "sample_size": n, "observed_successes": k, "estimate": p,
            "interval": [max(0, center - radius), min(1, center + radius)], "confidence_level": .95,
            "method": "Wilson score interval on recorded binary outcomes",
            "assumptions": ["Independent representative attempts under unchanged version and settings.",
                            "Every attempt and its target outcome were recorded."],
            "expected_attempts_at_observed_rate": None if p == 0 else 1 / p,
            "notice": "Sample estimate, not a verified final game probability or guaranteed waiting time."}

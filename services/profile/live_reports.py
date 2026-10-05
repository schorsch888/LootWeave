"""Descriptive statistics from local API measurements, without game formulas."""
from __future__ import annotations

import math
from collections import Counter, defaultdict

from contracts import digest, number, require
from services.profile.live_schema import LOADOUT, REPORT_INPUT, decode


def nonnegative(value):
    return number(value) and 0 <= value < 2**53


def add(values):
    if any(value is None for value in values):
        return None
    result = sum(values)
    require(nonnegative(result), "live_sample_invalid")
    return result


def frequency(n, k):
    return {"n": n, "k": k, "rate": k / n if n else None}


def rate(total, duration):
    result = total / duration
    require(nonnegative(result), "live_sample_invalid")
    return result


def group_runs(records):
    grouped = defaultdict(list)
    for row in records:
        if row["partial"] is False and nonnegative(row["dur"]) and row["dur"] > 0 and row["exp"] is not None and row["gold"] is not None:
            grouped[(row["map"], row["difficulty"])].append(row)
    result = []
    for (name, difficulty), rows in grouped.items():
        duration = add([row["dur"] for row in rows])
        experience, gold = (add([row[field] for row in rows]) for field in ("exp", "gold"))
        result.append({"map": name, "difficulty": difficulty, "runs": len(rows), "dur": duration,
                       "exp": experience, "gold": gold, "exp_s": rate(experience, duration), "gold_s": rate(gold, duration)})
    return result


def runs(data, sampled_at, producer):
    records = data["records"]
    if any(row["result"] == "live" for row in records):
        raise_invalid()
    live = data["live"] if data["live"]["id"] else None
    for row in records + ([live] if live else []):
        require(bool(row["id"]), "live_sample_invalid")
        for field in ("t0", "t1", "dur"):
            require(row[field] is None or nonnegative(row[field]), "live_sample_invalid")
        if row["t0"] is not None and row["t1"] is not None:
            require(row["t1"] >= row["t0"] and row["t1"] <= sampled_at + 30, "live_sample_invalid")
        damage = row["damage"]
        require(damage["dmg"] is None or nonnegative(damage["dmg"]), "live_sample_invalid")
        for source in damage["sources"]:
            require(source["dmg"] is None or nonnegative(source["dmg"]), "live_sample_invalid")
        row["id"] = "run-" + digest([producer, row["id"], row["t0"]])[:32]
        row["damage"]["sources"].sort(key=lambda source: -(source["dmg"] or 0))
    require(len({row["id"] for row in records}) == len(records), "live_sample_invalid")
    per_map = Counter((row["map"], row["difficulty"]) for row in records)
    whole = [row for row in records if row["partial"] is False and nonnegative(row["dur"])
             and row["dur"] > 0 and row["exp"] is not None and row["gold"] is not None][-20:]
    summary = group_runs(whole)
    duration = add([row["dur"] for row in summary]) if summary else None
    rates = {"runs": len(whole), "dur": duration,
             "exp_s": rate(add([row["exp"] for row in summary]), duration) if duration else None,
             "gold_s": rate(add([row["gold"] for row in summary]), duration) if duration else None}
    return {"records": records, "live": live, "total": len(records), "rates": rates,
            "window_maps": group_runs(records),
            "per_map": [{"map": name, "difficulty": difficulty, "runs": amount}
                        for (name, difficulty), amount in per_map.items()]}


def raise_invalid():
    require(False, "live_sample_invalid")


def combat(data, sampled_at, producer):
    start = data["coverage_started_at"]
    session_start = data["session_started_at"]
    require(start is None or nonnegative(start) and start <= sampled_at, "live_sample_invalid")
    require(session_start is None or nonnegative(session_start) and session_start <= sampled_at, "live_sample_invalid")
    events = data["events"]
    for event in events:
        require(nonnegative(event["at"]) and event["at"] <= sampled_at + 0.001 and nonnegative(event["damage"]), "live_sample_invalid")
        require(start is None or event["at"] >= start, "live_sample_invalid")
    recent = {period: [event for event in events if sampled_at - period < event["at"] <= sampled_at] for period in (10, 60)}
    live = {"dps" + str(period): add([event["damage"] for event in recent[period]]) / period
            if start is not None and start <= sampled_at - period else None for period in (10, 60)}
    live["active60"] = len({math.floor(event["at"]) for event in recent[60] if event["damage"] > 0}) if start is not None and start <= sampled_at - 60 else None
    scope = [event for event in events if session_start is not None and event["at"] >= session_start]
    sources = defaultdict(list)
    for event in scope:
        sources[(event["source_id"], event["source_name"], event["actor"])].append(event)
    by = []
    for (identity, name, actor), rows in sources.items():
        by.append({"id": "damage-" + digest([producer, identity])[:32], "name": name, "actor": actor,
                   "dmg": add([row["damage"] for row in rows]),
                   **{field: add([row[field] for row in rows]) for field in ("hits", "crits", "kills")}})
    by.sort(key=lambda row: -(row["dmg"] or 0))
    complete = start is not None and session_start is not None and start <= session_start
    return {"coverage_started_at": start, "live": live,
            "session": {"dmg": add([event["damage"] for event in scope]) if session_start is not None else None,
                        **{field: add([event[field] for event in scope]) if session_start is not None else None
                           for field in ("hits", "crits", "kills")},
                        "active": len({math.floor(event["at"]) for event in scope if event["damage"] > 0}) if session_start is not None else None,
                        "partial": not complete, "sources": by, "since": session_start,
                        "dur": sampled_at - session_start if session_start is not None else None}}


def draws_summary(records):
    rarities = Counter(row["rarity"] for row in records)
    top = [row for row in records if row["rarity"] in ("Legendary", "Divine")]
    ancient = [row for row in top if row["ancient"] is not None]
    mist = [row for row in top if row["black_mist"] is not None]
    pieces = defaultdict(list)
    for row in records:
        pieces[row["piece"] or "unknown"].append(row)
    prices = [row["price"] for row in records]
    return {"draws": len(records), "shards": add(prices) if records else 0,
            "rarities": [{"rarity": name, "count": amount, "frequency": amount / len(records)} for name, amount in rarities.items()],
            "top": frequency(len(records), len(top)), "ancient": frequency(len(ancient), sum(row["ancient"] for row in ancient)),
            "black_mist": frequency(len(mist), sum(row["black_mist"] for row in mist)),
            "pieces": {name: {"draws": len(rows), "top": sum(row["rarity"] in ("Legendary", "Divine") for row in rows),
                               "shards": add([row["price"] for row in rows])} for name, rows in pieces.items()}}


def lineage(data, sampled_at, producer):
    for row in data["draws"] + data["finds"]:
        require(row["time"] is None or nonnegative(row["time"]) and row["time"] <= sampled_at + 30, "live_sample_invalid")
    return {"gamble": {name: draws_summary([row for row in data["draws"] if name == "all" or row["how"] == name])
                       for name in ("all", "manual", "auto")},
            "draws": data["draws"], "finds": data["finds"], "market": [row for row in data["finds"] if row["market"] is True]}


def loadouts(data, sampled_at, producer):
    slots = data["slots"]
    require(all(1 <= (row["slot"] or 0) <= 5 for row in slots), "live_sample_invalid")
    require(len({row["slot"] for row in slots}) == len(slots), "live_sample_invalid")
    by_slot = {row["slot"]: row for row in slots}
    return {"slots": [by_slot.get(slot, {**decode(None, LOADOUT), "slot": slot}) for slot in range(1, 6)],
            "in_use": next((row["slot"] for row in slots if row["worn"] is True), None)}


def reports(value, sampled_at, producer, coverage):
    require(value is None or isinstance(value, dict), "live_sample_invalid")
    raw = value or {}
    data = decode(raw, REPORT_INPUT)
    result = {"contract": "lootweave-live/1", "kind": "local_measurements"}
    functions = {"runs": runs, "combat": combat, "lineage": lineage, "loadouts": loadouts}
    for name in REPORT_INPUT[1]:
        state = coverage.get(name, "unknown")
        if name not in raw or state == "unknown":
            result[name] = {"state": "unavailable", "data": None}
        else:
            if name == "combat" and state != "complete":
                data[name]["coverage_started_at"] = None
            result[name] = {"state": "enabled" if state == "complete" else "partial",
                            "data": functions[name](data[name], sampled_at, producer) if name in functions else data[name]}
    return result

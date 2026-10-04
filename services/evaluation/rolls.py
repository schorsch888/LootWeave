"""Compare confirmed item affix fields without inferring build or combat outcomes."""
from __future__ import annotations

from contracts import number


def compare_item_rolls(facts: dict) -> dict:
    candidate = facts["candidate_item"]
    current = facts["equipped_items"].get(candidate["slot"])
    current_affixes = {affix["id"]: affix for affix in current["affixes"]} if current else {}
    candidate_affixes = {affix["id"]: affix for affix in candidate["affixes"]}
    rows = []
    for affix_id in sorted(current_affixes.keys() | candidate_affixes.keys()):
        before, after = current_affixes.get(affix_id), candidate_affixes.get(affix_id)
        delta = None
        if before is None:
            status = "added"
        elif after is None:
            status = "removed"
        elif before["unit"] != after["unit"]:
            status = "unit_mismatch"
        else:
            delta = after["value"] - before["value"]
            status = "comparable" if number(delta) else "out_of_range"
            if status == "out_of_range":
                delta = None
        rows.append({
            "affix_id": affix_id,
            "current_value": before["value"] if before else None,
            "candidate_value": after["value"] if after else None,
            "current_unit": before["unit"] if before else None,
            "candidate_unit": after["unit"] if after else None,
            "delta": delta, "status": status,
            "input_evidence_ids": sorted({evidence_id for affix in (before, after) if affix
                                          for evidence_id in affix["evidence_ids"]}),
        })
    limitations = [
        "Raw item affix differences only; no whole-build, stacking, panel or DPS simulation.",
        "Affix identifiers and units must match exactly; missing affixes are not zero and units are not converted.",
        "Affix deltas do not establish an improvement or a validated retention or equipment recommendation.",
    ]
    if current is None:
        limitations.append("No item is confirmed for the candidate slot; only the candidate's listed affixes are shown.")

    def identity(item):
        name = item.get("name")
        return {"instance_id": item["instance_id"],
                "name": name if isinstance(name, str) else item["instance_id"]}

    return {"scope": "item_affixes_only", "current_item": identity(current) if current else None,
            "candidate_item": identity(candidate), "rows": rows, "limitations": limitations}

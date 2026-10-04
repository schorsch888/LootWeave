"""Conservative native OCR fields; original text and spans remain available."""
from __future__ import annotations
import math
import re

from contracts import number

FIELD_LABELS = {"level":"level","等级":"level","vitality":"vitality","活力":"vitality","armor":"armor","护甲":"armor"}
LABEL = r"(?:\bLevel\b|\bVitality\b|\bArmor\b|等[ \t]*级|活[ \t]*力|护[ \t]*甲)"
VALUE = r"[+\-−＋－一—–]?[ \t]*\d+(?:[ \t]*[.．,，][ \t]*\d+)?"
PATTERN = re.compile(r"(?P<label>"+LABEL+r")[ \t]*[:：.]?[ \t]*(?P<value>"+VALUE+r")[ \t]*(?P<unit>%|％|points|pts|点)?(?![\w.．,，·]|[ \t]*[\d.．,，·])",re.IGNORECASE)
NUMERIC = re.compile(r"(?<![\w.．,，·+\-−＋－一—–])(?P<value>(?:[+\-−＋－][ \t]*)?\d+(?:[ \t]*[.．][ \t]*\d+)?)(?![\w.．,，·+\-−＋－一—–]|[ \t]*[\d.．,，·])")
TRANSLATION = str.maketrans({"−":"-","＋":"+","－":"-","．":"."})

def numeric_value(raw):
    if any(character in raw for character in ",，一—–"):
        return None
    try:
        value = float(re.sub(r"[ \t]","",raw.translate(TRANSLATION)))
        return value if math.isfinite(value) else None
    except ValueError:
        return None

def parse_fields(text: str) -> list[dict]:
    result,seen = [],set()
    for match in PATTERN.finditer(text):
        field = FIELD_LABELS[re.sub(r"[ \t]","",match["label"]).lower()]
        raw = match["value"]
        value = numeric_value(raw)
        unit = "level" if field=="level" else "%" if match["unit"] in ("%","％") else "points" if match["unit"] else None
        result.append({"field":field,"raw_text":match.group(0),"raw_value":raw,"value":value,"unit":unit,
                       "span":[match.start(),match.end()],"ambiguous":value is None or unit is None or field in seen,
                       "requires_confirmation":True})
        seen.add(field)
    counts = {field: sum(row["field"] == field for row in result) for field in seen}
    for row in result:
        if counts[row["field"]] > 1:
            row["ambiguous"] = True
    return result

def line_bounds(line):
    words = line.get("words", [])
    if not isinstance(words, list) or not words or any(not isinstance(word, dict) for word in words):
        return None
    boxes = [word.get("bounds", {}) for word in words]
    if any(not isinstance(box, dict) or
           not all(number(box.get(key)) for key in ("x", "y", "width", "height")) or
           box["x"] < 0 or box["y"] < 0 or box["width"] <= 0 or box["height"] <= 0
           for box in boxes):
        return None
    return (min(box["x"] for box in boxes), min(box["y"] for box in boxes),
            max(box["x"]+box["width"] for box in boxes),
            max(box["y"]+box["height"] for box in boxes))


def same_row(left, right):
    return (min(left[3], right[3])-max(left[1], right[1])
            >= .6 * min(left[3]-left[1], right[3]-right[1]))


def right_only_level(primary, lines, candidate):
    if re.fullmatch(LABEL + r"[ \t]*[:：.]?[ \t]*", primary.get("text", ""), re.I) is None:
        return False
    if NUMERIC.fullmatch(candidate.get("text", "").strip(" \t:：")) is None:
        return False
    bounds, other = line_bounds(primary), line_bounds(candidate)
    if bounds is None or other is None or other[0] < bounds[2]:
        return False
    for line in lines:
        if line is primary:
            continue
        competing = line_bounds(line)
        if competing is None or same_row(bounds, competing):
            return False
    return True


def native_row_fields(text, lines, reference):
    """Associate only mutually unique label/value lines; preserve both raw spans."""
    mapped, cursor = [], 0
    for line in lines:
        raw = line.get("text", "")
        if not isinstance(raw, str):
            return []
        if not raw:
            continue
        start = text.find(raw, cursor)
        if start < 0:
            return []
        mapped.append((line, start))
        cursor = start + len(raw)
    labels, values, occurrences = [], [], {}
    value_pattern = r"[ \t]*" + VALUE + r"[ \t]*(?:%|％|points|pts|点)?[ \t]*"
    for line, start in mapped:
        raw = line["text"]
        matches = list(re.finditer(LABEL, raw, re.I))
        for match in matches:
            key = FIELD_LABELS[re.sub(r"[ \t]", "", match.group()).lower()]
            occurrences[key] = occurrences.get(key, 0) + 1
        bounds = line_bounds(line)
        if bounds is None:
            continue
        if (len(matches) == 1 and not raw[:matches[0].start()].strip()
            and not raw[matches[0].end():].strip(" \t:：.")):
            key = FIELD_LABELS[re.sub(r"[ \t]", "", matches[0].group()).lower()]
            labels.append((key, line, start, bounds))
        elif not matches and re.fullmatch(value_pattern, raw, re.I):
            values.append((line, start, bounds))

    def aligns(label, value):
        return value[0] >= label[2] and same_row(label, value)

    fields = []
    for key, label, label_start, bounds in labels:
        candidates = [value for value in values if aligns(bounds, value[2])]
        if occurrences[key] != 1 or len(candidates) != 1:
            continue
        value, value_start, value_bounds = candidates[0]
        if sum(aligns(other[3], value_bounds) for other in labels) != 1:
            continue
        if key == "level" and re.fullmatch(r"[ \t]*"+VALUE+r"[ \t]*", value["text"]) is None:
            continue
        competing = False
        for other_line, _ in mapped:
            if other_line is label or other_line is value:
                continue
            other_bounds = line_bounds(other_line)
            if other_bounds is None or same_row(bounds, other_bounds):
                competing = True
                break
        if competing:
            continue
        # The joined row is already populated, so this parser call cannot associate another row.
        joined = {"text": label["text"]+" "+value["text"], "words": label["words"]+value["words"]}
        associated = corroborate_fields(joined["text"], [joined], reference)
        if len(associated) != 1:
            continue
        field = associated[0]
        field["raw_text"] = value["text"]
        field["span"] = [value_start, value_start+len(value["text"])]
        field["label_source"] = {"raw_text": label["text"],
                                 "span": [label_start, label_start+len(label["text"])],
                                 "bounds": bounds, "method": "native_row_geometry"}
        field["bounds"] = value_bounds
        fields.append(field)
    return fields


def corroborate_fields(text, lines, reference):
    """Bind fields to native lines before pairing an English numeric line.

    Reference numbers never establish field identity. Conflicts remain ambiguous;
    unresolved Chinese dash glyphs are not guessed to mean minus.
    """
    fields, cursor = [], 0
    for line in lines:
        raw = line.get("text", "")
        if not isinstance(raw, str) or not raw:
            continue
        start = text.find(raw, cursor)
        if start < 0:
            continue
        for field in parse_fields(raw):
            field["span"] = [start + offset for offset in field["span"]]
            fields.append(field)
        cursor = start + len(raw)
    fields.extend(native_row_fields(text, lines, reference))
    seen = {field["field"] for field in fields}
    counts = {key: sum(row["field"] == key for row in fields) for key in seen}
    for field in fields:
        if counts[field["field"]] > 1:
            field["ambiguous"] = True
    if not isinstance(reference,dict) or reference.get("language") != "en-US":
        return fields
    def identities(line):
        return [FIELD_LABELS[match.group(0).replace(" ", "").replace("\t", "").lower()]
                for match in re.finditer(LABEL, line.get("text", ""), re.IGNORECASE)]
    # A known label and explicit unit may survive an unreadable numeric token.
    # Keep that original span, then offer the independent observed number for review.
    for line in lines:
        labels = identities(line)
        if len(labels) != 1 or any(field["field"] == labels[0] for field in fields):
            continue
        raw = line.get("text", "")
        start = text.find(raw)
        if start < 0:
            continue
        label = re.search(LABEL, raw, re.IGNORECASE)
        suffix = raw[label.end():].strip(" :：")
        unit_match = re.search(r"(%|％|points|pts|点)[ \t]*$", suffix, re.IGNORECASE)
        unit = "level" if labels[0] == "level" else (
            "%" if unit_match and unit_match.group(1) in ("%", "％") else "points" if unit_match else None)
        raw_value = suffix[:unit_match.start()].strip() if unit_match else suffix
        fields.append({"field": labels[0], "raw_text": raw, "raw_value": raw_value,
                       "value": None, "unit": unit, "span": [start, start + len(raw)],
                       "ambiguous": True, "requires_confirmation": True})
    for field in fields:
        if field.get("label_source"):
            continue  # This unique native row has already passed numeric corroboration.
        matches = [line for line in lines if identities(line) == [field["field"]]]
        if len(matches)!=1:
            continue
        primary = matches[0]
        if sum(candidate["field"] == field["field"] for candidate in fields) != 1:
            continue
        bounds = line_bounds(primary)
        if bounds is None:
            continue
        candidates = []
        for line in reference.get("lines",[]):
            other = line_bounds(line)
            if other is None:
                continue
            intersection = min(bounds[3],other[3])-max(bounds[1],other[1])
            horizontal = min(bounds[2], other[2]) - max(bounds[0], other[0])
            if (intersection >= .6*min(bounds[3]-bounds[1],other[3]-other[1]) and (
                (horizontal > 0 and bounds[0]-8 <= (other[0]+other[2])/2 <= bounds[2]+8)
                or (field["field"] == "level" and not field["raw_value"]
                    and right_only_level(primary, lines, line)))):
                candidates.append(line)
        if len(candidates)!=1:
            continue
        candidate = candidates[0]
        numbers = list(NUMERIC.finditer(candidate.get("text","")))
        if len(numbers)!=1:
            alternatives = [numeric_value(match["value"]) for match in numbers]
            if (field["value"] is not None and alternatives
                and all(value is not None and value != field["value"] for value in alternatives)):
                field["ambiguous"] = True
            continue
        raw = numbers[0]["value"]
        value = numeric_value(raw)
        if value is None or field["unit"] is None:
            continue
        primary_sign = field["raw_value"].strip().translate(TRANSLATION)[:1]
        reference_sign = raw.strip().translate(TRANSLATION)[:1]
        if (primary_sign in ("+", "-") and (
            reference_sign in ("+", "-") and primary_sign != reference_sign
            or primary_sign == "-" and reference_sign not in ("+", "-"))):
            field["ambiguous"] = True
            field["conflict"] = "numeric_readers_disagree"
            continue
        # If both numeric readings are available they must agree. An unreadable token
        # retains its original text alongside the independent reference, for confirmation.
        primary_magnitude = numeric_value(field["raw_value"].lstrip("一—–").strip())
        if primary_magnitude is not None and abs(primary_magnitude)!=abs(value):
            field["ambiguous"] = True
            field["conflict"] = "numeric_readers_disagree"
            continue
        if field["value"] is not None and field["value"] != value:
            field["ambiguous"] = True
            field["conflict"] = "numeric_readers_disagree"
            continue
        if (field["value"] is None and field["field"] != "level"
            and not raw.strip().startswith(("+","-","−","＋","－"))):
            continue
        if field["ambiguous"] and field["value"] is not None:
            continue  # Duplicates and missing units cannot be resolved by a numeric reader.
        recovered = field["value"] is None
        field["value"] = value
        field["ambiguous"] = False
        field["numeric_source" if recovered else "numeric_corroboration"] = {
            "language":"en-US","raw_value":raw,"raw_line":candidate["text"],"bounds":line_bounds(candidate)}
    return fields


def numeric_region_plan(text, lines, reference, width, height):
    """Select bounded numeric words from unique, mapped primary rows."""
    if (type(width) is not int or type(height) is not int
        or not 0 < width <= 1600 or not 0 < height <= 1200):
        return []
    baseline = corroborate_fields(text, lines, reference or {"language": "en-US", "lines": []})
    occurrences = {}
    for match in re.finditer(LABEL, text, re.I):
        key = FIELD_LABELS[re.sub(r"[ \t]", "", match.group()).lower()]
        occurrences[key] = occurrences.get(key, 0) + 1
    plans, cursor = [], 0
    for line in lines:
        raw, words = line.get("text", ""), line.get("words", [])
        if not isinstance(raw, str) or not raw or not isinstance(words, list):
            continue
        start = text.find(raw, cursor)
        if start < 0:
            return []
        cursor = start + len(raw)
        full = line_bounds(line)
        if full is None or full[2] > width or full[3] > height:
            continue
        if any(not isinstance(word.get("text"), str) or not word["text"] for word in words):
            continue
        if " ".join(word["text"] for word in words) != raw:
            continue
        labels = list(re.finditer(LABEL, raw, re.I))
        if len(labels) != 1 or raw[:labels[0].start()].strip():
            continue
        label = labels[0]
        key = FIELD_LABELS[re.sub(r"[ \t]", "", label.group()).lower()]
        fields = [field for field in baseline if field["field"] == key]
        if (occurrences.get(key) != 1 or len(fields) != 1 or not fields[0]["ambiguous"]
            or fields[0]["unit"] is None or fields[0].get("conflict")):
            continue
        if any(other is not line and
               (line_bounds(other) is None or same_row(full, line_bounds(other))) for other in lines):
            continue
        suffix = re.match(r"[ \t]*[:：.]?[ \t]*", raw[label.end():])
        value_start = label.end() + suffix.end()
        unit = re.search(r"(%|％|points|pts|点)[ \t]*$", raw, re.I)
        value_end = unit.start() if unit else len(raw)
        if key != "level" and unit is None:
            continue
        numeric, prefix, ending, position = [], [], [], 0
        for word in words:
            stop = position + len(word["text"])
            if stop <= value_start:
                prefix.append(word)
            elif position >= value_end:
                ending.append(word)
            else:
                numeric.append(word)
            position = stop + 1
        if not numeric or not prefix:
            continue
        bounds, label_bounds = line_bounds({"words": numeric}), line_bounds({"words": prefix})
        unit_bounds = line_bounds({"words": ending}) if ending else None
        if bounds is None or label_bounds is None or bounds[0] <= label_bounds[2]:
            continue
        if unit_bounds is not None and bounds[2] >= unit_bounds[0]:
            continue
        left = max(0, math.floor(bounds[0])-2, math.ceil(label_bounds[2])+1)
        right = min(width, math.ceil(bounds[2])+2,
                    math.floor(unit_bounds[0])-1 if unit_bounds else width)
        top, bottom = max(0, math.floor(full[1])-4), min(height, math.ceil(full[3])+4)
        if left >= right or top >= bottom:
            continue
        plans.append({"field": key, "bounds": {"x": left, "y": top, "width": right-left, "height": bottom-top},
                      "source_span": fields[0]["span"]})
    return plans[:3]


def recover_numeric_regions(text, lines, reference, plans, regions):
    """Recover unreadable numbers or corroborate primary values without replacing them."""
    fields = corroborate_fields(text, lines, reference or {"language": "en-US", "lines": []})
    for field in fields:
        if not field["ambiguous"] or field["unit"] is None or field.get("conflict"):
            continue
        if sum(other["field"] == field["field"] for other in fields) != 1:
            continue
        selected = [plan for plan in plans if plan["field"] == field["field"]
                    and plan["source_span"] == field["span"]]
        matched = [region for region in regions if isinstance(region, dict)
                   and region.get("field") == field["field"]]
        if len(selected) != 1:
            continue
        readable = field["value"] is not None
        if readable:
            field["ambiguous"] = True  # A required independent read has not yet succeeded.
        if len(matched) != 1:
            continue
        plan, region = selected[0], matched[0]
        if (region.get("language") != "en-US" or region.get("bounds") != plan["bounds"]
            or not isinstance(region.get("bounds"), dict)
            or any(type(region["bounds"].get(axis)) is not int for axis in ("x","y","width","height"))
            or region.get("error") or not isinstance(region.get("text"), str)
            or not isinstance(region.get("lines"), list)):
            continue
        frame = plan["bounds"]
        valid = True
        for line in region["lines"]:
            bounds = line_bounds(line) if isinstance(line, dict) else None
            if (bounds is None or bounds[0] < frame["x"] or bounds[1] < frame["y"]
                or bounds[2] > frame["x"]+frame["width"]
                or bounds[3] > frame["y"]+frame["height"]):
                valid = False
                break
        if not valid:
            continue
        candidates = corroborate_fields(text, lines, {"language": "en-US", "lines": region["lines"]})
        candidates = [candidate for candidate in candidates if candidate["field"] == field["field"]
                      and candidate["span"] == field["span"] and candidate["unit"] == field["unit"]]
        if len(candidates) != 1:
            continue
        candidate = candidates[0]
        if readable and candidate.get("conflict") == "numeric_readers_disagree":
            field["conflict"] = candidate["conflict"]
            continue
        evidence = "numeric_corroboration" if readable else "numeric_source"
        if candidate["ambiguous"] or candidate.get("conflict") or evidence not in candidate:
            continue
        original = numeric_value(field["raw_value"])
        if original is not None and original != candidate["value"]:
            continue
        field.update(candidate)
        field[evidence] = {**field[evidence], "method": "native_numeric_region", "region_bounds": frame}
    return fields

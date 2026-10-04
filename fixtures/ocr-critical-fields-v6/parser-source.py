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
            continue
        raw = numbers[0]["value"]
        value = numeric_value(raw)
        if value is None or field["unit"] is None:
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

"""Audit the archived synthetic OCR evidence; passing does not accept M2."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import re
import statistics
import struct
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from contracts import DomainError, digest, number, parse_json

FIXTURE = ROOT / "fixtures" / "ocr-critical-fields-v6"
GENERATOR = ROOT / "fixtures" / "ocr-v6-generator.py"
VERSION = "synthetic-critical-fields-v6"
SIGN_TRANSLATION = str.maketrans({"−": "-", "－": "-", "＋": "+"})


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def summarize(rows):
    fields = [field for row in rows for field in row["fields"]]
    correct = sum(field["correct"] for field in fields)
    rejected = sum(field["rejected"] for field in fields)
    unflagged = sum(field["unflagged_error"] for field in fields)
    return {"regions": len(rows), "critical_fields": len(fields),
            "correct_fields": correct, "accuracy": correct / len(fields),
            "rejected_or_missing_fields": rejected, "rejection_rate": rejected / len(fields),
            "unflagged_errors": unflagged, "unflagged_error_rate": unflagged / len(fields)}


def score(expected, observed, error):
    rows = []
    for truth in expected:
        matches = [field for field in observed if field["field"] == truth["field"]]
        field = matches[0] if len(matches) == 1 else None
        rejected = bool(error) or field is None or field["ambiguous"]
        raw = (field.get("numeric_source", {}).get("raw_value", field["raw_value"])
               if field else "").strip().translate(SIGN_TRANSLATION)
        correct = bool(not rejected and field["value"] == truth["value"]
                       and field["unit"] == truth["unit"]
                       and (not truth["sign"] or raw.startswith(truth["sign"])))
        rows.append({"field": truth["field"], "correct": correct,
                     "rejected": bool(rejected), "unflagged_error": not correct and not rejected})
    return rows


def audit_records(manifest, observations, report, version=VERSION):
    """Rescore every labeled field and check the saved dimensional/latency totals."""
    samples = manifest["samples"]
    require(manifest["dataset_version"] == report["dataset_version"] == version, "dataset_version")
    require(manifest["partition"] == report["partition"] == "holdout", "dataset_partition")
    require(len(samples) == len(observations) == 200, "region_denominator")
    require(manifest["truth_hash"] == report["truth_hash"] == digest(samples), "truth_hash")
    require(report["generator_sha256"] == manifest["generator_sha256"], "generator_identity")
    require(len({sample["id"] for sample in samples}) == 200, "duplicate_region_id")
    require(len({sample["image_sha256"] for sample in samples}) == 200, "duplicate_image")
    strata = Counter((sample["language"], sample["scale"], sample["quality"]) for sample in samples)
    expected_strata = {(language, scale, quality): 5
                       for language in ("en-US", "zh-Hans-CN")
                       for scale in (.75, 1., 1.25, 1.5, 2.)
                       for quality in ("clean", "low_contrast", "blurred", "downsampled")}
    require(dict(strata) == expected_strata, "sample_coverage")
    for sample, observed in zip(samples, observations):
        require(re.fullmatch(r"region-[0-9]{3}", sample["id"]) is not None, "region_identifier")
        require(sample["image"] == "images/" + sample["id"] + ".bmp", "image_path")
        require(observed["id"] == sample["id"], "observation_identity")
        for dimension in ("language", "scale", "quality"):
            require(observed[dimension] == sample[dimension], "observation_scope")
        truth = sample["expected"]
        require([field["field"] for field in truth] == ["level", "vitality", "armor"], "field_denominator")
        require([field["unit"] for field in truth] == ["level", "points", "%"], "truth_units")
        require(all(number(field["value"]) for field in truth), "truth_numbers")
        require(truth[0]["sign"] == "" and all(
            field["sign"] == ("+" if field["value"] > 0 else "-") for field in truth[1:]), "truth_signs")
        labels = ("Level", "Vitality", "Armor") if sample["language"] == "en-US" else ("等级", "活力", "护甲")
        colon, unit = (":", "points") if sample["language"] == "en-US" else ("：", "点")
        rendered = (f"{labels[0]}{colon} {truth[0]['value']}\n"
                    f"{labels[1]}{colon} {truth[1]['value']:+d} {unit}\n"
                    f"{labels[2]}{colon} {truth[2]['value']:+.1f}%")
        require(sample["text"] == rendered, "renderer_truth")
        require(sample["width"] == round(490 * sample["scale"])
                and sample["height"] == round(162 * sample["scale"]), "render_dimensions")
        require(number(observed["elapsed_seconds"]) and observed["elapsed_seconds"] > 0, "elapsed_time")
        raw = observed["raw_text"]
        require(isinstance(raw, str), "original_text")
        for field in observed["observed_fields"]:
            require(type(field["ambiguous"]) is bool and field["requires_confirmation"] is True,
                    "observation_confirmation")
            for source in (field, field.get("label_source")):
                if source is None:
                    continue
                span = source["span"]
                require(len(span) == 2 and all(type(value) is int for value in span)
                        and 0 <= span[0] < span[1] <= len(raw), "source_span")
                require(raw[span[0]:span[1]] == source["raw_text"], "source_mapping")
        if version == "synthetic-critical-fields-v7":
            require(observed["state"] == "unconfirmed" and observed["requires_confirmation"] is True,
                    "observation_state")
            require(observed["image_hash"] == sample["image_sha256"] and observed["bounds"] == {
                "x": 0, "y": 0, "width": sample["width"], "height": sample["height"]}, "observation_image")
            regions = observed["numeric_regions"]
            require(isinstance(regions, list) and len(regions) <= 3
                    and all(isinstance(region, dict) for region in regions), "numeric_region_set")
            require(len({region["field"] for region in regions}) == len(regions), "numeric_region_duplicate")
            require(observed["numeric_region_error"] in (None, "ocr_failed", "ocr_timeout"), "numeric_region_error")
        require(observed["fields"] == score(truth, observed["observed_fields"], observed["error"]),
                "critical_field_scoring")
    if version == "synthetic-critical-fields-v7":
        require(report["numeric_regions"] == {
            "observations_with_regions": sum(bool(row["numeric_regions"]) for row in observations),
            "regions_received": sum(len(row["numeric_regions"]) for row in observations),
            "optional_read_errors": sum(bool(row["numeric_region_error"]) for row in observations)}, "numeric_region_totals")
    require(report["overall"] == summarize(observations), "overall_totals")
    for dimension in ("language", "scale", "quality"):
        groups = defaultdict(list)
        for observed in observations:
            groups[str(observed[dimension])].append(observed)
        actual = {name: summarize(rows) for name, rows in groups.items()}
        require(report["by_dimension"][dimension] == actual, "dimension_totals")
    elapsed = [row["elapsed_seconds"] for row in observations]
    latency = report["latency"]
    require(latency["requests"] == 200, "latency_denominator")
    require(latency["p50_seconds"] == statistics.median(elapsed), "latency_p50")
    require(latency["p95_seconds"] == sorted(elapsed)[math.ceil(.95 * len(elapsed)) - 1], "latency_p95")
    require(number(latency["total_seconds"]) and latency["total_seconds"] >= sum(elapsed), "latency_total")
    require(report["targets"] == {"all_critical_field_accuracy": .95, "ocr_p95_seconds": 3.},
            "acceptance_targets")
    target_pass = report["overall"]["accuracy"] >= .95 and latency["p95_seconds"] <= 3.
    require(report["measured_target_pass"] is target_pass, "measured_target_verdict")
    return {"evidence_integrity_passed": True, **report["overall"],
            "measured_target_pass": target_pass, "m2_accepted": False}


def verify_images(samples, directory):
    directory = Path(directory).resolve(strict=True)
    require(directory.is_dir(), "image_directory")
    for sample in samples:
        image = directory / (sample["id"] + ".bmp")
        require(not image.is_symlink() and image.is_file()
                and image.resolve().parent == directory, "image_location")
        require(image.stat().st_size <= 12 * 1024 * 1024, "image_size")
        raw = image.read_bytes()
        require(hashlib.sha256(raw).hexdigest() == sample["image_sha256"], "image_hash")
        require(len(raw) >= 54 and raw[:2] == b"BM", "bmp_header")
        require(struct.unpack_from("<ii", raw, 18) == (sample["width"], sample["height"]),
                "bmp_dimensions")


def replay_records(manifest, observations, report, module, version):
    """Replay original geometry and crops; no native OCR or adapter inference."""
    crops = 0
    for sample, row in zip(manifest["samples"], observations, strict=True):
        if version == "v6":
            replayed = module.corroborate_fields(row["raw_text"], row["lines"], row["numeric_reference"])
        else:
            plans = (module.numeric_region_plan(row["raw_text"], row["lines"], row["numeric_reference"],
                                               sample["width"], sample["height"])
                     if "en-US" in report["environment"]["ocr_languages"] else [])
            regions = row["numeric_regions"]
            if row["numeric_region_error"]:
                require(not regions and bool(plans), "numeric_region_failed_read")
            else:
                require(len(regions) == len(plans), "numeric_region_denominator")
            for region in regions:
                matches = [plan for plan in plans if plan["field"] == region["field"]]
                require(len(matches) == 1 and region["bounds"] == matches[0]["bounds"], "numeric_region_mapping")
                frame = region["bounds"]
                require(all(type(frame[axis]) is int for axis in ("x", "y", "width", "height")),
                        "numeric_region_bounds")
                require(region["language"] == "en-US" and isinstance(region["text"], str)
                        and len(region["text"]) <= 65536 and isinstance(region["lines"], list), "numeric_region_reading")
                cursor = 0
                for line in region["lines"]:
                    require(isinstance(line, dict) and isinstance(line.get("text"), str), "numeric_region_line")
                    bounds = module.line_bounds(line)
                    require(bounds is not None and bounds[0] >= frame["x"] and bounds[1] >= frame["y"]
                            and bounds[2] <= frame["x"] + frame["width"]
                            and bounds[3] <= frame["y"] + frame["height"], "numeric_region_word_bounds")
                    require(all(isinstance(word.get("text"), str) and word["text"] for word in line["words"]),
                            "numeric_region_word_text")
                    require(" ".join(word["text"] for word in line["words"]) == line["text"], "numeric_region_word_mapping")
                    start = region["text"].find(line["text"], cursor)
                    require(start >= 0, "numeric_region_original_text")
                    cursor = start + len(line["text"])
                crops += 1
            replayed = (module.recover_numeric_regions(row["raw_text"], row["lines"], row["numeric_reference"], plans, regions)
                        if plans else module.corroborate_fields(row["raw_text"], row["lines"], row["numeric_reference"]))
        require(digest(replayed) == digest(row["observed_fields"]), "frozen_parser_replay")
    return {"frozen_parser_replays": len(observations), "numeric_regions_verified": crops}


def validate(images=None, version="v6"):
    require(version in ("v6", "v7"), "fixture_version")
    fixture = FIXTURE if version == "v6" else ROOT / "fixtures/ocr-critical-fields-v7"
    generator = GENERATOR if version == "v6" else ROOT / "fixtures/ocr-v7-generator.py"
    provenance = parse_json((fixture / "provenance.json").read_bytes())
    require(provenance["examined_after_measurement"] is True
            and provenance["independent_human_truth_review"] == "pending", "evidence_limitations")
    filenames = {"manifest.json", "observations.json", "report.json", "parser-source.py"}
    require(set(provenance["files_sha256"]) == filenames, "artifact_set")
    for name, expected in provenance["files_sha256"].items():
        path = fixture / name
        require(not path.is_symlink() and path.is_file(), "artifact_location")
        require(hashlib.sha256(path.read_bytes()).hexdigest() == expected, "artifact_hash")
    require(hashlib.sha256(generator.read_bytes()).hexdigest() == provenance["generator_sha256"],
            "frozen_generator_hash")
    manifest = parse_json((fixture / "manifest.json").read_bytes())
    observations = parse_json((fixture / "observations.json").read_bytes())
    report = parse_json((fixture / "report.json").read_bytes())
    require(manifest["generator_sha256"] == provenance["generator_sha256"], "manifest_generator")
    require(report["adapter_sha256"]["services/ocr/domain.py"]
            == provenance["files_sha256"]["parser-source.py"], "frozen_parser_hash")
    summary = audit_records(manifest, observations, report, "synthetic-critical-fields-" + version)
    spec = importlib.util.spec_from_file_location("ocr_" + version + "_frozen_parser", fixture / "parser-source.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    summary.update(replay_records(manifest, observations, report, module, version))
    if images is not None:
        verify_images(manifest["samples"], images)
    summary["images_verified"] = 200 if images is not None else 0
    summary["independent_human_truth_review"] = "pending"
    summary["future_tuning_requires_fresh_holdout"] = True
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--images", type=Path, help="Directory of reproduced region-000.bmp through region-199.bmp.")
    parser.add_argument("--version", choices=("v6", "v7"), default="v6", help="Archived dataset version; original v6 remains the default.")
    args = parser.parse_args()
    try:
        print(json.dumps(validate(args.images, args.version), ensure_ascii=False, indent=2))
    except (DomainError, ValueError, KeyError, TypeError, OSError, IndexError) as error:
        code = error.code if isinstance(error, DomainError) else str(error) if isinstance(error, ValueError) else type(error).__name__
        print(json.dumps({"evidence_integrity_passed": False, "reason": code}))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

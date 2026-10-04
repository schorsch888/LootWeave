"""Mutation checks for the complete archived OCR denominator and evidence."""
from __future__ import annotations

from copy import deepcopy
import json
import importlib.util
from pathlib import Path
import tempfile
import unittest

from contracts import digest
from scripts.validate_ocr_holdout import FIXTURE, audit_records, replay_records, score, validate, verify_images


class OCRHoldoutEvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = json.loads((FIXTURE / "manifest.json").read_text(encoding="utf-8"))
        cls.observations = json.loads((FIXTURE / "observations.json").read_text(encoding="utf-8"))
        cls.report = json.loads((FIXTURE / "report.json").read_text(encoding="utf-8"))

    def test_original_evidence_replays_all_regions_without_accepting_failed_accuracy(self):
        result = validate()
        self.assertEqual((result["regions"], result["critical_fields"], result["correct_fields"]), (200, 600, 550))
        self.assertEqual(result["frozen_parser_replays"], 200)
        self.assertEqual(result["rejected_or_missing_fields"], 50)
        self.assertEqual(result["unflagged_errors"], 0)
        self.assertFalse(result["measured_target_pass"])
        self.assertFalse(result["m2_accepted"])
        self.assertEqual(result["images_verified"], 0)

    def test_missing_observation_cannot_shrink_the_denominator(self):
        with self.assertRaisesRegex(ValueError, "region_denominator"):
            audit_records(self.manifest, self.observations[:-1], self.report)

    def test_duplicate_region_or_image_cannot_supply_holdout_coverage(self):
        for key in ("id", "image_sha256"):
            manifest, report = deepcopy(self.manifest), deepcopy(self.report)
            manifest["samples"][1][key] = manifest["samples"][0][key]
            manifest["truth_hash"] = report["truth_hash"] = digest(manifest["samples"])
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, "duplicate_"):
                audit_records(manifest, self.observations, report)

    def test_version_scope_and_renderer_truth_are_verified(self):
        cases = (("language", "de-DE", "sample_coverage"),
                 ("image", "../region-000.bmp", "image_path"),
                 ("text", "Level: 1", "renderer_truth"))
        for key, changed, reason in cases:
            manifest, report = deepcopy(self.manifest), deepcopy(self.report)
            manifest["samples"][0][key] = changed
            manifest["truth_hash"] = report["truth_hash"] = digest(manifest["samples"])
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, reason):
                audit_records(manifest, self.observations, report)

    def test_promoting_a_rejected_field_is_detected_by_full_rescoring(self):
        observations = deepcopy(self.observations)
        rejected = next(field for row in observations for field in row["fields"] if field["rejected"])
        rejected.update(correct=True, rejected=False, unflagged_error=False)
        with self.assertRaisesRegex(ValueError, "critical_field_scoring"):
            audit_records(self.manifest, observations, self.report)

    def test_value_equality_cannot_hide_a_missing_sign_or_wrong_unit(self):
        truth = [{"field": "armor", "value": -12, "unit": "%", "sign": "-"}]
        field = {"field": "armor", "value": -12, "unit": "%", "raw_value": "12", "ambiguous": False}
        self.assertEqual(score(truth, [field], None), [{"field": "armor", "correct": False, "rejected": False, "unflagged_error": True}])
        field.update(raw_value="-12", unit="points")
        self.assertFalse(score(truth, [field], None)[0]["correct"])
        field["unit"] = "%"
        self.assertTrue(score(truth, [field], None)[0]["correct"])
        self.assertTrue(score(truth, [field, field], None)[0]["rejected"])

    def test_source_mapping_and_confirmation_cannot_be_removed(self):
        for changed, reason in (({"span": [0, 99999]}, "source_span"),
                                ({"raw_text": "changed"}, "source_mapping"),
                                ({"requires_confirmation": False}, "observation_confirmation")):
            observations = deepcopy(self.observations)
            observations[0]["observed_fields"][0].update(changed)
            with self.subTest(changed=changed), self.assertRaisesRegex(ValueError, reason):
                audit_records(self.manifest, observations, self.report)

    def test_favorable_totals_and_latency_percentiles_cannot_replace_recorded_results(self):
        mutations = (("overall", "correct_fields", 600, "overall_totals"),
                     ("latency", "p95_seconds", .1, "latency_p95"),
                     ("targets", "all_critical_field_accuracy", .90, "acceptance_targets"))
        for group, key, changed, reason in mutations:
            report = deepcopy(self.report)
            report[group][key] = changed
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, reason):
                audit_records(self.manifest, self.observations, report)
        report = deepcopy(self.report)
        report["by_dimension"]["language"]["zh-Hans-CN"]["correct_fields"] = 300
        with self.assertRaisesRegex(ValueError, "dimension_totals"):
            audit_records(self.manifest, self.observations, report)

    def test_reconstructed_image_bytes_are_required_when_images_are_requested(self):
        with tempfile.TemporaryDirectory(prefix="lootweave-ocr-evidence-") as temporary:
            image = Path(temporary) / "region-000.bmp"
            image.write_bytes(b"BM" + bytes(52))
            with self.assertRaisesRegex(ValueError, "image_hash"):
                verify_images(self.manifest["samples"][:1], Path(temporary))



class OCRNumericHoldoutEvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixture = FIXTURE.parent / "ocr-critical-fields-v7"
        cls.manifest = json.loads((fixture / "manifest.json").read_text(encoding="utf-8"))
        cls.observations = json.loads((fixture / "observations.json").read_text(encoding="utf-8"))
        cls.report = json.loads((fixture / "report.json").read_text(encoding="utf-8"))
        spec = importlib.util.spec_from_file_location("ocr_v7_evidence_tests", fixture / "parser-source.py")
        cls.parser = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.parser)
        cls.crop_index = next(index for index, row in enumerate(cls.observations)
                              if 0 < len(row["numeric_regions"]) < 3
                              and row["numeric_regions"][0]["lines"]
                              and row["numeric_regions"][0]["lines"][0]["words"])

    def audit(self, observations=None, report=None):
        return audit_records(self.manifest,
                             self.observations if observations is None else observations,
                             self.report if report is None else report,
                             version="synthetic-critical-fields-v7")

    def replay(self, observations):
        return replay_records(self.manifest, observations, self.report, self.parser, "v7")

    def test_complete_numeric_evidence_passes_targets_without_accepting_m2(self):
        result = validate(version="v7")
        self.assertEqual((result["regions"], result["critical_fields"], result["correct_fields"]), (200, 600, 572))
        self.assertEqual((result["frozen_parser_replays"], result["numeric_regions_verified"]), (200, 30))
        self.assertEqual((result["rejected_or_missing_fields"], result["unflagged_errors"]), (28, 0))
        self.assertTrue(result["measured_target_pass"])
        self.assertFalse(result["m2_accepted"])
        self.assertEqual(result["independent_human_truth_review"], "pending")

    def test_image_identity_geometry_and_unconfirmed_state_are_required(self):
        changes = (("state", "confirmed", "observation_state"),
                   ("requires_confirmation", False, "observation_state"),
                   ("image_hash", "0" * 64, "observation_image"),
                   ("bounds", {"x": 1, "y": 0, "width": 490, "height": 162}, "observation_image"))
        for key, value, reason in changes:
            rows = deepcopy(self.observations)
            rows[0][key] = value
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, reason):
                self.audit(rows)

    def test_missing_duplicate_or_invented_failed_crops_are_detected(self):
        rows = deepcopy(self.observations)
        rows[self.crop_index]["numeric_regions"].pop()
        with self.assertRaisesRegex(ValueError, "numeric_region_denominator"):
            self.replay(rows)
        rows = deepcopy(self.observations)
        rows[self.crop_index]["numeric_regions"].append(deepcopy(rows[self.crop_index]["numeric_regions"][0]))
        with self.assertRaisesRegex(ValueError, "numeric_region_duplicate"):
            self.audit(rows)
        rows = deepcopy(self.observations)
        next(row for row in rows if not row["numeric_regions"])["numeric_region_error"] = "ocr_failed"
        with self.assertRaisesRegex(ValueError, "numeric_region_failed_read"):
            self.replay(rows)

    def test_numeric_crop_scope_and_original_pixel_bounds_are_required(self):
        for change, reason in (("field", "numeric_region_mapping"),
                               ("bounds", "numeric_region_mapping"),
                               ("language", "numeric_region_reading"),
                               ("word_bounds", "numeric_region_word_bounds")):
            rows = deepcopy(self.observations)
            crop = rows[self.crop_index]["numeric_regions"][0]
            if change == "field":
                crop["field"] = "unknown"
            elif change == "bounds":
                crop["bounds"]["width"] += 1
            elif change == "language":
                crop["language"] = "zh-Hans-CN"
            else:
                crop["lines"][0]["words"][0]["bounds"]["x"] = crop["bounds"]["x"] - 1
            with self.subTest(change=change), self.assertRaisesRegex(ValueError, reason):
                self.replay(rows)

    def test_numeric_text_must_map_to_original_native_words(self):
        for change, reason in (("word", "numeric_region_word_mapping"),
                               ("text", "numeric_region_original_text")):
            rows = deepcopy(self.observations)
            crop = rows[self.crop_index]["numeric_regions"][0]
            if change == "word":
                crop["lines"][0]["words"][0]["text"] = "altered"
            else:
                crop["text"] = "altered"
            with self.subTest(change=change), self.assertRaisesRegex(ValueError, reason):
                self.replay(rows)

    def test_crop_counts_chinese_totals_and_rejections_cannot_be_promoted(self):
        report = deepcopy(self.report)
        report["numeric_regions"]["regions_received"] = 0
        with self.assertRaisesRegex(ValueError, "numeric_region_totals"):
            self.audit(report=report)
        report = deepcopy(self.report)
        report["by_dimension"]["language"]["zh-Hans-CN"]["correct_fields"] = 300
        with self.assertRaisesRegex(ValueError, "dimension_totals"):
            self.audit(report=report)
        rows = deepcopy(self.observations)
        next(field for row in rows for field in row["fields"] if field["rejected"]).update(
            correct=True, rejected=False, unflagged_error=False)
        with self.assertRaisesRegex(ValueError, "critical_field_scoring"):
            self.audit(rows)
        with self.assertRaisesRegex(ValueError, "region_denominator"):
            self.audit(self.observations[:-1])

    def test_saved_numeric_result_must_match_the_frozen_parser(self):
        rows = deepcopy(self.observations)
        field = rows[self.crop_index]["observed_fields"][0]
        field["value"] = 999999
        with self.assertRaisesRegex(ValueError, "frozen_parser_replay"):
            self.replay(rows)


if __name__ == "__main__":
    unittest.main()

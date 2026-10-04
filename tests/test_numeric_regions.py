"""Numeric-region OCR must preserve primary evidence and fail optional reads safely."""
from __future__ import annotations

import base64
from copy import deepcopy
import json
import os
from pathlib import Path
import struct
import subprocess
import tempfile
import threading
import unittest
from unittest.mock import patch

from services.ocr.app import OCR
from services.ocr.domain import corroborate_fields, numeric_region_plan, recover_numeric_regions


def primary(value="一 140", unit="点", label="活力："):
    tokens = [label, *value.split(), unit] if unit else [label, *value.split()]
    x, words = 10, []
    for index, token in enumerate(tokens):
        if index == 1:
            x = 60
        width = max(8, len(token) * 9)
        words.append({"text": token, "bounds": {"x": x, "y": 20, "width": width, "height": 20}})
        x += width + 5
    text = " ".join(tokens)
    return text, [{"text": text, "words": words}]


def regional(plan, value="-140"):
    box = plan["bounds"]
    return {"field": plan["field"], "bounds": dict(box), "language": "en-US", "text": value,
            "lines": [{"text": value, "words": [{"text": value, "bounds": {
                "x": box["x"]+2, "y": box["y"]+4, "width": min(30, box["width"]-4), "height": 20}}]}]}


def bmp(width=240, height=80):
    pixels = bytes(((width*24+31)//32)*4*height)
    return struct.pack("<2sIHHI", b"BM", 54+len(pixels), 0, 0, 54) + struct.pack(
        "<IiiHHIIIIII", 40, width, height, 1, 24, 0, len(pixels), 0, 0, 0, 0) + pixels


class NumericRegionDomainTests(unittest.TestCase):
    def test_unique_unreadable_row_has_one_bounded_crop_and_keeps_original_span(self):
        text, lines = primary()
        plans = numeric_region_plan(text, lines, None, 240, 80)
        self.assertEqual(len(plans), 1)
        self.assertEqual(plans[0]["field"], "vitality")
        self.assertEqual(plans[0]["source_span"], [0, len(text)])
        box = plans[0]["bounds"]
        self.assertGreater(box["x"], 50)
        self.assertLess(box["x"]+box["width"], lines[0]["words"][-1]["bounds"]["x"])
        [field] = recover_numeric_regions(text, lines, None, plans, [regional(plans[0])])
        self.assertEqual((field["value"], field["unit"]), (-140, "points"))
        self.assertEqual(text[slice(*field["span"])], field["raw_text"])
        self.assertEqual(field["raw_value"], "一 140")
        self.assertEqual(field["numeric_source"]["method"], "native_numeric_region")
        self.assertTrue(field["requires_confirmation"])

    def test_readable_without_reference_missing_units_unknown_labels_and_duplicates_skip_crops(self):
        for value, unit, label in (("+140", "点", "活力："), ("一 140", "", "活力："),
                                   ("一 140", "点", "Mystery:")):
            text, lines = primary(value, unit, label)
            with self.subTest(value=value, unit=unit, label=label):
                self.assertEqual(numeric_region_plan(text, lines, None, 240, 80), [])
        text, lines = primary()
        duplicate = deepcopy(lines[0])
        for word in duplicate["words"]:
            word["bounds"]["y"] += 30
        self.assertEqual(numeric_region_plan(text+" "+text, lines+[duplicate], None, 240, 80), [])

    def test_unmapped_boolean_outside_image_and_competing_rows_cannot_support_crops(self):
        text, lines = primary()
        cases = []
        unmapped = deepcopy(lines); unmapped[0]["text"] = "missing"
        cases.append(unmapped)
        boolean = deepcopy(lines); boolean[0]["words"][1]["bounds"]["x"] = True
        cases.append(boolean)
        outside = deepcopy(lines); outside[0]["words"][-1]["bounds"]["x"] = 300
        cases.append(outside)
        competitor = deepcopy(lines)
        competitor.append({"text":"unknown","words":[{"text":"unknown","bounds":{"x":180,"y":20,"width":20,"height":20}}]})
        cases.append(competitor)
        for candidate in cases:
            with self.subTest(candidate=candidate):
                self.assertEqual(numeric_region_plan(text, candidate, None, 240, 80), [])

    def test_existing_reader_conflict_and_readable_primary_are_preserved(self):
        text, lines = primary("+140")
        reference = {"language":"en-US","lines":[{"text":"-141","words":[{"text":"-141","bounds":{"x":60,"y":20,"width":40,"height":20}}]}]}
        baseline = corroborate_fields(text, lines, reference)
        self.assertTrue(baseline[0]["ambiguous"])
        self.assertEqual(numeric_region_plan(text, lines, reference, 240, 80), [])
        self.assertEqual(recover_numeric_regions(text, lines, reference, [], []), baseline)
        text, lines = primary()
        plans = numeric_region_plan(text, lines, None, 240, 80)
        readable_text, readable_lines = primary("+140")
        preserved = recover_numeric_regions(readable_text, readable_lines, None, plans, [regional(plans[0], "-140")])
        self.assertEqual(preserved[0]["value"], 140)
        self.assertNotIn("numeric_source", preserved[0])

    def test_foreign_frames_languages_multiple_regions_and_malformed_lines_do_not_recover(self):
        text, lines = primary()
        plans = numeric_region_plan(text, lines, None, 240, 80)
        correct = regional(plans[0])
        cases = []
        wrong = deepcopy(correct); wrong["bounds"]["x"] += 1; cases.append([wrong])
        wrong = deepcopy(correct); wrong["language"] = "de-DE"; cases.append([wrong])
        wrong = deepcopy(correct); wrong["lines"][0]["words"][0]["bounds"]["x"] = 0; cases.append([wrong])
        wrong = deepcopy(correct); wrong["lines"] = [None]; cases.append([wrong])
        cases.extend(([correct, correct], [None], []))
        for regions in cases:
            with self.subTest(regions=regions):
                [field] = recover_numeric_regions(text, lines, None, plans, regions)
                self.assertIsNone(field["value"])
                self.assertTrue(field["ambiguous"])
                self.assertNotIn("numeric_source", field)

    def test_numeric_fragments_wrong_magnitude_and_explicit_sign_disagreement_remain_unresolved(self):
        text, lines = primary()
        plans = numeric_region_plan(text, lines, None, 240, 80)
        for token in ("-141", "-1.40e2", "-140,0", "-140.0.0"):
            with self.subTest(token=token):
                [field] = recover_numeric_regions(text, lines, None, plans, [regional(plans[0], token)])
                self.assertIsNone(field["value"])
                self.assertTrue(field["ambiguous"])
        text, lines = primary("1 9", "", "等级：")
        plans = numeric_region_plan(text, lines, None, 240, 80)
        self.assertEqual(len(plans), 1)
        [matching] = recover_numeric_regions(text, lines, None, plans, [regional(plans[0], "19")])
        self.assertEqual(matching["value"], 19)
        self.assertFalse(matching["ambiguous"])
        [field] = recover_numeric_regions(text, lines, None, plans, [regional(plans[0], "-19")])
        self.assertIsNone(field["value"])
        self.assertTrue(field["ambiguous"])


    def test_readable_primary_with_unusable_reference_is_checked_without_replacement(self):
        text, lines = primary("+233", "％", "护甲：")
        reference = {"language":"en-US","lines":[{"text":"+23.30/0","words":[{"text":"+23.30/0",
                     "bounds":{"x":60,"y":20,"width":45,"height":20}}]}]}
        original = corroborate_fields(text, lines, reference)[0]
        self.assertEqual(original["value"], 233)
        self.assertTrue(original["ambiguous"])
        plans = numeric_region_plan(text, lines, reference, 240, 80)
        self.assertEqual(len(plans), 1)
        for reading in ("+23.3", "-233"):
            with self.subTest(reading=reading):
                [field] = recover_numeric_regions(text, lines, reference, plans, [regional(plans[0], reading)])
                self.assertEqual(field["value"], 233)
                self.assertEqual(field["raw_text"], original["raw_text"])
                self.assertEqual(field["span"], original["span"])
                self.assertTrue(field["ambiguous"])
                self.assertEqual(field["conflict"], "numeric_readers_disagree")
                self.assertNotIn("numeric_source", field)
        [field] = recover_numeric_regions(text, lines, reference, plans, [regional(plans[0], "+233")])
        self.assertEqual(field["value"], 233)
        self.assertFalse(field["ambiguous"])
        self.assertNotIn("numeric_source", field)
        self.assertEqual(field["numeric_corroboration"]["method"], "native_numeric_region")
        [field] = recover_numeric_regions(text, lines, reference, plans, [])
        self.assertEqual(field["value"], 233)
        self.assertTrue(field["ambiguous"])

    def test_unreadable_magnitude_cannot_lose_an_explicit_primary_sign(self):
        cases = (("+23，3", "-23.3"), ("－23，3", "+23.3"), ("-1 9", "19"), ("+0", "-0"))
        for original, reading in cases:
            text, lines = primary(original, "％", "护甲：")
            reference = {"language":"en-US","lines":[{"text":reading,"words":[{"text":reading,
                         "bounds":{"x":60,"y":20,"width":45,"height":20}}]}]}
            with self.subTest(original=original,reading=reading):
                [field] = corroborate_fields(text, lines, reference)
                self.assertTrue(field["ambiguous"])
                self.assertEqual(field["conflict"], "numeric_readers_disagree")
                self.assertNotIn("numeric_source", field)
                self.assertEqual(numeric_region_plan(text, lines, reference, 240, 80), [])
        text, lines = primary("+23，3", "％", "护甲：")
        reference = {"language":"en-US","lines":[{"text":"+23.3","words":[{"text":"+23.3",
                     "bounds":{"x":60,"y":20,"width":45,"height":20}}]}]}
        [field] = corroborate_fields(text, lines, reference)
        self.assertEqual(field["value"], 23.3)
        self.assertFalse(field["ambiguous"])

    def test_unusable_reference_without_conflicting_candidates_preserves_primary(self):
        text, lines = primary("+233", "％", "护甲：")
        for reading in ("+233.0/0", "+233k", "unreadable"):
            reference = {"language":"en-US","lines":[{"text":reading,"words":[{"text":reading,
                         "bounds":{"x":60,"y":20,"width":45,"height":20}}]}]}
            with self.subTest(reading=reading):
                [field] = corroborate_fields(text, lines, reference)
                self.assertEqual(field["value"], 233)
                self.assertFalse(field["ambiguous"])
                self.assertEqual(numeric_region_plan(text, lines, reference, 240, 80), [])

    def test_already_corroborated_readable_primary_does_not_request_or_accept_another_read(self):
        text, lines = primary("+233", "％", "护甲：")
        reference = {"language":"en-US","lines":[{"text":"+233%","words":[{"text":"+233%",
                     "bounds":{"x":60,"y":20,"width":45,"height":20}}]}]}
        baseline = corroborate_fields(text, lines, reference)
        self.assertIn("numeric_corroboration", baseline[0])
        self.assertEqual(numeric_region_plan(text, lines, reference, 240, 80), [])
        self.assertEqual(recover_numeric_regions(text, lines, reference, [], []), baseline)



class NumericRegionWorkerTests(unittest.TestCase):
    def setUp(self):
        temporary_root = Path(__file__).resolve().parents[1] / ".local"
        temporary_root.mkdir(exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(prefix="lootweave-numeric-region-", dir=temporary_root)
        assert Path(self.temporary.name).resolve().is_relative_to(temporary_root.resolve())
        self.addCleanup(self.temporary.cleanup)
        self.engine = OCR.__new__(OCR)
        self.engine.data_dir = Path(self.temporary.name)
        self.engine.command = "controlled-test-helper"
        self.engine.script = Path("controlled-test-script.ps1")
        self.engine.enabled = True
        self.engine.languages = ["en-US", "zh-Hans-CN"]
        self.engine.slot = threading.BoundedSemaphore(1)
        self.text, self.lines = primary()
        self.body = {"observation_id":"controlled-region", "language":"zh-Hans-CN",
                     "image_base64":base64.b64encode(bmp()).decode(),
                     "bounds":{"x":0,"y":0,"width":240,"height":80}}
        self.plans = numeric_region_plan(self.text, self.lines, None, 240, 80)
        self.original = subprocess.CompletedProcess([], 0, json.dumps(
            {"text":self.text, "lines":self.lines, "numeric_reference":None}).encode(), b"")

    def test_optional_region_call_is_single_bounded_and_preserves_original_image_and_text(self):
        extra = subprocess.CompletedProcess([], 0, json.dumps(
            {"numeric_regions":[regional(self.plans[0])]}).encode(), b"")
        with patch("services.ocr.app.subprocess.run", side_effect=[self.original, extra]) as run:
            result = self.engine.recognize(self.body)
        self.assertEqual(run.call_count, 2)
        arguments = run.call_args_list[1].args[0]
        encoded = arguments[arguments.index("-NumericRegions")+1]
        plan = json.loads(base64.b64decode(encoded))
        self.assertEqual(plan, [{"field":self.plans[0]["field"],"bounds":self.plans[0]["bounds"]}])
        self.assertLessEqual(run.call_args_list[1].kwargs["timeout"], 6)
        self.assertEqual(result["raw_text"], self.text)
        self.assertEqual(result["image_hash"], __import__("hashlib").sha256(bmp()).hexdigest())
        self.assertEqual(result["fields"][0]["value"], -140)
        self.assertTrue(result["requires_confirmation"])
        self.assertTrue(self.engine.slot.acquire(blocking=False))
        self.engine.slot.release()

    def test_failed_timeout_and_malformed_optional_reads_leave_primary_observation_usable(self):
        failures = (subprocess.CompletedProcess([], 1, b'{"error":"ocr_failed"}', b""),
                    subprocess.CompletedProcess([], 0, b'{"numeric_regions":[null]}', b""),
                    subprocess.CompletedProcess([], 0, b'not-json', b""),
                    subprocess.TimeoutExpired("controlled-test-helper", 6),
                    OSError("controlled-test-failure"))
        for failure in failures:
            with self.subTest(failure=type(failure).__name__), patch(
                "services.ocr.app.subprocess.run", side_effect=[self.original, failure]):
                result = self.engine.recognize(self.body)
                self.assertEqual(result["raw_text"], self.text)
                self.assertEqual(result["state"], "unconfirmed")
                self.assertNotIn("error", result)
                self.assertIn("numeric_region_error", result)
                self.assertTrue(self.engine.slot.acquire(blocking=False))
                self.engine.slot.release()


    def test_failed_optional_corroboration_retains_readable_value_and_marks_it_for_review(self):
        text, lines = primary("+233", "％", "护甲：")
        reference = {"language":"en-US","lines":[{"text":"+23.30/0","words":[{"text":"+23.30/0",
                     "bounds":{"x":60,"y":20,"width":45,"height":20}}]}]}
        original = subprocess.CompletedProcess([], 0, json.dumps(
            {"text":text,"lines":lines,"numeric_reference":reference}).encode(), b"")
        with patch("services.ocr.app.subprocess.run", side_effect=[original, OSError("controlled-test-failure")]) as run:
            result = self.engine.recognize(self.body)
        self.assertEqual(run.call_count, 2)
        self.assertEqual(result["raw_text"], text)
        self.assertEqual(result["state"], "unconfirmed")
        self.assertNotIn("error", result)
        self.assertEqual(result["fields"][0]["value"], 233)
        self.assertTrue(result["fields"][0]["ambiguous"])
        self.assertIn("numeric_region_error", result)
        self.assertTrue(self.engine.slot.acquire(blocking=False))
        self.engine.slot.release()

    @unittest.skipUnless(os.name == "nt", "Native WinRT adapter requires Windows.")
    def test_native_helper_accepts_two_and_three_regions_and_rejects_duplicates(self):
        engine = OCR(self.engine.data_dir)
        if not engine.enabled or "en-US" not in engine.languages:
            self.skipTest("English Windows OCR model is unavailable.")
        image = engine.data_dir / "controlled-blank.bmp"
        image.write_bytes(bmp())
        plans = [{"field": key, "bounds": {"x": 10+60*index, "y": 10, "width": 50, "height": 30}}
                 for index, key in enumerate(("level", "vitality", "armor"))]
        for count in (2, 3):
            with self.subTest(count=count):
                regions, error = engine.numeric_regions(image, plans[:count], 6)
                self.assertIsNone(error)
                self.assertEqual(len(regions), count)
                self.assertEqual([row["field"] for row in regions], [row["field"] for row in plans[:count]])
                self.assertEqual([row["bounds"] for row in regions], [row["bounds"] for row in plans[:count]])
                self.assertTrue(all(row["language"] == "en-US" for row in regions))
        regions, error = engine.numeric_regions(image, [plans[0], plans[0]], 6)
        self.assertEqual(regions, [])
        self.assertEqual(error, "ocr_failed")

    def test_missing_english_model_skips_region_read(self):
        self.engine.languages = ["zh-Hans-CN"]
        with patch("services.ocr.app.subprocess.run", return_value=self.original) as run:
            result = self.engine.recognize(self.body)
        self.assertEqual(run.call_count, 1)
        self.assertEqual(result["numeric_regions"], [])
        self.assertNotIn("numeric_region_error", result)


if __name__ == "__main__":
    unittest.main()

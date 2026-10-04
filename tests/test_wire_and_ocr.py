"""Regression tests for strict JSON parsing and conservative OCR confirmation."""
import tempfile
import unittest
from pathlib import Path

from contracts import DomainError, parse_json
from scripts.benchmark_ocr import generate, score
from services.ocr.domain import corroborate_fields, parse_fields


def word_line(text, x=0, y=0, width=100, height=20):
    return {"text": text, "words": [{"text": text, "bounds": {"x": x, "y": y, "width": width, "height": height}}]}


def english_reference(*lines):
    return {"language": "en-US", "lines": list(lines)}


class StrictJSONTests(unittest.TestCase):
    def test_rejects_duplicate_keys_and_non_finite_values_recursively(self):
        invalid = (
            '{"x":1,"x":2}', '{"outer":{"x":1,"x":2}}',
            '{"items":[{"x":1,"x":2}]}', '{"x":NaN}',
            '{"x":Infinity}', '{"x":-Infinity}', '{"x":1e999}',
            '{"x":-1e999}', '{"items":[NaN]}',
            '{"outer":{"x":Infinity}}', '{"items":[1e999]}',
            '{"outer":{"x":-1e999}}',
        )
        for raw in invalid:
            with self.subTest(raw=raw), self.assertRaises(DomainError) as caught:
                parse_json(raw)
            self.assertEqual(caught.exception.code, "invalid_json")

    def test_accepts_unicode_and_finite_decimal(self):
        parsed = parse_json('{"名":"刀刃","values":[0.125,-42.75,1e-300]}')
        self.assertEqual(parsed["名"], "刀刃")
        self.assertEqual(parsed["values"], [0.125, -42.75, 1e-300])


class OCRFieldTests(unittest.TestCase):
    def test_spaced_chinese_labels_retain_exact_source_spans_and_fail_closed(self):
        text = "等 级 ： 60 活 力 ： 一 140 点 护 甲 ： + 20 ． 1 ％"
        fields = parse_fields(text)
        self.assertEqual([field["field"] for field in fields], ["level", "vitality", "armor"])
        self.assertEqual([field["value"] for field in fields], [60, None, 20.1])
        self.assertTrue(fields[1]["ambiguous"])
        self.assertEqual([text[slice(*field["span"])] for field in fields],
                         [field["raw_text"] for field in fields])
        self.assertEqual([field["raw_value"] for field in fields], ["60", "一 140", "+ 20 ． 1"])

    def test_signs_fullwidth_signs_and_decimal_keep_the_original_lexeme(self):
        text = "活力：+ 65 点 护甲：＋１２．５％ 护甲：-2.5％"
        fields = parse_fields(text)
        self.assertEqual(len(fields), 3)
        self.assertEqual(fields[0]["raw_value"], "+ 65")
        self.assertEqual(fields[0]["value"], 65)
        self.assertEqual(fields[1]["raw_value"], "＋１２．５")
        self.assertEqual(text[slice(*fields[1]["span"])], fields[1]["raw_text"])
        self.assertEqual(fields[1]["value"], 12.5)
        self.assertEqual(fields[2]["raw_value"], "-2.5")
        self.assertEqual(fields[2]["value"], -2.5)
        self.assertTrue(fields[2]["ambiguous"], "a repeated field must remain flagged")

    def test_repeated_fields_remain_ambiguous(self):
        fields = parse_fields("活力：65点 活力：70点")
        self.assertEqual(len(fields), 2)
        self.assertTrue(all(field["ambiguous"] for field in fields))

    def test_same_position_english_sign_confirms_chinese_dash_lookalike(self):
        text = "活 力 ： 一 140 点"
        [field] = corroborate_fields(text, [word_line(text)],
                                    english_reference(word_line("Value: -140 points")))
        self.assertEqual(field["value"], -140)
        self.assertEqual(field["numeric_source"]["raw_value"], "-140")
        self.assertTrue(field["requires_confirmation"])
        self.assertEqual(field["raw_text"], text)
        self.assertEqual(field["raw_value"], "一 140")
        self.assertFalse(field["ambiguous"])

    def test_wrong_geometry_multiple_lines_or_numbers_do_not_confirm(self):
        text = "活 力 ： 一 140 点"
        primary = word_line(text)
        cases = (
            english_reference(word_line("Value: -140 points", y=100)),
            english_reference(word_line("Value: -140 points"), word_line("Value: -140 points", y=2)),
            english_reference(word_line("Value: -140 / +140 points")),
        )
        for reference in cases:
            with self.subTest(reference=reference):
                [field] = corroborate_fields(text, [primary], reference)
                self.assertIsNone(field["value"])
                self.assertTrue(field["ambiguous"])

    def test_conflicts_unknown_identity_missing_unit_and_duplicates_stay_unresolved(self):
        [conflict] = corroborate_fields("活力：140 点", [word_line("活力：140 点")],
                                       english_reference(word_line("Value: -141 points")))
        self.assertTrue(conflict["ambiguous"])
        self.assertEqual(conflict.get("conflict"), "numeric_readers_disagree")

        # Equal magnitudes with conflicting explicit signs are also a disagreement.
        [sign_conflict] = corroborate_fields("活力：+140 点", [word_line("活力：+140 点")],
                                            english_reference(word_line("Value: -140 points")))
        self.assertTrue(sign_conflict["ambiguous"])
        self.assertEqual(sign_conflict.get("conflict"), "numeric_readers_disagree")

        # An English number cannot create or rename a primary-language field.
        [unknown] = corroborate_fields("等级：60", [word_line("等级：60")],
                                      english_reference(word_line("Mystery: -60 points")))
        self.assertEqual(unknown["field"], "level")
        self.assertEqual(unknown["value"], 60)

        [no_unit] = corroborate_fields("活力：140", [word_line("活力：140")],
                                      english_reference(word_line("Value: -140 points")))
        self.assertIsNone(no_unit["unit"])
        self.assertTrue(no_unit["ambiguous"])
        self.assertNotIn("numeric_source", no_unit)

        text = "活力：140 点 活力：140 点"
        fields = corroborate_fields(text, [word_line(text)],
                                    english_reference(word_line("Value: -140 points")))
        self.assertEqual(len(fields), 2)
        self.assertTrue(all(field["ambiguous"] for field in fields))
        self.assertTrue(all("numeric_source" not in field for field in fields))

    def test_partial_or_split_numeric_tokens_are_not_confirmed(self):
        for text in ("等级：1 1", "Level: 12e3", "Armor: +30B%", "Vitality: +3S8 points"):
            with self.subTest(text=text):
                self.assertFalse(any(field["value"] is not None and not field["ambiguous"]
                                     for field in parse_fields(text)))

    def test_complete_unit_and_reference_can_recover_an_unreadable_whole_token(self):
        text = "护 甲 ： +30B％"
        [field] = corroborate_fields(text, [word_line(text)],
                                    english_reference(word_line("Value: +30.8%")))
        self.assertEqual(field["value"], 30.8)
        self.assertEqual(field["unit"], "%")
        self.assertEqual(field["raw_text"], text)
        self.assertEqual(field["raw_value"], "+30B")
        self.assertEqual(field["numeric_source"]["raw_value"], "+30.8")
        self.assertTrue(field["requires_confirmation"])
        self.assertFalse(field["ambiguous"])

    def test_reference_cannot_use_number_fragments_from_malformed_tokens(self):
        text = "活力：巧140 点"
        for token in ("-1.40e2", "-140,0", "-140.0.0"):
            with self.subTest(token=token):
                [field] = corroborate_fields(text, [word_line(text)],
                                            english_reference(word_line("Value: " + token + " points")))
                self.assertIsNone(field["value"])
                self.assertTrue(field["ambiguous"])
                self.assertNotIn("numeric_source", field)
        [field] = corroborate_fields("护甲：+1.4%", [word_line("护甲：+1.4%")],
                                    english_reference(word_line("Value: t1.4%")))
        self.assertEqual(field["value"], 1.4)
        self.assertFalse(field["ambiguous"])

    def test_clear_primary_sign_remains_the_source_when_reference_omits_plus(self):
        text = "活力：+140 点"
        [field] = corroborate_fields(text, [word_line(text)],
                                    english_reference(word_line("Value: 140 points")))
        self.assertEqual(field["value"], 140)
        self.assertEqual(field["raw_value"], "+140")
        self.assertNotIn("numeric_source", field)
        self.assertEqual(field["numeric_corroboration"]["raw_value"], "140")
        [measured] = score([{"field": "vitality", "value": 140, "unit": "points", "sign": "+"}], [field])
        self.assertTrue(measured["correct"])


    def test_unit_suffix_requires_complete_words_and_accepts_real_tabs(self):
        text = "活力：巧140 pointst"
        [field] = corroborate_fields(text, [word_line(text)],
                                    english_reference(word_line("Value: -140 points")))
        self.assertIsNone(field["unit"])
        self.assertIsNone(field["value"])
        self.assertTrue(field["ambiguous"])
        self.assertNotIn("numeric_source", field)

        text = "活力：巧140 点\t"
        [field] = corroborate_fields(text, [word_line(text)],
                                    english_reference(word_line("Value: -140 points")))
        self.assertEqual(field["value"], -140)
        self.assertEqual(field["unit"], "points")
        self.assertEqual(field["raw_text"], text)
        self.assertFalse(field["ambiguous"])

    def test_spaced_corrupt_decimal_never_leaves_a_numeric_prefix(self):
        for raw in ("+14 · 9", "- 31 · 9", "+ 5 ， x", "-40 ． x"):
            text = "护甲：" + raw + "％"
            with self.subTest(raw=raw):
                self.assertEqual(parse_fields(text), [])

    def test_reference_recovers_the_whole_spaced_corrupt_decimal(self):
        cases = (("+14 · 9", "+14.9", 14.9), ("一 31 · 9", "-31.9", -31.9))
        for raw, reference_value, value in cases:
            text = "护甲：" + raw + "％"
            with self.subTest(raw=raw):
                [field] = corroborate_fields(text, [word_line(text)],
                    english_reference(word_line("Value: " + reference_value + "%")))
                self.assertEqual(field["value"], value)
                self.assertEqual(field["unit"], "%")
                self.assertEqual(field["raw_text"], text)
                self.assertEqual(field["raw_value"], raw)
                self.assertEqual(text[slice(*field["span"])], text)
                self.assertEqual(field["numeric_source"]["raw_value"], reference_value)
                self.assertFalse(field["ambiguous"])
                self.assertTrue(field["requires_confirmation"])

    def test_numeric_reference_cannot_recover_a_spaced_decimal_prefix(self):
        text = "护甲：+1S％"
        for token in ("+14 · x", "+14 ， x", "-14 ． x"):
            with self.subTest(token=token):
                [field] = corroborate_fields(text, [word_line(text)],
                    english_reference(word_line("Value: " + token + "%")))
                self.assertIsNone(field["value"])
                self.assertTrue(field["ambiguous"])
                self.assertNotIn("numeric_source", field)

    def test_flattened_native_text_respects_unique_row_ownership(self):
        cases = (("Vitality:", "Armor:", "+65 points", "+12%"),
                 ("活力：", "护甲：", "+65 点", "+12%"))
        for vitality, armor, points, percent in cases:
            for reverse_values in (False, True):
                value_lines = [word_line(points, x=110, y=0), word_line(percent, x=110, y=40)]
                if reverse_values:
                    value_lines.reverse()
                lines = [word_line(vitality, y=0), word_line(armor, y=40), *value_lines]
                raw = " ".join(line["text"] for line in lines)
                for reference in (None, english_reference()):
                    with self.subTest(raw=raw, reference=reference):
                        fields = {field["field"]: field for field in corroborate_fields(raw, lines, reference)}
                        self.assertEqual({"vitality", "armor"}, set(fields))
                        self.assertEqual((65, "points"), (fields["vitality"]["value"], fields["vitality"]["unit"]))
                        self.assertEqual((12, "%"), (fields["armor"]["value"], fields["armor"]["unit"]))
                        for field in fields.values():
                            self.assertFalse(field["ambiguous"])
                            self.assertTrue(field["requires_confirmation"])
                            self.assertEqual(raw[slice(*field["span"])], field["raw_text"])
                            source = field["label_source"]
                            self.assertEqual(raw[slice(*source["span"])], source["raw_text"])
                            self.assertEqual("native_row_geometry", source["method"])

    def test_row_association_rejects_competing_labels_values_and_text(self):
        cases = (
            [word_line("Vitality:"), word_line("Armor:", x=110), word_line("+65 points", x=220)],
            [word_line("Vitality:"), word_line("+65 points", x=110), word_line("+12%", x=220)],
            [word_line("Vitality:"), word_line("Unknown:", x=110), word_line("+65 points", x=220)],
            [word_line("Vitality:"), word_line("+65 points", x=110, y=40)],
            [word_line("Vitality: Armor:"), word_line("+65 points", x=220)],
            [word_line("Vitality:"), word_line("Vitality:", y=40),
             word_line("+65 points", x=110), word_line("+12%", x=110, y=40)],
        )
        for lines in cases:
            raw = " ".join(line["text"] for line in lines)
            with self.subTest(raw=raw):
                self.assertEqual([], corroborate_fields(raw, lines, None))

    def test_separate_native_value_preserves_sign_conflicts_and_missing_units(self):
        for reference_value, expected_value, conflict in (("-140", -140, None),
                                                         ("-141", None, "numeric_readers_disagree"),
                                                         ("140", None, None)):
            lines = [word_line("活力："), word_line("一140 点", x=110)]
            raw = " ".join(line["text"] for line in lines)
            with self.subTest(reference_value=reference_value):
                [field] = corroborate_fields(raw, lines, english_reference(word_line(reference_value, x=110)))
                self.assertEqual(expected_value, field["value"])
                self.assertEqual("一140", field["raw_value"])
                self.assertEqual(expected_value is None, field["ambiguous"])
                if conflict:
                    self.assertEqual(conflict, field["conflict"])
                self.assertEqual(raw[slice(*field["span"])], field["raw_text"])
        lines = [word_line("Vitality:"), word_line("140", x=110)]
        raw = " ".join(line["text"] for line in lines)
        [field] = corroborate_fields(raw, lines, None)
        self.assertEqual(140, field["value"])
        self.assertIsNone(field["unit"])
        self.assertTrue(field["ambiguous"])

    def test_empty_level_label_uses_a_standalone_uncontested_right_hand_number(self):
        raw = "等级："
        primary = word_line(raw, width=50)
        [field] = corroborate_fields(raw, [primary], english_reference(word_line("44", x=70, width=30)))
        self.assertEqual(44, field["value"])
        self.assertFalse(field["ambiguous"])
        self.assertTrue(field["requires_confirmation"])
        self.assertEqual("44", field["numeric_source"]["raw_value"])
        self.assertEqual(raw[slice(*field["span"])], field["raw_text"])

    def test_right_hand_level_requires_known_identity_and_an_uncontested_row(self):
        raw = "等级："
        primary = word_line(raw, width=50)
        references = (word_line("44", x=70, y=40, width=30),
                      word_line("44 45", x=70, width=50),
                      word_line("44 points", x=70, width=50),
                      word_line("Unknown 44", x=70, width=50))
        for reference in references:
            with self.subTest(reference=reference["text"]):
                [field] = corroborate_fields(raw, [primary], english_reference(reference))
                self.assertIsNone(field["value"])
                self.assertTrue(field["ambiguous"])
        raw += " Damage:"
        lines = [primary, word_line("Damage:", x=55, width=50)]
        [field] = corroborate_fields(raw, lines, english_reference(word_line("44", x=110, width=30)))
        self.assertIsNone(field["value"])
        self.assertTrue(field["ambiguous"])

    def test_boolean_native_coordinates_cannot_corroborate_a_number(self):
        raw = "活力：一140 点"
        for axis in ("x", "y"):
            primary = word_line(raw)
            primary["words"][0]["bounds"][axis] = True
            with self.subTest(axis=axis):
                [field] = corroborate_fields(raw, [primary], english_reference(word_line("-140")))
                self.assertIsNone(field["value"])
                self.assertTrue(field["ambiguous"])
                self.assertNotIn("numeric_source", field)

    def test_native_fields_require_mapped_line_text(self):
        raw = "Armor: +12%"
        for lines in ([], [word_line("Armor: +65 points")]):
            with self.subTest(lines=lines):
                self.assertEqual(corroborate_fields(raw, lines, None), [])

    def test_line_binding_preserves_global_spans_and_duplicate_ambiguity(self):
        line = "Armor: +12%"
        text = line + " " + line
        fields = corroborate_fields(text, [word_line(line), word_line(line, y=40)], None)
        self.assertEqual(len(fields), 2)
        self.assertTrue(all(field["ambiguous"] for field in fields))
        self.assertEqual(fields[0]["span"], [0, len(line)])
        self.assertEqual(fields[1]["span"], [len(line) + 1, len(text)])
        for field in fields:
            self.assertEqual(text[slice(*field["span"])], field["raw_text"])
            self.assertTrue(field["requires_confirmation"])

    def test_label_period_does_not_change_the_number_or_unit(self):
        text = "Armor. +22.2%"
        [field] = parse_fields(text)
        self.assertEqual(field["field"], "armor")
        self.assertEqual(field["value"], 22.2)
        self.assertEqual(field["unit"], "%")
        self.assertEqual(field["raw_value"], "+22.2")
        self.assertEqual(field["raw_text"], text)
        self.assertFalse(field["ambiguous"])


class OCRDatasetTests(unittest.TestCase):
    def test_generation_does_not_touch_an_examined_dataset(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            (output / "images").mkdir()
            image = output / "images/region-000.bmp"
            image.write_bytes(b"sealed original pixels")
            (output / "report.json").write_text('{"accuracy": 0.5}', encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "already contains evidence"):
                generate(output, "holdout")
            self.assertEqual(image.read_bytes(), b"sealed original pixels")
            self.assertEqual((output / "report.json").read_text(encoding="utf-8"), '{"accuracy": 0.5}')
            self.assertFalse((output / "manifest.json").exists())


class OCRScoreTests(unittest.TestCase):
    truth = [{"field": "vitality", "value": -140, "unit": "points", "sign": "-"}]

    def test_missing_rejected_wrong_unit_lost_sign_and_duplicates_stay_in_denominator(self):
        cases = (
            ([], None, True),
            ([{"field": "vitality", "value": -140, "unit": "points", "ambiguous": True}], None, True),
            ([{"field": "vitality", "value": -140, "unit": "%", "raw_value": "-140", "ambiguous": False}], None, False),
            ([{"field": "vitality", "value": -140, "unit": "points", "raw_value": "140", "ambiguous": False}], None, False),
            ([{"field": "vitality", "value": -140, "unit": "points", "raw_value": "-140", "ambiguous": False}] * 2, None, True),
            ([{"field": "vitality", "value": -140, "unit": "points", "raw_value": "-140", "ambiguous": False}], "engine failed", True),
        )
        for observed, error, rejected in cases:
            with self.subTest(observed=observed, error=error):
                [row] = score(self.truth, observed, error)
                self.assertFalse(row["correct"])
                self.assertEqual(row["rejected"], rejected)
                self.assertEqual(row["unflagged_error"], not rejected)

    def test_correct_independent_numeric_source_supplies_the_sign(self):
        observed = [{"field": "vitality", "value": -140, "unit": "points", "raw_value": "一 140",
                     "ambiguous": False, "numeric_source": {"raw_value": "-140"}}]
        [row] = score(self.truth, observed)
        self.assertEqual(row, {"field": "vitality", "correct": True, "rejected": False,
                               "unflagged_error": False})

    def test_wrong_independent_numeric_source_sign_is_an_unflagged_error(self):
        observed = [{"field": "vitality", "value": -140, "unit": "points", "raw_value": "一 140",
                     "ambiguous": False, "numeric_source": {"raw_value": "+140"}}]
        [row] = score(self.truth, observed)
        self.assertFalse(row["correct"])
        self.assertFalse(row["rejected"])
        self.assertTrue(row["unflagged_error"])


if __name__ == "__main__":
    unittest.main()

"""OCR field checks never promote observations to facts."""
from __future__ import annotations

import unittest

from services.ocr.domain import parse_fields


class OCRFieldTests(unittest.TestCase):
    def test_sign_unit_and_original_text_are_preserved(self):
        result = parse_fields("Level: 15 Vitality: +65 points Armor: -12%")
        self.assertEqual(["level", "vitality", "armor"], [f["field"] for f in result])
        self.assertEqual([15, 65, -12], [f["value"] for f in result])
        self.assertEqual(["level", "points", "%"], [f["unit"] for f in result])
        self.assertTrue(all(f["requires_confirmation"] for f in result))
        self.assertEqual("+65", result[1]["raw_value"])

    def test_missing_unit_remains_ambiguous(self):
        result = parse_fields("Vitality 65")
        self.assertTrue(result[0]["ambiguous"])
        self.assertIsNone(result[0]["unit"])

    def test_decimal_comma_is_not_guessed(self):
        result = parse_fields("Armor: 1,500 points")
        self.assertTrue(result[0]["ambiguous"])
        self.assertIsNone(result[0]["value"])

    def test_duplicate_field_requires_review(self):
        result = parse_fields("Armor: 15 points Armor: 25 points")
        self.assertTrue(result[1]["ambiguous"])

    def test_chinese_and_unicode_minus_are_preserved(self):
        result = parse_fields("等级：15 活力：+65 点 护甲：−12%")
        self.assertEqual([15, 65, -12], [f["value"] for f in result])
        self.assertTrue(all(f["requires_confirmation"] for f in result))

    def test_unrecognized_words_do_not_establish_field_identity(self):
        self.assertEqual([], parse_fields("Unknown icon 9999"))

    def test_numeric_span_maps_back_to_original_text(self):
        text = "Start\nVitality: +65 points\nEnd"
        field = parse_fields(text)[0]
        self.assertEqual(field["raw_text"], text[field["span"][0]:field["span"][1]])


if __name__ == "__main__":
    unittest.main()

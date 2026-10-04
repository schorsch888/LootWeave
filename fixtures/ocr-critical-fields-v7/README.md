# Archived synthetic OCR holdout v7

This fixture preserves all 200 original synthetic region inputs, 600 labeled
critical fields, native primary and numeric-region observations, scores and
latency measurements. It covers two languages, five scales and four image
quality conditions. No game/player images or font files are distributed.

The frozen adapter measured 572/600 correct (95.33%), 28 rejected/missing fields
and zero unflagged errors. Whole-request P95 was 1.780 s. The overall numerical
targets passed; Chinese accuracy was 91%, while low-contrast and downsampled
accuracy was 93.33% and 92.67%. This evidence does not accept M2: independent
human truth review, actual game/layout coverage and other stage gates remain
pending. Every observation remains unconfirmed until user review.

The [provenance](provenance.json) pins the original artifacts and
[generator](../ocr-v7-generator.py). The [parser snapshot](parser-source.py)
replays recorded primary text/geometry and actual native crops without Windows
OCR. Source/JSON bytes are immutable across Git checkouts. The dataset was
newly generated after source freeze and excluded from tuning; it has now been
examined. No image hash overlaps the v1 tuning set or holdouts v1 through v6.
Further algorithm/model/renderer changes require a fresh unseen holdout.

Run the complete evidence checks from the repository root:

```powershell
python scripts/validate_ocr_holdout.py --version v7
```

A successful integrity audit verifies all 600 field scores and 200 frozen
parser replays. It preserves measured_target_pass=true and m2_accepted=false.
It neither reruns OCR nor proves independent manual review.

To reconstruct the original BMPs on Windows, use the exact installed fonts and
renderer versions in provenance; font files are not redistributed:

```powershell
python fixtures/ocr-v7-generator.py --generate-only --output .local/ocr-v7-reproduction
python scripts/validate_ocr_holdout.py --version v7 --images .local/ocr-v7-reproduction/images
```

Reconstruction must match every BMP hash and dimension before using images
for reproduction. Existing evidence directories are never overwritten.

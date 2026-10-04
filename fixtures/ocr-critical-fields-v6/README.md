# Archived synthetic OCR holdout v6

This fixture publishes the complete frozen measurement: 200 original synthetic
regions and all 600 labeled critical fields, covering two languages, five scales
and four quality conditions. It contains renderer inputs, exact image hashes,
recorded native OCR text/geometry, parsed observations, per-field scores and
aggregate measurements. No game images, player material or font files are included.

The archived result is 550/600 correct (91.67%), with 50 rejected/missing fields
and zero unflagged errors. Missing fields, rejection, incorrect values, lost signs
and wrong units remain in the denominator. Accuracy misses the 95% target;
independent human ground-truth review remains pending, and M2 is unaccepted.

The [provenance record](provenance.json) pins the original artifact bytes and the
[historical generator](../ocr-v6-generator.py). The
[parser source](parser-source.py) is an immutable snapshot, used only to replay
recorded native observations. Repository attributes preserve the exact frozen
source/JSON bytes across Git checkouts without newline conversion. The current application parser remains owned by
the OCR service. The dataset was held out before its recorded measurement and
has since been examined. Future parser/model/renderer changes require a fresh
unseen acceptance set; this fixture is historical evaluation evidence.

## Inspect and replay without Windows OCR

Run from the repository root with Python 3.12:

```powershell
python scripts/validate_ocr_holdout.py
```

This checks artifact identities, all 200 parser replays, all 600 critical-field
scores, exact raw-text spans, confirmation flags, balanced coverage, dimensional
totals and recorded latency calculations. Exit code 0 means the archived evidence
is consistent; the output separately retains measured_target_pass=false and
m2_accepted=false. It does not rerun OCR or measure current latency.

## Recreate every image

Use Windows with installed Segoe UI and Microsoft YaHei fonts matching the hashes
in [manifest.json](manifest.json), Pillow 12.3.0 and FreeType 2.14.3. These
dependencies and fonts are not included in the fixture. Use a new empty output
directory; the frozen generator refuses to overwrite existing evidence.

```powershell
python fixtures/ocr-v6-generator.py --output .local/ocr-v6-reproduction --generate-only
python scripts/validate_ocr_holdout.py --images .local/ocr-v6-reproduction/images
```

The second command verifies all 200 exact BMP hashes and dimensions. A different
font/rendering environment must fail instead of silently supplying different
inputs. Review all reproduced images against the manifest independently before
claiming manual ground-truth acceptance. The generator also creates a twelve-image
preview sheet; that preview is not a substitute for the full review.

Original report: [report.json](report.json). Complete raw observations:
[observations.json](observations.json). Product gates: [Roadmap](../../docs/roadmap.md).

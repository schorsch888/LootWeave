"""Synthetic Windows OCR holdout: no game images, assets or player data."""
from __future__ import annotations
import argparse
import base64
import hashlib
import json
import math
import os
import platform
import random
import statistics
import sys
import time
from collections import defaultdict
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from contracts import digest
from services.ocr.app import OCR

SCALES = (0.75, 1.0, 1.25, 1.5, 2.0)
QUALITIES = ("clean", "low_contrast", "blurred", "downsampled")
LANGUAGES = ("en-US", "zh-Hans-CN")
VERSION = "synthetic-critical-fields-v6"

def percentile(values, fraction):
    return sorted(values)[max(0, math.ceil(len(values) * fraction) - 1)]

def score(expected, observed, error=None):
    """Missing, rejected, wrong signs and wrong units all stay in the denominator."""
    by_field = defaultdict(list)
    for field in observed:
        by_field[field["field"]].append(field)
    rows = []
    for truth in expected:
        matches = by_field[truth["field"]]
        field = matches[0] if len(matches) == 1 else None
        rejected = bool(error) or field is None or field.get("ambiguous", True)
        raw = field.get("numeric_source", {}).get("raw_value", field.get("raw_value", "")).strip() if field else ""
        raw = raw.translate(str.maketrans({"−": "-", "－": "-", "＋": "+"}))
        sign_ok = not truth["sign"] or raw.startswith(truth["sign"])
        correct = (not rejected and field.get("value") == truth["value"]
                   and field.get("unit") == truth["unit"] and sign_ok)
        rows.append({"field": truth["field"], "correct": bool(correct), "rejected": bool(rejected),
                     "unflagged_error": not correct and not rejected})
    return rows

def generate(output, partition):
    # A fresh directory keeps examined evidence and sealed inputs immutable.
    if output.exists() and (not output.is_dir() or any(output.iterdir())):
        raise RuntimeError("Output already contains evidence. Preserve it and use a new output directory.")
    from PIL import Image, ImageDraw, ImageFilter, ImageFont
    output.mkdir(parents=True, exist_ok=True)
    fonts_dir = Path(os.environ.get("WINDIR", "")) / "Fonts"
    fonts = {"en-US": fonts_dir / "segoeui.ttf", "zh-Hans-CN": fonts_dir / "msyh.ttc"}
    if not all(path.is_file() for path in fonts.values()):
        raise RuntimeError("Installed Windows Segoe UI and Microsoft YaHei fonts are required; fonts are not redistributed.")
    seed = f"{VERSION}/{partition}/2026-10-04"
    rng = random.Random(hashlib.sha256(seed.encode()).hexdigest())
    images = output / "images"
    images.mkdir(exist_ok=True)
    samples = []
    for language in LANGUAGES:
        for scale in SCALES:
            for quality in QUALITIES:
                for _ in range(5):
                    level = rng.randint(1, 99)
                    vitality = rng.choice((-1, 1)) * rng.randint(20, 950)
                    armor = rng.choice((-1, 1)) * rng.randint(11, 409) / 10
                    labels = ("Level", "Vitality", "Armor") if language == "en-US" else ("等级", "活力", "护甲")
                    unit = "points" if language == "en-US" else "点"
                    colon = ":" if language == "en-US" else "："
                    lines = [f"{labels[0]}{colon} {level}", f"{labels[1]}{colon} {vitality:+d} {unit}",
                             f"{labels[2]}{colon} {armor:+.1f}%"]
                    width, height = round(490 * scale), round(162 * scale)
                    colors = ((45,48,53),(133,139,147)) if quality == "low_contrast" else ((25,29,34),(236,240,229))
                    image = Image.new("RGB", (width, height), colors[0])
                    draw = ImageDraw.Draw(image)
                    font = ImageFont.truetype(str(fonts[language]), round(29 * scale))
                    for index, line in enumerate(lines):
                        draw.text((round(14*scale), round((9+47*index)*scale)), line, font=font, fill=colors[1])
                    if quality == "blurred":
                        image = image.filter(ImageFilter.GaussianBlur(radius=0.65*scale))
                    elif quality == "downsampled":
                        image = image.resize((round(width*0.7),round(height*0.7)),Image.Resampling.BILINEAR).resize((width,height),Image.Resampling.BILINEAR)
                    name = f"region-{len(samples):03d}.bmp"
                    image.save(images / name)
                    expected = [{"field":"level","value":level,"unit":"level","sign":""},
                                {"field":"vitality","value":vitality,"unit":"points","sign":"+" if vitality>0 else "-"},
                                {"field":"armor","value":armor,"unit":"%","sign":"+" if armor>0 else "-"}]
                    samples.append({"id":name[:-4],"image":"images/"+name,"language":language,"scale":scale,
                                    "quality":quality,"text":"\n".join(lines),"expected":expected,"width":width,"height":height,
                                    "image_sha256":hashlib.sha256((images/name).read_bytes()).hexdigest()})
    manifest = {"dataset_version":VERSION,"partition":partition,"seed_identity":seed,
                "generator_sha256":hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                "truth_method":"Exact renderer inputs; manually inspect review-sheet.bmp against this manifest before accepting.",
                "lawful_scope":"Original synthetic text; locally rendered with installed Windows fonts. No game or player material.",
                "font_names":{lang:path.name for lang,path in fonts.items()},
                "font_sha256":{lang:hashlib.sha256(path.read_bytes()).hexdigest() for lang,path in fonts.items()},
                "samples":samples,"truth_hash":digest(samples)}
    target = output / "manifest.json"
    if target.exists() and json.loads(target.read_text(encoding="utf-8")) != manifest:
        raise RuntimeError("Existing dataset differs. Preserve it and use a new output directory.")
    target.write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    (output/"benchmark-source.py").write_bytes(Path(__file__).read_bytes())
    sheet = Image.new("RGB",(980,1170),"#eeeeee")
    for slot,index in enumerate((0,5,10,15,80,85,100,105,110,115,180,185)):
        sample = samples[index]
        with Image.open(output/sample["image"]) as original:
            preview = original.copy()
        preview.thumbnail((480,164))
        x,y = slot%2*490,slot//2*195
        sheet.paste(preview,(x,y+25))
        ImageDraw.Draw(sheet).text((x+8,y+5),sample["id"]+" / "+sample["language"]+" / "+sample["quality"],fill="black")
    sheet.save(output/"review-sheet.bmp")
    return manifest

def summarize(rows):
    fields = [field for row in rows for field in row["fields"]]
    correct = sum(field["correct"] for field in fields)
    rejected = sum(field["rejected"] for field in fields)
    unflagged = sum(field["unflagged_error"] for field in fields)
    return {"regions":len(rows),"critical_fields":len(fields),"correct_fields":correct,"accuracy":correct/len(fields),
            "rejected_or_missing_fields":rejected,"rejection_rate":rejected/len(fields),
            "unflagged_errors":unflagged,"unflagged_error_rate":unflagged/len(fields)}

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output",type=Path,default=ROOT/".local/ocr-holdout-v6")
    parser.add_argument("--partition",choices=("holdout","tuning"),default="holdout")
    parser.add_argument("--generate-only",action="store_true")
    args = parser.parse_args()
    if os.name != "nt":
        parser.error("Native OCR measurement requires Windows.")
    output = args.output.resolve()
    if not output.is_relative_to((ROOT/".local").resolve()):
        parser.error("Output must remain in the ignored .local directory.")
    adapter_names = ("services/ocr/app.py", "services/ocr/domain.py", "scripts/windows_ocr.ps1")
    adapter_sources = {name: (ROOT / name).read_bytes() for name in adapter_names}
    adapter_hashes = {name: hashlib.sha256(data).hexdigest() for name, data in adapter_sources.items()}
    manifest = generate(output,args.partition)
    print(f"Sealed 200 regions / 600 fields: {manifest['truth_hash']}",flush=True)
    if args.generate_only:
        return 0
    archived = output / "adapter-source"
    archived.mkdir()
    for name, data in adapter_sources.items():
        (archived / Path(name).name).write_bytes(data)
    engine = OCR(output/"private-worker")
    observations = []
    started = time.perf_counter()
    for sample in manifest["samples"]:
        image = (output/sample["image"]).read_bytes()
        if hashlib.sha256(image).hexdigest() != sample["image_sha256"]:
            raise RuntimeError("Sealed input changed.")
        request = {"observation_id":sample["id"],"image_base64":base64.b64encode(image).decode(),"language":sample["language"],
                   "bounds":{"x":0,"y":0,"width":sample["width"],"height":sample["height"]}}
        before = time.perf_counter()
        result = engine.recognize(request)
        elapsed = time.perf_counter()-before
        observations.append({"id":sample["id"],"language":sample["language"],"scale":sample["scale"],"quality":sample["quality"],
                             "elapsed_seconds":elapsed,"fields":score(sample["expected"],result["fields"],result.get("error")),
                             "raw_text":result["raw_text"],"observed_fields":result["fields"],
                             "lines":result["lines"],"numeric_reference":result.get("numeric_reference"),
                             "error":result.get("error")})
        if len(observations)%10 == 0:
            print(json.dumps({"completed":len(observations),**summarize(observations)}),flush=True)
    for name, expected_hash in adapter_hashes.items():
        if hashlib.sha256((ROOT / name).read_bytes()).hexdigest() != expected_hash:
            raise RuntimeError("OCR adapter changed during measurement; do not accept this run.")
    report = {"schema_version":1,"dataset_version":VERSION,"partition":args.partition,"truth_hash":manifest["truth_hash"],
              "generator_sha256":manifest["generator_sha256"],
              "adapter_sha256":adapter_hashes,
              "environment":{"os":platform.system(),"os_version":platform.version(),"architecture":platform.machine(),
                             "python":platform.python_version(),"ocr_languages":engine.languages,"font_names":manifest["font_names"]},
              "scope":("Independent synthetic holdout, excluded from tuning. " if args.partition=="holdout" else "Tuning partition; not acceptance evidence. ")+"Three fields only; no claims about game UI, affix names, icons or arbitrary layouts.",
              "denominator":"All labeled critical fields; missing, rejection, wrong value, lost sign and wrong unit count as incorrect.",
              "unflagged_definition":"Incorrect parsed fields not marked ambiguous. Every OCR observation still requires human confirmation.",
              "truth_review":"Pending manual review against rendered inputs; this measurement alone does not accept an M2 gate.",
              "overall":summarize(observations),"by_dimension":{},
              "latency":{"requests":200,"method":"Whole OCR.recognize call including PowerShell startup, BMP validation and field parsing.",
                         "p50_seconds":statistics.median(row["elapsed_seconds"] for row in observations),
                         "p95_seconds":percentile([row["elapsed_seconds"] for row in observations],0.95),
                         "total_seconds":time.perf_counter()-started},
              "targets":{"all_critical_field_accuracy":0.95,"ocr_p95_seconds":3.0}}
    for dimension in ("language","scale","quality"):
        groups = defaultdict(list)
        for row in observations:
            groups[str(row[dimension])].append(row)
        report["by_dimension"][dimension] = {value:summarize(rows) for value,rows in groups.items()}
    report["measured_target_pass"] = report["overall"]["accuracy"]>=0.95 and report["latency"]["p95_seconds"]<=3
    for name,value in (("observations.json",observations),("report.json",report)):
        (output/name).write_text(json.dumps(value,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(report,ensure_ascii=False,indent=2),flush=True)
    return 0 if report["measured_target_pass"] else 1

if __name__ == "__main__":
    raise SystemExit(main())

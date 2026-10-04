"""Private BMP regions to unconfirmed observations using native Windows OCR."""
from __future__ import annotations

import base64
import binascii
import hashlib
import json
import os
import re
import struct
import subprocess
import threading
import time
from pathlib import Path

from contracts import DomainError, identifier, object_value, parse_json, require
from services.ocr.domain import corroborate_fields, numeric_region_plan, recover_numeric_regions

ROOT = Path(__file__).resolve().parents[2]


def capture_context(value, bounds):
    """Validate capture provenance without promoting game/version claims to facts."""
    require(isinstance(value, dict) and set(value) == {
        "format_version", "game_id", "executable", "window_binding", "client_bounds",
        "relative_bounds", "verification", "captured_at_ms", "game_version", "game_build",
    }, "invalid_capture_context")
    require(type(value["format_version"]) is int and value["format_version"] == 1
            and value["game_id"] == "deskrawl" and value["executable"] == "Deskrawl.exe"
            and value["verification"] == "foreground_before_and_after"
            and value["game_version"] == "unknown" and value["game_build"] == "unknown",
            "invalid_capture_context")
    require(isinstance(value["window_binding"], str)
            and re.fullmatch(r"[0-9a-f]{32}", value["window_binding"]) is not None
            and type(value["captured_at_ms"]) is int and 0 < value["captured_at_ms"] < 2**53,
            "invalid_capture_context")
    rectangles = []
    for key in ("client_bounds", "relative_bounds"):
        rectangle = value[key]
        require(isinstance(rectangle, dict) and set(rectangle) == {"x", "y", "width", "height"}
                and all(type(rectangle[axis]) is int and -2**31 <= rectangle[axis] < 2**31
                        for axis in rectangle)
                and 0 < rectangle["width"] <= 65536 and 0 < rectangle["height"] <= 65536,
                "invalid_capture_context")
        rectangles.append(rectangle)
    client, relative = rectangles
    require(relative["x"] >= 0 and relative["y"] >= 0
            and relative["x"] + relative["width"] <= client["width"]
            and relative["y"] + relative["height"] <= client["height"]
            and bounds == {"x": client["x"] + relative["x"], "y": client["y"] + relative["y"],
                           "width": relative["width"], "height": relative["height"]},
            "capture_context_bounds_mismatch")
    return value


class OCR:
    def __init__(self, data_dir: Path, command: str | None = None):
        self.data_dir = data_dir.resolve()
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.command = command or str(Path(os.environ.get("WINDIR", "")) / "System32/WindowsPowerShell/v1.0/powershell.exe")
        self.script = ROOT / "scripts/windows_ocr.ps1"
        self.enabled = os.name == "nt" and Path(self.command).is_file() and self.script.is_file()
        self.languages = []
        if self.enabled:
            try:
                completed = subprocess.run([self.command, "-NoProfile", "-NonInteractive", "-File",
                                            str(self.script), "-Capabilities"], capture_output=True, timeout=6,
                                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                result = parse_json(completed.stdout.decode("utf-8-sig"))
                self.languages = result.get("languages", [])
                self.enabled = completed.returncode == 0 and bool(self.languages)
            except (DomainError, OSError, UnicodeError, subprocess.TimeoutExpired):
                self.enabled = False
        self.slot = threading.BoundedSemaphore(1)

    def handle(self, method, path, body):
        if method == "GET" and path == "/v1/health":
            return {"service": "ocr", "contract_version": 1, "available": self.enabled, "languages": self.languages}
        if method == "POST" and path == "/v1/regions":
            return self.recognize(body)
        raise DomainError("not_found", 404)

    def recognize(self, body):
        identifier(body.get("observation_id"))
        require(isinstance(body.get("image_base64"), str), "image_required")
        language = body.get("language", "en-US")
        require(isinstance(language, str) and re.fullmatch(r"[A-Za-z]{2,8}(?:-[A-Za-z0-9]{2,8}){0,2}", language)
                is not None, "invalid_ocr_language")
        try:
            image = base64.b64decode(body["image_base64"], validate=True)
        except (ValueError, binascii.Error):
            raise DomainError("invalid_image_encoding") from None
        require(54 <= len(image) <= 6 * 1024 * 1024 and image[:2] == b"BM", "bounded_bmp_required")
        offset = struct.unpack_from("<I", image, 10)[0]
        header, width, height, planes, bits, compression = struct.unpack_from("<IiiHHI", image, 14)
        require(header == 40 and planes == 1 and bits in (24, 32) and compression == 0,
                "unsupported_bmp_layout")
        require(0 < width <= 1600 and 0 < abs(height) <= 1200, "image_dimensions_exceeded")
        required = ((width * bits + 31) // 32) * 4 * abs(height)
        require(offset >= 54 and offset + required <= len(image), "incomplete_image")
        bounds = object_value(body.get("bounds"))
        require(all(type(bounds.get(key)) is int for key in ("x", "y", "width", "height")) and
                bounds["width"] == width and bounds["height"] == abs(height), "region_bounds_mismatch")
        context = capture_context(body["capture_context"], bounds) if "capture_context" in body else None
        image_hash = hashlib.sha256(image).hexdigest()
        path = self.data_dir / (image_hash + ".bmp")
        if not path.exists():
            path.write_bytes(image)
        result = {"observation_id": body["observation_id"], "method": "ocr", "state": "unconfirmed",
                  "image_ref": "capture://" + image_hash, "image_hash": image_hash,
                  "bounds": bounds, "language": language, "raw_text": "", "fields": [],
                  "lines": [], "requires_confirmation": True}
        if context is not None:
            result["capture_context"] = context
        if not self.enabled:
            return {**result, "error": "ocr_unavailable"}
        require(self.slot.acquire(blocking=False), "ocr_busy", 429)
        started = time.perf_counter()
        try:
            completed = subprocess.run([self.command, "-NoProfile", "-NonInteractive", "-File",
                                        str(self.script), "-ImagePath", str(path), "-Language", language],
                                       capture_output=True, timeout=12,
                                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            try:
                recognized = parse_json(completed.stdout.decode("utf-8-sig"))
            except (DomainError, UnicodeError):
                return {**result, "error": "ocr_failed"}
            if completed.returncode or recognized.get("error"):
                return {**result, "error": recognized.get("error", "ocr_failed")}
            text = recognized.get("text")
            require(isinstance(text, str) and len(text) <= 65536, "invalid_ocr_result")
            lines = recognized.get("lines", [])
            reference = recognized.get("numeric_reference")
            fields = corroborate_fields(text, lines, reference)
            plans = numeric_region_plan(text, lines, reference, width, abs(height)) if "en-US" in self.languages else []
            regions, region_error = self.numeric_regions(path, plans, 12-(time.perf_counter()-started)) if plans else ([], None)
            if plans:
                fields = recover_numeric_regions(text, lines, reference, plans, regions)
            result = {**result, "raw_text": text, "lines": lines, "numeric_reference": reference,
                      "fields": fields, "numeric_regions": regions}
            if region_error:
                result["numeric_region_error"] = region_error
            return result
        except OSError:
            return {**result, "error": "ocr_unavailable"}
        except subprocess.TimeoutExpired:
            return {**result, "error": "ocr_timeout"}
        finally:
            self.slot.release()

    def numeric_regions(self, path, plans, remaining):
        """One bounded helper call; optional failures preserve primary observations."""
        if remaining <= 0:
            return [], "ocr_timeout"
        request = base64.b64encode(json.dumps(
            [{"field": plan["field"], "bounds": plan["bounds"]} for plan in plans],
            separators=(",", ":")).encode()).decode()
        try:
            completed = subprocess.run([self.command, "-NoProfile", "-NonInteractive", "-File",
                                        str(self.script), "-ImagePath", str(path), "-Language", "en-US",
                                        "-NumericRegions", request],
                                       capture_output=True, timeout=min(6, remaining),
                                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            recognized = parse_json(completed.stdout.decode("utf-8-sig"))
            regions = recognized.get("numeric_regions")
            if (completed.returncode or recognized.get("error") or not isinstance(regions, list)
                or len(regions) != len(plans) or any(not isinstance(region, dict) for region in regions)):
                return [], "ocr_failed"
            return regions, None
        except (DomainError, OSError, UnicodeError, AttributeError):
            return [], "ocr_failed"
        except subprocess.TimeoutExpired:
            return [], "ocr_timeout"

"""Versioned wire helpers. Business models remain inside their services."""
from __future__ import annotations

import hashlib
import json
import math
import re
from datetime import datetime, timedelta, timezone

CONTRACT_VERSION = 1
CONTEXT_KEYS = ("game_id", "edition", "game_build", "mode", "season", "ruleset_id")


class DomainError(Exception):
    def __init__(self, code: str, status: int = 400):
        super().__init__(code)
        self.code, self.status = code, status


def require(condition: bool, code: str, status: int = 400) -> None:
    if not condition:
        raise DomainError(code, status)


def canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                      allow_nan=False)


def digest(value: object) -> str:
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def parse_json(raw: str | bytes):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate key")
            result[key] = value
        return result

    def invalid(_value):
        raise ValueError("non-finite number")

    def finite_float(value):
        parsed = float(value)
        if not math.isfinite(parsed):
            raise ValueError("non-finite number")
        return parsed

    try:
        return json.loads(raw, object_pairs_hook=unique, parse_constant=invalid, parse_float=finite_float)
    except (ValueError, UnicodeError, RecursionError):
        raise DomainError("invalid_json") from None


def identifier(value: object) -> str:
    require(isinstance(value, str) and re.fullmatch(r"[a-zA-Z0-9_.-]{1,100}", value)
            is not None, "invalid_identifier")
    return value


def object_value(value: object) -> dict:
    require(isinstance(value, dict), "object_required")
    return value


def strings(value: object, code="string_list_required") -> list[str]:
    require(isinstance(value, list) and all(isinstance(x, str) for x in value), code)
    return value


def context(value: object) -> dict:
    value = object_value(value)
    require(all(isinstance(value.get(key), str) and 0 < len(value[key]) <= 100
                for key in CONTEXT_KEYS), "context_fields_required")
    strings(value.get("content_entitlements"), "content_entitlements_required")
    return value


def timestamp(value: object) -> datetime:
    require(isinstance(value, str), "capture_time_required")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise DomainError("invalid_capture_time") from None
    require(parsed.tzinfo is not None, "capture_timezone_required")
    return parsed



def timestamp_milliseconds(value: object) -> datetime:
    """Convert a positive wire millisecond instant exactly, without float rounding."""
    require(type(value) is int and 0 < value < 2**53, "invalid_capture_time")
    try:
        return datetime(1970, 1, 1, tzinfo=timezone.utc) + timedelta(milliseconds=value)
    except OverflowError:
        raise DomainError("invalid_capture_time") from None


def number(value: object) -> bool:
    if isinstance(value, bool) or not isinstance(value, (float, int)):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False

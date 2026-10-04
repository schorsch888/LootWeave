"""Offline v1 backup and restore. Existing data is never overwritten.

Only capability databases and OCR capture evidence are included. WebView cache,
build products and lock files are excluded. A restore always creates a new directory.
"""
from __future__ import annotations

import argparse
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import time
import uuid

from contracts import DomainError, parse_json, require
from storage import acquire_instance_lock
from version import __version__

DATABASES = ("profile/profile.sqlite3", "evaluation/evaluation.sqlite3", "planning/planning.sqlite3")
CAPTURE = re.compile(r"ocr/[0-9a-f]{64}\.bmp\Z")
MAX_FILE = 512 * 1024 * 1024
MAX_TOTAL = 2 * 1024 * 1024 * 1024
MAX_FILES = 10000


def ordinary(path: Path):
    require(not path.is_symlink() and not path.is_junction(), "backup_link_rejected")
    return path.resolve()


def checksum(path: Path):
    value = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(65536), b""):
            value.update(chunk)
    return value.hexdigest()


def recognized(name):
    return name in DATABASES or bool(CAPTURE.fullmatch(name))


def check_database(path):
    with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=3)) as db:
        require(db.execute("PRAGMA user_version").fetchone()[0] == 1, "incompatible_backup_storage")
        require(db.execute("PRAGMA integrity_check").fetchall() == [("ok",)], "backup_database_corrupted")


def target_stage(source: Path, destination: Path):
    source, destination = ordinary(source), ordinary(destination)
    require(source.is_dir(), "backup_source_missing")
    require(not destination.exists(), "backup_destination_exists", 409)
    require(not destination.is_relative_to(source) and not source.is_relative_to(destination),
            "backup_directories_overlap")
    destination.parent.mkdir(parents=True, exist_ok=True)
    stage = destination.parent / (".lootweave-stage-" + uuid.uuid4().hex)
    stage.mkdir()
    return source, destination, stage


def verify(backup_dir: Path):
    root = ordinary(backup_dir)
    manifest_path = root / "backup-manifest.json"
    require(manifest_path.is_file() and ordinary(manifest_path).stat().st_size <= 2 * 1024 * 1024,
            "backup_manifest_missing")
    manifest = parse_json(manifest_path.read_bytes())
    require(isinstance(manifest, dict) and type(manifest.get("format_version")) is int
            and manifest["format_version"] == 1 and type(manifest.get("storage_version")) is int
            and manifest["storage_version"] == 1, "incompatible_backup")
    expected = manifest.get("files")
    require(isinstance(expected, dict) and 0 < len(expected) <= MAX_FILES, "invalid_backup_manifest")
    for name, entry in expected.items():
        require(isinstance(name, str) and recognized(name) and isinstance(entry, dict)
                and set(entry) == {"size", "sha256"} and type(entry["size"]) is int
                and 0 <= entry["size"] <= MAX_FILE and isinstance(entry["sha256"], str)
                and re.fullmatch("[0-9a-f]{64}", entry["sha256"]), "invalid_backup_manifest")
    require(any(name in DATABASES for name in expected), "backup_database_missing")
    actual = {}
    total = 0
    for path in root.rglob("*"):
        ordinary(path)
        if path.is_dir():
            continue
        require(path.is_file(), "backup_file_invalid")
        name = path.relative_to(root).as_posix()
        if name == "backup-manifest.json":
            continue
        require(recognized(name) and len(actual) < MAX_FILES, "backup_file_unrecognized")
        size = path.stat().st_size
        total += size
        require(size <= MAX_FILE and total <= MAX_TOTAL, "backup_size_exceeded")
        value = checksum(path)
        require(not CAPTURE.fullmatch(name) or path.stem == value, "backup_capture_corrupted")
        actual[name] = {"size": size, "sha256": value}
    require(actual == expected, "backup_integrity_error")
    for name in DATABASES:
        if name in actual:
            check_database(root / name)
    return manifest


def backup(data_dir: Path, destination: Path):
    data_dir, destination, stage = target_stage(data_dir, destination)
    files = {}
    total = 0
    with closing(acquire_instance_lock(data_dir)):
        for name in DATABASES:
            source = data_dir / name
            if not source.exists():
                continue
            ordinary(source.parent)
            ordinary(source)
            require(source.is_file() and source.stat().st_size <= MAX_FILE, "backup_size_exceeded")
            check_database(source)
            target = stage / name
            target.parent.mkdir(parents=True, exist_ok=True)
            with closing(sqlite3.connect(source.as_uri() + "?mode=ro", uri=True, timeout=3)) as original, \
                    closing(sqlite3.connect(target)) as copied:
                deadline = time.monotonic() + 30
                def progress(*_):
                    require(time.monotonic() < deadline, "backup_database_timeout")
                original.backup(copied, pages=256, progress=progress, sleep=.05)
            size = target.stat().st_size
            total += size
            require(size <= MAX_FILE and total <= MAX_TOTAL, "backup_size_exceeded")
            files[name] = {"size": size, "sha256": checksum(target)}
        captures = data_dir / "ocr"
        if captures.exists():
            ordinary(captures)
            for source in sorted(captures.iterdir()):
                name = "ocr/" + source.name
                require(recognized(name), "backup_file_unrecognized")
                ordinary(source)
                require(source.is_file(), "backup_file_invalid")
                size = source.stat().st_size
                total += size
                require(size <= MAX_FILE and total <= MAX_TOTAL and len(files) < MAX_FILES,
                        "backup_size_exceeded")
                target = stage / name
                target.parent.mkdir(exist_ok=True)
                with source.open("rb") as original, target.open("xb") as copied:
                    for chunk in iter(lambda: original.read(65536), b""):
                        copied.write(chunk)
                files[name] = {"size": size, "sha256": checksum(target)}
        require(any(name in files for name in DATABASES), "backup_database_missing")
        manifest = {"format_version": 1, "storage_version": 1, "application_version": __version__,
                    "created_at": datetime.now(timezone.utc).isoformat(), "files": files}
        (stage / "backup-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        verify(stage)
        require(not destination.exists(), "backup_destination_exists", 409)
        stage.rename(destination)
    return manifest


def restore(backup_dir: Path, destination: Path):
    # Validate before creating a target. Failed restores never touch existing data.
    manifest = verify(backup_dir)
    source, destination, stage = target_stage(backup_dir, destination)
    for name in manifest["files"]:
        target = stage / name
        target.parent.mkdir(parents=True, exist_ok=True)
        with (source / name).open("rb") as original, target.open("xb") as copied:
            for chunk in iter(lambda: original.read(65536), b""):
                copied.write(chunk)
    # Recheck copied bytes and schemas, including changes during the copy.
    (stage / "backup-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    verify(stage)
    require(not destination.exists(), "backup_destination_exists", 409)
    stage.rename(destination)
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    operations = parser.add_subparsers(dest="operation", required=True)
    save = operations.add_parser("backup")
    save.add_argument("--data-dir", type=Path, required=True)
    save.add_argument("--destination", type=Path, required=True)
    load = operations.add_parser("restore")
    load.add_argument("--backup-dir", type=Path, required=True)
    load.add_argument("--destination", type=Path, required=True)
    args = parser.parse_args()
    try:
        manifest = backup(args.data_dir, args.destination) if args.operation == "backup" else \
            restore(args.backup_dir, args.destination)
    except (DomainError, OSError, sqlite3.Error) as error:
        code = error.code if isinstance(error, DomainError) else "maintenance_io_failed"
        print(json.dumps({"error": code}), flush=True)
        return 1
    print(json.dumps({"operation": args.operation, "storage_version": 1, "files": len(manifest["files"])}),
          flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

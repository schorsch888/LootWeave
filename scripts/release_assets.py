#!/usr/bin/env python3
"""Stage or verify Windows assets built on a GitHub Actions runner."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PORTABLE_SOURCE = Path("dist/LootWeave-portable-windows-x64.zip")
INSTALLER_DIR = Path("desktop/target/release/bundle/nsis")
MANIFEST_NAME = "build-manifest.json"
SUMS_NAME = "SHA256SUMS.txt"


class ReleaseError(Exception):
    pass


def require(condition, message):
    if not condition:
        raise ReleaseError(message)


def commit_id(value):
    require(isinstance(value, str) and re.fullmatch(r"[0-9a-fA-F]{40}", value) is not None,
            "source commit must be exactly 40 hexadecimal characters")
    return value.lower()


def version(root):
    try:
        value = json.loads((root / "desktop/tauri.conf.json").read_text(encoding="utf-8"))["version"]
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise ReleaseError("cannot read Tauri application version") from error
    require(isinstance(value, str) and re.fullmatch(r"[0-9A-Za-z][0-9A-Za-z.+-]*", value) is not None,
            "Tauri version is invalid")
    return value


def sha256_file(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def portable_source_commit(path):
    try:
        with zipfile.ZipFile(path) as archive:
            names = archive.namelist()
            require(names.count("portable.json") == 1, "portable ZIP must contain one root portable.json")
            marker = json.loads(archive.read("portable.json"))
    except (OSError, zipfile.BadZipFile, ValueError, KeyError, TypeError) as error:
        raise ReleaseError("cannot read portable ZIP source commit") from error
    require(isinstance(marker, dict), "portable.json schema is invalid")
    return commit_id(marker.get("source_commit"))


def installer_source(root):
    directory = root / INSTALLER_DIR
    require(directory.is_dir() and not directory.is_symlink(), "NSIS installer directory is invalid")
    try:
        installers = sorted(path for path in directory.glob("*.exe") if path.is_file() and not path.is_symlink())
    except OSError as error:
        raise ReleaseError("cannot inspect NSIS installer directory") from error
    require(len(installers) == 1, "expected exactly one NSIS installer .exe")
    return installers[0]


def expected_names(app_version):
    return [f"LootWeave-{app_version}-portable-windows-x64.zip",
            f"LootWeave-{app_version}-windows-x64-setup.exe"]


def stage_release(root: Path, source_commit: str):
    root, source_commit = Path(root), commit_id(source_commit)
    app_version = version(root)
    portable = root / PORTABLE_SOURCE
    require(portable.is_file() and not portable.is_symlink(), "portable ZIP is missing or not a regular file")
    require(portable_source_commit(portable) == source_commit, "portable ZIP source commit does not match")
    installer = installer_source(root)
    output = root / "dist/release"
    require(not output.exists(), "dist/release already exists; refusing to overwrite")
    names = expected_names(app_version)
    output.mkdir(parents=True, exist_ok=False)
    created = []
    try:
        for source, name in zip((portable, installer), names):
            destination = output / name
            with source.open("rb") as src, destination.open("xb") as dst:
                created.append(destination)
                shutil.copyfileobj(src, dst, 1024 * 1024)
        files = [{"name": name, "bytes": (output / name).stat().st_size,
                  "sha256": sha256_file(output / name)} for name in names]
        manifest = {"format_version": 1, "source_commit": source_commit,
                    "version": app_version, "files": files}
        manifest_path = output / MANIFEST_NAME
        with manifest_path.open("x", encoding="utf-8", newline="\n") as stream:
            created.append(manifest_path)
            stream.write(json.dumps(manifest, indent=2) + "\n")
        sums = "".join(f"{entry['sha256']}  {entry['name']}\n" for entry in files)
        sums_path = output / SUMS_NAME
        with sums_path.open("x", encoding="utf-8", newline="\n") as stream:
            created.append(sums_path)
            stream.write(sums)
    except Exception:
        for path in created:
            try:
                path.unlink()
            except OSError:
                pass
        try:
            output.rmdir()
        except OSError:
            pass
        raise
    return output


def verify_release(root: Path, source_commit: str):
    root, source_commit = Path(root), commit_id(source_commit)
    app_version = version(root)
    directory = root / "dist/release"
    names = expected_names(app_version)
    expected_entries = set(names) | {MANIFEST_NAME, SUMS_NAME}
    require(directory.is_dir() and not directory.is_symlink(), "dist/release is missing or invalid")
    actual_entries = {path.name for path in directory.iterdir()}
    require(actual_entries == expected_entries and all((directory / name).is_file() and not (directory / name).is_symlink() for name in expected_entries),
            "release directory contains missing, extra, or non-file entries")
    try:
        manifest = json.loads((directory / MANIFEST_NAME).read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise ReleaseError("build manifest is unreadable") from error
    require(isinstance(manifest, dict) and set(manifest) == {"format_version", "source_commit", "version", "files"}
            and manifest.get("format_version") == 1 and manifest.get("source_commit") == source_commit
            and manifest.get("version") == app_version, "build manifest identity or schema is invalid")
    entries = manifest.get("files")
    require(isinstance(entries, list) and len(entries) == 2 and all(isinstance(item, dict) for item in entries),
            "build manifest must describe exactly two release files")
    require(all(set(item) == {"name", "bytes", "sha256"} for item in entries)
            and [item["name"] for item in entries] == names, "manifest file names or schema are invalid")
    for entry in entries:
        require(type(entry["bytes"]) is int and entry["bytes"] >= 0
                and isinstance(entry["sha256"], str)
                and re.fullmatch(r"[0-9a-f]{64}", entry["sha256"]) is not None,
                "manifest file size or hash is invalid")
        path = directory / entry["name"]
        require(path.stat().st_size == entry["bytes"] and sha256_file(path) == entry["sha256"],
                f"release asset does not match manifest: {entry['name']}")
    require(portable_source_commit(directory / names[0]) == source_commit,
            "portable ZIP source commit does not match manifest")
    expected_sums = "".join(f"{item['sha256']}  {item['name']}\n" for item in entries)
    require((directory / SUMS_NAME).read_text(encoding="utf-8") == expected_sums,
            "SHA256SUMS.txt does not match release files")
    return directory


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--verify", action="store_true", help="verify existing dist/release")
    args = parser.parse_args(argv)
    try:
        output = verify_release(ROOT, args.source_commit) if args.verify else stage_release(ROOT, args.source_commit)
    except (ReleaseError, OSError) as error:
        parser.error(str(error))
    print(f"{'Verified' if args.verify else 'Staged'} release assets: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
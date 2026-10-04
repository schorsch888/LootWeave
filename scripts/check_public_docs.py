#!/usr/bin/env python3
"""Check public repository candidates without printing matched private content.

This is a conservative documentation preflight, not a comprehensive secret scanner.
It requires Git and Python's standard library. No game installation is required.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path
from urllib.parse import unquote, urlsplit


ROOT = Path(__file__).resolve().parents[1]
TEXT_SUFFIXES = {".md", ".json", ".jsonl", ".py", ".ps1", ".toml", ".yaml", ".yml", ".txt", ".rst", ".ini", ".cfg", ".csv", ".ts", ".tsx", ".css", ".html", ".rs", ".mjs", ".lock"}
PRIVATE_PARTS = {".tools", "data/extracted", ".local", "private", "captures", "screenshots", ".codex", ".aws"}
PRIVATE_SUFFIXES = {".exe", ".dll", ".pdb", ".dmp", ".assets", ".bundle", ".ress", ".resource", ".key", ".pfx", ".p12", ".d2s", ".d2i"}
PATTERNS = {
    "absolute_windows_path": re.compile(r"(?<![A-Za-z0-9])[A-Za-z]:[\\/]"),
    "absolute_user_path": re.compile(r"/(?:Users|home)/[^/\s<>]+/", re.IGNORECASE),
    "unc_path": re.compile(r"(?<![\\])\\\\[A-Za-z0-9_.-]+\\[A-Za-z0-9_$.-]+"),
    "windows_user_sid": re.compile(r"\bS-1-5-21-\d+-\d+-\d+-\d+\b"),
    "steam_account_id": re.compile(r"(?<![A-Za-z0-9])7656119\d{10}(?![A-Za-z0-9])"),
    "email_address": re.compile(r"(?<![\w.+-])[\w.+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}(?!\w)"),
    "github_token": re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{30,})\b"),
    "api_secret": re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_-]{24,}\b"),
    "private_key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
}
PERSONAL_JSON_KEYS = {"stats_from_user_screenshot", "reference_character", "lastowner", "steamid", "steam_id", "lastupdated"}


def git(*args: str) -> bytes:
    result = subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True)
    if result.returncode:
        raise RuntimeError("Git enumeration failed; check repository access and ownership locally.")
    return result.stdout


def public_paths() -> list[Path]:
    names = git("ls-files", "--cached", "--others", "--exclude-standard", "-z").decode("utf-8").split("\0")
    return sorted({ROOT / name for name in names if name})


def private_artifact(path: Path) -> bool:
    relative = path.relative_to(ROOT).as_posix()
    return (
        any(relative == prefix or relative.startswith(prefix + "/") for prefix in PRIVATE_PARTS)
        or path.suffix.lower() in PRIVATE_SUFFIXES
        or path.name.lower() in {"save.json", "global-metadata.dat"}
        or path.name.startswith("codex-clipboard-")
        or (path.name.startswith(".env") and path.name != ".env.example")
    )


def json_keys(value: object) -> set[str]:
    keys: set[str] = set()
    if isinstance(value, dict):
        for key, item in value.items():
            keys.add(key.lower())
            keys.update(json_keys(item))
    elif isinstance(value, list):
        for item in value:
            keys.update(json_keys(item))
    return keys


def check(paths: list[Path], local_paths: set[Path],
          public_candidates: set[Path] | None = None) -> tuple[list[tuple[str, int, str]], int]:
    findings: list[tuple[str, int, str]] = []
    count = 0
    if public_candidates is None:
        public_candidates = set(paths) - local_paths

    def report(path: Path, line: int, category: str) -> None:
        findings.append((path.relative_to(ROOT).as_posix(), line, category))

    for path in paths:
        if path.is_symlink():
            report(path, 1, "symlink_requires_review")
            continue
        if not path.exists():  # A deletion in the working tree is not published content.
            continue
        if not path.is_file():
            continue
        if path not in local_paths and private_artifact(path):
            report(path, 1, "private_artifact_in_public_candidates")
        if path.suffix.lower() not in TEXT_SUFFIXES and path.name not in {".gitignore", ".gitattributes", "LICENSE", "NOTICE"}:
            report(path, 1, "unreviewed_file_type")
            continue
        try:
            source = path.read_text(encoding="utf-8-sig")
        except (UnicodeError, OSError):
            report(path, 1, "unreadable_text")
            continue
        count += 1
        for category, pattern in PATTERNS.items():
            for match in pattern.finditer(source):
                report(path, source.count("\n", 0, match.start()) + 1, category)

        if path.suffix.lower() in {".json", ".jsonl"}:
            documents = source.splitlines() if path.suffix.lower() == ".jsonl" else [source]
            for line, document in enumerate(documents, 1):
                if not document.strip():
                    continue
                try:
                    value = json.loads(document)
                except json.JSONDecodeError:
                    report(path, line, "invalid_json")
                    continue
                if json_keys(value) & PERSONAL_JSON_KEYS:
                    report(path, line, "personal_json_fields_require_removal")

        if path.suffix.lower() != ".md":
            continue
        # Local targets must be publishable, not merely present in the workspace.
        # Remote availability and heading anchors still need review.
        markdown = re.sub(r"(?ms)^```[^\n]*\n.*?^```\s*$", lambda match: "\n" * match.group(0).count("\n"), source)
        for match in re.finditer(r"!?\[[^\]\n]*\]\((<[^>]+>|[^\s)]+)(?:\s+\"[^\"]*\")?\)", markdown):
            line = markdown.count("\n", 0, match.start()) + 1
            target = match.group(1).strip("<>")
            parsed = urlsplit(target)
            if parsed.scheme or parsed.netloc or not parsed.path:
                continue
            destination = (path.parent / unquote(parsed.path)).resolve()
            if not destination.is_relative_to(ROOT):
                report(path, line, "local_link_outside_repository")
            elif not destination.exists():
                report(path, line, "missing_local_link")
            elif path not in local_paths and private_artifact(destination):
                report(path, line, "public_link_to_private_artifact")
            elif path not in local_paths:
                included = (any(p.is_file() and not p.is_symlink() and p.is_relative_to(destination)
                                for p in public_candidates)
                            if destination.is_dir() else destination in public_candidates)
                if not included:
                    report(path, line, "local_link_not_in_public_candidates")

    return sorted(set(findings)), count


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--include-local-reports", action="store_true", help="Also inspect generated extraction text and tool provenance; they remain unpublished.")
    args = parser.parse_args()
    try:
        candidates = public_paths()
    except (OSError, RuntimeError) as error:
        print(str(error))
        return 2
    local_paths: set[Path] = set()
    if args.include_local_reports:
        root = ROOT / "data" / "extracted"
        if root.exists():
            local_paths.update(p for p in root.rglob("*") if p.is_file() and p.suffix.lower() in TEXT_SUFFIXES)
        provenance = ROOT / ".tools" / "cpp2il" / "provenance.json"
        if provenance.exists():
            local_paths.add(provenance)
    findings, count = check(sorted(set(candidates) | local_paths), local_paths, set(candidates))
    for path, line, category in findings:
        print(f"{path}:{line}: {category}")
    print(f"Checked {count} text files; findings: {len(findings)}. Pattern checks do not replace publication review.")
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())

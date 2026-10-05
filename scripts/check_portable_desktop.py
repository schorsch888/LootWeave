#!/usr/bin/env python3
"""Verify a portable ZIP's contents and its native default-path persistence."""
from __future__ import annotations

import argparse
import ctypes
from ctypes import wintypes
import hashlib
import json
import os
import shutil
import time
import uuid
import zipfile
from pathlib import Path, PurePosixPath

from check_desktop import CheckFailed, Desktop, ROOT, fictional_flow, replay


def fail(code):
    raise CheckFailed(code)


def expect(condition, code):
    if not condition:
        fail(code)


def hash_file(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def hash_zip_entry(archive, name):
    digest = hashlib.sha256()
    with archive.open(name) as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def safe_name(name):
    path = PurePosixPath(name)
    return bool(name) and "\\" not in name and not path.is_absolute() and ".." not in path.parts and "." not in path.parts and path.as_posix() == name


def verify_archive(path):
    with zipfile.ZipFile(path) as archive:
        infos = archive.infolist()
        names = [info.filename for info in infos]
        expect(len(names) == len(set(names)) and all(safe_name(name) for name in names), "archive_paths_invalid")
        expect(all(not info.is_dir() for info in infos), "archive_contains_unexpected_directory_entries")
        expect("portable.json" in names, "portable_marker_missing")
        marker = json.loads(archive.read("portable.json"))
        files = marker.get("files")
        expect(marker.get("format_version") == 1 and marker.get("publisher") == "lootweave-portable"
               and marker.get("platform") == "windows-x64" and isinstance(files, dict), "portable_marker_invalid")
        expect("portable.json" not in files and all(safe_name(name) for name in files), "portable_file_map_invalid")
        expect(set(names) == set(files) | {"portable.json"}, "portable_archive_file_set_mismatch")
        expect("LootWeave.exe" in files and "sidecar/bundle-manifest.json" in files
               and "webview2/msedgewebview2.exe" in files
               and all(name in files and "sidecar/" + name in files
                       for name in ("vcruntime140.dll", "vcruntime140_1.dll")), "portable_required_file_missing")
        expect(len(marker.get("source_commit", "")) == 40 and all(c in "0123456789abcdef" for c in marker["source_commit"]),
               "portable_source_commit_invalid")
        for name, expected in files.items():
            expect(isinstance(expected, str) and hash_zip_entry(archive, name) == expected.lower(),
                   "portable_file_hash_mismatch")
        sidecar = json.loads(archive.read("sidecar/bundle-manifest.json"))
        expect(sidecar.get("publisher") == "lootweave-build" and sidecar.get("platform") == "windows-x64",
               "portable_sidecar_manifest_invalid")
        expect(isinstance(marker.get("webview_version"), str) and marker["webview_version"],
               "portable_webview_version_missing")
        return marker, names


def within(path, root):
    resolved, boundary = path.resolve(), root.resolve()
    expect(resolved == boundary or boundary in resolved.parents, "portable_stage_path_escape")
    return resolved


def verify_local_crt(app, directory):
    api = ctypes.WinDLL("psapi", use_last_error=True)
    api.EnumProcessModulesEx.argtypes = (wintypes.HANDLE, ctypes.POINTER(ctypes.c_void_p), wintypes.DWORD,
                                        ctypes.POINTER(wintypes.DWORD), wintypes.DWORD)
    api.EnumProcessModulesEx.restype = wintypes.BOOL
    api.GetModuleFileNameExW.argtypes = (wintypes.HANDLE, ctypes.c_void_p, wintypes.LPWSTR, wintypes.DWORD)
    api.GetModuleFileNameExW.restype = wintypes.DWORD
    for process in (app.host_handle, *app.workers):
        modules = (ctypes.c_void_p * 2048)()
        used = wintypes.DWORD()
        expect(api.EnumProcessModulesEx(process.handle, modules, ctypes.sizeof(modules), ctypes.byref(used), 3),
               "portable_module_query_failed")
        expect(used.value <= ctypes.sizeof(modules), "portable_module_list_exceeded")
        loaded = set()
        for module in modules[:used.value // ctypes.sizeof(ctypes.c_void_p)]:
            name = ctypes.create_unicode_buffer(32768)
            expect(api.GetModuleFileNameExW(process.handle, module, name, len(name)), "portable_module_path_unavailable")
            path = Path(name.value).resolve()
            if path.name.lower() in ("vcruntime140.dll", "vcruntime140_1.dll"):
                expected = [directory] if process is app.host_handle else [directory / "sidecar", directory / "sidecar/_internal"]
                expect(path.parent in [folder.resolve() for folder in expected], "portable_crt_loaded_outside_package")
                loaded.add(path.name.lower())
        if process is app.host_handle:
            expect(loaded == {"vcruntime140.dll", "vcruntime140_1.dll"}, "portable_host_crt_missing")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path)
    args = parser.parse_args()
    if os.name != "nt":
        parser.error("Requires the Windows native desktop host.")
    archive = args.archive.resolve()
    if not archive.is_file():
        parser.error("Portable archive does not exist.")
    started = time.perf_counter()
    marker, _ = verify_archive(archive)
    check_root = ROOT / ".local/portable-check" / uuid.uuid4().hex
    check_root.mkdir(parents=True)
    extracted = check_root / "LootWeave portable 验收目录"
    moved = check_root / "移动后 portable 目录"
    report = {"artifact_sha256": hash_file(archive), "webview_version": marker["webview_version"],
              "source_commit": marker["source_commit"], "checks": [], "elapsed_seconds": 0, "passed": False}
    app = None
    stage = "extract"
    failure = None
    try:
        within(extracted, check_root).parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(archive) as bundle:
            bundle.extractall(extracted)
        expect((extracted / "portable.json").is_file(), "portable_marker_not_extracted")
        report["checks"].append("archive_file_hashes_and_exact_contents")
        app = Desktop(extracted / "LootWeave.exe", extracted / "sidecar", extracted / "data", default_paths=True, cwd=ROOT)
        stage = "portable_first_run"
        verify_local_crt(app, extracted)
        report["checks"].append("host_and_workers_load_application_local_vc_runtime")
        fictional_flow(app)
        profile = app.call("GET", "/api/profile/profiles/desktop-fixture/revisions/1")
        evaluation = app.call("GET", "/api/evaluation/evaluations/desktop-evaluation")
        expect((extracted / "data/profile/profile.sqlite3").is_file()
               and (extracted / "data/evaluation/evaluation.sqlite3").is_file(), "portable_data_not_saved_beside_exe")
        for _ in range(10):
            replay(app)
        report["checks"] += ["portable_default_paths_create_local_sqlite", "synthetic_profile_evaluation_and_ten_replays"]
        app.stop()
        expect(app.process.returncode == 0, "portable_first_host_exit_failed")
        app = None
        source = within(extracted, check_root)
        target = within(moved, check_root)
        expect(not target.exists(), "portable_move_target_exists")
        shutil.move(str(source), str(target))
        stage = "portable_after_move"
        app = Desktop(moved / "LootWeave.exe", moved / "sidecar", moved / "data", default_paths=True, cwd=ROOT)
        verify_local_crt(app, moved)
        moved_profile = app.call("GET", "/api/profile/profiles/desktop-fixture/revisions/1")
        moved_evaluation = app.call("GET", "/api/evaluation/evaluations/desktop-evaluation")
        expect(moved_profile == profile and moved_evaluation == evaluation, "portable_move_changed_saved_data")
        for _ in range(10):
            replay(app)
        expect((moved / "data/profile/profile.sqlite3").is_file()
               and (moved / "data/evaluation/evaluation.sqlite3").is_file(), "portable_moved_data_missing")
        report["checks"] += ["moved_portable_uses_executable_relative_paths", "moved_profile_evaluation_and_ten_replays_match"]
        app.stop()
        expect(app.process.returncode == 0, "portable_moved_host_exit_failed")
        app = None
        report["passed"] = True
    except Exception as error:
        failure = (stage, str(error) if isinstance(error, CheckFailed) else type(error).__name__)
    finally:
        if app is not None:
            try:
                app.stop()
            except Exception:
                failure = (stage, "owned_worker_cleanup_failed")
        report["elapsed_seconds"] = round(time.perf_counter() - started, 3)
        if failure:
            report["failure_stage"], report["failure_code"] = failure
            report["passed"] = False
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if failure:
        print(f"Portable check failed: {failure[0]} ({failure[1]}); evidence retained.")
        return 1
    print(f"Portable check passed: {len(report['checks'])} checks in {report['elapsed_seconds']}s; report={args.report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
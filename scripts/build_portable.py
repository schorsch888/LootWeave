#!/usr/bin/env python3
"""Build an offline Windows x64 portable ZIP from already-built inputs."""
import argparse
import hashlib
import json
import os
import re
import shutil
import uuid
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXED = re.compile(r"^Microsoft\.WebView2\.FixedVersionRuntime\.(\d+\.\d+\.\d+\.\d+)\.x64$")
README = """LootWeave 绿色版 / Portable — Windows 10/11 x64

完整解压到本地可写目录，双击 LootWeave.exe 即可启动；无需安装 Python 或 WebView2。
个人档案、SQLite、OCR 截图和浏览器数据保存在旁边的 data/。先退出应用再移动整个目录；升级时保留 data/。
OCR 使用 Windows 已有语言模型，缺少模型时仍可手动输入。两台干净机器的发行验收尚未通过。

Extract this folder and double-click LootWeave.exe. The extracted folder must be locally writable.
LootWeave saves its SQLite database and OCR data under data/ beside the executable. Keep data/ when updating the application.
No Python, WebView2 or Visual C++ Runtime installation is required; this package includes its Fixed Version browser and application-local CRT DLLs.
OCR language models depend on those already available on Windows. If OCR cannot read a language, enter the observation manually.
This build has not completed acceptance on two clean machines.
"""


def fail(message):
    raise SystemExit(message)


def is_reparse(path):
    info = path.lstat()
    return path.is_symlink() or bool(getattr(info, "st_file_attributes", 0) & 0x400)


def files_under(root):
    found = []
    for base, dirs, names in os.walk(root, followlinks=False):
        base = Path(base)
        for name in list(dirs) + names:
            path = base / name
            if is_reparse(path):
                fail(f"reparse point or symlink is not allowed: {path}")
        for name in names:
            path = base / name
            if not path.is_file():
                fail(f"not a regular file: {path}")
            found.append(path)
    return sorted(found)


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def copy_file(source, destination):
    destination.parent.mkdir(parents=True, exist_ok=True)
    with source.open("rb") as src, destination.open("xb") as dst:
        shutil.copyfileobj(src, dst, 1024 * 1024)


def check_sidecar(root):
    manifest_path = root / "bundle-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if (manifest.get("format_version") != 1 or manifest.get("publisher") != "lootweave-build"
            or manifest.get("platform") != "windows-x64" or not isinstance(manifest.get("files"), dict)):
        fail("sidecar bundle-manifest.json has unexpected identity or format")
    actual = {p.relative_to(root).as_posix(): p for p in files_under(root) if p != manifest_path}
    expected = manifest["files"]
    if set(actual) != set(expected):
        fail("sidecar manifest file list does not exactly match the directory")
    for relative, path in actual.items():
        if not isinstance(expected[relative], str) or sha256(path) != expected[relative].lower():
            fail(f"sidecar SHA-256 mismatch: {relative}")
    return actual


def runtime_version(root):
    if not (root / "msedgewebview2.exe").is_file():
        fail("webview runtime must directly contain msedgewebview2.exe")
    match = FIXED.fullmatch(root.name)
    if not match:
        fail("webview runtime folder must be Microsoft.WebView2.FixedVersionRuntime.<version>.x64")
    return match.group(1)
def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--executable", required=True, type=Path)
    parser.add_argument("--resources", type=Path, default=ROOT / "dist/sidecar")
    parser.add_argument("--webview-runtime", required=True, type=Path)
    parser.add_argument("--vc-runtime-dir", required=True, type=Path, help="Visual Studio x64 redistributable CRT directory")
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--source-commit", required=True)
    args = parser.parse_args()
    executable, resources, runtime = (p.absolute() for p in (args.executable, args.resources, args.webview_runtime))
    output = args.output.absolute()
    if not re.fullmatch(r"[0-9a-fA-F]{40}", args.source_commit):
        fail("--source-commit must be a 40-character Git commit hash")
    if not executable.is_file() or is_reparse(executable):
        fail("--executable must be a regular, non-reparse file")
    if not resources.is_dir() or is_reparse(resources) or not runtime.is_dir() or is_reparse(runtime):
        fail("--resources and --webview-runtime must be regular directories")
    executable, resources, runtime = (p.resolve() for p in (executable, resources, runtime))
    sidecar = check_sidecar(resources)
    runtime_files = files_under(runtime)
    version = runtime_version(runtime)
    vc_runtime = args.vc_runtime_dir.resolve()
    crt = [vc_runtime / name for name in ("vcruntime140.dll", "vcruntime140_1.dll")]
    if not vc_runtime.is_dir() or is_reparse(vc_runtime) or any(not path.is_file() or is_reparse(path) for path in crt):
        fail("--vc-runtime-dir must contain both regular x64 VCRUNTIME DLLs from Visual Studio Redist")
    output_resolved = output.resolve(strict=False)
    if output.exists():
        fail(f"output already exists: {output}")
    for protected in (executable, resources, runtime, vc_runtime, (ROOT / ".local/portable-build").resolve()):
        if output_resolved == protected or protected.is_dir() and output_resolved.is_relative_to(protected):
            fail("output must not overwrite an input or staging directory")
    local_root = ROOT / ".local"
    stage_root = local_root / "portable-build"
    if local_root.exists() and (not local_root.is_dir() or is_reparse(local_root)):
        fail(".local must be a regular directory")
    if stage_root.exists() and (not stage_root.is_dir() or is_reparse(stage_root)):
        fail("portable staging directory must be a regular directory")
    stage_root.mkdir(parents=True, exist_ok=True)
    stage = stage_root / uuid.uuid4().hex
    stage.mkdir()
    try:
        copy_file(executable, stage / "LootWeave.exe")
        copy_file(resources / "bundle-manifest.json", stage / "sidecar" / "bundle-manifest.json")
        for relative, source in sidecar.items():
            copy_file(source, stage / "sidecar" / Path(*relative.split("/")))
        # Application-local CRTs cover both the Rust host and frozen Python workers.
        sidecar_manifest = json.loads((stage / "sidecar/bundle-manifest.json").read_text(encoding="utf-8"))
        for source in crt:
            copy_file(source, stage / source.name)
            copy_file(source, stage / "sidecar" / source.name)
            sidecar_manifest["files"][source.name] = sha256(source)
        (stage / "sidecar/bundle-manifest.json").write_text(json.dumps(sidecar_manifest, indent=2) + "\n", encoding="utf-8")
        for source in runtime_files:
            relative = source.relative_to(runtime)
            copy_file(source, stage / "webview2" / relative)
        (stage / "README-portable.txt").write_text(README, encoding="utf-8", newline="\n")
        packaged = {}
        for source in sorted(p for p in stage.rglob("*") if p.is_file()):
            packaged[source.relative_to(stage).as_posix()] = sha256(source)
        marker = {"format_version": 1, "publisher": "lootweave-portable", "platform": "windows-x64",
                  "source_commit": args.source_commit.lower(), "webview_version": version, "files": packaged}
        (stage / "portable.json").write_text(json.dumps(marker, indent=2) + "\n", encoding="utf-8")
        archive = stage / "portable-package.zip"
        archive_files = sorted(p for p in stage.rglob("*") if p.is_file() and p != archive)
        with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6, allowZip64=True) as bundle:
            for source in archive_files:
                bundle.write(source, source.relative_to(stage).as_posix())
        output.parent.mkdir(parents=True, exist_ok=True)
        created_output = False
        try:
            with archive.open("rb") as src, output.open("xb") as dst:
                created_output = True
                shutil.copyfileobj(src, dst, 1024 * 1024)
        except Exception:
            if created_output and output.exists():
                output.unlink()
            raise
        print(f"output={output} bytes={output.stat().st_size} sha256={sha256(output)} files={len(packaged) + 1}")
    finally:
        cleanup = stage.resolve()
        if cleanup.parent != stage_root.resolve() or is_reparse(stage):
            fail("portable staging cleanup target escaped its owned directory")
        shutil.rmtree(cleanup)


if __name__ == "__main__":
    main()
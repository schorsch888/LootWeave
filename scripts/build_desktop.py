"""Build a local Python directory bundle and Rust desktop. Never publishes artifacts."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run(command, cwd=ROOT, env=None):
    subprocess.run([str(x) for x in command], cwd=cwd, env=env, check=True)



def cargo_environment():
    """Avoid embedding personal source locations in distributed Rust binaries."""
    environment = dict(os.environ)
    encoded = environment.get("CARGO_ENCODED_RUSTFLAGS")
    flags = encoded.split("\x1f") if encoded else environment.get("RUSTFLAGS", "").split()
    flags = [flag for flag in flags if flag]
    prefixes = [(Path.home().resolve(), "builder-home")]
    cargo_home = Path(environment.get("CARGO_HOME", str(Path.home() / ".cargo"))).resolve()
    if not cargo_home.is_relative_to(Path.home().resolve()):
        prefixes.append((cargo_home, "cargo-home"))
    # More specific prefixes come last, so project files retain useful relative locations.
    prefixes.append((ROOT, "lootweave"))
    flags.extend("--remap-path-prefix=" + str(prefix) + "=" + label for prefix, label in prefixes)
    environment.pop("RUSTFLAGS", None)
    environment["CARGO_ENCODED_RUSTFLAGS"] = "\x1f".join(flags)
    return environment

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sidecar-only", action="store_true")
    parser.add_argument("--debug", action="store_true")
    parser.add_argument("--installer", action="store_true")
    parser.add_argument("--test-native", action="store_true")
    args = parser.parse_args()
    if args.test_native:
        if args.debug or args.installer or args.sidecar_only:
            parser.error("--test-native is a separate validation operation.")
        cargo = shutil.which("cargo")
        if not cargo:
            parser.error("Cargo is required for native tests.")
        run([cargo, "test", "--release", "--locked", "--manifest-path", ROOT / "desktop/Cargo.toml"],
            env=cargo_environment())
        return 0
    if args.sidecar_only and args.installer:
        parser.error("An installer requires the Rust host and its dependency notices.")
    if os.name != "nt" or sys.maxsize <= 2**32:
        parser.error("The Windows x64 packaging gate requires a Windows x64 builder.")
    if not (ROOT / "frontend/dist/index.html").is_file():
        parser.error("Build the frontend first.")
    cargo = None
    if not args.sidecar_only:
        cargo = shutil.which("cargo")
        if not cargo:
            raise RuntimeError("Cargo is required to build the Rust host.")
        # Attribution uses locked offline metadata; a clean builder must fetch first.
        run([cargo, "fetch", "--locked", "--target", "x86_64-pc-windows-msvc",
             "--manifest-path", ROOT / "desktop/Cargo.toml"])
    build_id = uuid.uuid4().hex
    work = ROOT / ".local/build" / build_id
    work.mkdir(parents=True)
    from PIL import Image, ImageDraw, ImageFont
    image = Image.new("RGBA", (256, 256), "#18231a")
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((16, 16, 240, 240), radius=40, fill="#c7dd96")
    draw.text((80, 48), "L", font=ImageFont.load_default(size=156), fill="#18231a")
    icon = ROOT / ".local/generated/icon.ico"
    icon.parent.mkdir(parents=True, exist_ok=True)
    image.save(icon, sizes=[(32, 32), (48, 48), (256, 256)])
    command = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onedir",
               "--name", "lootweave-sidecar", "--distpath", work / "dist", "--workpath", work / "work",
               "--specpath", work, "--paths", ROOT, "--collect-submodules", "services",
               "--exclude-module", "PIL", "--exclude-module", "numpy", "--exclude-module", "tkinter",
               "--exclude-module", "unittest", "--icon", icon]
    for source, destination in (("knowledge-packs", "knowledge-packs"), ("fixtures/demo.json", "fixtures"),
                                ("frontend/dist", "frontend/dist"), ("scripts/windows_ocr.ps1", "scripts")):
        command.extend(["--add-data", str(ROOT / source) + ";" + destination])
    command.append(ROOT / "runtime.py")
    run(command)
    bundle = work / "dist/lootweave-sidecar"
    from collect_notices import collect_notices
    collect_notices(bundle, include_rust=not args.sidecar_only)
    shutil.copy2(ROOT / "LICENSE", bundle / "PROJECT-LICENSE.txt")
    manifest = {"format_version": 1, "publisher": "lootweave-build", "platform": "windows-x64",
                "python_version": sys.version.split()[0], "files": {}}
    for path in sorted(bundle.rglob("*")):
        if path.is_file():
            manifest["files"][path.relative_to(bundle).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    (bundle / "bundle-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    target = ROOT / "dist/sidecar"
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        old_manifest = target / "bundle-manifest.json"
        if not old_manifest.is_file() or json.loads(old_manifest.read_text())["publisher"] != "lootweave-build":
            raise RuntimeError("Existing directory is not a recognized build; it was preserved.")
        backup = ROOT / ".local/build-backups" / build_id
        backup.parent.mkdir(parents=True, exist_ok=True)
        target.rename(backup)
    bundle.rename(target)
    print("Built dist/sidecar with a file integrity manifest; no artifacts were published.")
    if not args.sidecar_only and not args.installer:
        command = [cargo, "build", "--locked", "--manifest-path", ROOT / "desktop/Cargo.toml"]
        if not args.debug:
            command.append("--release")
        run(command, env=cargo_environment())
    if args.installer:
        node = shutil.which("node")
        cli = ROOT / "frontend/node_modules/@tauri-apps/cli/tauri.js"
        if not node or not cli.is_file():
            raise RuntimeError("Install the pinned frontend Tauri CLI before building NSIS.")
        command = [node, cli, "build", "--bundles", "nsis"]
        if args.debug:
            command.append("--debug")
        run(command, cwd=ROOT / "desktop", env=cargo_environment())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

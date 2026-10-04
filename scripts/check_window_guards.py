"""Run Windows capture and service-lifecycle guards against actual Rust modules."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import uuid
from pathlib import Path

from build_desktop import ROOT, cargo_environment


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    cargo = shutil.which("cargo")
    if os.name != "nt" or not cargo:
        parser.error("Windows and a local Rust toolchain are required.")
    folder = ROOT / ".local/window-guards" / uuid.uuid4().hex
    (folder / "src").mkdir(parents=True)
    # Versions match desktop/Cargo.lock. No separate implementation is tested.
    manifest = """
[package]
name = "lootweave-window-guards"
version = "0.1.0"
edition = "2021"

[dependencies]
serde = { version = "=1.0.228", features = ["derive"] }
serde_json = "=1.0.151"
getrandom = "=0.3.4"
base64 = "=0.22.1"
sha2 = "=0.10.9"
windows-sys = { version = "=0.61.2", features = [
    "Win32_Foundation", "Win32_Security", "Win32_System_JobObjects", "Win32_System_Threading",
    "Win32_System_Diagnostics_ToolHelp", "Win32_Graphics_Gdi", "Win32_UI_WindowsAndMessaging"
] }
[profile.dev]
debug = 0
incremental = false
"""
    (folder / "Cargo.toml").write_text(manifest, encoding="utf-8")
    names = ("capture.rs", "game_window.rs", "supervisor.rs")
    identities = {name: hashlib.sha256((ROOT / "desktop/src" / name).read_bytes()).hexdigest() for name in names}
    imports = "\n".join('#[path = ' + json.dumps(str(ROOT / "desktop/src" / name).replace("\\", "/"))
                        + "]\nmod " + name.removesuffix(".rs") + ";"
                        for name in names)
    (folder / "src/main.rs").write_text(imports + "\nfn main() {}\n", encoding="utf-8")
    environment = cargo_environment()
    environment["CARGO_BUILD_JOBS"] = "1"
    with (folder / "cargo.log").open("wb") as log:
        result = subprocess.run([cargo, "test", "--offline", "--manifest-path", folder / "Cargo.toml",
                                "--", "--test-threads=1"],
                                cwd=ROOT, env=environment, stdout=log, stderr=subprocess.STDOUT)
    unchanged = all(hashlib.sha256((ROOT / "desktop/src" / name).read_bytes()).hexdigest() == value
                    for name, value in identities.items())
    log_text = (folder / "cargo.log").read_text(encoding="utf-8")
    cases = re.findall(r"^test ([\w:]+) \.\.\. (ok|FAILED|ignored)$", log_text, re.MULTILINE)
    report = {"scope": "Actual Rust capture/window/supervisor modules; no Tauri host or installer rebuild.",
              "passed": result.returncode == 0 and unchanged and bool(cases),
              "tests_passed": sum(state == "ok" for _, state in cases),
              "tests_failed": sum(state == "FAILED" for _, state in cases),
              "tests_ignored": sum(state == "ignored" for _, state in cases),
              "tests": [{"name": name, "state": state} for name, state in cases],
              "source_sha256": identities, "source_unchanged_during_check": unchanged,
              "limitations": ["Native IPC ACL and packaged GUI require separate desktop validation.",
                              "No pixels from a user's game or desktop are captured.",
                              "Boot-permit and job cleanup use controlled PowerShell processes; the frozen sidecar still needs a rebuild."]}
    (folder / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print("Window guard tests " + ("passed." if report["passed"] else "failed; inspect local cargo.log."))
    print("Evidence: " + folder.relative_to(ROOT).as_posix())
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

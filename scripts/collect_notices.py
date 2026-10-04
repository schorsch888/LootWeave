"""Collect local dependency attribution. This does not replace a rights review."""
from __future__ import annotations
import hashlib
import json
import shutil
import subprocess
import sys
from importlib import metadata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def collect_notices(bundle: Path, include_rust: bool):
    notices = bundle / "THIRD-PARTY"
    notices.mkdir(exist_ok=True)
    records = []
    def copy_files(name, version, expression, paths):
        destination = notices / name.replace("/", "_").replace("@", "") / version
        destination.mkdir(parents=True, exist_ok=True)
        copied=[]
        for path in paths:
            if path.is_file():
                target=destination/path.name
                shutil.copy2(path,target)
                copied.append(target.relative_to(bundle).as_posix())
        records.append({"name":name,"version":version,"license_expression":expression,"notice_files":copied})
    copy_files("CPython",sys.version.split()[0],"PSF-2.0 and bundled third-party notices",
               [Path(sys.base_prefix)/"LICENSE.txt"])
    for name in ("pyinstaller","pyinstaller-hooks-contrib"):
        dist=metadata.distribution(name)
        paths=[Path(dist.locate_file(path)) for path in dist.files
               if any(part.lower() in ("licenses","license","copying.txt") for part in path.parts)]
        copy_files(name,dist.version,dist.metadata.get("License-Expression") or "See complete license and distribution exceptions",paths)
    for folder in (ROOT/"frontend/node_modules/react",ROOT/"frontend/node_modules/react-dom",
                   ROOT/"frontend/node_modules/@tauri-apps/api",
                   *sorted((ROOT/"frontend/node_modules/.pnpm").glob("scheduler@*/node_modules/scheduler"))):
        data=json.loads((folder/"package.json").read_text(encoding="utf-8"))
        paths=[path for path in folder.iterdir() if path.is_file() and
               path.name.lower().startswith(("license","copying","notice"))]
        copy_files(data["name"],data["version"],data.get("license","review required"),paths)
    if include_rust:
        cargo=shutil.which("cargo")
        if not cargo:
            raise RuntimeError("Cargo is required for Rust dependency attribution.")
        completed=subprocess.run([cargo,"metadata","--locked","--offline","--format-version","1",
                                  "--filter-platform","x86_64-pc-windows-msvc",
                                  "--manifest-path",str(ROOT/"desktop/Cargo.toml")],
                                 check=True,capture_output=True,text=True,encoding="utf-8")
        cargo_metadata=json.loads(completed.stdout)
        nodes={node["id"]:node for node in cargo_metadata["resolve"]["nodes"]}
        reachable=set()
        pending=[cargo_metadata["resolve"]["root"]]
        while pending:
            node=pending.pop()
            if node in reachable:
                continue
            reachable.add(node)
            pending.extend(dependency["pkg"] for dependency in nodes[node]["deps"])
        for package in cargo_metadata["packages"]:
            if package["id"] not in reachable or package["id"]==cargo_metadata["resolve"]["root"]:
                continue
            folder=Path(package["manifest_path"]).parent
            paths=[path for path in folder.iterdir() if path.is_file() and
                   path.name.lower().startswith(("license","copying","notice","copyright"))]
            if package.get("license_file"):
                paths.append(folder/package["license_file"])
            copy_files(package["name"],package["version"],package.get("license") or "review required",paths)
    inventory={"format_version":1,"review_status":"Attribution collected; independent rights review remains open.",
               "frontend_lock_sha256":hashlib.sha256((ROOT/"frontend/pnpm-lock.yaml").read_bytes()).hexdigest(),
               "cargo_lock_sha256":hashlib.sha256((ROOT/"desktop/Cargo.lock").read_bytes()).hexdigest(),
               "dependencies":records}
    (notices/"inventory.json").write_text(json.dumps(inventory,indent=2)+"\n",encoding="utf-8")

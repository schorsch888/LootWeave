"""Verify FSD imports and Python business-capability isolation using stdlib."""
from __future__ import annotations

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LAYERS = ["shared", "entities", "features", "widgets", "pages", "app"]
IMPORTS = re.compile(r"(?:from\s*|import\s*\(\s*|import\s*)(['\"])([^'\"]+)\1")


def frontend_errors(root: Path):
    errors = []
    for path in sorted(root.rglob("*")):
        if path.suffix not in (".ts", ".tsx") or path.name.endswith(".d.ts"):
            continue
        parts = path.relative_to(root).parts
        if parts[0] not in LAYERS:
            errors.append((path, "unknown_fsd_layer"))
            continue
        layer = parts[0]
        owner = parts[:2] if layer not in ("app", "shared") else (layer,)
        for match in IMPORTS.finditer(path.read_text(encoding="utf-8")):
            specifier = match[2]
            if not specifier.startswith("."):
                if specifier.startswith("@/") or specifier.startswith("~/"):
                    errors.append((path, "unresolved_internal_alias"))
                continue
            destination = (path.parent / specifier).resolve()
            if not destination.is_relative_to(root):
                errors.append((path, "import_outside_frontend"))
                continue
            target = destination.relative_to(root).parts
            if not target or target[0] not in LAYERS:
                errors.append((path, "unknown_import_layer"))
                continue
            other = target[:2] if target[0] not in ("app", "shared") else (target[0],)
            if owner == other:
                continue
            if LAYERS.index(target[0]) >= LAYERS.index(layer):
                errors.append((path, "cross_slice_or_upward_import"))
            elif target[0] not in ("app", "shared") and len(target) > 2 and \
                    not (len(target) == 3 and target[2] in ("index", "index.ts", "index.tsx")):
                errors.append((path, "slice_public_api_required"))
    return errors


def backend_errors(root: Path):
    errors = []
    service_names = {path.name for path in root.iterdir() if path.is_dir() and not path.name.startswith("_")}
    io_modules = {"sqlite3", "storage", "transport", "urllib", "http", "requests", "subprocess", "socket"}

    def imported_modules(node, package):
        if isinstance(node, ast.Import):
            return [alias.name for alias in node.names]
        if not isinstance(node, ast.ImportFrom):
            return []
        if node.level == 0:
            base = node.module or ""
        else:
            trim = node.level - 1
            if trim >= len(package):
                return []
            base = ".".join(package[:len(package) - trim])
            if node.module:
                base = ".".join(part for part in (base, node.module) if part)
        modules = [base] if base else []
        # ``from services import knowledge`` and ``from .. import knowledge``
        # name the imported capability in the alias, not in node.module.
        if base == "services" or base.startswith("services."):
            modules.extend(".".join(part for part in (base, alias.name) if part)
                           for alias in node.names if alias.name != "*")
        return modules

    for path in sorted(root.rglob("*.py")):
        parts = path.relative_to(root).parts
        if len(parts) < 2:
            continue
        owner = parts[0]
        tree = ast.parse(path.read_text(encoding="utf-8"))
        package = ("services", *parts[:-1])
        for node in ast.walk(tree):
            for module in imported_modules(node, package):
                segments = module.split(".")
                if len(segments) > 1 and segments[0] == "services" and \
                        segments[1] in service_names and segments[1] != owner:
                    errors.append((path, "foreign_business_domain_import"))
                if path.name == "domain.py" and segments[0] in io_modules:
                    errors.append((path, "domain_io_import"))
    return errors


def main():
    errors = frontend_errors((ROOT / "frontend/src").resolve()) + backend_errors(ROOT / "services")
    for path, category in errors:
        print(f"{path.relative_to(ROOT).as_posix()}: {category}")
    print(f"Architecture findings: {len(errors)}")
    return bool(errors)


if __name__ == "__main__":
    raise SystemExit(main())

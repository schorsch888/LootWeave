"""Regression coverage for frontend boundaries and service import ownership."""
import tempfile
import unittest
from pathlib import Path

from scripts.check_architecture import backend_errors, frontend_errors


class ArchitectureCheckerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()

    def write_frontend(self, relative, source):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source, encoding="utf-8")
        return path

    def test_frontend_rejects_cross_layer_import(self):
        source = self.write_frontend("entities/item/index.tsx", 'import { useItem } from "../../features/item";')
        findings = frontend_errors(self.root)
        self.assertIn((source, "cross_slice_or_upward_import"), findings)

    def test_frontend_rejects_same_layer_cross_slice_import(self):
        source = self.write_frontend("features/equip/index.tsx", 'import { compare } from "../compare";')
        self.write_frontend("features/compare/index.tsx", "export const compare = () => null;")
        self.assertIn((source, "cross_slice_or_upward_import"), frontend_errors(self.root))

    def test_frontend_requires_lower_layer_public_api(self):
        source = self.write_frontend("features/equip/index.tsx", 'import { item } from "../../entities/item/private";')
        self.write_frontend("entities/item/private.ts", "export const item = {}; ")
        self.assertIn((source, "slice_public_api_required"), frontend_errors(self.root))

    def test_frontend_rejects_relative_import_outside_source_root(self):
        source = self.write_frontend("features/equip/index.tsx", 'import value from "../../../../outside";')
        self.assertIn((source, "import_outside_frontend"), frontend_errors(self.root))

    def test_frontend_allows_import_within_same_slice(self):
        source = self.write_frontend("features/equip/index.tsx", 'import { helper } from "./helper";')
        self.write_frontend("features/equip/helper.ts", "export const helper = true;")
        self.assertEqual([], frontend_errors(self.root))

    def write_backend(self, relative, source):
        services = self.root / "services"
        path = services / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source, encoding="utf-8")
        return services, path

    def assert_foreign_import(self, source):
        services, path = self.write_backend("profile/domain.py", source)
        (services / "knowledge").mkdir(exist_ok=True)
        self.assertIn((path, "foreign_business_domain_import"), backend_errors(services))

    def test_backend_rejects_foreign_absolute_relative_and_package_from_imports(self):
        cases = (
            "from services.knowledge.domain import validate_pack",
            "from ..knowledge.domain import validate_pack",
            "from .. import knowledge",
            "from services import knowledge",
        )
        for source in cases:
            with self.subTest(source=source):
                self.assert_foreign_import(source)

    def test_backend_allows_same_service_absolute_and_relative_imports(self):
        services, _ = self.write_backend("profile/domain.py", """
from services.profile.app import Profile
from . import domain
from .domain import snapshot
from contracts import require
""")
        (services / "knowledge").mkdir()
        self.assertEqual([], backend_errors(services))

    def test_backend_rejects_io_modules_in_domain_but_allows_them_in_app(self):
        forbidden = """
import sqlite3
import urllib.parse
import http.client
import requests
import subprocess
import socket
import storage
import transport
"""
        services, domain = self.write_backend("profile/domain.py", forbidden)
        app = services / "profile" / "app.py"
        app.write_text(forbidden, encoding="utf-8")
        findings = backend_errors(services)
        self.assertEqual(8, sum(path == domain and category == "domain_io_import"
                                for path, category in findings))
        self.assertFalse(any(path == app for path, _category in findings))


if __name__ == "__main__":
    unittest.main()

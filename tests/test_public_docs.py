"""Publication-boundary tests using disposable Git repositories and synthetic data."""
from __future__ import annotations

import importlib.util
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch


MODULE_PATH = Path(__file__).resolve().parents[1] / 'scripts' / 'check_public_docs.py'
SPEC = importlib.util.spec_from_file_location('public_docs', MODULE_PATH)
checker = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(checker)


class PublicDocsTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='lootweave-check-')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.root_patch = patch.object(checker, 'ROOT', self.root)
        self.root_patch.start()
        self.addCleanup(self.root_patch.stop)
        self.git('init', '-q')
        self.git('config', 'core.autocrlf', 'false')

    def git(self, *args):
        subprocess.run(['git', '-C', str(self.root), *args], check=True,
                       capture_output=True)

    def write(self, name, text):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding='utf-8')
        return path

    def categories(self):
        findings, _ = checker.check(checker.public_paths(), set())
        return {category for _, _, category in findings}

    def test_untracked_private_material_cannot_escape_public_review(self):
        path = self.write('.tools/report.json', '{}')
        self.assertIn(path, checker.public_paths())
        self.assertIn('private_artifact_in_public_candidates', self.categories())

    def test_already_tracked_ignored_material_is_still_checked(self):
        self.write('.gitignore', '.tools/\n')
        path = self.write('.tools/report.json', '{}')
        self.assertNotIn(path, checker.public_paths())
        self.git('add', '-f', '.tools/report.json')
        self.assertIn(path, checker.public_paths())
        self.assertIn('private_artifact_in_public_candidates', self.categories())

    def test_missing_markdown_target_is_reported(self):
        self.write('README.md', '[Guide](docs/missing.md)\n')
        self.assertIn('missing_local_link', self.categories())

    def test_existing_ignored_markdown_target_is_not_public(self):
        self.write('.gitignore', 'docs/local.md\n')
        self.write('docs/local.md', '# Local note\n')
        self.write('README.md', '[Guide](docs/local.md)\n')
        self.assertIn('local_link_not_in_public_candidates', self.categories())

    def test_directory_with_only_ignored_files_is_not_public(self):
        self.write('.gitignore', 'docs/local.md\n')
        self.write('docs/local.md', '# Local note\n')
        self.write('README.md', '[Docs](docs/)\n')
        self.assertIn('local_link_not_in_public_candidates', self.categories())

    def test_directory_with_an_included_document_is_public(self):
        self.write('.gitignore', 'docs/local.md\n')
        self.write('docs/local.md', '# Local note\n')
        self.write('docs/design.md', '# Design\n')
        self.write('README.md', '[Docs](docs/)\n')
        self.assertEqual(set(), self.categories())

    def test_published_target_with_an_anchor_remains_valid(self):
        self.write('docs/guide.md', '# Overview\n')
        self.write('README.md', '[Guide](docs/guide.md#overview)\n')
        self.assertEqual(set(), self.categories())

    def test_dangling_symlink_requires_review(self):
        path = self.root / 'dangling.md'
        try:
            path.symlink_to('missing-target.md')
        except OSError:
            self.skipTest('This environment cannot create symlinks; CI exercises the real fixture.')
        self.assertFalse(path.exists())
        self.assertIn('symlink_requires_review', self.categories())

    def test_invalid_json_is_reported(self):
        self.write('evidence.json', '{"version":')
        self.assertIn('invalid_json', self.categories())

    def test_sensitive_synthetic_values_are_redacted_in_findings(self):
        secret = 'gh' + 'p_' + ('x' * 36)
        email = 'synthetic' + '@' + 'example.invalid'
        self.write('note.md', secret + '\n' + email)
        findings, _ = checker.check(checker.public_paths(), set())
        self.assertEqual({'github_token', 'email_address'}, {r[2] for r in findings})
        self.assertNotIn(secret, repr(findings))
        self.assertNotIn(email, repr(findings))

    def test_logical_source_identifiers_are_not_private_paths(self):
        self.write('evidence.json', '{"sources":["repo://research/current.json",'
                   '"game://Deskrawl_Data/resources.assets",'
                   '"steam://appmanifest_4623570.acf"]}')
        self.assertEqual(set(), self.categories())

    def test_opt_in_local_reports_do_not_exempt_public_documents(self):
        local = self.write('private/local.md', '# Local\n')
        public = self.write('README.md', '[Local](private/local.md)\n')
        findings, _ = checker.check([local, public], {local}, {public})
        self.assertIn('public_link_to_private_artifact', {r[2] for r in findings})


if __name__ == '__main__':
    unittest.main()

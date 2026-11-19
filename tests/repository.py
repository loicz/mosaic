#!/usr/bin/env python3
"""Check public source assets, relative documentation links and portability."""
import ast
import json
from pathlib import Path
import re
import unittest
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parents[1]
PUBLIC_DIRECTORIES = ('.github', 'apps', 'config', 'dashboard', 'docs', 'include',
                      'models', 'scripts', 'src', 'tests', 'third_party')


def public_files():
    files = list(ROOT.glob('*.md')) + [ROOT/'CMakeLists.txt', ROOT/'.gitignore']
    for directory in PUBLIC_DIRECTORIES:
        files.extend(p for p in (ROOT/directory).rglob('*')
                     if p.is_file() and '__pycache__' not in p.parts and p.suffix!='.pyc')
    return files


class RepositoryTests(unittest.TestCase):
    def test_document_links_resolve(self):
        for path in public_files():
            if path.suffix != '.md':
                continue
            for target in re.findall(r'\]\(([^)]+)\)', path.read_text()):
                if '://' in target or target.startswith(('#', 'mailto:')):
                    continue
                relative = unquote(target.split('#')[0].split('?')[0])
                self.assertTrue((path.parent/relative).exists(), f'{path.relative_to(ROOT)}: {target}')

    def test_sources_and_machine_readable_assets_parse(self):
        for path in public_files():
            if path.suffix == '.py':
                ast.parse(path.read_text(), filename=str(path))
            elif path.suffix == '.json':
                json.loads(path.read_text())

    def test_public_files_are_small_and_have_no_local_home_or_credential_literals(self):
        personal_path = re.compile(r'/(?:home|Users)/[^\s/]+/|[A-Z]:\\Users\\')
        credential = re.compile(r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----|'
                                r'AKIA[0-9A-Z]{16}|github_pat_[A-Za-z0-9_]{40,}|'
                                r'gh[pousr]_[A-Za-z0-9]{30,}')
        for path in public_files():
            self.assertFalse(path.is_symlink(), str(path))
            self.assertLess(path.stat().st_size, 5*1024*1024, str(path))
            try:
                text = path.read_text()
            except UnicodeDecodeError:
                continue
            self.assertIsNone(personal_path.search(text), str(path))
            self.assertIsNone(credential.search(text), str(path))


if __name__ == '__main__':
    unittest.main()

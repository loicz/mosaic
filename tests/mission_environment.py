#!/usr/bin/env python3
"""Check source-checkout setup without requiring flight dependencies."""
import os
from pathlib import Path
import runpy
import shutil
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


class EnvironmentTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory(prefix='mosaic-env-')
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        scripts = self.root / 'project/scripts'
        scripts.mkdir(parents=True)
        self.module = scripts / 'mission_env.py'
        shutil.copy2(ROOT / 'scripts/mission_env.py', self.module)

    def test_unprepared_clone_uses_project_directory_and_explains_setup(self):
        with patch.dict(os.environ, {}, clear=True):
            module = runpy.run_path(str(self.module))
        expected = self.root / 'project/.runtime/toolchain'
        self.assertEqual(module['DEFAULT_TOOLCHAIN'], expected)
        with self.assertRaises(SystemExit) as error:
            module['command'](expected, ['true'])
        self.assertIn('offline runtime release', str(error.exception))
        self.assertIn('MOSAIC_TOOLCHAIN', str(error.exception))

    def test_explicit_relative_toolchain_is_resolved_and_bound(self):
        selected = self.root / 'selected'
        (selected / 'ubuntu24/bin').mkdir(parents=True)
        (selected / 'ubuntu24/bin/sh').touch()
        # Express a real temporary directory relative to the test working dir.
        relative = os.path.relpath(selected)
        with patch.dict(os.environ, {'MOSAIC_TOOLCHAIN': relative}):
            module = runpy.run_path(str(self.module))
        self.assertEqual(module['DEFAULT_TOOLCHAIN'], selected)
        with patch('shutil.which', return_value='/usr/bin/bwrap'):
            command = module['command'](module['DEFAULT_TOOLCHAIN'], ['true'], network=False)
        self.assertIn(str(selected / 'ubuntu24'), command)
        self.assertIn(str(self.root / 'project'), command)
        self.assertIn('--unshare-net', command)
        self.assertNotIn('/etc/resolv.conf', command)


if __name__ == '__main__':
    unittest.main()

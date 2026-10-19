"""Synthetic generator never initializes or changes the operator's DATA_DIR."""
from __future__ import annotations
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(sys.platform.startswith('linux'), 'Supported fixture image and guarded /proc sentinel use Linux.')
class FixtureGeneratorTests(unittest.TestCase):
    def test_impossible_operator_state_is_ignored_and_existing_output_preserved(self):
        with tempfile.TemporaryDirectory(prefix='seorap-generator-regression-') as temp:
            output = Path(temp) / 'fixtures'
            command = [sys.executable, str(ROOT / 'scripts/create-fixtures.py'), '--output', str(output)]
            environment = {**os.environ, 'DATA_DIR': '/proc/seorap-fixture-import-must-not-write'}
            result = subprocess.run(command, cwd=ROOT, env=environment, capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse(Path(environment['DATA_DIR']).exists())
            self.assertEqual(len(list((output / 'media').glob('*'))), 5)
            catalog = output / 'catalog.json'
            original = catalog.read_bytes()
            self.assertEqual(json.loads(original)['fixH264aacA']['file'], '/fixtures/media/h264.mp4')
            second = subprocess.run(command, cwd=ROOT, env=environment, capture_output=True, text=True, timeout=5)
            self.assertNotEqual(second.returncode, 0)
            self.assertIn('never overwritten', second.stderr)
            self.assertEqual(catalog.read_bytes(), original)


if __name__ == '__main__':
    unittest.main()

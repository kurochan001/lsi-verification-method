"""Check the documented relative-path invocation against real tools."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = Path(__file__).resolve().parents[1]
ROOT = HERE.parents[1]


class RelativeConfigTest(unittest.TestCase):
    def test_relative_config_survives_child_working_directory(self):
        config = shutil.which('lsi-ngspice-config')
        self.assertIsNotNone(config, 'prepare ngspice and add install/bin to PATH for all selftests')
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / 'out'
            config_arg = os.path.relpath(config, ROOT)
            run = subprocess.run([sys.executable, str(HERE / 'run.py'), '--ngspice-config',
                                  config_arg, '--out', str(output)],
                                 cwd=ROOT, capture_output=True, text=True, timeout=90)
            self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
            summary = json.loads((output / 'summary.json').read_text())
            self.assertTrue(summary['success'])
            self.assertTrue((output / 'rc47us' / 'early' / 'comparison.csv').is_file())


if __name__ == '__main__':
    unittest.main()

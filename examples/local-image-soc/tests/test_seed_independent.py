"""The interrupt must meet a held access whatever the seed: these three once let mutation 5 survive."""
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
HERE=Path(__file__).resolve().parents[1]
SEEDS=(21,777,90210)


class SeedIndependentTests(unittest.TestCase):
    def test_the_dropped_access_is_detected_for_seeds_that_once_missed_it(self):
        if not (shutil.which('iverilog') and shutil.which('vvp')):raise unittest.SkipTest('Icarus required')
        for seed in SEEDS:
            with self.subTest(seed=seed),tempfile.TemporaryDirectory() as tmp:
                out=Path(tmp)/'out'
                result=subprocess.run([sys.executable,str(HERE/'run.py'),'--seed',str(seed),'--out',str(out)],capture_output=True,text=True,timeout=300)
                self.assertEqual(result.returncode,0,result.stdout+result.stderr)
                records={r['id']:r for r in json.loads((out/'executions.json').read_text())}
                for cfg in ('w5h5-wait0','w7h5-wait2'):
                    self.assertIn('irq/waits-for-access',records[cfg+'/irq-during-read']['coverage'])
                    self.assertEqual((records[cfg+'/mutation-5']['status'],records[cfg+'/mutation-5']['expected_failure']),('detected','SOC_CPU_HOLD'))


if __name__=='__main__':unittest.main()

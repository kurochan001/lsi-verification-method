import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'local-common'))
from local_test_support import load_example,read_json
P=load_example('local-cocotb')
# No default: a fixed path in a world-writable directory must not be run just because it exists.
PYTHON=Path(os.environ['COCOTB_PYTHON']) if os.environ.get('COCOTB_PYTHON') else None
class CocotbTest(unittest.TestCase):
    def prepared_python(self):
        if PYTHON is None:self.fail('set COCOTB_PYTHON to the Python of the prepared cocotb environment')
        if not PYTHON.is_file():self.fail('COCOTB_PYTHON does not name a file: '+str(PYTHON))
        return str(PYTHON)
    def test_three_rtl_mutants_and_one_expected_value_diagnostic(self):
        cases=P.cases(SimpleNamespace(seed=17,profile='smoke',iterations=2))
        self.assertEqual(len(cases),12);self.assertEqual(sum(c['category']=='mutation' for c in cases),6)
        self.assertEqual(sum(c['category']=='diagnostic' for c in cases),2)
    def test_seed_metadata_matches_generated_operations(self):
        cases=P.cases(SimpleNamespace(seed=17,profile='nightly',iterations=2))
        case=next(c for c in cases if c['id']=='wait0-random-seed18')
        self.assertEqual(case['seed'],18);self.assertEqual(case['operations'],P.operations(18,2))
    def test_reference_counts_include_read_only_and_unmapped_errors(self):
        self.assertEqual(P.totals(P.operations(17,0,True)),dict(transactions=10,reads=5,writes=5,errors=3))
    def test_real_cocotb_native_reports_and_waveforms(self):
        with tempfile.TemporaryDirectory() as tmp:
            out=Path(tmp)/'out';p=subprocess.run([self.prepared_python(),P.__file__,'--iterations','2','--out',str(out)],capture_output=True,text=True,timeout=90)
            self.assertEqual(p.returncode,0,p.stdout+p.stderr);summary=read_json(out/'summary.json');self.assertTrue(summary['success'])
            self.assertEqual(sum(r['outcome']=='detected' for r in summary['results']),8)
            for c in out.glob('*/result.json'):
                r=read_json(c)
                if r['category']!='functional':self.assertEqual(r['credited_coverage'],[])
                self.assertTrue((c.parent/'cocotb-junit.xml').is_file());self.assertGreater((c.parent/'build/apb_regs.fst').stat().st_size,0)
    def test_missing_requested_icarus_cannot_fallback_to_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            out=Path(tmp)/'out';p=subprocess.run([self.prepared_python(),P.__file__,'--iterations','1','--iverilog',str(Path(tmp)/'absent'),'--out',str(out)],capture_output=True,text=True,timeout=90)
            self.assertEqual(p.returncode,1,p.stdout+p.stderr);self.assertFalse(read_json(out/'summary.json')['success'])
            self.assertTrue(all(r['outcome']=='error' for r in read_json(out/'summary.json')['results']))
if __name__=='__main__':unittest.main()

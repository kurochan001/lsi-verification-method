from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'local-common'))
from local_test_support import load_example,read_json
P=load_example('local-differential')
class DifferentialTest(unittest.TestCase):
    def test_trace_contains_every_clock_exactly_once(self):
        log='OBS DSP cycle=0 ready=0 valid=0\nOBS DSP cycle=1 ready=0 valid=1 data=ff clipped=0\n'
        self.assertEqual(len(P.traces(log,2)),2)
        with self.assertRaises(ValueError):P.traces(log+log,2)
        with self.assertRaises(ValueError):P.traces(log,3)
    def test_unknown_payload_and_invalid_schema_are_not_comparable(self):
        for line in ('OBS DSP cycle=0 ready=0 valid=1 data=xx clipped=0','OBS random cycle=0','OBS AXIS cycle=0 ready=1 valid=1 data=123 keep=f last=1'):
            with self.assertRaises(ValueError):P.traces(line+'\n',1)
    def test_four_state_and_checker_off_cases_are_diagnostics(self):
        cases=P.cases(SimpleNamespace(profile='smoke',seed=17,iterations=2));self.assertEqual(len(cases),12)
        diagnostics=[c for c in cases if c['category']=='diagnostic'];self.assertEqual({c['kind'] for c in diagnostics},{'different','active-x'})
        self.assertTrue(all(c['expected_failure'] for c in diagnostics))
    @unittest.skipUnless(all(shutil.which(t) for t in ('iverilog','vvp','verilator')),'simulation tools required')
    def test_real_backend_pairs_and_difference_detection(self):
        with tempfile.TemporaryDirectory() as tmp:
            out=Path(tmp)/'out';p=subprocess.run([sys.executable,P.__file__,'--iterations','2','--out',str(out)],capture_output=True,text=True,timeout=120)
            self.assertEqual(p.returncode,0,p.stdout+p.stderr);summary=read_json(out/'summary.json');self.assertTrue(summary['success'])
            self.assertEqual(sum(r['outcome']=='detected' for r in summary['results']),2)
            self.assertTrue(all(c['success'] for c in read_json(out/'coverage.json').values()))
    def test_build_failures_are_not_backend_differences(self):
        with tempfile.TemporaryDirectory() as tmp:
            out=Path(tmp)/'out';absent=str(Path(tmp)/'absent')
            p=subprocess.run([sys.executable,P.__file__,'--iterations','1','--iverilog',absent,'--verilator',absent,'--out',str(out)],capture_output=True,text=True,timeout=20)
            self.assertEqual(p.returncode,1,p.stdout+p.stderr);summary=read_json(out/'summary.json');self.assertFalse(summary['success'])
            self.assertTrue(all(r['outcome']=='error' for r in summary['results']))
if __name__=='__main__':unittest.main()

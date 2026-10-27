import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
spec=importlib.util.spec_from_file_location('host_support',Path(__file__).resolve().parents[1]/'runner.py');H=importlib.util.module_from_spec(spec);spec.loader.exec_module(H)
class RunnerTest(unittest.TestCase):
    def setUp(self):self.case=dict(checks=2,expected_failure=None,counts=dict(completed=1));self.ok=dict(error=None,returncode=0)
    def test_valid_completion(self):self.assertEqual(H.evaluate(self.case,self.ok,'COUNT completed=1\nRESULT PASS checks=2\n')[0],'pass')
    def test_missing_wrong_duplicate_counts(self):
        for log in ('','COUNT completed=2\n','COUNT completed=1\nCOUNT completed=1\n'):
            self.assertEqual(H.evaluate(self.case,self.ok,log+'RESULT PASS checks=2\n')[0],'error')
    def test_incomplete_pass_marker(self):self.assertEqual(H.evaluate(self.case,self.ok,'COUNT completed=1\n')[0],'error')
    def test_unrelated_crash_is_not_detection(self):
        case=dict(self.case,expected_failure='EXPECTED')
        self.assertEqual(H.evaluate(case,dict(error=None,returncode=1),'unrelated crash\n')[0],'error')
    def test_intended_failure_requires_nonzero_exit(self):
        case=dict(self.case,expected_failure='EXPECTED')
        self.assertEqual(H.evaluate(case,self.ok,'CHECK_FAIL EXPECTED\n')[0],'error')
        self.assertEqual(H.evaluate(case,dict(error=None,returncode=1),'CHECK_FAIL EXPECTED\n')[0],'detected')
    def test_timeout_cannot_pass(self):self.assertEqual(H.evaluate(self.case,dict(error='timeout',returncode=None),'RESULT PASS checks=2\n')[0],'error')
    def test_missing_compiler_fails_all_cases(self):
        with tempfile.TemporaryDirectory() as tmp:
            out=Path(tmp)/'out';script=Path(H.__file__).parent.parent/'local-c-driver/run.py'
            p=subprocess.run([sys.executable,str(script),'--iterations','1','--cc',str(Path(tmp)/'absent'),'--out',str(out)],capture_output=True,text=True,timeout=20)
            self.assertEqual(p.returncode,1,p.stdout+p.stderr)
            summary=json.loads((out/'summary.json').read_text());self.assertFalse(summary['success']);self.assertTrue(all(r['outcome']=='error' for r in summary['results']))
    def test_existing_output_and_invalid_iterations(self):
        with tempfile.TemporaryDirectory() as tmp:
            out=Path(tmp)/'out';out.mkdir();(out/'keep').write_text('keep');script=Path(H.__file__).parent.parent/'local-c-driver/run.py'
            for opts in (['--out',str(out)],['--iterations','0','--out',str(Path(tmp)/'other')]):
                p=subprocess.run([sys.executable,str(script),*opts],capture_output=True,text=True);self.assertEqual(p.returncode,2)
            self.assertEqual((out/'keep').read_text(),'keep')
if __name__=='__main__':unittest.main()

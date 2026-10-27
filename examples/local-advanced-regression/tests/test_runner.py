import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
spec=importlib.util.spec_from_file_location('system_runner',Path(__file__).resolve().parents[1]/'run.py')
R=importlib.util.module_from_spec(spec);spec.loader.exec_module(R)
class RunnerTest(unittest.TestCase):
    def test_consistent_simulation_and_formal_children_are_accepted(self):
        self.assertTrue(R.child_success(dict(success=True,planned=2,results=2,complete=True)))
        self.assertTrue(R.child_success(dict(success=True,planned=2,results=[dict(outcome='pass'),dict(outcome='detected')])))
    def test_success_flag_cannot_hide_missing_or_failed_cases(self):
        for record in (dict(success=True),dict(success=True,planned=2,results=1,complete=True),
                       dict(success=True,planned=1,results=[dict(outcome='error')]),dict(success=True,planned=0,results=[],complete=True),
                       dict(success=True,planned=1,results=1,complete=False)):
            self.assertFalse(R.child_success(record))
    def test_missing_child_python_fails_and_existing_output_is_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            out=Path(tmp)/'out'
            p=subprocess.run([sys.executable,R.__file__,'--stage','simulation','--python',str(Path(tmp)/'absent'),'--cocotb-python',str(Path(tmp)/'absent'),'--out',str(out)],capture_output=True,text=True)
            self.assertEqual(p.returncode,1,p.stdout+p.stderr)
            summary=json.loads((out/'summary.json').read_text());self.assertFalse(summary['success']);self.assertEqual(len(summary['results']),6)
            (out/'keep').write_text('keep')
            p=subprocess.run([sys.executable,R.__file__,'--out',str(out)],capture_output=True,text=True)
            self.assertEqual(p.returncode,2);self.assertEqual((out/'keep').read_text(),'keep')
if __name__=='__main__':unittest.main()

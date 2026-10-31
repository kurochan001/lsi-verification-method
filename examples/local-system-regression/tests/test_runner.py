import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch
spec=importlib.util.spec_from_file_location('system_runner',Path(__file__).resolve().parents[1]/'run.py')
R=importlib.util.module_from_spec(spec);spec.loader.exec_module(R)
class RunnerTest(unittest.TestCase):
    def test_simulation_timeout_reaches_children_without_changing_formal_timeout(self):
        for timeout in (None,60.0):
            with self.subTest(timeout=timeout),tempfile.TemporaryDirectory() as tmp:
                args=SimpleNamespace(out=Path(tmp)/'out',stage='all',profile='nightly',seed=17,
                                     python=sys.executable,timeout=1800,formal_timeout=300,
                                     simulation_timeout=timeout)
                commands=[]
                def execute(command,log,limit,cwd):
                    commands.append(command)
                    out=Path(command[command.index('--out')+1]);out.mkdir()
                    (out/'summary.json').write_text(json.dumps(dict(success=True,planned=1,results=1,complete=True)))
                    self.assertEqual(limit,1800)
                    return dict(returncode=0,error=None,seconds=0)
                with patch.object(R.P,'execute',side_effect=execute):
                    self.assertEqual(R.run(args),0)
                self.assertEqual(len(commands),7)
                for command in commands:
                    name=Path(command[1]).parent.name
                    expected=timeout if name in R.SIMULATIONS else 300
                    if expected is None:self.assertNotIn('--timeout',command)
                    else:self.assertEqual(float(command[command.index('--timeout')+1]),expected)
                self.assertEqual(json.loads((args.out/'manifest.json').read_text())['simulation_timeout'],timeout)

    def test_invalid_simulation_timeout_is_rejected_before_starting_children(self):
        with tempfile.TemporaryDirectory() as tmp:
            out=Path(tmp)/'out'
            for value in ('0','-1','nan','inf'):
                with self.subTest(value=value):
                    process=subprocess.run([sys.executable,R.__file__,'--stage','simulation',
                                            '--simulation-timeout',value,'--out',str(out)],capture_output=True,text=True)
                    self.assertEqual(process.returncode,2,process.stdout+process.stderr)
                    self.assertFalse(out.exists())

    def test_consistent_simulation_and_formal_children_are_accepted(self):
        self.assertTrue(R.child_success(dict(success=True,planned=2,results=2,complete=True)))
        self.assertTrue(R.child_success(dict(success=True,planned=2,results=[dict(id='proof',outcome='pass'),dict(id='mutation',outcome='detected')])))
    def test_success_flag_cannot_hide_missing_or_failed_cases(self):
        for record in (dict(success=True),dict(success=True,planned=2,results=1,complete=True),
                       dict(success=True,planned=1,results=[dict(outcome='error')]),dict(success=True,planned=0,results=[],complete=True),
                       dict(success=True,planned=1,results=1,complete=False)):
            self.assertFalse(R.child_success(record))
    def test_missing_child_python_fails_and_existing_output_is_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            out=Path(tmp)/'out'
            p=subprocess.run([sys.executable,R.__file__,'--stage','simulation','--python',str(Path(tmp)/'absent'),'--out',str(out)],capture_output=True,text=True)
            self.assertEqual(p.returncode,1,p.stdout+p.stderr)
            summary=json.loads((out/'summary.json').read_text());self.assertFalse(summary['success']);self.assertEqual(len(summary['results']),5)
            (out/'keep').write_text('keep')
            p=subprocess.run([sys.executable,R.__file__,'--out',str(out)],capture_output=True,text=True)
            self.assertEqual(p.returncode,2);self.assertEqual((out/'keep').read_text(),'keep')
    def test_duplicate_missing_or_malformed_result_ids_are_rejected(self):
        good=dict(id='check', outcome='pass')
        for rows in ([good,dict(good)], [dict(outcome='pass')], [dict(good,id='')], [dict(good,id=' ')], ['pass'], [None]):
            with self.subTest(rows=rows):
                self.assertFalse(R.child_success(dict(success=True,complete=True,planned=len(rows),results=rows)))
        for summary in (None,[],True):self.assertFalse(R.child_success(summary))
if __name__=='__main__':unittest.main()

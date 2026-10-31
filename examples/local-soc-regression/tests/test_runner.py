from pathlib import Path
import json,subprocess,sys,tempfile,unittest
from types import SimpleNamespace
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'local-common'))
from local_test_support import load_example
P=load_example('local-soc-regression')
class AggregateTests(unittest.TestCase):
    def test_simulation_timeout_reaches_only_core_children(self):
        for timeout in (None,60.0):
            with self.subTest(timeout=timeout),tempfile.TemporaryDirectory() as tmp:
                args=SimpleNamespace(out=Path(tmp)/'out',stage='all',profile='nightly',seed=17,
                                     uvm_home=Path(tmp)/'uvm',rdl_python=sys.executable,
                                     formal_python=sys.executable,solver='z3',child_timeout=1800,
                                     simulation_timeout=timeout)
                commands=[]
                def execute(command,log,limit,cwd):
                    commands.append(command)
                    out=Path(command[command.index('--out')+1]);out.mkdir()
                    (out/'summary.json').write_text(json.dumps(dict(success=True,planned=1,results=1,complete=True)))
                    self.assertEqual(limit,1800)
                    return dict(returncode=0,error=None,seconds=0)
                with patch.object(P.E.P,'execute',side_effect=execute):
                    self.assertEqual(P.run(args),0)
                self.assertEqual(len(commands),7)
                for command in commands:
                    name=Path(command[1]).parent.name
                    if name in P.CORE and timeout is not None:
                        self.assertEqual(float(command[command.index('--timeout')+1]),timeout)
                    else:self.assertNotIn('--timeout',command)
                self.assertEqual(json.loads((args.out/'manifest.json').read_text())['options']['simulation_timeout'],timeout)

    def test_invalid_simulation_timeout_is_rejected_before_starting_children(self):
        with tempfile.TemporaryDirectory() as tmp:
            out=Path(tmp)/'out'
            for value in ('0','-1','nan','inf'):
                with self.subTest(value=value):
                    process=subprocess.run([sys.executable,P.__file__,'--stage','core',
                                            '--simulation-timeout',value,'--out',str(out)],capture_output=True,text=True)
                    self.assertEqual(process.returncode,2,process.stdout+process.stderr)
                    self.assertFalse(out.exists())

    def test_missing_or_empty_plan_cannot_pass(self):
        for d in ({},dict(success=True,complete=True,planned=0,results=[]),dict(success=True,complete=True,planned=True,results=1)):
            self.assertFalse(P.child_success(d))
    def test_list_plan_requires_every_check(self):
        d=dict(success=True,complete=True,planned=1,results=[dict(id='check',status='pass')]);self.assertTrue(P.child_success(d))
        self.assertFalse(P.child_success(dict(d,results=['pass'])));self.assertFalse(P.child_success(dict(d,results=[])))
    def test_integer_plan_requires_completion(self):
        d=dict(success=True,complete=True,planned=6,results=6);self.assertTrue(P.child_success(d))
        self.assertFalse(P.child_success(dict(d,complete=False)));self.assertFalse(P.child_success(dict(d,results=5)))
    def test_duplicate_missing_or_malformed_result_ids_are_rejected(self):
        good=dict(id='check', status='pass')
        for rows in ([good,dict(good)], [dict(status='pass')], [dict(good,id='')], [dict(good,id=' ')], ['pass'], [None]):
            with self.subTest(rows=rows):
                self.assertFalse(P.child_success(dict(success=True,complete=True,planned=len(rows),results=rows)))
        for summary in (None,[],True):self.assertFalse(P.child_success(summary))
if __name__=='__main__':unittest.main()

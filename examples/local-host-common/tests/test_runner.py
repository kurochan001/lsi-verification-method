import contextlib
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET
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
class AggregationTests(unittest.TestCase):
    """The verdict of a whole run, from a stand-in plugin whose execute writes prepared logs."""
    GOOD='COUNT completed=1\nCOVER goal/a\nCOVER goal/b\nRESULT PASS checks=2\n'
    NORMAL=('normal','functional',None,GOOD,0);MUTANT=('mutant','mutation','LABEL','CHECK_FAIL LABEL\n',1)
    def run_plan(self,*runs):
        """Each run is (id, category, expected label, log, exit code); returns exit code, summary, coverage and JUnit."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp=Path(tmp).resolve();(tmp/'plugin.py').write_text('# stand-in plugin\n')
            (tmp/'requirements.json').write_text(json.dumps(dict(schema_version=1,revision=1,requirements=[dict(id='R1',goals=['goal/a','goal/b'])])))
            def execute(args,out,d,case,context):
                log,code=next(r[3:] for r in runs if r[0]==case['id']);(d/'simulation.log').write_text(log);return dict(command=['stand-in'],returncode=code,error=None,seconds=0.0)
            plugin=SimpleNamespace(__file__=str(tmp/'plugin.py'),NAME='stand-in',CONFIGS=dict(only={}),INPUTS=[],probes=lambda args:{},prepare=lambda args,out:None,execute=execute,
                cases=lambda args:[dict(id=i,configuration='only',category=c,expected_failure=x,checks=2,counts=dict(completed=1)) for i,c,x,_,_ in runs])
            args=SimpleNamespace(out=tmp/'out',profile='smoke',seed=17,iterations=1,timeout=10)
            # The manifest names its inputs relative to ROOT; the stand-in lives outside the repository.
            with patch.object(H,'ROOT',Path(tmp.anchor)),contextlib.redirect_stdout(io.StringIO()):code=H.run(plugin,args)
            summary=json.loads((tmp/'out/summary.json').read_text());self.assertEqual(code,0 if summary['success'] else 1)
            return code,{r['id']:(r['outcome'],r['message']) for r in summary['results']},json.loads((tmp/'out/coverage.json').read_text())['only'],ET.parse(tmp/'out/junit.xml').getroot()
    def nodes(self,suite,kind):return [(c.get('name'),c.find(kind).get('message')) for c in suite if c.find(kind) is not None]
    def test_a_complete_plan_passes_with_a_clean_junit(self):
        code,outcomes,coverage,suite=self.run_plan(self.NORMAL,self.MUTANT)
        self.assertEqual(code,0);self.assertEqual({k:v[0] for k,v in outcomes.items()},dict(normal='pass',mutant='detected'));self.assertTrue(coverage['success'])
        self.assertEqual((suite.get('tests'),suite.get('failures'),suite.get('errors')),('3','0','0'));self.assertEqual(self.nodes(suite,'failure')+self.nodes(suite,'error'),[])
    def test_a_failing_case_fails_the_run_and_its_junit(self):
        code,outcomes,coverage,suite=self.run_plan(self.NORMAL,('second','functional',None,'CHECK_FAIL DATA\n',1),self.MUTANT)
        self.assertEqual(code,1);self.assertEqual(outcomes['second'],('fail','checker failure: DATA'));self.assertTrue(coverage['success'])
        self.assertEqual((suite.get('tests'),suite.get('failures'),suite.get('errors')),('4','1','0'))
        self.assertEqual(self.nodes(suite,'failure'),[('second','checker failure: DATA')]);self.assertEqual(self.nodes(suite,'error'),[])
        # What the failing case observed is not credited either.
        code,outcomes,coverage,suite=self.run_plan(('normal','functional',None,self.GOOD.replace('COVER goal/b\n',''),0),('second','functional',None,'COVER goal/b\nCHECK_FAIL DATA\n',1))
        self.assertEqual(coverage['missing'],['goal/b']);self.assertEqual(sorted(self.nodes(suite,'failure')),[('only-coverage','missing required goals'),('second','checker failure: DATA')])
    def test_a_surviving_mutant_fails_the_run_and_its_junit(self):
        code,outcomes,coverage,suite=self.run_plan(self.NORMAL,('mutant','mutation','LABEL',self.GOOD,0))
        self.assertEqual(code,1);self.assertEqual(outcomes,dict(normal=('pass','completed planned checks: 2'),mutant=('fail','mutation survived; expected LABEL')));self.assertTrue(coverage['success'])
        self.assertEqual((suite.get('failures'),suite.get('errors')),('1','0'));self.assertEqual(self.nodes(suite,'failure'),[('mutant','mutation survived; expected LABEL')])
    def test_an_error_outcome_fails_the_run_and_is_a_junit_error(self):
        code,outcomes,coverage,suite=self.run_plan(self.NORMAL,('second','functional',None,'RESULT PASS checks=2\n',0),self.MUTANT)
        self.assertEqual(code,1);self.assertEqual(outcomes['second'],('error','missing/duplicate/incorrect counts'));self.assertTrue(coverage['success'])
        self.assertEqual((suite.get('failures'),suite.get('errors')),('0','1'))
        self.assertEqual(self.nodes(suite,'error'),[('second','missing/duplicate/incorrect counts')]);self.assertEqual(self.nodes(suite,'failure'),[])
    def test_a_goal_seen_only_outside_a_passing_functional_case_fails_the_coverage_gate(self):
        partial=self.GOOD.replace('COVER goal/b\n','')
        for name,other in (('diagnostic',('other','diagnostic',None,self.GOOD,0)),('detected',('other','mutation','LABEL','COVER goal/b\nCHECK_FAIL LABEL\n',1))):
            with self.subTest(name):
                code,outcomes,coverage,suite=self.run_plan(('normal','functional',None,partial,0),other)
                self.assertEqual(code,1);self.assertEqual({v[0] for v in outcomes.values()}-{'pass','detected'},set())
                self.assertEqual((coverage['success'],coverage['missing'],coverage['hit'],coverage['required']),(False,['goal/b'],1,2))
                self.assertEqual((suite.get('tests'),suite.get('failures'),suite.get('errors')),('3','1','0'))
                self.assertEqual(self.nodes(suite,'failure'),[('only-coverage','missing required goals')]);self.assertEqual(suite.find('.//failure').text,'goal/b')
    def test_an_empty_or_duplicate_plan_is_refused(self):
        for runs in ((),(self.NORMAL,self.NORMAL)):
            with self.subTest(runs=len(runs)),self.assertRaisesRegex(ValueError,'empty/duplicate case plan'):self.run_plan(*runs)
if __name__=='__main__':unittest.main()

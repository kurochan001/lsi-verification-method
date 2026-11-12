import contextlib
import copy
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
HERE=Path(__file__).resolve().parents[1];EXAMPLES=HERE.parent

def load(path):
    spec=importlib.util.spec_from_file_location(path.parent.name.replace('-','_'),path)
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
R=load(HERE/'runner.py');EQ=load(EXAMPLES/'local-equivalence/run.py')

class EvidenceTest(unittest.TestCase):
    def setUp(self):
        self.case=EQ.plan(12,0)[0];self.props=EQ.properties(dict(DEPTH=2,WIDTH=4),self.case)
        self.ok=dict(error=None,returncode=0)
    def judge(self,case=None,execution=None,status='PASS',log='',traces=None):
        return R.judge(case or self.case,execution or self.ok,status,log,[] if traces is None else traces,self.props)[0]
    def test_proof_requires_completed_induction(self):
        self.assertEqual(self.judge(),'error')
        self.assertEqual(self.judge(log='successful proof by k-induction'),'pass')
    def test_timeout_unknown_and_status_exit_conflicts_fail(self):
        self.assertEqual(self.judge(status='TIMEOUT'),'error')
        self.assertEqual(self.judge(status='UNKNOWN'),'error')
        self.assertEqual(self.judge(execution=dict(error='command timeout',returncode=None)),'error')
        self.assertEqual(self.judge(execution=dict(error=None,returncode=2)),'error')
    def test_pass_status_with_an_assertion_violation_is_an_error(self):
        self.assertEqual(self.judge(log='successful proof by k-induction\nAssert failed in equivalence_formal: ap_data'),'error')
    def test_compiled_inventory_is_enforced_by_the_runner(self):
        with tempfile.TemporaryDirectory() as tmp:
            out=Path(tmp)/'out';sby=Path(tmp)/'fake-sby'
            sby.write_text('#!/bin/sh\nmkdir -p task/model task/engine_0\necho PASS > task/status\necho "successful proof by k-induction" > task/logfile.txt\necho \'{"modules":{}}\' > task/model/inventory.json\n');sby.chmod(0o755)
            p=subprocess.run([sys.executable,EQ.__file__,'--configuration','depth2','--task','equivalence-proof','--sby',str(sby),'--out',str(out)],capture_output=True,text=True,timeout=30)
            self.assertEqual(p.returncode,1,p.stdout+p.stderr)
            self.assertIn('invalid evidence',json.loads((out/'summary.json').read_text())['results'][0]['message'])
    def test_bmc_requires_engine_completion(self):
        case=dict(self.case,mode='bmc')
        self.assertEqual(self.judge(case=case),'error')
        self.assertEqual(self.judge(case=case,log='Status: passed'),'pass')
    def test_cover_requires_every_goal_and_witness(self):
        case=EQ.plan(12,0)[1]
        log='\n'.join(f'Reached cover statement in step 4 at equivalence_formal: {goal}' for goal in EQ.COVERS)
        self.assertEqual(self.judge(case=case,log=log),'error')
        self.assertEqual(self.judge(case=case,log=log,traces=['witness.vcd']),'pass')
        self.assertEqual(self.judge(case=case,log=log.replace('cp_full','unknown_goal'),traces=['witness.vcd']),'error')
    def test_mutation_requires_intended_assertion_and_counterexample(self):
        case=EQ.plan(12,0)[2];execution=dict(error=None,returncode=2)
        for log,traces in [('Assert failed in equivalence_formal: ap_data',['trace.vcd']),('Assert failed in equivalence_formal: ap_control',[])]:
            self.assertEqual(self.judge(case,execution,'FAIL',log,traces),'error')
        self.assertEqual(self.judge(case,execution,'FAIL','Assert failed in equivalence_formal: ap_control',['trace.vcd']),'detected')
    def test_environment_counterexample_requires_intended_assertion(self):
        case=dict(self.case,mode='bmc',expect='FAIL',category='counterexample',failure='ap_control')
        self.assertEqual(self.judge(case,dict(error=None,returncode=2),'FAIL','Assert failed in equivalence_formal: ap_control',['trace.vcd']),'detected')
        self.assertEqual(self.judge(case,dict(error=None,returncode=2),'FAIL','Assert failed in equivalence_formal: ap_data',['trace.vcd']),'error')
    def test_overconstraint_is_diagnostic_and_requires_all_unreached(self):
        case=EQ.plan(12,0)[-1];execution=dict(error=None,returncode=2)
        log='\n'.join(f'Unreached cover statement at equivalence_formal: {g}' for g in EQ.COVERS)
        self.assertEqual(self.judge(case,execution,'FAIL',log,[]),'detected')
        self.assertEqual(self.judge(case,execution,'FAIL',log,['trace.vcd']),'error')
    def test_a_status_other_than_the_expected_one_is_a_failure(self):
        self.assertEqual(R.judge(self.case,dict(error=None,returncode=2),'FAIL','Assert failed in equivalence_formal: ap_data',['trace.vcd'],self.props),('fail','expected PASS, got FAIL'))
        self.assertEqual(R.judge(EQ.plan(12,0)[2],self.ok,'PASS','Status: passed',[],self.props),('fail','expected FAIL, got PASS'))
    def test_a_counterexample_that_also_fails_an_unplanned_assertion_is_an_error(self):
        execution=dict(error=None,returncode=2);log='Assert failed in equivalence_formal: ap_control\n'
        for case in (EQ.plan(12,0)[2],dict(self.case,mode='bmc',expect='FAIL',category='counterexample',failure='ap_control')):
            with self.subTest(case['category']):
                self.assertEqual(self.judge(case,execution,'FAIL',log+'Assert failed in equivalence_formal: ap_data',['trace.vcd']),'detected')
                self.assertEqual(R.judge(case,execution,'FAIL',log+'Assert failed in equivalence_formal: ap_unplanned',['trace.vcd'],self.props),('error','FAIL lacks intended property and trace evidence'))
        self.assertEqual(self.judge(dict(EQ.plan(12,0)[2],category='normal'),execution,'FAIL',log,['trace.vcd']),'error')
    def test_overconstraint_is_accepted_only_for_a_diagnostic_cover_with_exactly_the_planned_goals_unreached(self):
        case=EQ.plan(12,0)[-1];execution=dict(error=None,returncode=2);goals=sorted(EQ.COVERS)
        log='\n'.join(f'Unreached cover statement at equivalence_formal: {g}' for g in goals)
        self.assertEqual(R.judge(case,execution,'FAIL',log,[],self.props),('detected','permanent reset blocks all normal goals within bound'))
        for name,text in (('one goal not reported',log.replace(f'Unreached cover statement at equivalence_formal: {goals[0]}','')),('unplanned goal',log+'\nUnreached cover statement at equivalence_formal: cp_unplanned'),
                          ('one goal reached',log+f'\nReached cover statement in step 3 at equivalence_formal: {goals[0]}'),('assertion failed',log+'\nAssert failed in equivalence_formal: ap_data')):
            with self.subTest(name):self.assertEqual(R.judge(case,execution,'FAIL',text,[],self.props),('error','FAIL lacks intended property and trace evidence'))
        for change in (dict(category='normal'),dict(category='mutation'),dict(mode='bmc')):
            with self.subTest(change=change):self.assertEqual(self.judge(dict(case,**change),execution,'FAIL',log,[]),'error')
    def test_cover_pass_with_an_unplanned_or_unreached_goal_is_an_error(self):
        case=EQ.plan(12,0)[1];log='\n'.join(f'Reached cover statement in step 4 at equivalence_formal: {goal}' for goal in sorted(EQ.COVERS))
        self.assertEqual(R.judge(case,self.ok,'PASS',log,['witness.vcd'],self.props),('pass','all covers reached'))
        for extra in ('Reached cover statement in step 4 at equivalence_formal: cp_unplanned','Unreached cover statement at equivalence_formal: cp_unplanned','Unreached cover statement at equivalence_formal: cp_full'):
            with self.subTest(extra):self.assertEqual(R.judge(case,self.ok,'PASS',log+'\n'+extra,['witness.vcd'],self.props),('error','incomplete covers or witnesses'))
    def test_compiled_inventory_checks_names_parameters_and_duplicates(self):
        params=dict(DEPTH=2,WIDTH=4);case=self.case
        cells={}
        for kind,names in self.props.items():
            for name in names:cells[name]=dict(type='$check',parameters=dict(FLAVOR=kind))
        top=dict(parameter_default_values={k:format(v,'032b') for k,v in {**params,**case['parameters']}.items()},cells=cells)
        model=dict(modules={EQ.TOP:top})
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'inventory.json';path.write_text(json.dumps(model))
            R.inventory(path,EQ,params,case)
            for change in ('parameter','missing','duplicate'):
                bad=copy.deepcopy(model);t=bad['modules'][EQ.TOP]
                if change=='parameter':t['parameter_default_values']['DEPTH']='11'
                elif change=='missing':del t['cells']['ap_data']
                else:t['cells']['dut.ap_data']=t['cells']['ap_data']
                path.write_text(json.dumps(bad))
                with self.assertRaises(ValueError):R.inventory(path,EQ,params,case)
    def test_parameters_may_live_on_a_module_below_the_checker(self):
        CONN=load(EXAMPLES/'local-connectivity/run.py');case=CONN.plan(8,0)[2];props=CONN.properties({},case)
        cells={n:dict(type='$check',parameters=dict(FLAVOR=k)) for k,names in props.items() for n in names}
        model=dict(modules={CONN.TOP:dict(parameter_default_values={},cells=cells),
                            CONN.PARAMETER_MODULE:dict(parameter_default_values=dict(MUTATION=format(1,'032b')),cells={})})
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'inventory.json';path.write_text(json.dumps(model))
            self.assertEqual(R.inventory(path,CONN,{},case)['assume'],[])
            model['modules'][CONN.PARAMETER_MODULE]['parameter_default_values']['MUTATION']=format(2,'032b')
            path.write_text(json.dumps(model))
            with self.assertRaises(ValueError):R.inventory(path,CONN,{},case)
        self.assertIn('read -formal -sv conn_check.sv',CONN.prepare({},case))
    def test_runner_writes_the_plugin_preparation_into_the_task(self):
        CONN=load(EXAMPLES/'local-connectivity/run.py')
        with tempfile.TemporaryDirectory() as tmp:
            out=Path(tmp)/'out';absent=str(Path(tmp)/'absent')
            p=subprocess.run([sys.executable,CONN.__file__,'--task','connectivity-proof','--sby',absent,'--yosys',absent,'--out',str(out)],capture_output=True,text=True,timeout=30)
            self.assertEqual(p.returncode,1,p.stdout+p.stderr)
            script=(out/'soc-connectivity-proof/task.sby').read_text().split('[script]\n')[1].split('prep -top')[0]
            self.assertEqual(script,CONN.prepare({},CONN.plan(8,0)[0]))
    def test_induction_traces_are_not_required_to_carry_a_witness(self):
        with tempfile.TemporaryDirectory() as tmp:
            engine=Path(tmp)/'engine_0';engine.mkdir()
            for name,text in [('trace.vcd','$enddefinitions'),('trace.yw','w'),('trace_induct.vcd','$enddefinitions')]:(engine/name).write_text(text)
            self.assertEqual(R.witnessed_traces(engine,Path(tmp)),['engine_0/trace.vcd'])
            (engine/'trace.yw').unlink()
            with self.assertRaises(ValueError):R.witnessed_traces(engine,Path(tmp))
    def test_missing_tools_cannot_be_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            out=Path(tmp)/'out';absent=str(Path(tmp)/'absent')
            p=subprocess.run([sys.executable,EQ.__file__,'--configuration','depth2','--task','equivalence-proof','--sby',absent,'--yosys',absent,'--out',str(out)],capture_output=True,text=True,timeout=15)
            self.assertEqual(p.returncode,1,p.stdout+p.stderr)
            summary=json.loads((out/'summary.json').read_text());self.assertFalse(summary['success'])
            self.assertEqual(summary['results'][0]['outcome'],'error')
            sentinel=out/'keep';sentinel.write_text('keep')
            p=subprocess.run([sys.executable,EQ.__file__,'--out',str(out)],capture_output=True,text=True)
            self.assertEqual(p.returncode,2);self.assertEqual(sentinel.read_text(),'keep')
class RunTests(unittest.TestCase):
    """The verdict of a whole run, from a stand-in plugin and a stand-in sby that writes prepared results."""
    COVERS=['cp_first','cp_second']
    BASE=dict(depth=12,failure=None,parameters={})
    PROOF=(dict(BASE,id='proof',mode='prove',expect='PASS',category='normal'),dict(status='PASS',log='successful proof by k-induction\n',code=0))
    COVER=(dict(BASE,id='scenario-cover',mode='cover',expect='PASS',category='normal'),dict(status='PASS',log=''.join(f'Reached cover statement in step 3 at top: {g}\n' for g in COVERS),code=0,traces=['trace0']))
    MUTANT=(dict(BASE,id='detect-mutation1',mode='bmc',expect='FAIL',category='mutation',failure='ap_only'),dict(status='FAIL',log='Assert failed in top: ap_only\n',code=2,traces=['trace']))
    def run_plan(self,*tasks):
        """Each task is (case, what sby leaves behind); returns exit code, results by case, coverage and JUnit."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp=Path(tmp).resolve();(tmp/'plugin.py').write_text('# stand-in plugin\n')
            cells={n:dict(type='$check',parameters=dict(FLAVOR=k)) for k,names in (('assert',['ap_only']),('cover',self.COVERS)) for n in names}
            (tmp/'sby.json').write_text(json.dumps(dict(inventory=dict(modules=dict(top=dict(parameter_default_values={},cells=cells))),tasks={'only-'+c['id']:r for c,r in tasks})))
            sby=tmp/'sby';sby.write_text('#!'+sys.executable+'\nimport json,os,sys\nif "--version" in sys.argv:print("stand-in");sys.exit(0)\n'
                f'spec=json.load(open({str(tmp/"sby.json")!r}));task=spec["tasks"][os.path.basename(os.getcwd())];os.makedirs("task/model");os.mkdir("task/engine_0")\n'
                'json.dump(spec["inventory"],open("task/model/inventory.json","w"));open("task/logfile.txt","w").write(task["log"])\n'
                'if task["status"] is not None:open("task/status","w").write(task["status"])\n'
                'for name in task.get("traces",[]):open(f"task/engine_0/{name}.vcd","w").write("$enddefinitions $end\\n");open(f"task/engine_0/{name}.yw","w").write("witness\\n")\n'
                'sys.exit(task["code"])\n');sby.chmod(0o755)
            plugin=SimpleNamespace(__file__=str(tmp/'plugin.py'),TOP='top',CONFIGS=dict(only={}),SOURCES=[],SCOPE='stand-in',plan=lambda bound,bug:[copy.deepcopy(c) for c,_ in tasks],
                properties=lambda parameters,case:{'assert':['ap_only'],'assume':[],'cover':self.COVERS})
            absent=str(tmp/'absent');args=SimpleNamespace(out=tmp/'out',configuration='all',task='all',bound=12,demo_bug=0,timeout=10,sby=str(sby),yosys=absent,smtbmc=absent,witness=absent)
            # The manifest names its inputs relative to ROOT; the stand-in lives outside the repository.
            with patch.object(R,'ROOT',Path(tmp.anchor)),contextlib.redirect_stdout(io.StringIO()):code=R.run(plugin,args)
            summary=json.loads((tmp/'out/summary.json').read_text());self.assertEqual(code,0 if summary['success'] else 1);self.assertEqual(summary['planned'],len(tasks))
            return code,{r['id'][5:]:(r['outcome'],r['message'],r['formal_status']) for r in summary['results']},json.loads((tmp/'out/coverage.json').read_text()),ET.parse(tmp/'out/junit.xml').getroot()
    def nodes(self,suite,kind):return [(c.get('name'),c.find(kind).get('message')) for c in suite if c.find(kind) is not None]
    def test_an_empty_or_duplicate_plan_is_refused_before_anything_is_written(self):
        for tasks in ((),(self.PROOF,self.PROOF)):
            with self.subTest(tasks=len(tasks)),tempfile.TemporaryDirectory() as tmp:
                plugin=SimpleNamespace(__file__=str(Path(tmp)/'plugin.py'),CONFIGS=dict(only={}),SOURCES=[],plan=lambda bound,bug:[copy.deepcopy(c) for c,_ in tasks])
                args=SimpleNamespace(out=Path(tmp)/'out',configuration='all',task='all',bound=12,demo_bug=0)
                with self.assertRaisesRegex(ValueError,'empty or duplicate task plan'):R.run(plugin,args)
                self.assertFalse(args.out.exists())
    def test_a_complete_plan_passes_with_a_clean_junit(self):
        code,results,coverage,suite=self.run_plan(self.PROOF,self.COVER,self.MUTANT)
        self.assertEqual(code,0);self.assertEqual({k:v[0] for k,v in results.items()},{'proof':'pass','scenario-cover':'pass','detect-mutation1':'detected'})
        self.assertEqual(coverage,dict(only=dict(success=True,hit=self.COVERS,missing=[])))
        self.assertEqual((suite.get('tests'),suite.get('failures'),suite.get('errors')),('3','0','0'));self.assertEqual(self.nodes(suite,'failure')+self.nodes(suite,'error'),[])
    def test_a_missing_or_empty_status_file_is_an_error_even_with_a_complete_log_and_exit_zero(self):
        for status in (None,' \n'):
            code,results,coverage,suite=self.run_plan((self.PROOF[0],dict(self.PROOF[1],status=status)),self.COVER,self.MUTANT)
            with self.subTest(status=status):
                self.assertEqual(code,1);self.assertEqual(results['proof'],('error','incomplete task or inconsistent status/exit','MISSING'))
                self.assertEqual((suite.get('failures'),suite.get('errors')),('0','1'));self.assertEqual(self.nodes(suite,'error'),[('only-proof','incomplete task or inconsistent status/exit')])
    def test_a_surviving_mutant_fails_the_run_with_a_junit_failure(self):
        code,results,coverage,suite=self.run_plan(self.PROOF,self.COVER,(self.MUTANT[0],dict(status='PASS',log='Status: passed\n',code=0)))
        self.assertEqual(code,1);self.assertEqual(results['detect-mutation1'],('fail','expected FAIL, got PASS','PASS'));self.assertTrue(coverage['only']['success'])
        self.assertEqual((suite.get('tests'),suite.get('failures'),suite.get('errors')),('3','1','0'))
        self.assertEqual(self.nodes(suite,'failure'),[('only-detect-mutation1','expected FAIL, got PASS')]);self.assertEqual(self.nodes(suite,'error'),[])
    def test_covers_of_a_run_that_did_not_pass_are_not_credited(self):
        code,results,coverage,suite=self.run_plan(self.PROOF,(self.COVER[0],dict(self.COVER[1],traces=[])),self.MUTANT)
        self.assertEqual(code,1);self.assertEqual(results['scenario-cover'],('error','incomplete covers or witnesses','PASS'))
        self.assertEqual(coverage,dict(only=dict(success=False,hit=[],missing=self.COVERS)));self.assertEqual(self.nodes(suite,'error'),[('only-scenario-cover','incomplete covers or witnesses')])
    def test_the_coverage_gate_fails_a_run_whose_cases_are_all_accepted(self):
        # Only a plan whose scenario-cover is itself a diagnostic reaches this: every outcome is accepted, yet no goal was reached.
        blocked=(dict(self.COVER[0],expect='FAIL',category='diagnostic'),dict(status='FAIL',log=''.join(f'Unreached cover statement at top: {g}\n' for g in self.COVERS),code=2))
        code,results,coverage,suite=self.run_plan(self.PROOF,blocked,self.MUTANT)
        self.assertEqual({v[0] for v in results.values()},{'pass','detected'});self.assertEqual(results['scenario-cover'][0],'detected')
        self.assertEqual(coverage,dict(only=dict(success=False,hit=[],missing=self.COVERS)));self.assertEqual(code,1)
if __name__=='__main__':unittest.main()

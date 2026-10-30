import copy
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
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
if __name__=='__main__':unittest.main()

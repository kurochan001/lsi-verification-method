"""Reject incomplete or misleading formal evidence without requiring formal tools."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET

PATH=Path(__file__).resolve().parents[1]/'run.py'
spec=importlib.util.spec_from_file_location('bus_formal',PATH)
FORMAL=importlib.util.module_from_spec(spec);spec.loader.exec_module(FORMAL)


class FormalRunnerTest(unittest.TestCase):
    def execution(self,code=0,error=None):return dict(returncode=code,error=error)
    def model(self,config,case):
        p=FORMAL.PROPERTIES[config['bus']]
        params={config['parameter']:config['value'],'MUTATION':case['mutation'],'CHECK_DATA':case['data'],'LOCK_RESET':case['lock']}
        cells={}
        for flavor,names in [('assert',p['control'] | (p['data'] if case['data'] else set())),
                             ('assume',p['assumptions'] | ({'as_lock_reset'} if case['lock'] else set())),('cover',p['covers'])]:
            for name in names:cells[name]=dict(type='$check',parameters=dict(FLAVOR=flavor))
        return dict(modules={config['bus']+'_formal':dict(parameter_default_values={k:format(v,'032b') for k,v in params.items()},cells=cells)})

    def test_proof_requires_induction_completion(self):
        case=FORMAL.plan(0,12)[0]
        self.assertEqual(FORMAL.judge('ahb',case,self.execution(),'PASS','',[])[0],'error')
        self.assertEqual(FORMAL.judge('ahb',case,self.execution(),'PASS','successful proof by k-induction',[])[0],'pass')

    def test_bmc_requires_engine_completion(self):
        case=FORMAL.plan(0,12)[1]
        self.assertEqual(FORMAL.judge('axi',case,self.execution(),'PASS','',[])[0],'error')
        self.assertEqual(FORMAL.judge('axi',case,self.execution(),'PASS','Status: passed',[])[0],'pass')

    def test_unknown_error_timeout_missing_are_not_success(self):
        case=FORMAL.plan(0,12)[0]
        for state in ('MISSING','UNKNOWN','ERROR','TIMEOUT'):
            self.assertEqual(FORMAL.judge('ahb',case,self.execution(),state,'',[])[0],'error')
        self.assertEqual(FORMAL.judge('ahb',case,self.execution(error='command timeout'),'PASS','successful proof by k-induction',[])[0],'error')

    def test_status_and_exit_code_must_agree(self):
        for case,code,state in [(FORMAL.plan(0,12)[0],1,'PASS'),(FORMAL.plan(0,12)[3],0,'FAIL')]:
            self.assertEqual(FORMAL.judge('ahb',case,self.execution(code),state,'',[])[0],'error')

    def test_mutant_needs_expected_assertion_and_trace(self):
        case=FORMAL.plan(0,12)[3]
        log='Assert failed in ahb_formal: data_checks.ap_data'
        self.assertEqual(FORMAL.judge('ahb',case,self.execution(2),'FAIL',log,['trace.vcd'])[0],'detected')
        self.assertEqual(FORMAL.judge('ahb',case,self.execution(2),'FAIL',log,[])[0],'error')
        self.assertEqual(FORMAL.judge('ahb',case,self.execution(2),'FAIL','Assert failed in ahb_formal: ap_reset',['trace.vcd'])[0],'error')

    def test_surviving_mutant_is_failure(self):
        self.assertEqual(FORMAL.judge('axi',FORMAL.plan(0,12)[3],self.execution(),'PASS','Status: passed',[])[0],'fail')

    def test_cover_needs_all_goals_and_witness(self):
        case=FORMAL.plan(0,12)[2]
        for bus in ('ahb','axi'):
            log='\n'.join(f'Reached cover statement in step 5 at {bus}_formal: {n}' for n in FORMAL.PROPERTIES[bus]['covers'])
            self.assertEqual(FORMAL.judge(bus,case,self.execution(),'PASS',log,['trace.vcd'])[0],'pass')
            self.assertEqual(FORMAL.judge(bus,case,self.execution(),'PASS',log,[])[0],'error')
            self.assertEqual(FORMAL.judge(bus,case,self.execution(),'PASS',log.splitlines()[0],['trace.vcd'])[0],'error')

    def test_overconstraint_diagnostic_is_not_arbitrary_fail(self):
        case=FORMAL.plan(0,12)[-1]
        log='\n'.join(f'Unreached cover statement at axi_formal: {n}' for n in FORMAL.PROPERTIES['axi']['covers'])
        self.assertEqual(FORMAL.judge('axi',case,self.execution(2),'FAIL',log,[])[0],'detected')
        for bad in ('crash',log+'\nAssert failed in axi_formal: ap_reset'):
            self.assertEqual(FORMAL.judge('axi',case,self.execution(2),'FAIL',bad,[])[0],'error')

    def test_inventory_rejects_missing_assertion_and_extra_assumption(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'inventory.json';config=FORMAL.CONFIGS['ahb-wait0'];case=FORMAL.plan(0,12)[1]
            model=self.model(config,case);path.write_text(json.dumps(model))
            self.assertIn('ap_data',FORMAL.inspect_model(path,config,case)['assert'])
            cells=model['modules']['ahb_formal']['cells'];del cells['ap_data'];path.write_text(json.dumps(model))
            with self.assertRaises(ValueError):FORMAL.inspect_model(path,config,case)
            cells['ap_data']=dict(type='$check',parameters=dict(FLAVOR='assert'))
            cells['extra_assumption']=dict(type='$check',parameters=dict(FLAVOR='assume'));path.write_text(json.dumps(model))
            with self.assertRaises(ValueError):FORMAL.inspect_model(path,config,case)

    def test_inventory_rejects_duplicate_labels_and_wrong_parameters(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'inventory.json';config=FORMAL.CONFIGS['axi-delay2'];case=FORMAL.plan(0,12)[0]
            model=self.model(config,case)
            model['modules']['axi_formal']['cells']['other.ap_reset']=dict(type='$check',parameters=dict(FLAVOR='assert'))
            path.write_text(json.dumps(model))
            with self.assertRaises(ValueError):FORMAL.inspect_model(path,config,case)
            del model['modules']['axi_formal']['cells']['other.ap_reset']
            model['modules']['axi_formal']['parameter_default_values']['RESP_DELAY']='0';path.write_text(json.dumps(model))
            with self.assertRaises(ValueError):FORMAL.inspect_model(path,config,case)

    def test_missing_tool_fails_every_planned_junit_case(self):
        with tempfile.TemporaryDirectory() as tmp:
            out=Path(tmp)/'out';missing=str(Path(tmp)/'missing')
            p=subprocess.run([sys.executable,str(PATH),'--bus','ahb','--configuration','ahb-wait0',
                '--sby',missing,'--yosys',missing,'--out',str(out)],capture_output=True,text=True,timeout=30)
            self.assertEqual(p.returncode,1,p.stdout+p.stderr)
            self.assertFalse(json.loads((out/'summary.json').read_text())['success'])
            suite=ET.parse(out/'junit.xml').getroot()
            self.assertEqual(suite.get('errors'),'9');self.assertEqual(len(suite.findall('testcase/error')),9)

    def test_existing_output_and_invalid_configuration_do_not_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            out=Path(tmp)/'out';out.mkdir();(out/'sentinel').write_text('keep')
            p=subprocess.run([sys.executable,str(PATH),'--out',str(out)],capture_output=True,text=True)
            self.assertEqual(p.returncode,2);self.assertEqual((out/'sentinel').read_text(),'keep')
            other=Path(tmp)/'other'
            for options in [('--bus','axi','--configuration','ahb-wait0'),('--bound','0')]:
                p=subprocess.run([sys.executable,str(PATH),'--out',str(other),*options],capture_output=True,text=True)
                self.assertEqual(p.returncode,2);self.assertFalse(other.exists())


if __name__=='__main__':unittest.main()

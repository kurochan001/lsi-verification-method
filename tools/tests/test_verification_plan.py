import copy
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
SPEC=importlib.util.spec_from_file_location('verification_plan',Path(__file__).resolve().parents[1]/'verification_plan.py')
V=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(V)

class PlanTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        (self.root/'仕様.txt').write_text('S01: acceptance specification\n');(self.root/'rtl.sv').write_text('// implementation\n')
        (self.root/'execution.log').write_text('checked real observations\n')
        self.plan=dict(schema_version=1,id='example-r1',sources=['仕様.txt','rtl.sv'],requirements=[dict(id='R1',source='仕様.txt',anchor='S01')],
                       tests=[dict(id='directed',configuration='port0')],items=[dict(id='T1',requirements=['R1'],tests=['directed'],configurations=['port0'],checkers=['compare'],goals=['boundary'])])
        self.evidence=dict(schema_version=1,plan_id='example-r1',plan_sha256='reviewed-plan',source_sha256={n:V.digest(self.root/n) for n in self.plan['sources']},
                           artifacts={'execution.log':V.digest(self.root/'execution.log')},results=[dict(id='directed',configuration='port0',status='pass',complete=True,comparisons=2,checkers={'compare':2},goals={'boundary':1})])
    def audit(self,p=None,e=None):return V.audit(p or self.plan,e or self.evidence,self.root,'reviewed-plan',self.root)
    def test_valid_plan_with_japanese_source_paths(self):self.assertTrue(self.audit()['success'])
    def test_requirements_without_items_are_rejected(self):
        p=copy.deepcopy(self.plan);p['requirements'].append(dict(id='R2',source='仕様.txt',anchor='S01'))
        self.assertIn('UNMAPPED_REQUIREMENT',';'.join(self.audit(p=p)['errors']))
    def test_missing_duplicate_and_unplanned_executions(self):
        for rows in ([],self.evidence['results']*2,[dict(self.evidence['results'][0],id='other')]):
            e=copy.deepcopy(self.evidence);e['results']=rows;self.assertFalse(self.audit(e=e)['success'])
    def test_failed_incomplete_and_zero_comparison_tests_are_not_credited(self):
        for change in (dict(status='fail'),dict(complete=False),dict(comparisons=0),dict(comparisons=True)):
            e=copy.deepcopy(self.evidence);e['results'][0].update(change);r=self.audit(e=e)
            self.assertFalse(r['success']);self.assertTrue(all(not i['success'] for i in r['items']))
    def test_missing_checker_goal_or_required_hits_is_rejected(self):
        for key in ('checkers','goals'):
            e=copy.deepcopy(self.evidence);e['results'][0][key]={};self.assertFalse(self.audit(e=e)['success'])
        p=copy.deepcopy(self.plan);p['items'][0]['min_hits']=3;self.assertFalse(self.audit(p=p)['success'])
    def test_counter_inventory_and_types_are_checked(self):
        for counts in ({'other':1},{'compare':-1},{'compare':True},{'compare':1.5}):
            e=copy.deepcopy(self.evidence);e['results'][0]['checkers']=counts;self.assertFalse(self.audit(e=e)['success'])
    def test_instances_cannot_fill_each_others_missing_goals(self):
        p=copy.deepcopy(self.plan);p['tests'].append(dict(id='second',configuration='port1'));p['items'][0]['tests'].append('second');p['items'][0]['configurations'].append('port1')
        e=copy.deepcopy(self.evidence);e['results'].append(dict(copy.deepcopy(e['results'][0]),id='second',configuration='port1',goals={'boundary':0}))
        self.assertFalse(self.audit(p,e)['success'])
    def test_wrong_configuration_is_not_credited(self):
        e=copy.deepcopy(self.evidence);e['results'][0]['configuration']='port1';self.assertFalse(self.audit(e=e)['success'])
    def test_goal_cannot_borrow_checker_completion_from_another_test(self):
        p=copy.deepcopy(self.plan);p['tests'].append(dict(id='unchecked',configuration='port0'));p['items'][0]['tests'].append('unchecked')
        e=copy.deepcopy(self.evidence);e['results'][0]['goals']['boundary']=0
        e['results'].append(dict(copy.deepcopy(e['results'][0]),id='unchecked',checkers={'compare':0},goals={'boundary':1}))
        self.assertFalse(self.audit(p,e)['success'])
    def test_changed_plan_source_and_artifact_invalidate_all_items(self):
        e=copy.deepcopy(self.evidence);e['plan_sha256']='old';self.assertFalse(self.audit(e=e)['success'])
        for file in ('rtl.sv','仕様.txt','execution.log'):
            p=self.root/file;before=p.read_bytes();p.write_bytes(before+b'changed')
            report=self.audit();self.assertFalse(report['success']);self.assertTrue(all(not i['success'] for i in report['items']));p.write_bytes(before)
    def test_bad_references_and_schema_are_rejected(self):
        for field,value in [('schema_version',True),('sources',['../missing']),('requirements',[])]:
            p=copy.deepcopy(self.plan);p[field]=value;self.assertFalse(self.audit(p=p)['success'])
        p=copy.deepcopy(self.plan);p['items'][0]['requirements']=['unknown'];self.assertFalse(self.audit(p=p)['success'])
    def test_cli_writes_failure_report_and_never_overwrites_output(self):
        plan=self.root/'plan.json';evidence=self.root/'evidence.json';out=self.root/'out'
        plan.write_text(json.dumps(self.plan));evidence.write_text(json.dumps(self.evidence))
        command=[sys.executable,V.__file__,'--root',str(self.root),'--plan',str(plan),'--evidence',str(evidence),'--out',str(out)]
        p=subprocess.run(command,capture_output=True,text=True);self.assertEqual(p.returncode,1,p.stdout+p.stderr)
        before=(out/'report.json').read_bytes();self.assertFalse(json.loads(before)['success']);self.assertTrue((out/'junit.xml').is_file())
        p=subprocess.run(command,capture_output=True,text=True);self.assertEqual(p.returncode,2);self.assertEqual((out/'report.json').read_bytes(),before)
if __name__=='__main__':unittest.main()

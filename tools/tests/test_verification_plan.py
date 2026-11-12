import copy
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
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
    def errors(self,p=None,e=None,root=None):
        report=V.audit(p or self.plan,e or self.evidence,root or self.root,'reviewed-plan',self.root);self.assertFalse(report['success']);return report['errors']
    def test_a_source_must_be_a_relative_path_inside_the_root(self):
        inner=self.root/'inner';inner.mkdir();(inner/'仕様.txt').write_text('S01: acceptance specification\n')
        for name,label in (('../rtl.sv','INVALID_EVIDENCE: missing/outside-root source: ../rtl.sv'),(str(self.root/'rtl.sv'),'INVALID_EVIDENCE: source path must be relative to --root')):
            p=copy.deepcopy(self.plan);p['sources']=['仕様.txt',name];e=copy.deepcopy(self.evidence);e['source_sha256']={'仕様.txt':V.digest(inner/'仕様.txt'),name:V.digest(self.root/'rtl.sv')}
            with self.subTest(name):self.assertEqual(self.errors(p,e,inner),[label])
        (inner/'rtl.sv').write_text('// implementation\n');p['sources']=['仕様.txt','rtl.sv'];e['source_sha256']['rtl.sv']=e['source_sha256'].pop(name)
        self.assertTrue(V.audit(p,e,inner,'reviewed-plan',self.root)['success'])
    def test_min_hits_must_be_a_positive_integer(self):
        e=copy.deepcopy(self.evidence);e['results'][0]['goals']['boundary']=0
        self.assertEqual(self.errors(e=e),['UNMET_ITEM: T1'])
        for value in (0,-1,True,1.5,'1',None):
            p=copy.deepcopy(self.plan);p['items'][0]['min_hits']=value
            with self.subTest(value=value):
                self.assertEqual(self.errors(p,e),['INVALID_EVIDENCE: invalid min_hits']);self.assertEqual(self.errors(p),['INVALID_EVIDENCE: invalid min_hits'])
        p['items'][0]['min_hits']=2;self.assertEqual(self.errors(p),['UNMET_ITEM: T1']);e['results'][0]['goals']['boundary']=2;self.assertTrue(self.audit(p,e)['success'])
    def test_a_test_bound_to_no_item_is_rejected(self):
        p=copy.deepcopy(self.plan);p['tests'].append(dict(id='extra',configuration='port0'));e=copy.deepcopy(self.evidence);e['results'].append(dict(copy.deepcopy(e['results'][0]),id='extra'))
        self.assertEqual(self.errors(p,e),['UNMAPPED_TEST: extra'])
    def test_item_configurations_must_be_exactly_those_of_its_tests(self):
        for configurations in (['port0','port1'],['port1']):
            p=copy.deepcopy(self.plan);p['items'][0]['configurations']=configurations
            with self.subTest(configurations=configurations):self.assertEqual(self.errors(p),['INVALID_EVIDENCE: CONFIGURATION_PLAN: T1'])
    def test_requirement_source_and_anchor_are_checked(self):
        for change,label in ((dict(anchor='S99'),'SOURCE_ANCHOR: R1'),(dict(anchor=''),'INVALID_EVIDENCE: SOURCE_REFERENCE: R1'),(dict(anchor=None),'INVALID_EVIDENCE: SOURCE_REFERENCE: R1'),
                             (dict(source='execution.log',anchor='checked'),'INVALID_EVIDENCE: SOURCE_REFERENCE: R1')):
            p=copy.deepcopy(self.plan);p['requirements'][0].update(change)
            with self.subTest(change=change):self.assertEqual(self.errors(p),[label])
    def test_unknown_test_or_requirement_reference_is_rejected(self):
        for key in ('tests','requirements'):
            p=copy.deepcopy(self.plan);p['items'][0][key]=p['items'][0][key]+['unknown']
            with self.subTest(key):self.assertEqual(self.errors(p),['INVALID_EVIDENCE: UNKNOWN_REFERENCE: T1'])
    def test_evidence_without_artifacts_is_rejected(self):
        for artifacts in ({},None,[]):
            e=copy.deepcopy(self.evidence);e['artifacts']=artifacts
            with self.subTest(artifacts=artifacts):self.assertEqual(self.errors(e=e),['INVALID_EVIDENCE: ARTIFACT_INVENTORY: no underlying execution artifacts'])
    def test_evidence_for_another_plan_id_is_stale(self):
        e=copy.deepcopy(self.evidence);e['plan_id']='example-r2';r=self.audit(e=e)
        self.assertEqual(r['errors'],['STALE_PLAN: evidence does not identify this plan revision']);self.assertEqual([i['success'] for i in r['items']],[False])
    def test_junit_carries_a_failure_node_for_the_gate_and_each_failed_item(self):
        def junit(report,name):
            V.write_report(self.root/name,report);suite=ET.parse(self.root/name/'junit.xml').getroot()
            return (suite.get('tests'),suite.get('failures'),suite.get('errors')),[(c.get('name'),c.find('failure').get('message')) for c in suite if c.find('failure') is not None]
        self.assertEqual(junit(self.audit(),'good'),(('2','0','0'),[]))
        e=copy.deepcopy(self.evidence);e['results'][0]['goals']['boundary']=0
        self.assertEqual(junit(self.audit(e=e),'unmet'),(('2','2','0'),[('evidence-integrity','UNMET_ITEM: T1'),('T1','port0/goals/boundary')]))
        e=copy.deepcopy(self.evidence);e['plan_id']='other'
        self.assertEqual(junit(self.audit(e=e),'stale'),(('2','2','0'),[('evidence-integrity','STALE_PLAN: evidence does not identify this plan revision'),('T1','')]))
    def test_cli_writes_failure_report_and_never_overwrites_output(self):
        plan=self.root/'plan.json';evidence=self.root/'evidence.json';out=self.root/'out'
        plan.write_text(json.dumps(self.plan));evidence.write_text(json.dumps(self.evidence))
        command=[sys.executable,V.__file__,'--root',str(self.root),'--plan',str(plan),'--evidence',str(evidence),'--out',str(out)]
        p=subprocess.run(command,capture_output=True,text=True);self.assertEqual(p.returncode,1,p.stdout+p.stderr)
        before=(out/'report.json').read_bytes();self.assertFalse(json.loads(before)['success']);self.assertTrue((out/'junit.xml').is_file())
        p=subprocess.run(command,capture_output=True,text=True);self.assertEqual(p.returncode,2);self.assertEqual((out/'report.json').read_bytes(),before)
if __name__=='__main__':unittest.main()

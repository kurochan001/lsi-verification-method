import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
HERE=Path(__file__).resolve().parents[1]
def load(name,file):
    s=importlib.util.spec_from_file_location(name,HERE/file);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
D=load('test_dependency','dependencies.py');F=load('test_contract_tasks','formal_tasks.py')
class DependencyTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name);(self.root/'rtl.sv').write_text('source')
        self.sources={'rtl.sv':hashlib.sha256((self.root/'rtl.sv').read_bytes()).hexdigest()};self.plan=json.loads((HERE/'plan.json').read_text())
        self.rows=[dict(id='chain-'+task,configuration='chain',category='normal',mode='prove',outcome='pass',formal_status='PASS',inventory={'assert':['ap_example']}) for task in F.PROOFS.values()]
    def audit(self):return D.audit(self.plan,self.rows,self.sources,self.root,F.PROOFS)
    def test_valid_closure_keeps_assumption_discharge_before_integration(self):
        r=self.audit();self.assertTrue(r['success']);self.assertLess(r['order'].index('producer'),r['order'].index('connection'));self.assertEqual(r['order'][-1],'integration')
    def test_missing_or_duplicate_proof_cannot_pass(self):
        original=copy.deepcopy(self.rows)
        for rows in (original[:-1],original+[original[0]],original[:-1]+[original[0]]):self.rows=rows;self.assertFalse(self.audit()['success'])
    def test_bmc_failed_wrong_configuration_and_diagnostic_proof_are_rejected(self):
        for field,value in [('mode','bmc'),('outcome','detected'),('formal_status','FAIL'),('configuration','other'),('category','diagnostic'),('inventory',{})]:
            rows=copy.deepcopy(self.rows);self.rows[0][field]=value;self.assertFalse(self.audit()['success']);self.rows=rows
    def test_stale_sources_invalidate_the_complete_claim(self):
        (self.root/'rtl.sv').write_text('new implementation');self.assertFalse(self.audit()['success'])
    def test_cycles_orphans_unknown_dependencies_and_duplicate_nodes(self):
        original=copy.deepcopy(self.plan)
        for mutate in (lambda p:p['nodes'][0]['requires'].append('integration'),lambda p:p['nodes'][-1].update(requires=['consumer']),lambda p:p['nodes'][0]['requires'].append('unknown'),lambda p:p['nodes'].append(copy.deepcopy(p['nodes'][0]))):
            self.plan=copy.deepcopy(original);mutate(self.plan);self.assertFalse(self.audit()['success'])
    def test_property_inventories_and_fixed_task_plan_are_distinct(self):
        cases=F.plan(8,0);self.assertEqual(len(cases),11);self.assertEqual(sum(c['mode']=='prove' and c['category']=='normal' for c in cases),4)
        consumer=next(c for c in cases if c['id']=='consumer-guarantee');connection=next(c for c in cases if c['id']=='connection-contract')
        self.assertIn('as_upstream_hold',F.properties({},consumer)['assume']);self.assertNotIn('as_upstream_hold',F.properties({},connection)['assume'])
        missing=next(c for c in cases if c['id']=='missing-assumption');self.assertNotIn('as_upstream_hold',F.properties({},missing)['assume'])
    def test_invalid_plan_types_never_become_success(self):
        for plan in (None,[],{},dict(self.plan,schema_version=True)):
            self.assertFalse(D.audit(plan,self.rows,self.sources,self.root,F.PROOFS)['success'])
if __name__=='__main__':unittest.main()

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
STATEMENTS={'ag_source_hold':'contract_formal.sv:54.1-54.9','ag_sink_hold':'contract_formal.sv:56.1-56.9'}
class DependencyTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name);(self.root/'rtl.sv').write_text('source')
        self.sources={'rtl.sv':hashlib.sha256((self.root/'rtl.sv').read_bytes()).hexdigest()};self.plan=json.loads((HERE/'plan.json').read_text())
        self.cases={c['id']:c for c in F.plan(F.BOUND,0)};self.required=['rtl.sv']
        self.rows=[self.row(task) for task in F.PROOFS.values()]
    def row(self,task,identity=None,category='normal'):
        case=self.cases[task];inventory={k:sorted(v) for k,v in F.properties({},case).items()}
        table={name:[flavor,STATEMENTS.get(name,'other.sv:'+name)] for flavor,names in inventory.items() for name in names}
        return dict(id='chain-'+(identity or task),configuration='chain',category=category,mode=case['mode'],outcome='pass',formal_status='PASS',inventory=inventory,compiled=dict(parameters=dict(case['parameters']),properties=table))
    def audit(self):return D.audit(self.plan,self.rows,self.sources,self.root,F.PROOFS,self.cases,F.properties,self.required)
    def consumer(self):return next(r for r in self.rows if r['id']=='chain-consumer-guarantee')
    def rejected(self,text):
        r=self.audit();self.assertFalse(r['success']);self.assertIn(text,';'.join(r['errors']))
    def test_valid_closure_discharges_each_assumption_before_its_user(self):
        r=self.audit();self.assertTrue(r['success'],r);self.assertLess(r['order'].index('producer'),r['order'].index('connection'));self.assertLess(r['order'].index('connection'),r['order'].index('consumer'));self.assertEqual(r['target'],'consumer')
    def test_missing_or_duplicate_proof_cannot_pass(self):
        original=copy.deepcopy(self.rows)
        for rows in (original[:-1],original+[original[0]],original[:-1]+[original[0]]):self.rows=rows;self.assertFalse(self.audit()['success'])
    def test_bmc_failed_wrong_configuration_and_diagnostic_proof_are_rejected(self):
        for field,value in [('mode','bmc'),('outcome','detected'),('formal_status','FAIL'),('configuration','other'),('category','diagnostic'),('inventory',{})]:
            rows=copy.deepcopy(self.rows);self.rows[0][field]=value;self.assertFalse(self.audit()['success']);self.rows=rows
    def test_stale_sources_invalidate_the_complete_claim(self):
        (self.root/'rtl.sv').write_text('new implementation');self.rejected('stale source')
    def test_source_inventory_must_contain_the_compiled_sources(self):
        (self.root/'LICENSE').write_text('other');self.sources={'LICENSE':hashlib.sha256((self.root/'LICENSE').read_bytes()).hexdigest()};self.rejected('source inventory')
    def test_cycles_orphans_unknown_dependencies_and_duplicate_nodes(self):
        original=copy.deepcopy(self.plan)
        for mutate,text in ((lambda p:p['nodes'][0]['requires'].append('consumer'),'cyclic'),(lambda p:p.update(target='connection'),'orphan'),(lambda p:p['nodes'][0]['requires'].append('unknown'),'dependency inventory'),(lambda p:p['nodes'].append(copy.deepcopy(p['nodes'][0])),'proof inventory')):
            self.plan=copy.deepcopy(original);mutate(self.plan);self.rejected(text)
    def test_forged_property_list_or_relabelled_diagnostic_proof_is_rejected(self):
        self.consumer()['inventory']['assert']=['ap_reset'];self.rejected('property inventory')
        self.rows=[self.row(t) for t in F.PROOFS.values()]
        self.rows=[self.row('overconstrained-proof','consumer-guarantee') if r['id']=='chain-consumer-guarantee' else r for r in self.rows];self.rejected('property inventory')
    def test_compiled_parameters_must_match_the_reviewed_case(self):
        for key,value in (('LOCK_RESET',1),('ASSUME_HOLD',0),('MUTATION',2),('ROLE',3)):
            rows=copy.deepcopy(self.rows);self.consumer()['compiled']['parameters'][key]=value;self.rejected('proof configuration');self.rows=rows
    def test_every_assumption_needs_a_discharging_guarantee_from_the_same_statement(self):
        original=copy.deepcopy(self.plan)
        self.plan['contracts'].pop();self.rejected('undischarged');self.plan=copy.deepcopy(original)
        self.plan['environment_assumptions'].append('ag_sink_hold');self.rejected('contract inventory');self.plan=copy.deepcopy(original)
        self.consumer()['compiled']['properties']['ag_sink_hold'][1]='contract_formal.sv:1.1-1.2';self.rejected('not one statement')
        self.rows=[self.row(t) for t in F.PROOFS.values()]
        self.plan['contracts'][1]['guaranteed_by']='producer';self.rejected('contract roles differ')
    def test_dependency_edges_must_be_contract_edges(self):
        next(n for n in self.plan['nodes'] if n['id']=='consumer')['requires'].append('producer');self.rejected('dependency without')
    def test_cross_check_stays_independent_of_the_composition(self):
        original=copy.deepcopy(self.plan)
        next(n for n in self.plan['nodes'] if n['id']=='integration')['requires'].append('consumer');self.rejected('not independent');self.plan=copy.deepcopy(original)
        self.plan['cross_checks']=[];self.rejected('orphan')
    def test_compiled_table_keeps_flavor_and_statement(self):
        model=dict(modules=dict(top=dict(cells={'gen.ag_sink_hold':dict(type='$check',parameters=dict(FLAVOR='assume'),attributes=dict(src='a.sv:1'))})))
        self.assertEqual(D.compiled_properties(model),{'ag_sink_hold':['assume','a.sv:1']})
        model['modules']['other']=copy.deepcopy(model['modules']['top'])
        with self.assertRaises(ValueError):D.compiled_properties(model)
    def test_property_inventories_and_fixed_task_plan_are_distinct(self):
        cases=F.plan(8,0);self.assertEqual(len(cases),18);self.assertEqual(sum(c['mode']=='prove' and c['category']=='normal' for c in cases),4)
        self.assertEqual(sum(c['mode']=='cover' and c['category']=='normal' for c in cases),4)
        by_id={c['id']:c for c in cases}
        self.assertIn('ag_sink_hold',F.properties({},by_id['consumer-guarantee'])['assume']);self.assertIn('ag_sink_hold',F.properties({},by_id['connection-contract'])['assert'])
        self.assertIn('ag_source_hold',F.properties({},by_id['connection-contract'])['assume']);self.assertIn('ag_source_hold',F.properties({},by_id['producer-guarantee'])['assert'])
        self.assertNotIn('ag_sink_hold',F.properties({},by_id['missing-assumption'])['assume']);self.assertNotIn('ag_source_hold',F.properties({},by_id['connection-missing-assumption'])['assume'])
        self.assertEqual(F.properties({},by_id['integration-result'])['assume'],{'as_initial_reset'})
    def test_covers_use_the_same_role_and_assumptions_as_each_proof(self):
        by_id={c['id']:c for c in F.plan(8,0)}
        for proof,cover in (('producer-guarantee','cover-producer'),('consumer-guarantee','cover-consumer'),('connection-contract','cover-connection'),('integration-result','scenario-cover')):
            self.assertEqual(by_id[proof]['parameters'],by_id[cover]['parameters']);self.assertEqual(F.properties({},by_id[proof]),F.properties({},by_id[cover]))
            self.assertEqual(F.prepare({},by_id[proof]),F.prepare({},by_id[cover]))
    def test_only_the_connection_proof_flips_the_contract_statements(self):
        by_id={c['id']:c for c in F.plan(8,0)}
        self.assertIn('chformal',F.prepare({},by_id['connection-contract']));self.assertNotIn('chformal',F.prepare({},by_id['consumer-guarantee']));self.assertNotIn('chformal',F.prepare({},by_id['producer-guarantee']))
    def test_invalid_plan_types_never_become_success(self):
        for plan in (None,[],{},dict(self.plan,schema_version=True),dict(self.plan,schema_version=1)):
            self.assertFalse(D.audit(plan,self.rows,self.sources,self.root,F.PROOFS,self.cases,F.properties,self.required)['success'])
if __name__=='__main__':unittest.main()

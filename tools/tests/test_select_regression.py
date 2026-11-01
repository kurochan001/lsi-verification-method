import copy
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import select_regression as S

class SelectionTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        self.git('init','-q');self.git('config','user.name','Fixture');self.git('config','user.email','fixture@example.invalid')
        for name,content in {'.gitignore':'out/\n','examples/local-a/run.py':'# source','examples/local-b/run.py':'# depends local-a','examples/local-c/run.py':'# independent','docs/guide.md':'# Guide','tools/lint_targets.json':json.dumps(dict(targets=[],examples={},rtl_files=[]))}.items():
            p=self.root/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(content)
        self.git('add','.');self.git('commit','-qm','fixture')
        self.entries={n:dict(id=n,script='examples/'+n+'/run.py',kind='simulation',profile=True,options=[],tools=[]) for n in ('local-a','local-b','local-c')}
        self.catalog=S.dependency_inventory(self.root,self.entries)
    def git(self,*args):return subprocess.check_output(['git','-C',str(self.root),*args],stderr=subprocess.STDOUT)
    def selected(self,name,status='M',**kw):return S.select(self.root,self.entries,[dict(status=status,paths=[name])],self.catalog,**kw)
    def test_direct_and_transitive_consumers(self):
        selected=self.selected('examples/local-a/run.py');self.assertEqual(selected['examples'],['local-a','local-b']);self.assertEqual(selected['status'],'affected')
        self.assertEqual(self.selected('examples/local-c/run.py')['examples'],['local-c'])
    def test_docs_only_and_no_change_are_not_hardware_passes(self):
        self.assertEqual(self.selected('docs/guide.md')['status'],'docs-only')
        self.assertEqual(S.select(self.root,self.entries,[],self.catalog)['status'],'no-change')
        for name in ('docs/templates/plan.md','tools/helper.py','requirements.txt','image.png'):
            with self.subTest(name=name):self.assertEqual(self.selected(name)['status'],'full')
    def test_unknown_added_deleted_renamed_or_missing_base_runs_all(self):
        for status in ('D','R100','T','U'):
            self.assertEqual(self.selected('examples/local-a/run.py',status)['examples'],sorted(self.entries))
        self.assertEqual(self.selected('examples/local-new/run.py','A')['status'],'full')
        self.assertEqual(self.selected('docs/guide.md',uncertain='missing base')['status'],'full')
    def test_reference_drift_and_new_runtime_input_run_all(self):
        (self.root/'examples/local-c/run.py').write_text('# now depends local-b')
        self.assertEqual(self.selected('examples/local-c/run.py')['status'],'full')
        (self.root/'examples/local-a/fixture.json').write_text('{}')
        self.assertEqual(self.selected('docs/guide.md')['status'],'full')
    def test_registry_children_and_shared_dut_are_dependencies(self):
        entries=copy.deepcopy(self.entries);entries['local-c']['children']={'local-b':'child'}
        catalog=json.loads((self.root/'tools/lint_targets.json').read_text());catalog.update(targets=[dict(id='shared',sources=['examples/local-a/rtl/dut.sv'])],examples={'local-c':dict(targets=['shared'])})
        (self.root/'tools/lint_targets.json').write_text(json.dumps(catalog))
        inventory=S.dependency_inventory(self.root,entries)
        self.assertEqual(inventory['dependencies']['local-c'],['local-a','local-b'])
    def test_dirty_worktree_must_be_explicit(self):
        self.assertEqual(S.changes(self.root,'HEAD','HEAD',False)[0],[])
        (self.root/'examples/local-a/run.py').write_text('# changed')
        with self.assertRaisesRegex(ValueError,'dirty'):S.changes(self.root,'HEAD','HEAD',False)
        records,refs,uncertain=S.changes(self.root,'HEAD','HEAD',True)
        self.assertIsNone(uncertain);self.assertEqual(records,[dict(status='M',paths=['examples/local-a/run.py'])])
        records,refs,uncertain=S.changes(self.root,'missing-base','HEAD',True);self.assertIn('unavailable',uncertain)
    def test_head_must_match_checked_out_inputs(self):
        self.git('commit','--allow-empty','-qm','second')
        with self.assertRaisesRegex(ValueError,'checked-out'):S.changes(self.root,'HEAD~1','HEAD~1',False)
    def test_null_delimited_rename_keeps_both_paths(self):
        self.assertEqual(S.diff_records(b'R100\0old name\0new name\0M\0plain\0'),[dict(status='R100',paths=['old name','new name']),dict(status='M',paths=['plain'])])
        with self.assertRaises(ValueError):S.diff_records(b'R100\0old\0')
    def test_semantic_runner_overrides_are_forbidden(self):
        r=subprocess.run([sys.executable,str(Path(S.__file__)),'--base','HEAD','--','--example','local-a'],capture_output=True,text=True)
        self.assertEqual(r.returncode,2);self.assertIn('only tool bindings',r.stderr)
    def run_fixture(self,drift=False):
        for name in ('run_regression.py','regression_report.py'):(self.root/'tools'/name).write_text('# fixture')
        (self.root/'tools/regressions.json').write_text(json.dumps(dict(schema_version=1,examples=list(self.entries.values()))))
        config=self.root/'tools/regression_dependencies.json';config.write_text(json.dumps(S.dependency_inventory(self.root,self.entries)))
        self.git('add','.');self.git('commit','-qm','complete fixture')
        (self.root/'docs/guide.md').write_text('# edited documentation')
        a=SimpleNamespace(base='HEAD',head='HEAD',include_worktree=True,profile='smoke',seed=17,run=True,out=self.root/'out',runner_args=[],execution_timeout=5)
        original=S.Q.Report.fresh
        def fresh(report):
            if drift:(self.root/('tools/new-helper.py' if drift=='shared' else 'examples/local-a/new-input.json')).write_text('{}')
            return original(report)
        with patch.object(S.Q,'ROOT',self.root),patch.object(S,'DEPENDENCIES',config),patch.object(S.Q.Report,'fresh',fresh),redirect_stdout(io.StringIO()):rc=S.run(a)
        return rc,json.loads((a.out/'selection.json').read_text()),json.loads((a.out/'summary.json').read_text())
    def test_docs_only_run_records_zero_execution(self):
        rc,selection,summary=self.run_fixture();self.assertEqual(rc,0)
        self.assertEqual(selection['executed_jobs'],0);self.assertFalse(selection['hardware_verified']);self.assertEqual(selection['selected_jobs'],[])
    def test_new_input_during_selection_invalidates_even_zero_execution(self):
        rc,selection,summary=self.run_fixture(True);self.assertEqual(rc,1)
        self.assertEqual(next(r['status'] for r in summary['results'] if r['id']=='source-freshness'),'fail')
    def test_new_shared_input_during_selection_is_rejected(self):
        self.assertEqual(self.run_fixture('shared')[0],1)
    def run_hardware_fixture(self,mode='pass',drift=False):
        for name in ('run_regression.py','regression_report.py'):(self.root/'tools'/name).write_text('# fixture')
        (self.root/'tools/regressions.json').write_text(json.dumps(dict(schema_version=1,examples=list(self.entries.values()))))
        config=self.root/'tools/regression_dependencies.json';config.write_text(json.dumps(S.dependency_inventory(self.root,self.entries)))
        self.git('add','.');self.git('commit','-qm','complete fixture')
        (self.root/'examples/local-a/run.py').write_text('# changed source')
        a=SimpleNamespace(base='HEAD',head='HEAD',include_worktree=True,profile='smoke',seed=17,run=True,out=self.root/'out',runner_args=[],execution_timeout=5)
        def execute(command,log,*unused):
            Path(log).write_text('');campaign=a.out/'campaign';audit=a.out/'audit'
            if 'run_regression.py' in command[1]:
                campaign.mkdir();jobs=S.R.make_plan(self.entries,S.plan_args(a,campaign,['local-a','local-b']),self.root)
                rows=[dict(id=j['id'],started=mode=='pass' or mode=='partial' and i==0,success=mode=='pass',returncode=0 if mode=='pass' else None) for i,j in enumerate(jobs)]
                (campaign/'summary.json').write_text(json.dumps(dict(success=mode=='pass',complete=mode=='pass',planned=len(jobs),results=rows)))
                (campaign/'manifest.json').write_text(json.dumps(dict(jobs=jobs)))
            else:
                audit.mkdir();(audit/'summary.json').write_text(json.dumps(dict(success=mode=='pass')))
                if drift:(self.root/'tools/new-helper.py').write_text('# added during execution')
            return dict(returncode=0 if mode=='pass' else 1,error=None,command=command)
        with patch.object(S.Q,'ROOT',self.root),patch.object(S,'DEPENDENCIES',config),patch.object(S.Q.P,'execute',execute),redirect_stdout(io.StringIO()):rc=S.run(a)
        return rc,json.loads((a.out/'selection.json').read_text())
    def test_successful_execution_and_audit_set_verified(self):
        rc,selection=self.run_hardware_fixture();self.assertEqual(rc,0);self.assertTrue(selection['hardware_verified']);self.assertEqual(selection['executed_jobs'],2)
    def test_source_drift_clears_verified_after_successful_execution_and_audit(self):
        rc,selection=self.run_hardware_fixture(drift=True);self.assertEqual(rc,1);self.assertFalse(selection['hardware_verified']);self.assertEqual(selection['executed_jobs'],2)
    def test_failed_preflight_does_not_count_unstarted_jobs(self):
        rc,selection=self.run_hardware_fixture('preflight');self.assertEqual(rc,1);self.assertFalse(selection['hardware_verified']);self.assertEqual(selection['executed_jobs'],0)
    def test_partial_execution_counts_only_started_jobs(self):
        rc,selection=self.run_hardware_fixture('partial');self.assertEqual(rc,1);self.assertEqual(selection['executed_jobs'],1)
    def test_repository_catalog_matches_current_runtime_inventory(self):
        root=Path(S.__file__).resolve().parents[1];entries=S.R.load_registry(root/'tools/regressions.json',root)
        self.assertEqual(json.loads(S.DEPENDENCIES.read_text()),S.dependency_inventory(root,entries))
if __name__=='__main__':unittest.main()

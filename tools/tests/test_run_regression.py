import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
S=importlib.util.spec_from_file_location('campaign',Path(__file__).resolve().parents[1]/'run_regression.py');R=importlib.util.module_from_spec(S);S.loader.exec_module(R)
class CampaignTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        self.entries={}
        for name,kind in [('local-child','simulation'),('local-proof','formal'),('local-parent','aggregate')]:
            path=self.root/'examples'/name/'run.py';path.parent.mkdir(parents=True);path.write_text('# fixture\n')
            self.entries[name]=dict(id=name,script=str(path.relative_to(self.root)),kind=kind,profile=kind!='formal',tools=[],options=[])
        self.entries['local-parent']['children']={'local-child':'local-child','local-proof':'local-proof'}
        self.entries['local-child']['matrix']={'width':[1,8]}
        self.registry=self.root/'registry.json';self.write_registry()
    def write_registry(self):self.registry.write_text(json.dumps(dict(schema_version=1,examples=list(self.entries.values()))))
    def args(self,**changes):
        values=dict(example=None,suite='all',profile='nightly',seed=17,out=self.root/'out',python=sys.executable,formal_python=sys.executable,
                    rdl_python=sys.executable,cocotb_python=sys.executable,uvm_home=None,formal_timeout=None,child_timeout=None,build_timeout=None,command_timeout=None,tool_bin=[])
        values.update(changes);return SimpleNamespace(**values)
    def test_registered_inventory_must_include_new_example(self):
        self.assertEqual(set(R.load_registry(self.registry,self.root)),set(self.entries))
        path=self.root/'examples/local-new/run.py';path.parent.mkdir();path.write_text('')
        with self.assertRaisesRegex(ValueError,'unregistered'):R.load_registry(self.registry,self.root)
    def test_aggregate_dedup_and_formal_and_simulation_selection(self):
        self.assertEqual([j['example'] for j in R.make_plan(self.entries,self.args(),self.root)],['local-parent'])
        jobs=R.make_plan(self.entries,self.args(suite='formal'),self.root);self.assertEqual([j['example'] for j in jobs],['local-proof'])
        jobs=R.make_plan(self.entries,self.args(suite='simulation'),self.root);self.assertEqual(len(jobs),2);self.assertEqual({j['configuration']['width'] for j in jobs},{1,8})
    def test_explicit_child_does_not_expand_to_its_parent(self):
        jobs=R.make_plan(self.entries,self.args(example=['local-child']),self.root);self.assertEqual(len(jobs),2)
        self.assertTrue(all(j['example']=='local-child' for j in jobs))
    def test_cycles_unknown_children_and_bad_matrix_are_rejected(self):
        self.entries['local-child']['children']={'local-parent':'bad'};self.write_registry()
        with self.assertRaisesRegex(ValueError,'cycle'):R.load_registry(self.registry,self.root)
        self.entries['local-child'].pop('children');self.entries['local-child']['matrix']={'width':['../escape']};self.write_registry()
        with self.assertRaisesRegex(ValueError,'matrix'):R.load_registry(self.registry,self.root)
    def test_child_evidence_paths_must_be_distinct_relative_descendants(self):
        for children in ({'local-child':p} for p in ('','.', '../old', 'nested/../../old', str(self.root/'old'), None)):
            self.entries['local-parent']['children']=children;self.write_registry()
            with self.subTest(children=children),self.assertRaisesRegex(ValueError,'child evidence'):
                R.load_registry(self.registry,self.root)
        for children in ([], {'local-child':'nested/result','local-proof':'nested/./result'}):
            self.entries['local-parent']['children']=children;self.write_registry()
            with self.subTest(children=children),self.assertRaisesRegex(ValueError,'child evidence'):
                R.load_registry(self.registry,self.root)
    def test_missing_tools_are_a_preflight_failure(self):
        self.entries['local-proof']['tools']=['no-such-verification-tool-20261031']
        jobs=R.make_plan(self.entries,self.args(),self.root);result=R.preflight(jobs,self.entries,self.args(),dict(os.environ))
        self.assertFalse(result['success']);self.assertIn('missing executable',';'.join(result['errors']))
    def test_zero_duplicate_and_failed_summary_cases_are_rejected(self):
        good=dict(success=True,planned=1,results=[dict(id='check',status='pass')]);self.assertEqual(R.validate_summary(good),{'check'})
        for d in (dict(good,planned=0,results=[]),dict(good,planned=2,results=good['results']*2),dict(good,results=[dict(id='check',status='pass',outcome='error')]),dict(success=True,complete=True,planned=2,results=1)):
            with self.assertRaises(ValueError):R.validate_summary(d)
    def test_incomplete_or_failed_row_cannot_claim_a_passing_status(self):
        for change in (dict(complete=False),dict(success=False)):
            with self.subTest(change=change), self.assertRaises(ValueError):
                R.validate_summary(dict(success=True,planned=1,results=[dict(id='check',status='pass',**change)]))
    def output(self):
        directory=self.root/'result';directory.mkdir();source=self.root/'rtl.sv';source.write_text('// source\n')
        (directory/'manifest.json').write_text(json.dumps(dict(profile='nightly',source_sha256={'rtl.sv':hashlib.sha256(source.read_bytes()).hexdigest()})))
        (directory/'summary.json').write_text(json.dumps(dict(success=True,planned=1,results=[dict(id='check',status='pass')])))
        (directory/'junit.xml').write_text('<testsuite tests="1"><testcase name="check"/></testsuite>')
        return directory,dict(profile=True)
    def test_valid_summary_cannot_hide_missing_skipped_or_duplicate_junit(self):
        directory,entry=self.output();self.assertEqual(R.inspect_output(directory,entry,{},self.root,'nightly')['junit'],1)
        for xml in ('<testsuite tests="0"/>','<testsuite tests="1"><testcase name="check"><skipped/></testcase></testsuite>','<testsuite tests="2"><testcase name="check"/><testcase name="check"/></testsuite>','<testsuite tests="2"><testcase name="check"/></testsuite>',
                    '<testsuite tests="1" failures="1"><testcase name="check"/></testsuite>',
                    '<testsuites tests="2"><testsuite tests="1"><testcase name="check"/></testsuite></testsuites>'):
            (directory/'junit.xml').write_text(xml)
            with self.assertRaises(ValueError):R.inspect_output(directory,entry,{},self.root,'nightly')
    def test_junit_root_hierarchy_and_planned_case_identity_are_checked(self):
        directory,entry=self.output()
        for xml in ('<result><testcase name="check"/></result>',
                    '<testsuites tests="1"><testsuite tests="0"/><testcase name="check"/></testsuites>',
                    '<testsuites tests="1"><wrapper><testsuite tests="1"><testcase name="check"/></testsuite></wrapper></testsuites>',
                    '<testsuite tests="2"><testcase classname="first" name="check"/><testcase classname="second" name="check"/></testsuite>'):
            (directory/'junit.xml').write_text(xml)
            with self.subTest(xml=xml),self.assertRaisesRegex(ValueError,'JUnit'):
                R.inspect_output(directory,entry,{},self.root,'nightly')
        (directory/'junit.xml').write_text('<testsuites tests="1"><testsuite tests="1"><testcase name="check"/></testsuite></testsuites>')
        self.assertEqual(R.inspect_output(directory,entry,{},self.root,'nightly')['junit'],1)
    def test_child_evidence_cannot_borrow_parent_or_external_output(self):
        directory,entry=self.output();borrowed=self.root/'borrowed';borrowed.mkdir()
        for name in ('manifest.json','summary.json','junit.xml'):(borrowed/name).write_bytes((directory/name).read_bytes())
        (directory/'linked').symlink_to(borrowed,target_is_directory=True)
        (directory/'self-linked').symlink_to(directory,target_is_directory=True)
        for relative in ('.','../borrowed',str(borrowed),'linked','self-linked'):
            parent=dict(entry,children={'local-child':relative})
            with self.subTest(relative=relative),self.assertRaisesRegex(ValueError,'child evidence'):
                R.inspect_output(directory,parent,{'local-child':entry},self.root,'nightly')
        child=directory/'nested/child';child.mkdir(parents=True)
        for name in ('manifest.json','summary.json','junit.xml'):(child/name).write_bytes((directory/name).read_bytes())
        parent=dict(entry,children={'local-child':'nested/child'})
        self.assertEqual(R.inspect_output(directory,parent,{'local-child':entry},self.root,'nightly')['junit'],1)
    def test_stale_source_and_wrong_profile_are_rejected(self):
        directory,entry=self.output()
        with self.assertRaisesRegex(ValueError,'profile'):R.inspect_output(directory,entry,{},self.root,'smoke')
        (self.root/'rtl.sv').write_text('changed')
        with self.assertRaisesRegex(ValueError,'stale source'):R.inspect_output(directory,entry,{},self.root,'nightly')
    def test_integer_summary_requires_every_manifest_case_in_junit(self):
        directory,entry=self.output()
        manifest=json.loads((directory/'manifest.json').read_text());manifest['cases']=[dict(id='check'),dict(id='missing')]
        (directory/'manifest.json').write_text(json.dumps(manifest))
        (directory/'summary.json').write_text(json.dumps(dict(success=True,complete=True,planned=2,results=2)))
        with self.assertRaisesRegex(ValueError,'JUnit'):R.inspect_output(directory,entry,{},self.root,'nightly')
        # A same-size replacement must not satisfy the missing planned ID.
        (directory/'junit.xml').write_text('<testsuite tests="2"><testcase name="check"/><testcase name="unplanned"/></testsuite>')
        with self.assertRaisesRegex(ValueError,'JUnit'):R.inspect_output(directory,entry,{},self.root,'nightly')
        (directory/'junit.xml').write_text('<testsuite tests="3"><testcase name="check"/><testcase name="missing"/><testcase name="coverage"/></testsuite>')
        self.assertEqual(R.inspect_output(directory,entry,{},self.root,'nightly')['junit'],3)
    def test_summary_and_junit_cannot_shrink_a_fixed_check_plan(self):
        directory,entry=self.output()
        manifest=json.loads((directory/'manifest.json').read_text());manifest['check_ids']=['check','missing']
        (directory/'manifest.json').write_text(json.dumps(manifest))
        with self.assertRaisesRegex(ValueError,'manifest'):R.inspect_output(directory,entry,{},self.root,'nightly')
    def test_uvm_library_snapshot_cannot_be_missing_empty_or_stale(self):
        directory,entry=self.output();entry['options']=['uvm-home']
        for record in (None,dict(root=str(self.root),source_sha256={}),dict(root=str(self.root),source_sha256={'rtl.sv':'stale'})):
            if record is not None:(directory/'uvm-source.json').write_text(json.dumps(record))
            with self.subTest(record=record), self.assertRaisesRegex(ValueError,'UVM'):
                R.inspect_output(directory,entry,{},self.root,'nightly')
        (directory/'uvm-source.json').write_text(json.dumps(dict(root=str(self.root),source_sha256={'rtl.sv':R.hashlib.sha256((self.root/'rtl.sv').read_bytes()).hexdigest()})))
        self.assertEqual(R.inspect_output(directory,entry,{},self.root,'nightly')['junit'],1)
    def test_partial_campaign_junit_contains_an_integrity_failure(self):
        directory=self.root/'campaign';directory.mkdir();jobs=[dict(id='one'),dict(id='two')]
        results=[dict(id='one',success=True,message='ok')]
        for complete in (False,True):
            self.assertFalse(R.save(directory,jobs,results,complete,True))
            xml=R.ET.parse(directory/'junit.xml')
            self.assertIsNotNone(xml.find('.//testcase[@name="campaign-integrity"]/failure'))
        self.assertFalse(R.save(directory,jobs,results*2,True,True))
        self.assertIsNotNone(R.ET.parse(directory/'junit.xml').find('.//testcase[@name="campaign-integrity"]/failure'))
    def test_matrix_values_with_identical_command_arguments_are_rejected(self):
        self.entries['local-child']['matrix']={'width':[1,'1']};self.write_registry()
        with self.assertRaisesRegex(ValueError,'matrix'):R.load_registry(self.registry,self.root)
    def test_partial_campaign_cannot_pass_and_integrity_failure_reaches_junit(self):
        directory=self.root/'campaign';directory.mkdir();job=dict(id='job')
        self.assertFalse(R.save(directory,[job],[],False,True))
        self.assertFalse(R.save(directory,[job],[dict(id='job',success=True,message='ok')],True,True,'changed registry'))
        self.assertIn('changed registry',(directory/'junit.xml').read_text())
    @unittest.skipUnless(os.name=='posix','POSIX process groups required')
    def test_cancellation_stops_detached_grandchild(self):
        pidfile=self.root/'child.pid'
        program='import subprocess,sys,time; p=subprocess.Popen([sys.executable,"-c","import time;time.sleep(60)"],start_new_session=True);open(sys.argv[1],"w").write(str(p.pid));time.sleep(60)'
        parent=subprocess.Popen([sys.executable,'-c',program,str(pidfile)],start_new_session=True)
        try:
            deadline=time.monotonic()+5
            while not pidfile.exists() and time.monotonic()<deadline:time.sleep(.02)
            self.assertTrue(pidfile.exists());child=int(pidfile.read_text());R.stop_tree(parent)
            deadline=time.monotonic()+3
            while time.monotonic()<deadline:
                result=subprocess.run(['ps','-p',str(child),'-o','stat='],capture_output=True,text=True)
                if result.returncode or result.stdout.strip().startswith('Z'):break
                time.sleep(.02)
            else:self.fail('detached grandchild survived cancellation')
        finally:
            if parent.poll() is None:R.stop_tree(parent)
    def test_real_registry_covers_all_run_files_and_all_migration_modes(self):
        entries=R.load_registry(R.ROOT/'tools/regressions.json');self.assertEqual(entries['local-uvm-migration']['matrix']['mode'],['passive','active'])
        jobs=R.make_plan(entries,self.args());self.assertEqual(len({j['id'] for j in jobs}),len(jobs))
    @unittest.skipUnless(os.name=='posix','POSIX signals required')
    def test_interrupted_campaign_records_no_active_jobs_and_never_passes(self):
        ready=self.root/'ready';out=self.root/'interrupted'
        args=self.args(out=out,registry=self.registry,check_tools=False,jobs=1,job_timeout=60)
        job=dict(id='interrupt-fixture',example='local-child',out=str(out/'runs/fixture'),
                 command=[sys.executable,'-c','from pathlib import Path;import sys,time;Path(sys.argv[1]).write_text("ready");time.sleep(60)',str(ready)])
        def stop_when_started():
            deadline=time.monotonic()+5
            while not ready.exists() and time.monotonic()<deadline:time.sleep(.02)
            if ready.exists():os.kill(os.getpid(),signal.SIGTERM)
        sender=threading.Thread(target=stop_when_started,daemon=True);sender.start()
        try:self.assertEqual(R.run(args,self.entries,[job]),143)
        finally:sender.join(timeout=6)
        progress=json.loads((out/'progress.json').read_text());summary=json.loads((out/'summary.json').read_text())
        self.assertEqual(progress['active'],[]);self.assertTrue(progress['interrupted']);self.assertFalse(summary['success']);self.assertFalse(summary['complete'])
if __name__=='__main__':unittest.main()

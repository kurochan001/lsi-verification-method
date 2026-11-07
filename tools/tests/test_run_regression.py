from contextlib import redirect_stdout
import copy
import hashlib
import io
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
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
S=importlib.util.spec_from_file_location('campaign',Path(__file__).resolve().parents[1]/'run_regression.py');R=importlib.util.module_from_spec(S);S.loader.exec_module(R)
EVIDENCE='''import hashlib,json,sys
from pathlib import Path
out,source,code,configuration=Path(sys.argv[1]),Path(sys.argv[2]),int(sys.argv[3]),json.loads(sys.argv[4])
out.mkdir(parents=True)
(out/"manifest.json").write_text(json.dumps(dict(profile="nightly",configuration=configuration,source_sha256={str(source):hashlib.sha256(source.read_bytes()).hexdigest()})))
(out/"summary.json").write_text(json.dumps(dict(success=True,planned=1,results=[dict(id="check",status="pass")])))
(out/"junit.xml").write_text('<testsuite tests="1"><testcase name="check"/></testsuite>')
sys.exit(code)
'''
class CampaignTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        self.entries={}
        for name,kind in [('local-child','simulation'),('local-proof','formal'),('local-parent','aggregate')]:
            path=self.root/'examples'/name/'run.py';path.parent.mkdir(parents=True);path.write_text('# fixture\n')
            self.entries[name]=dict(id=name,script=str(path.relative_to(self.root)),kind=kind,profile=kind!='formal',tools=[],options=[])
        self.entries['local-parent']['children']={'local-child':'local-child','local-proof':'local-proof'}
        self.entries['local-child']['matrix']={'width':[1,8]};self.entries['local-child']['matrix_evidence']={'width':'configuration.width'}
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
    def test_every_matrix_value_needs_a_manifest_path(self):
        for evidence in ({},{'width':''},{'width':'configuration.width','depth':'configuration.depth'},['configuration.width']):
            self.entries['local-child']['matrix_evidence']=evidence;self.write_registry()
            with self.subTest(evidence=evidence),self.assertRaisesRegex(ValueError,'manifest path'):R.load_registry(self.registry,self.root)
    def test_matrix_values_reach_the_runner_command(self):
        jobs=R.make_plan(self.entries,self.args(example=['local-child']),self.root)
        self.assertEqual({j['configuration']['width']:j['command'][j['command'].index('--width')+1] for j in jobs},{1:'1',8:'8'})
    def test_missing_python_package_is_a_preflight_failure(self):
        self.entries['local-proof']['packages']={'python':['no_such_verification_module_20261107']}
        jobs=R.make_plan(self.entries,self.args(),self.root);result=R.preflight(jobs,self.entries,self.args(),dict(os.environ))
        self.assertFalse(result['success']);self.assertIn('missing/unusable packages',';'.join(result['errors']))
    def test_every_aggregate_child_limit_is_reachable_as_child_timeout(self):
        entries=R.load_registry(R.ROOT/'tools/regressions.json');jobs=R.make_plan(entries,self.args(child_timeout=7200.0))
        for job in (j for j in jobs if entries[j['example']]['kind']=='aggregate'):
            with self.subTest(job=job['id']):
                self.assertEqual(job['command'][job['command'].index('--child-timeout')+1],'7200.0')
                self.assertIn('--child-timeout',subprocess.run([sys.executable,str(R.ROOT/entries[job['example']]['script']),'--help'],capture_output=True,text=True,timeout=30).stdout)
        for name in ('local-system-regression','local-advanced-regression'):
            with self.subTest(name=name):  # The alias is the limit that these parents validate and apply.
                r=subprocess.run([sys.executable,str(R.ROOT/entries[name]['script']),'--child-timeout','0','--out',str(self.root/name)],capture_output=True,text=True,timeout=30)
                self.assertEqual(r.returncode,2);self.assertFalse((self.root/name).exists())
    def test_missing_tools_are_a_preflight_failure(self):
        self.entries['local-proof']['tools']=['no-such-verification-tool-20261031']
        jobs=R.make_plan(self.entries,self.args(),self.root);result=R.preflight(jobs,self.entries,self.args(),dict(os.environ))
        self.assertFalse(result['success']);self.assertIn('missing executable',';'.join(result['errors']))
    def test_zero_duplicate_and_failed_summary_cases_are_rejected(self):
        good=dict(success=True,planned=1,results=[dict(id='check',status='pass')]);self.assertEqual(R.validate_summary(good),{'check'})
        for d in (dict(good,planned=0,results=[]),dict(good,planned=2,results=good['results']*2),dict(good,results=[dict(id='check',status='pass',outcome='error')]),dict(success=True,complete=True,planned=2,results=1),dict(success=True,results=good['results'])):
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
    def test_failed_child_evidence_fails_its_parent(self):
        directory,entry=self.output();child=directory/'nested/child';child.mkdir(parents=True)
        for name in ('manifest.json','summary.json','junit.xml'):(child/name).write_bytes((directory/name).read_bytes())
        (child/'summary.json').write_text(json.dumps(dict(success=False,planned=1,results=[dict(id='check',status='fail')])))
        with self.assertRaisesRegex(ValueError,'unsuccessful'):R.inspect_output(directory,dict(entry,children={'local-child':'nested/child'}),{'local-child':entry},self.root,'nightly')
    def test_configuration_evidence_must_exist_and_match(self):
        directory,entry=self.output();entry['matrix_evidence']={'width':'configuration.width'}
        with self.assertRaisesRegex(ValueError,'missing configuration'):R.inspect_output(directory,entry,{},self.root,'nightly',{'width':8})
        manifest=json.loads((directory/'manifest.json').read_text());manifest['configuration']=dict(width=8);(directory/'manifest.json').write_text(json.dumps(manifest))
        self.assertEqual(R.inspect_output(directory,entry,{},self.root,'nightly',{'width':8})['junit'],1)
        with self.assertRaisesRegex(ValueError,'configuration differs'):R.inspect_output(directory,entry,{},self.root,'nightly',{'width':16})
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
    def uvm_snapshot(self,directory):
        home=self.root/'uvm';(home/'src').mkdir(parents=True)
        for name in ('src/uvm_pkg.sv','src/uvm_macros.svh','LICENSE.txt','NOTICE.txt'):(home/name).write_text('official '+name)
        expected={str(p.relative_to(home)):hashlib.sha256(p.read_bytes()).hexdigest() for p in home.rglob('*') if p.is_file()}
        pin=self.root/'tools/uvm-source-sha256.json';pin.parent.mkdir(exist_ok=True);pin.write_text(json.dumps(dict(sha256=expected)))
        record=dict(root=str(home),source_sha256={n:h for n,h in expected.items() if n.startswith('src/')})
        (directory/'uvm-source.json').write_text(json.dumps(record))
        return home,record
    def test_uvm_library_snapshot_cannot_be_missing_empty_or_stale(self):
        directory,entry=self.output();entry['options']=['uvm-home'];home,valid=self.uvm_snapshot(directory)
        (directory/'uvm-source.json').unlink()
        for record in (None,dict(root=str(self.root),source_sha256={}),dict(root=str(self.root),source_sha256={'rtl.sv':'stale'})):
            if record is not None:(directory/'uvm-source.json').write_text(json.dumps(record))
            with self.subTest(record=record), self.assertRaisesRegex(ValueError,'UVM'):
                R.inspect_output(directory,entry,{},self.root,'nightly')
        (directory/'uvm-source.json').write_text(json.dumps(valid))
        self.assertEqual(R.inspect_output(directory,entry,{},self.root,'nightly')['junit'],1)
    def test_changed_uvm_and_self_consistent_snapshot_are_rejected(self):
        directory,entry=self.output();entry['options']=['uvm-home'];home,record=self.uvm_snapshot(directory)
        source=home/'src/uvm_pkg.sv';source.write_text('modified library')
        record['source_sha256']['src/uvm_pkg.sv']=hashlib.sha256(source.read_bytes()).hexdigest()
        (directory/'uvm-source.json').write_text(json.dumps(record))
        with self.assertRaisesRegex(ValueError,'UVM'):R.inspect_output(directory,entry,{},self.root,'nightly')
    def test_uvm_subset_and_added_unrecorded_source_are_rejected(self):
        directory,entry=self.output();entry['options']=['uvm-home'];home,record=self.uvm_snapshot(directory)
        source=home/'src/uvm_macros.svh';original=source.read_bytes();expected=record['source_sha256'].pop('src/uvm_macros.svh');source.unlink()
        (directory/'uvm-source.json').write_text(json.dumps(record))
        with self.assertRaisesRegex(ValueError,'UVM'):R.inspect_output(directory,entry,{},self.root,'nightly')
        source.write_bytes(original);record['source_sha256']['src/uvm_macros.svh']=expected
        (directory/'uvm-source.json').write_text(json.dumps(record));(home/'src/extra.svh').write_text('unrecorded source')
        with self.assertRaisesRegex(ValueError,'UVM'):R.inspect_output(directory,entry,{},self.root,'nightly')
    def test_uvm_license_and_notice_are_bound(self):
        directory,entry=self.output();entry['options']=['uvm-home'];home,record=self.uvm_snapshot(directory)
        for name in ('LICENSE.txt','NOTICE.txt'):
            path=home/name;original=path.read_bytes();path.write_text('modified')
            with self.subTest(name=name),self.assertRaisesRegex(ValueError,'UVM'):R.inspect_output(directory,entry,{},self.root,'nightly')
            path.write_bytes(original)
    def test_uvm_legacy_snapshot_field_uses_same_pin(self):
        directory,entry=self.output();entry['options']=['uvm-home'];home,record=self.uvm_snapshot(directory)
        record['sha256']=record.pop('source_sha256');(directory/'uvm-source.json').write_text(json.dumps(record))
        self.assertEqual(R.inspect_output(directory,entry,{},self.root,'nightly')['junit'],1)
    def test_preflight_rejects_modified_uvm_before_execution(self):
        directory,entry=self.output();home,record=self.uvm_snapshot(directory)
        self.entries['local-child']['options']=['uvm-home']
        args=self.args(example=['local-child'],uvm_home=home);jobs=R.make_plan(self.entries,args,self.root)
        with patch.object(R,'ROOT',self.root):
            self.assertTrue(R.preflight(jobs,self.entries,args,dict(os.environ))['success'])
            (home/'src/uvm_pkg.sv').write_text('modified library')
            check=R.preflight(jobs,self.entries,args,dict(os.environ))
            self.assertFalse(check['success']);self.assertIn('UVM verification failed',';'.join(check['errors']))
    def test_execution_plan_binds_the_uvm_pin(self):
        args=self.args(registry=self.registry);job=dict(command=['runner','--uvm-home','library'])
        self.assertIn(self.root/'tools/uvm-source-sha256.json',R.plan_inputs(args,[job],self.root))
        self.assertNotIn(self.root/'tools/uvm-source-sha256.json',R.plan_inputs(args,[dict(command=['runner'])],self.root))
    def test_failed_preflight_records_jobs_as_not_started(self):
        self.entries['local-child']['tools']=['missing-tool-review-20261101']
        args=self.args(out=self.root/'preflight',registry=self.registry,check_tools=False,jobs=1,job_timeout=1)
        self.assertEqual(R.run(args,self.entries,R.make_plan(self.entries,args,self.root)),1)
        data=json.loads((args.out/'summary.json').read_text())
        self.assertTrue(all(r['started'] is False for r in data['results']))
    def test_oss_toolchain_snapshot_is_required_and_content_checked(self):
        directory,entry=self.output();entry['options']=['oss-home']
        with self.assertRaisesRegex(ValueError,'missing OSS CAD'):R.inspect_output(directory,entry,{},self.root,'nightly')
        import oss_cad
        (directory/'oss-source.json').write_text(json.dumps(dict(root=str(self.root),platform=oss_cad.platform_key(),release='claimed',archive_sha256='claimed',tree_sha256='claimed',files=1)))
        with self.assertRaisesRegex(ValueError,'pinned installation'):R.inspect_output(directory,entry,{},self.root,'nightly')
    def test_oss_snapshot_is_compared_with_the_verified_installation_field_by_field(self):
        directory,entry=self.output();entry['options']=['oss-home']
        observed=dict(root=str(self.root),platform='fixture',release='r1',archive_sha256='a'*64,tree_sha256='b'*64,files=3)
        stub=SimpleNamespace(verify=lambda root,platform:dict(observed))
        snapshot=directory/'oss-source.json';snapshot.write_text(json.dumps(observed))
        with patch.object(R,'load_oss',return_value=stub):
            R.inspect_output(directory,entry,{},self.root,'nightly')
            for field,value in (('release','r2'),('archive_sha256','c'*64),('tree_sha256','d'*64),('files',4)):
                snapshot.write_text(json.dumps(dict(observed,**{field:value})))
                with self.subTest(field=field),self.assertRaisesRegex(ValueError,'snapshot differs'):R.inspect_output(directory,entry,{},self.root,'nightly')
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
    def test_permission_error_for_zombie_group_is_ignored(self):
        with patch.object(R.os,'killpg',side_effect=PermissionError),patch.object(R.os,'getpgrp',return_value=77),patch.object(R.subprocess,'check_output',return_value='PGID STAT\n321 Z\n322 S\n'):
            R.signal_group(321,signal.SIGTERM)
    def test_permission_error_for_live_group_remains_failure(self):
        for states in ('321 S','321 Z\n321 S'):
            with self.subTest(states=states),patch.object(R.os,'killpg',side_effect=PermissionError),patch.object(R.os,'getpgrp',return_value=77),patch.object(R.subprocess,'check_output',return_value='PGID STAT\n'+states+'\n'):
                with self.assertRaises(PermissionError):R.signal_group(321,signal.SIGTERM)
    def test_permission_error_for_disappeared_group_is_ignored(self):
        with patch.object(R.os,'killpg',side_effect=PermissionError),patch.object(R.os,'getpgrp',return_value=77),patch.object(R.subprocess,'check_output',return_value='PGID STAT\n322 S\n'):
            R.signal_group(321,signal.SIGTERM)
    def test_unsafe_process_groups_are_never_signalled(self):
        with patch.object(R.os,'getpgrp',return_value=77),patch.object(R.os,'killpg') as kill:
            for group in (-1,0,1,77):
                with self.subTest(group=group),self.assertRaises(ValueError):R.signal_group(group,signal.SIGTERM)
            kill.assert_not_called()
    @unittest.skipUnless(os.name=='posix','POSIX process groups required')
    def test_already_exited_runner_can_be_reaped(self):
        child=subprocess.Popen([sys.executable,'-c','pass'],start_new_session=True)
        try:
            deadline=time.monotonic()+5
            while time.monotonic()<deadline:
                state=subprocess.run(['ps','-p',str(child.pid),'-o','stat='],capture_output=True,text=True)
                if state.returncode or state.stdout.strip().startswith('Z'):break
                time.sleep(.02)
            else:self.fail('short child did not exit')
            R.stop_tree(child);self.assertEqual(child.returncode,0)
        finally:
            if child.poll() is None:child.terminate()
            child.wait(timeout=5)
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
    def evidence_job(self,identity,code=0,example='local-proof',configuration=None,produced=None):
        source=self.root/'rtl.sv';source.write_text('// source\n');out=self.root/'campaign/runs'/identity;configuration=configuration or {}
        return dict(id=identity,example=example,configuration=configuration,out=str(out),command=[sys.executable,'-c',EVIDENCE,str(out),str(source),str(code),json.dumps(configuration if produced is None else produced)])
    def campaign(self,*jobs,**changes):
        out=self.root/'campaign';values=dict(out=out,registry=R.ROOT/'tools/regressions.json',check_tools=False,jobs=1,job_timeout=30);values.update(changes)
        with redirect_stdout(io.StringIO()):rc=R.run(self.args(**values),self.entries,list(jobs))
        summary=json.loads((out/'summary.json').read_text())
        return rc,summary,{r['id']:r for r in summary['results']}
    def test_run_accepts_complete_evidence(self):
        rc,summary,rows=self.campaign(self.evidence_job('job'))
        self.assertEqual(rc,0);self.assertTrue(summary['success']);self.assertTrue(rows['job']['success'])
    def test_zero_exit_without_evidence_fails_when_the_job_finishes(self):
        job=dict(self.evidence_job('job'),command=[sys.executable,'-c','pass'])
        rc,summary,rows=self.campaign(job)
        self.assertEqual(rc,1);self.assertFalse(summary['success']);self.assertFalse(rows['job']['success'])
        self.assertIn('manifest.json',rows['job']['message']);self.assertNotIn('final audit',rows['job']['message'])
    def test_nonzero_exit_fails_despite_valid_evidence(self):
        rc,summary,rows=self.campaign(self.evidence_job('job',code=3))
        self.assertEqual(rc,1);self.assertFalse(summary['success']);self.assertEqual(rows['job']['message'],'runner exit 3')
    def test_final_audit_rechecks_jobs_that_finished_earlier(self):
        first=self.evidence_job('first');second=self.evidence_job('second')
        damage=[sys.executable,'-c','import subprocess,sys;from pathlib import Path;Path(sys.argv[1]).unlink();raise SystemExit(subprocess.call(sys.argv[2:]))',str(Path(first['out'])/'junit.xml'),*second['command']]
        rc,summary,rows=self.campaign(first,dict(second,command=damage))
        self.assertEqual(rc,1);self.assertFalse(rows['first']['success']);self.assertTrue(rows['first']['message'].startswith('final audit: '));self.assertTrue(rows['second']['success'])
    def test_campaign_source_change_is_an_integrity_failure(self):
        registry=self.root/'copy.json';registry.write_bytes((R.ROOT/'tools/regressions.json').read_bytes());job=self.evidence_job('job')
        edit=[sys.executable,'-c','import subprocess,sys;from pathlib import Path;p=Path(sys.argv[1]);p.write_text(p.read_text()+"\\n");raise SystemExit(subprocess.call(sys.argv[2:]))',str(registry),*job['command']]
        rc,summary,rows=self.campaign(dict(job,command=edit),registry=registry)
        self.assertEqual(rc,1);self.assertIn('campaign source changed',summary['integrity_error']);self.assertFalse(summary['success'])
    def test_job_timeout_fails_and_stops_the_job(self):
        job=dict(self.evidence_job('job'),command=[sys.executable,'-c','import time;time.sleep(30)'])
        started=time.monotonic();rc,summary,rows=self.campaign(job,job_timeout=.2)
        self.assertEqual(rc,1);self.assertEqual(rows['job']['message'],'job timeout');self.assertLess(time.monotonic()-started,10)
    def test_matrix_job_is_not_credited_with_another_configuration(self):
        good=self.evidence_job('good',example='local-child',configuration={'width':1})
        wrong=self.evidence_job('wrong',example='local-child',configuration={'width':1},produced={'width':8})
        rc,summary,rows=self.campaign(good,wrong)
        self.assertEqual(rc,1);self.assertTrue(rows['good']['success']);self.assertFalse(rows['wrong']['success']);self.assertEqual(rows['wrong']['message'],'configuration differs from plan: width')
    def test_failed_process_inspection_is_recorded_and_the_job_is_stopped(self):
        real=subprocess.check_output;pidfile=self.root/'job.pid'
        def ps(command,*args,**kwargs):
            if command[0]=='ps':raise subprocess.CalledProcessError(1,command)
            return real(command,*args,**kwargs)
        job=dict(self.evidence_job('job'),command=[sys.executable,'-c','import os,sys,time;open(sys.argv[1],"w").write(str(os.getpid()));time.sleep(30)',str(pidfile)])
        started=time.monotonic()
        with patch.object(R.subprocess,'check_output',side_effect=ps):rc,summary,rows=self.campaign(job,job_timeout=1)
        self.assertEqual(rc,1);self.assertFalse(summary['success']);self.assertTrue(summary['complete']);self.assertIn('ps',rows['job']['message']);self.assertTrue(rows['job']['started']);self.assertLess(time.monotonic()-started,15)
        state=subprocess.run(['ps','-p',pidfile.read_text(),'-o','stat='],capture_output=True,text=True)
        self.assertTrue(state.returncode or state.stdout.strip().startswith('Z'),'job survived')
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
        second=dict(job,id='queued-fixture',out=str(out/'runs/queued'),command=[sys.executable,'-c','raise SystemExit(99)'])
        try:self.assertEqual(R.run(args,self.entries,[job,second]),143)
        finally:sender.join(timeout=6)
        progress=json.loads((out/'progress.json').read_text());summary=json.loads((out/'summary.json').read_text())
        self.assertEqual(progress['active'],[]);self.assertTrue(progress['interrupted']);self.assertFalse(summary['success']);self.assertFalse(summary['complete'])
        self.assertEqual({r['id']:r['started'] for r in summary['results']},{'interrupt-fixture':True,'queued-fixture':False})
if __name__=='__main__':unittest.main()

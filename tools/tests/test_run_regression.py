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
    def test_missing_tools_are_a_preflight_failure(self):
        self.entries['local-proof']['tools']=['no-such-verification-tool-20261031']
        jobs=R.make_plan(self.entries,self.args(),self.root);result=R.preflight(jobs,self.entries,self.args(),dict(os.environ))
        self.assertFalse(result['success']);self.assertIn('missing executable',';'.join(result['errors']))
    def test_zero_duplicate_and_failed_summary_cases_are_rejected(self):
        good=dict(success=True,planned=1,results=[dict(id='check',status='pass')]);self.assertEqual(R.validate_summary(good),{'check'})
        for d in (dict(good,planned=0,results=[]),dict(good,planned=2,results=good['results']*2),dict(good,results=[dict(id='check',status='pass',outcome='error')]),dict(success=True,complete=True,planned=2,results=1)):
            with self.assertRaises(ValueError):R.validate_summary(d)
    def output(self):
        directory=self.root/'result';directory.mkdir();source=self.root/'rtl.sv';source.write_text('// source\n')
        (directory/'manifest.json').write_text(json.dumps(dict(profile='nightly',source_sha256={'rtl.sv':hashlib.sha256(source.read_bytes()).hexdigest()})))
        (directory/'summary.json').write_text(json.dumps(dict(success=True,planned=1,results=[dict(id='check',status='pass')])))
        (directory/'junit.xml').write_text('<testsuite tests="1"><testcase name="check"/></testsuite>')
        return directory,dict(profile=True)
    def test_valid_summary_cannot_hide_missing_skipped_or_duplicate_junit(self):
        directory,entry=self.output();self.assertEqual(R.inspect_output(directory,entry,{},self.root,'nightly')['junit'],1)
        for xml in ('<testsuite tests="0"/>','<testsuite tests="1"><testcase name="check"><skipped/></testcase></testsuite>','<testsuite tests="2"><testcase name="check"/><testcase name="check"/></testsuite>','<testsuite tests="2"><testcase name="check"/></testsuite>'):
            (directory/'junit.xml').write_text(xml)
            with self.assertRaises(ValueError):R.inspect_output(directory,entry,{},self.root,'nightly')
    def test_stale_source_and_wrong_profile_are_rejected(self):
        directory,entry=self.output()
        with self.assertRaisesRegex(ValueError,'profile'):R.inspect_output(directory,entry,{},self.root,'smoke')
        (self.root/'rtl.sv').write_text('changed')
        with self.assertRaisesRegex(ValueError,'stale source'):R.inspect_output(directory,entry,{},self.root,'nightly')
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

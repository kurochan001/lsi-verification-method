import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
S=importlib.util.spec_from_file_location('report_under_test',Path(__file__).resolve().parents[1]/'regression_report.py');T=importlib.util.module_from_spec(S);S.loader.exec_module(T)

class ReportTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        for name in ('examples/local-fixture/run.py','tools/run_regression.py','examples/local-irq-cdc/run.py','rtl.sv'):
            p=self.root/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text('# fixture\n')
        self.registry=self.root/'tools/regressions.json'
        entry=dict(id='local-fixture',script='examples/local-fixture/run.py',kind='simulation',profile=True,tools=[],options=['timeout'])
        helper=dict(id='local-irq-cdc',script='examples/local-irq-cdc/run.py',kind='simulation',profile=False,tools=[],options=[])
        self.registry.write_text(json.dumps(dict(schema_version=1,examples=[entry,helper])))
        self.entries={entry['id']:entry,helper['id']:helper}
        self.args=SimpleNamespace(example=['local-fixture'],suite='all',profile='nightly',seed=17,out=self.root/'expected',registry=self.registry,python=sys.executable,formal_python=sys.executable,rdl_python=sys.executable,cocotb_python=sys.executable,uvm_home=None,formal_timeout=None,child_timeout=None,build_timeout=None,command_timeout=30,tool_bin=[])
        self.plan=dict(schema_version=1,profile='nightly',suite='all',seed=17,options={k:str(v) if isinstance(v,Path) else v for k,v in vars(self.args).items()},jobs=T.R.make_plan(self.entries,self.args,self.root),source_sha256={n:T.digest(self.root/n) for n in ('tools/run_regression.py','tools/regressions.json','examples/local-irq-cdc/run.py')})
    def campaign(self,name,success=True,complete=True,record=True,timeout=30):
        out=self.root/name;out.mkdir();args=copy.copy(self.args);args.out=out;args.command_timeout=timeout
        jobs=T.R.make_plan(self.entries,args,self.root);manifest=copy.deepcopy(self.plan);manifest['jobs']=jobs;manifest['options']['out']=str(out)
        (out/'manifest.json').write_text(json.dumps(manifest));d=Path(jobs[0]['out']);d.mkdir(parents=True)
        (d/'manifest.json').write_text(json.dumps(dict(profile='nightly',source_sha256={'rtl.sv':T.digest(self.root/'rtl.sv')})))
        (d/'summary.json').write_text(json.dumps(dict(success=True,complete=True,planned=1,results=[dict(id='compare',status='pass')])))
        (d/'junit.xml').write_text('<testsuite tests="1"><testcase name="compare"/></testsuite>')
        rows=[dict(id=jobs[0]['id'],success=success,returncode=0 if success else 1,message='passed' if success else 'original failure')] if record else []
        T.R.save(out,jobs,rows,complete,True)
        return out
    def report(self,*campaigns):return T.build_report(copy.deepcopy(self.plan),campaigns,self.root)
    def test_original_failure_and_successful_retry_remain_visible(self):
        bad=self.campaign('first',False);good=self.campaign('retry');report=self.report(bad,good)
        self.assertTrue(report['success']);self.assertEqual(len(report['results'][0]['history']),2)
        self.assertFalse(report['campaigns'][0]['success']);self.assertEqual(report['results'][0]['selected']['campaign'],str(good.resolve()))
    def test_later_failure_never_falls_back_to_an_earlier_pass(self):
        good=self.campaign('first');bad=self.campaign('later',False);report=self.report(good,bad)
        self.assertFalse(report['success']);self.assertIsNone(report['results'][0]['selected'])
    def test_missing_latest_result_is_incomplete(self):
        good=self.campaign('first');empty=self.campaign('incomplete',complete=False,record=False)
        report=self.report(good,empty);self.assertFalse(report['success']);self.assertFalse(report['complete'])
    def test_completed_children_from_incomplete_parent_are_reported_coherently(self):
        partial=self.campaign('partial',complete=False);report=self.report(partial)
        self.assertTrue(report['success']);self.assertTrue(report['complete']);self.assertFalse(report['campaigns'][0]['complete'])
    def test_changed_limits_are_recorded_but_changed_seed_is_rejected(self):
        first=self.campaign('first',False,timeout=1);retry=self.campaign('retry',timeout=60)
        r=self.report(first,retry);self.assertTrue(r['success']);self.assertEqual(r['results'][0]['history'][1]['limits']['--timeout'],60)
        p=retry/'manifest.json';m=json.loads(p.read_text());c=m['jobs'][0]['command'];c[c.index('--seed')+1]='18';p.write_text(json.dumps(m))
        r=self.report(first,retry);self.assertFalse(r['success']);self.assertIn('inputs/configuration',r['results'][0]['reason'])
    def test_changed_job_output_cannot_borrow_another_campaign(self):
        good=self.campaign('good');later=self.campaign('later');p=later/'manifest.json';m=json.loads(p.read_text());job=m['jobs'][0];job['out']=str(good/'runs/local-fixture');job['command'][job['command'].index('--out')+1]=job['out'];p.write_text(json.dumps(m))
        r=self.report(later);self.assertFalse(r['success']);self.assertIn('outside',r['results'][0]['reason'])
    def test_plan_and_child_sources_are_checked(self):
        good=self.campaign('good');(self.root/'rtl.sv').write_text('changed')
        self.assertFalse(self.report(good)['success'])
        (self.root/'tools/run_regression.py').write_text('changed')
        with self.assertRaisesRegex(ValueError,'stale source'):self.report(good)
    def test_missing_skipped_or_failed_leaf_junit_is_rejected(self):
        good=self.campaign('good');p=good/'runs/local-fixture/junit.xml'
        for text in ('<testsuite tests="0"/>','<testsuite tests="1"><testcase name="compare"><skipped/></testcase></testsuite>','<testsuite tests="1"><testcase name="compare"><failure/></testcase></testsuite>'):
            p.write_text(text);self.assertFalse(self.report(good)['success'])
    def test_duplicate_campaign_job_or_result_ids_are_rejected(self):
        good=self.campaign('good')
        with self.assertRaisesRegex(ValueError,'duplicate campaign'):self.report(good,good)
        p=good/'manifest.json';m=json.loads(p.read_text());m['jobs']*=2;p.write_text(json.dumps(m))
        with self.assertRaisesRegex(ValueError,'duplicate job'):self.report(good)
    def test_parent_junit_and_integrity_failures_cannot_be_ignored(self):
        good=self.campaign('good');jobs=json.loads((good/'manifest.json').read_text())['jobs'];rows=json.loads((good/'summary.json').read_text())['results']
        T.R.save(good,jobs,rows,True,True,'changed campaign source');self.assertFalse(self.report(good)['success'])
        (good/'junit.xml').write_text('<testsuite tests="0"/>')
        with self.assertRaisesRegex(ValueError,'JUnit'):self.report(good)
    def test_parent_junit_contradicting_summary_is_rejected(self):
        good=self.campaign('good');p=good/'junit.xml';x=T.ET.parse(p);T.ET.SubElement(next(c for c in x.iter('testcase') if c.get('name')=='local-fixture'),'failure',message='hidden');x.write(p)
        with self.assertRaisesRegex(ValueError,'contradicts summary'):self.report(good)
    def test_contradictory_summary_and_changed_plan_count_are_rejected(self):
        good=self.campaign('good');p=good/'summary.json';original=p.read_text()
        for change,message in [(dict(complete=False),'contradictory'),(dict(planned=2),'completion plan')]:
            p.write_text(json.dumps({**json.loads(original),**change}))
            with self.subTest(change=change),self.assertRaisesRegex(ValueError,message):self.report(good)
    def test_successful_row_needs_a_zero_returncode(self):
        good=self.campaign('good');jobs=json.loads((good/'manifest.json').read_text())['jobs'];rows=json.loads((good/'summary.json').read_text())['results'];rows[0]['returncode']=1
        T.R.save(good,jobs,rows,True,True);r=self.report(good);self.assertFalse(r['success']);self.assertEqual(r['results'][0]['status'],'fail')
    def test_campaign_profile_must_match_the_plan(self):
        good=self.campaign('good');p=good/'manifest.json';m=json.loads(p.read_text());m['profile']='smoke';p.write_text(json.dumps(m))
        r=self.report(good);self.assertFalse(r['success']);self.assertIn('profile',r['results'][0]['reason'])
    def test_changes_while_reporting_are_rejected(self):
        real=T.R.inspect_output
        good=self.campaign('good')
        def edit_artifact(*args,**kwargs):
            (good/'junit.xml').write_text((good/'junit.xml').read_text()+'\n');return real(*args,**kwargs)
        with patch.object(T.R,'inspect_output',side_effect=edit_artifact):r=self.report(good)
        self.assertFalse(r['success']);self.assertIn('changed while reporting',';'.join(r['errors']))
        later=self.campaign('later')
        def edit_plan_source(*args,**kwargs):
            (self.root/'tools/run_regression.py').write_text('changed');return real(*args,**kwargs)
        with patch.object(T.R,'inspect_output',side_effect=edit_plan_source),self.assertRaisesRegex(ValueError,'stale source'):self.report(later)
    def test_final_audit_rejects_an_adopted_result(self):
        good=self.campaign('good')
        with patch.object(T.R,'inspect_output',side_effect=[dict(junit=1,source_hashes=1),ValueError('replaced evidence')]):r=self.report(good)
        self.assertFalse(r['success']);self.assertIsNone(r['results'][0]['selected']);self.assertIn('final audit: replaced evidence',r['results'][0]['reason'])
    def test_matrix_value_must_match_the_child_manifest(self):
        entry=self.entries['local-fixture'];entry.update(matrix={'width':[8]},matrix_evidence={'width':'configuration.width'})
        self.registry.write_text(json.dumps(dict(schema_version=1,examples=list(self.entries.values()))))
        self.plan['jobs']=T.R.make_plan(self.entries,self.args,self.root);self.plan['source_sha256']['tools/regressions.json']=T.digest(self.registry)
        good=self.campaign('good');child=Path(json.loads((good/'manifest.json').read_text())['jobs'][0]['out'])/'manifest.json';record=json.loads(child.read_text())
        for value,success in [(16,False),(8,True)]:
            child.write_text(json.dumps(dict(record,configuration=dict(width=value))))
            with self.subTest(value=value):self.assertEqual(self.report(good)['success'],success)
        child.write_text(json.dumps(record));r=self.report(good);self.assertFalse(r['success']);self.assertIn('missing configuration',r['results'][0]['reason'])
    def test_oss_snapshot_is_included_in_report_input_hashes(self):
        good=self.campaign('good');snapshot=good/'runs/local-fixture/oss-source.json'
        snapshot.write_text('{"root":"fixture"}')
        # Isolate artifact enumeration; toolchain validation has its own tests.
        with patch.object(T.R,'inspect_output',return_value=dict(junit=1,source_hashes=1)):report=self.report(good)
        self.assertTrue(report['success']);self.assertEqual(report['input_sha256'][str(snapshot.resolve())],T.digest(snapshot))
    def test_missing_campaigns_cannot_produce_success(self):
        with self.assertRaises(ValueError):self.report()
        p=copy.deepcopy(self.plan);p['jobs'][0]['configuration']={'unexpected':1}
        with self.assertRaisesRegex(ValueError,'registry'):T.build_report(p,[],self.root)
    def test_report_escapes_html_and_junit_contains_rejected_job(self):
        bad=self.campaign('bad',False);r=self.report(bad);r['results'][0]['reason']='<script>alert(1)</script>'
        out=self.root/'report';T.write_report(out,r);self.assertNotIn('<script>',(out/'report.html').read_text());self.assertIn('&lt;script&gt;',(out/'report.html').read_text());self.assertEqual(len(list(T.ET.parse(out/'junit.xml').iter('failure'))),1)
    def test_cli_missing_plan_is_failure_and_existing_output_is_preserved(self):
        out=self.root/'cli';command=[sys.executable,T.__file__,'--plan',str(self.root/'missing.json'),'--campaign',str(self.root/'missing'),'--out',str(out)]
        r=subprocess.run(command,capture_output=True,text=True);self.assertEqual(r.returncode,1,r.stderr);self.assertFalse(json.loads((out/'summary.json').read_text())['success'])
        before=(out/'summary.json').read_bytes();r=subprocess.run(command,capture_output=True,text=True);self.assertEqual(r.returncode,2);self.assertEqual((out/'summary.json').read_bytes(),before)
if __name__=='__main__':unittest.main()

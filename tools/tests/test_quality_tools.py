"""Exercise failure gates with small repositories and bounded fake processes."""
import argparse
from contextlib import redirect_stdout
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[2]
(ROOT/'artifacts').mkdir(exist_ok=True)  # git-ignored, so absent from a fresh clone; some tests need a temporary inside the repository
sys.path.insert(0,str(ROOT/'tools'))
import quality_common as Q
import check_docs as D
import check_environment as E
import run_selftests as S
import setup_environment as U
import build_native as N

class QualityEvidenceTests(unittest.TestCase):
    def test_added_test_during_execution_invalidates_inventory(self):
        with tempfile.TemporaryDirectory() as directory,redirect_stdout(io.StringIO()):
            root=Path(directory);group=root/'tools/tests';group.mkdir(parents=True)
            subprocess.run(['git','init','-q',str(root)],check=True)
            (root/'.gitignore').write_text('out/\n')
            (group/'test_first.py').write_text('# original test')
            def execute(command,log,*args):
                Path(log).write_text('Ran 1 test in 0.1s\n\nOK\n')
                (group/'test_new.py').write_text('# newly added test')
                return dict(command=command,error=None,returncode=0)
            a=argparse.Namespace(scope='tools',out=root/'out',python=sys.executable,timeout=1,jobs=1)
            with patch.object(Q,'ROOT',root),patch.object(Q.P,'execute',side_effect=execute):rc=S.run(a)
            self.assertEqual(rc,1)
            summary=json.loads((a.out/'summary.json').read_text())
            self.assertEqual(next(r['status'] for r in summary['results'] if r['id']=='source-freshness'),'fail')
    def run_selftest_source_fixture(self,change=None):
        with tempfile.TemporaryDirectory() as directory,redirect_stdout(io.StringIO()):
            root=Path(directory);subprocess.run(['git','init','-q',str(root)],check=True)
            for name,text in {'.gitignore':'cache/\n','tools/tests/test_fixture.py':'# test','examples/local-a/model.py':'# model','examples/local-a/rtl/dut.sv':'// RTL','examples/local-a/requirements.json':'{}'}.items():
                p=root/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(text)
            def execute(command,log,*args):
                Path(log).write_text('Ran 1 test in 0.1s\n\nOK\n')
                if change=='add':(root/'examples/local-a/new.py').write_text('# new implementation')
                elif change=='delete':(root/'examples/local-a/model.py').unlink()
                elif change=='ignored':(root/'cache').mkdir();(root/'cache/generated.json').write_text('{}')
                elif change:
                    name={'model':'model.py','rtl':'rtl/dut.sv','requirements':'requirements.json'}[change]
                    (root/'examples/local-a'/name).write_text('# changed input')
                return dict(command=command,error=None,returncode=0)
            a=argparse.Namespace(scope='tools',out=root/'out',python=sys.executable,timeout=1,jobs=1)
            with patch.object(Q,'ROOT',root),patch.object(Q.P,'execute',side_effect=execute):rc=S.run(a)
            return rc,json.loads((a.out/'summary.json').read_text()),json.loads((a.out/'manifest.json').read_text())
    def test_selftests_bind_implementation_rtl_and_requirements_even_in_tools_scope(self):
        rc,summary,manifest=self.run_selftest_source_fixture();self.assertEqual(rc,0);self.assertTrue(summary['success'])
        sources=manifest['source_sha256']
        self.assertFalse(any('/out/' in p for p in sources))
        for name in ('model.py','rtl/dut.sv','requirements.json'):
            self.assertTrue(any(p.endswith('/examples/local-a/'+name) for p in sources))
    def test_implementation_changes_additions_and_deletions_invalidate_selftests(self):
        for change in ('model','rtl','requirements','add','delete'):
            with self.subTest(change=change):
                rc,summary,_=self.run_selftest_source_fixture(change);self.assertEqual(rc,1);self.assertFalse(summary['success'])
                self.assertEqual(next(r['status'] for r in summary['results'] if r['id']=='source-freshness'),'fail')
    def test_ignored_generated_files_do_not_invalidate_selftests(self):
        self.assertEqual(self.run_selftest_source_fixture('ignored')[0],0)
    def test_incomplete_and_changed_inputs_fail(self):
        with tempfile.TemporaryDirectory() as directory,redirect_stdout(io.StringIO()):
            p=Path(directory);source=p/'source';source.write_text('original')
            r=Q.Report('fixture',p/'out',[source],['first','second'])
            r.check('first',True,'observed');source.write_text('edited')
            self.assertIn(str(source),r.fresh());self.assertEqual(r.finish(),1)
            summary=json.loads((r.out/'summary.json').read_text())
            self.assertFalse(summary['complete']);self.assertFalse(summary['success'])
            self.assertEqual(summary['results'][1]['status'],'fail')
    def test_venv_executable_symlink_is_preserved(self):
        with tempfile.TemporaryDirectory(dir=ROOT/'artifacts') as directory:
            p=Path(directory)/'python';p.symlink_to(sys.executable)
            relative=p.relative_to(ROOT)
            self.assertEqual(Q.executable(str(relative)),str(p.absolute()))
            self.assertNotEqual(Q.executable(str(relative)),str(p.resolve()))
    def test_skipped_empty_or_missing_test_summary_never_pass(self):
        execution=dict(error=None,returncode=0)
        self.assertTrue(S.evaluate(execution,'Ran 2 tests in 0.1s\n\nOK\n')['success'])
        for log in ('Ran 0 tests in 0.1s\nOK\n','Ran 1 test in 0.1s\nOK (skipped=1)\n','thing ... skipped reason\nRan 2 tests in 0.1s\nOK\n','OK\n','Ran 1 test in 0s\nRan 1 test in 0s\nOK\n'):
            with self.subTest(log=log):self.assertFalse(S.evaluate(execution,log)['success'])
        self.assertFalse(S.evaluate(dict(error='timeout',returncode=0),'Ran 1 test in 0s\nOK\n')['success'])
        self.assertFalse(S.evaluate(dict(error=None,returncode=1),'Ran 1 test in 0s\nOK\n')['success'])

class DocumentTests(unittest.TestCase):
    def test_stray_closing_code_tag_cannot_hide_subsequent_links(self):
        page=D.Page();page.feed('</code></pre><a href="missing.md">link</a>')
        self.assertEqual(page.links,['missing.md'])
        page=D.Page();page.feed('<pre><code><a href="sample.md">code example</a></code></pre><a href="real.md">link</a>')
        self.assertEqual(page.links,['real.md'])
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=ROOT/'artifacts');self.addCleanup(self.temp.cleanup)
        self.base=Path(self.temp.name);self.root=self.base/'repo';self.root.mkdir()
        subprocess.run(['git','init','-q',str(self.root)],check=True)
        (self.root/'docs').mkdir()
        (self.root/'docs/glossary.md').write_text('| 用語 | 意味 |\n| --- | --- |\n| DUT | 対象 |\n')
        (self.root/'docs/faq.md').write_text('# Q1. 質問\n回答\n')
        (self.root/'README.md').write_text('# Main\n[FAQ](docs/faq.md#q1-質問)\n[Documents](docs/)\n\n```mermaid\nflowchart LR\n A-->B\n```\n')
    def run_docs(self,node='node'):
        a=argparse.Namespace(root=self.root,node=Q.executable(node),timeout=30,out=self.base/'out')
        with redirect_stdout(io.StringIO()):rc=D.run(a)
        return rc,json.loads((a.out/'summary.json').read_text())
    def test_good_repository_uses_real_mermaid_parser(self):
        rc,result=self.run_docs();self.assertEqual(rc,0);self.assertTrue(result['complete'])
        self.assertTrue(any(r['id'].startswith('diagram/') for r in result['results']))
    def test_edit_after_read_before_manifest_capture_invalidates_documents(self):
        import markdown
        source=self.root/'README.md';original=Q.digest(source);render=markdown.markdown
        def edit_after_render(text,*args,**kwargs):
            result=render(text,*args,**kwargs)
            if text.startswith('# Main'):source.write_text('# Edited\n[broken](missing.md)\n')
            return result
        with patch.object(markdown,'markdown',side_effect=edit_after_render):rc,result=self.run_docs()
        self.assertEqual(rc,1);self.assertFalse(result['success'])
        gate=next(r for r in result['results'] if r['id']=='source-freshness');self.assertEqual(gate['status'],'fail')
        self.assertIn('document changed before input snapshot: README.md',gate['detail'])
        record=json.loads((self.base/'out/documentation-check.json').read_text())
        self.assertEqual(record['document_read_sha256']['README.md'],original);self.assertNotEqual(original,Q.digest(source))
    def test_document_read_hash_preserves_crlf_bytes(self):
        source=self.root/'README.md';source.write_bytes(source.read_bytes().replace(b'\n',b'\r\n'))
        expected=Q.digest(source);rc,result=self.run_docs();self.assertEqual(rc,0);self.assertTrue(result['success'])
        record=json.loads((self.base/'out/documentation-check.json').read_text())
        self.assertEqual(record['document_read_sha256']['README.md'],expected)
    def test_missing_link_and_heading_are_reported(self):
        (self.root/'README.md').write_text('[missing](absent.md)\n[heading](docs/faq.md#absent)\n')
        rc,result=self.run_docs();self.assertEqual(rc,1)
        detail=next(r['detail'] for r in result['results'] if r['id']=='document/README.md')
        self.assertEqual({r['error'] for r in detail},{'missing/untracked target','missing heading/anchor'})
    def test_ignored_and_outside_files_do_not_satisfy_links(self):
        (self.root/'.gitignore').write_text('hidden.md\ncache/\n')
        (self.root/'hidden.md').write_text('# Exists')
        (self.root/'cache').mkdir();(self.root/'cache/generated.txt').write_text('ignored output')
        (self.base/'outside.md').write_text('# Exists')
        (self.root/'README.md').write_text('[ignored](hidden.md)\n[ignored directory](cache/)\n[outside](../outside.md)')
        rc,result=self.run_docs();self.assertEqual(rc,1)
        detail=next(r['detail'] for r in result['results'] if r['id']=='document/README.md')
        self.assertEqual(len(detail),3)
        self.assertEqual({r['error'] for r in detail},{'missing/untracked target','link escapes repository'})
    def test_invalid_diagram_fails_even_when_documents_have_no_link_errors(self):
        (self.root/'README.md').write_text('```mermaid\nflowchart LR\n A --[\n```\n')
        rc,result=self.run_docs();self.assertEqual(rc,1)
        self.assertTrue(any(r['id'].startswith('diagram/') and r['status']=='fail' for r in result['results']))
    def test_absent_parser_cannot_look_like_zero_diagrams_success(self):
        rc,result=self.run_docs(str(self.base/'missing-node'));self.assertEqual(rc,1)
        self.assertEqual(next(r['status'] for r in result['results'] if r['id']=='mermaid-runtime'),'fail')
    def test_forged_empty_parser_result_is_rejected(self):
        def execute(command,log,*args):
            Path(log).write_text('');Path(command[-1]).write_text('{"success":true,"results":[]}')
            return dict(error=None,returncode=0)
        with patch.object(Q.P,'execute',side_effect=execute):rc,result=self.run_docs()
        self.assertEqual(rc,1);self.assertFalse(result['success'])
    def test_parser_exit_code_must_agree_with_its_result(self):
        def execute(command,log,*args):
            Path(log).write_text('');blocks=json.loads(Path(command[-2]).read_text())
            Path(command[-1]).write_text(json.dumps(dict(success=True,results=[dict(id=b['id'],success=True) for b in blocks])))
            return dict(error=None,returncode=1)
        with patch.object(Q.P,'execute',side_effect=execute):rc,result=self.run_docs()
        self.assertEqual(rc,1);self.assertEqual(next(r['status'] for r in result['results'] if r['id']=='mermaid-runtime'),'fail')
    def test_glossary_and_faq_negative_controls(self):
        for text,checker in [('<table><tr><th>用語</th></tr><tr><td></td></tr></table>',D.glossary),('<table><tr><th>用語</th></tr><tr><td>A</td></tr><tr><td>A</td></tr></table>',D.glossary),('<h2>Q1. A</h2><h2>Q3. B</h2>',D.faq),('<h2>Q1. A</h2><h2>Q1. B</h2>',D.faq)]:
            page=D.Page();page.feed(text)
            with self.subTest(text=text),self.assertRaises(ValueError):checker(page)
    def test_fence_table_and_colliding_heading_names(self):
        errors,blocks=D.structure('| A | B |\n| --- | --- |\n| only |\n\n```mermaid\nflowchart LR\n A-->B\n','file.md')
        self.assertEqual({e['error'] for e in errors},{'table column count differs','unclosed code fence'})
        self.assertEqual(blocks,[])
        page=D.Page();page.feed('<h1>Foo</h1><h1>Foo-1</h1><h1>Foo</h1>')
        self.assertEqual(page.anchors(),{'foo','foo-1','foo-2'})

class EnvironmentTests(unittest.TestCase):
    def test_uvm_modified_missing_and_added_files_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            home=Path(directory);(home/'src').mkdir();source=home/'src/uvm.sv';source.write_text('library')
            license=home/'LICENSE.txt';license.write_text('license')
            expected={'src/uvm.sv':Q.digest(source),'LICENSE.txt':Q.digest(license)}
            self.assertTrue(E.uvm_snapshot(home,expected)[0])
            source.write_text('modified');self.assertFalse(E.uvm_snapshot(home,expected)[0])
            source.write_text('library');extra=home/'src/extra.sv';extra.touch();self.assertFalse(E.uvm_snapshot(home,expected)[0])
            extra.unlink();license.unlink();self.assertFalse(E.uvm_snapshot(home,expected)[0])
    def test_wrong_versions_fail(self):
        for name,good,bad in [('node','v24.1.0','v20.1.0'),('iverilog','Icarus Verilog version 14.0','Icarus Verilog version 12.0'),('vvp','Icarus Verilog runtime version 14.0','Icarus Verilog runtime version 13.0'),('verilator','Verilator 5.052 2026-09-05 rev x','Verilator 5.052-dev x'),('sta','3.1.0 abc','3.0.0'),('yowasp-yosys','Yosys 0.70 (git sha1 x)','Yosys 0.69'),('z3','Z3 version 4.15.3 - 64 bit','Z3 version 4.14.0')]:
            with self.subTest(name=name):self.assertTrue(E.version_ok(name,good));self.assertFalse(E.version_ok(name,bad))
    def test_relative_oss_home_still_runs_from_the_report_directory(self):
        with tempfile.TemporaryDirectory(dir=ROOT/'artifacts') as directory,redirect_stdout(io.StringIO()):
            base=Path(directory);(base/'oss/bin').mkdir(parents=True);real=Q.P.execute
            for name in ('yosys','sby','mcy'):
                p=base/'oss/bin'/name;p.write_text('#!/bin/sh\nexit 0\n');p.chmod(0o755)
            def execute(command,log,*args):
                # Only the OSS tools are under test; every other probe is a bounded failure.
                if Path(command[0]).parent==(base/'oss/bin').absolute() or not Path(command[0]).is_absolute() and 'oss/bin' in command[0]:return real(command,log,*args)
                Path(log).write_text('');return dict(command=command,returncode=None,error='not under test')
            out=base/'out';argv=['check_environment.py','--profile','full','--oss-home',os.path.relpath(base/'oss'),'--out',str(out)]
            with patch.object(sys,'argv',argv),patch.object(E.O,'verify',return_value=dict(fixture=True)),patch.object(Q.P,'execute',side_effect=execute):self.assertEqual(E.main(),1)
            rows={r['id']:r['status'] for r in json.loads((out/'summary.json').read_text())['results']}
            self.assertEqual([rows[k] for k in ('oss-cad','oss/yosys','oss/sby','oss/mcy')],['pass']*4)
    def test_wrong_python_package_version_fails(self):
        with tempfile.TemporaryDirectory() as directory,redirect_stdout(io.StringIO()):
            packages={n:v['version'] for n,v in json.loads((ROOT/'tools/environment.json').read_text())['packages']['docs'].items()}
            def run(installed):
                def execute(command,log,*args):
                    Path(log).write_text(json.dumps(dict(python=list(sys.version_info[:3]),packages=installed)) if 'importlib.metadata' in ' '.join(command) else '');return dict(command=command,returncode=0,error=None)
                a=argparse.Namespace(profile='docs',python=sys.executable,formal_python=sys.executable,rdl_python=sys.executable,cocotb_python=sys.executable,tool_bin=[],timeout=1,out=Path(directory)/str(len(list(Path(directory).iterdir()))))
                with patch.object(Q.P,'execute',side_effect=execute):E.run(a)
                return next(r['status'] for r in json.loads((a.out/'summary.json').read_text())['results'] if r['id']=='packages/docs')
            self.assertEqual(run(packages),'pass');self.assertEqual(run({**packages,'Markdown':'0.0.0'}),'fail')
    def test_setup_rejects_exit_zero_diagnosis_with_a_failed_summary(self):
        with tempfile.TemporaryDirectory() as directory,redirect_stdout(io.StringIO()):
            a=argparse.Namespace(profile='smoke',out=Path(directory)/'setup',python=sys.executable,npm='npm',timeout=1,tool_bin=[])
            def execute(command,log,*args):
                Path(log).write_text('')
                if 'check_environment.py' in ' '.join(command):
                    (a.out/'diagnosis').mkdir();(a.out/'diagnosis/summary.json').write_text(json.dumps(dict(success=False,complete=True,planned=1,results=[dict(id='python',status='fail')])))
                return dict(command=command,returncode=0,error=None)
            with patch.object(Q.P,'execute',side_effect=execute):self.assertEqual(U.run(a),1)
            self.assertEqual(next(r['status'] for r in json.loads((a.out/'summary.json').read_text())['results'] if r['id']=='diagnosis'),'fail')
    def test_failed_setup_does_not_run_dependent_commands(self):
        with tempfile.TemporaryDirectory() as directory,redirect_stdout(io.StringIO()):
            calls=[]
            def execute(command,log,*args):
                calls.append(command);Path(log).write_text('missing interpreter');return dict(command=command,error='not found',returncode=None)
            a=argparse.Namespace(profile='docs',out=Path(directory)/'setup',python='/missing/python',npm='/missing/npm',timeout=1,tool_bin=[])
            with patch.object(Q.P,'execute',side_effect=execute):rc=U.run(a)
            self.assertEqual(rc,1);self.assertEqual(len(calls),1)
            summary=json.loads((a.out/'summary.json').read_text())
            self.assertTrue(summary['complete']);self.assertFalse(summary['success'])
            self.assertIn('setup-recheck',(a.out/'next-command.txt').read_text())
    def test_native_checkout_revision_mismatch_stops_build(self):
        with tempfile.TemporaryDirectory() as directory,redirect_stdout(io.StringIO()):
            phases=[]
            def execute(command,log,*args):
                phases.append(Path(log).stem);Path(log).write_text('wrong commit' if Path(log).stem=='revision' else '')
                return dict(command=command,error=None,returncode=0)
            a=argparse.Namespace(profile='smoke',out=Path(directory)/'native',timeout=1,jobs=1)
            with patch.object(Q.P,'execute',side_effect=execute):rc=N.run(a)
            self.assertEqual(rc,1);self.assertNotIn('configure',phases);self.assertNotIn('build',phases)
            summary=json.loads((a.out/'summary.json').read_text())
            self.assertTrue(summary['complete']);self.assertFalse(summary['success'])

class WorkflowTests(unittest.TestCase):
    def test_ci_runs_real_gates_and_keeps_failure_evidence(self):
        import yaml
        for name in ('quality','nightly','affected','kirimasim'):
            workflow=yaml.load((ROOT/f'.github/workflows/{name}.yml').read_text(),Loader=yaml.BaseLoader)
            self.assertEqual(workflow['permissions'],{'contents':'read','actions':'read'} if name=='affected' else {'contents':'read'})
            for job in workflow['jobs'].values():
                self.assertIn('timeout-minutes',job)
                uploads=[]
                for step in job['steps']:
                    self.assertNotIn('continue-on-error',step)
                    if 'uses' in step:self.assertRegex(step['uses'],r'^[^@]+@[a-f0-9]{40}$')
                    if step.get('uses','').startswith('actions/upload-artifact@'):uploads.append(step)
                self.assertTrue(uploads);self.assertTrue(all(s['if']=='always()' for s in uploads))
        quality=yaml.load((ROOT/'.github/workflows/quality.yml').read_text(),Loader=yaml.BaseLoader)
        nightly=yaml.load((ROOT/'.github/workflows/nightly.yml').read_text(),Loader=yaml.BaseLoader)
        self.assertIn('push',quality['on']);self.assertIn('pull_request',quality['on'])
        self.assertIn('schedule',nightly['on']);self.assertIn('workflow_dispatch',nightly['on'])
        full='\n'.join(s.get('run','') for s in nightly['jobs']['full']['steps'])
        self.assertIn('--profile nightly',full);self.assertIn('tools/run_selftests.py',full)
        self.assertNotIn('--check-tools',full)
        affected=yaml.load((ROOT/'.github/workflows/affected.yml').read_text(),Loader=yaml.BaseLoader)
        steps=affected['jobs']['affected']['steps'];commands='\n'.join(s.get('run','') for s in steps)
        self.assertIn('--base "$CHANGE_BASE" --run --profile smoke',commands)
        self.assertIn('tools/select_regression.py',commands)
        self.assertEqual(next(s for s in steps if s.get('id')=='selection')['name'],'Select affected jobs')
        self.assertIn("steps.selection.outputs.jobs != '0'",next(s for s in steps if s.get('name')=='Run and audit the selected jobs')['if'])
    def affected_base(self,event,gh=None,gh_code=0,before='',pull=''):
        import yaml
        script=next(s for s in yaml.load((ROOT/'.github/workflows/affected.yml').read_text(),Loader=yaml.BaseLoader)['jobs']['affected']['steps'] if s.get('id')=='base')['run']
        output=self.repo/'output';calls=self.repo/'calls';output.write_text('');calls.write_text('')
        env=dict(os.environ,GITHUB_EVENT_NAME=event,GITHUB_REF_NAME='feature',GITHUB_OUTPUT=str(output),PUSH_BEFORE=before,PULL_REQUEST_BASE=pull,PATH=str(self.bin)+os.pathsep+os.environ['PATH'],FAKE_GH_OUTPUT=gh or '',FAKE_GH_CODE=str(gh_code),FAKE_GH_CALLS=str(calls))
        r=subprocess.run(['bash','-e','-c',script],cwd=self.repo,env=env,capture_output=True,text=True);self.assertEqual(r.returncode,0,r.stdout+r.stderr)
        return dict(line.split('=',1) for line in output.read_text().splitlines())['value'],calls.read_text(),r.stdout
    def test_affected_base_follows_the_last_successful_push(self):
        with tempfile.TemporaryDirectory() as directory:
            self.repo=Path(directory)/'repo';self.bin=Path(directory)/'bin';self.repo.mkdir();self.bin.mkdir()
            gh=self.bin/'gh';gh.write_text('#!/bin/sh\necho "$@" >> "$FAKE_GH_CALLS"\nif [ -n "$FAKE_GH_OUTPUT" ]; then echo "$FAKE_GH_OUTPUT"; fi\nexit "$FAKE_GH_CODE"\n');gh.chmod(0o755)
            def git(*args):return subprocess.check_output(['git','-c','user.name=Fixture','-c','user.email=fixture@example.invalid','-C',str(self.repo),*args],text=True).strip()
            git('init','-q')
            commits=[]
            for name in ('verified','failed','latest'):git('commit','-q','--allow-empty','-m',name);commits.append(git('rev-parse','HEAD'))
            verified,failed,latest=commits
            git('checkout','-q','-b','other',verified);git('commit','-q','--allow-empty','-m','elsewhere');elsewhere=git('rev-parse','HEAD');git('checkout','-q',latest)
            # A failed or replaced push stays inside the next push's comparison.
            base,calls,_=self.affected_base('push',gh=verified,before=failed);self.assertEqual(base,verified)
            for flag in ('--workflow affected.yml','--branch feature','--event push','--status success'):self.assertIn(flag,calls)
            for label,kwargs in [('no successful run',dict(gh='')),('rewritten history',dict(gh=elsewhere)),('unknown commit',dict(gh='f'*40))]:
                with self.subTest(label):self.assertEqual(self.affected_base('push',before=failed,**kwargs)[0],failed)
            base,_,stdout=self.affected_base('push',gh_code=1,before=failed);self.assertEqual(base,failed);self.assertIn('::warning::',stdout)
            base,calls,_=self.affected_base('pull_request',gh=verified,before=failed,pull=elsewhere);self.assertEqual((base,calls),(elsewhere,''))
            base,calls,_=self.affected_base('workflow_dispatch',gh=verified);self.assertEqual((base,calls),('HEAD~1',''))
    def test_affected_uses_one_base_and_only_cancels_pull_requests(self):
        import yaml
        workflow=yaml.load((ROOT/'.github/workflows/affected.yml').read_text(),Loader=yaml.BaseLoader);steps=workflow['jobs']['affected']['steps']
        self.assertEqual(workflow['concurrency']['cancel-in-progress'],"${{ github.event_name == 'pull_request' }}")
        users=[s for s in steps if 'CHANGE_BASE' in s.get('env',{})];self.assertEqual([s['name'] for s in users],['Select affected jobs','Run and audit the selected jobs'])
        self.assertTrue(all(s['env']['CHANGE_BASE']=='${{ steps.base.outputs.value }}' for s in users))
        self.assertLess([s.get('id') for s in steps].index('base'),[s.get('id') for s in steps].index('selection'))
    def kirimasim_steps(self):
        import yaml
        return yaml.load((ROOT/'.github/workflows/kirimasim.yml').read_text(),Loader=yaml.BaseLoader)['jobs']['smoke']['steps']
    def test_kirimasim_workflow_runs_one_decided_commit_on_a_schedule(self):
        import yaml
        workflow=yaml.load((ROOT/'.github/workflows/kirimasim.yml').read_text(),Loader=yaml.BaseLoader)
        for trigger in ('schedule','push','workflow_dispatch'):self.assertIn(trigger,workflow['on'])
        self.assertEqual(workflow['concurrency']['cancel-in-progress'],'false')
        steps=self.kirimasim_steps();ids=[s.get('id') for s in steps];names=[s.get('name') for s in steps]
        commit='${{ steps.kirimasim.outputs.commit }}'
        self.assertIn(commit,next(s for s in steps if s.get('id')=='binary')['with']['key'])
        source=next(s for s in steps if s.get('with',{}).get('repository')=='kurochan001/kirimasim');self.assertEqual(source['with']['ref'],commit)
        run=next(s['run'] for s in steps if s.get('name')=='Run the pure-Icarus examples on kirimasim')
        for flag in ('tools/run_kirimasim_examples.py','--profile smoke','--seed 17'):self.assertIn(flag,run)
        # A binary is identified, then cached, then trusted with a verdict.
        self.assertLess(ids.index('kirimasim'),ids.index('binary'))
        self.assertLess(names.index('Build kirimasim'),ids.index('identity'))
        self.assertLess(ids.index('identity'),names.index('Save the confirmed binary before verification'))
        self.assertLess(names.index('Save the confirmed binary before verification'),names.index('Run the pure-Icarus examples on kirimasim'))
    def test_kirimasim_commit_is_a_full_hash_from_the_request_or_the_latest_main(self):
        script=next(s for s in self.kirimasim_steps() if s.get('id')=='kirimasim')['run']
        latest,requested='a'*40,'b'*40
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'bin').mkdir();git=root/'bin/git'
            git.write_text('#!/bin/sh\necho "$@" >> "$FAKE_CALLS"\nif [ -n "$FAKE_REMOTE" ]; then printf \'%s\\trefs/heads/main\\n\' "$FAKE_REMOTE"; fi\n');git.chmod(0o755)
            def decide(request='',remote=latest):
                output,calls=root/'output',root/'calls';output.write_text('');calls.write_text('')
                env=dict(os.environ,REQUESTED_COMMIT=request,FAKE_REMOTE=remote,FAKE_CALLS=str(calls),GITHUB_OUTPUT=str(output),PATH=str(root/'bin')+os.pathsep+os.environ['PATH'])
                r=subprocess.run(['bash','-e','-c',script],cwd=root,env=env,capture_output=True,text=True)
                return r.returncode,output.read_text().strip(),calls.read_text()
            code,output,calls=decide();self.assertEqual((code,output),(0,'commit='+latest));self.assertIn('refs/heads/main',calls)
            self.assertEqual(decide(requested)[:2],(0,'commit='+requested));self.assertEqual(decide(requested)[2],'')
            for label,kwargs in [('remote unreachable',dict(remote='')),('branch name',dict(request='main')),('short hash',dict(request='a'*12)),('injection',dict(request=latest+'; touch hacked'))]:
                with self.subTest(label):
                    code,output,_=decide(**kwargs);self.assertNotEqual(code,0);self.assertEqual(output,'')
            self.assertFalse((root/'hacked').exists())
    def test_kirimasim_binary_must_report_the_decided_commit(self):
        script=next(s for s in self.kirimasim_steps() if s.get('id')=='identity')['run']
        commit='0123456789ab'+'c'*28
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);binary=root/'artifacts/kirimasim-tool/kirimasim';binary.parent.mkdir(parents=True)
            def identity(text):
                binary.write_text(f'#!/bin/sh\necho "{text}"\n');binary.chmod(0o755)
                return subprocess.run(['bash','-e','-c',script],cwd=root,env=dict(os.environ,KIRIMASIM_COMMIT=commit),capture_output=True,text=True).returncode
            self.assertEqual(identity('kirimasim 0.0.0 (commit 0123456789ab), built with GNU 13.3.0'),0)
            for text in ('kirimasim 0.0.0 (commit 111111111111), built with GNU 13.3.0','kirimasim 0.0.0'):
                with self.subTest(text):self.assertNotEqual(identity(text),0)

if __name__=='__main__':unittest.main()

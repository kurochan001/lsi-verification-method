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
        for name in ('quality','nightly'):
            workflow=yaml.load((ROOT/f'.github/workflows/{name}.yml').read_text(),Loader=yaml.BaseLoader)
            self.assertEqual(workflow['permissions'],{'contents':'read'})
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

if __name__=='__main__':unittest.main()

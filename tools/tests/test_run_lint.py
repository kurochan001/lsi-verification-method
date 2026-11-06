from contextlib import redirect_stdout
import copy
import importlib.util
import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[2]
s=importlib.util.spec_from_file_location('lint_under_test',ROOT/'tools/run_lint.py');L=importlib.util.module_from_spec(s);s.loader.exec_module(L)
class LintPolicyTests(unittest.TestCase):
    def test_release_identity_preserves_build_independence(self):
        for build in ('rev vUNKNOWN-built20260905','rev v5.052'):
            self.assertEqual(L.release_version('Verilator 5.052 2026-09-05 '+build),'5.052')
        self.assertEqual(L.release_version('Verilator 5.050 2026-08-01 rev x'),'5.050')
        for text in ('Verilator 5.052-dev x','Verilator 5.052','Verilator 5.052 x\nextra','5.052'):
            self.assertIsNone(L.release_version(text))
    def setUp(self):
        self.d=dict(severity='Warning',rule='WIDTHTRUNC',file='examples/x/rtl/x.sv',line=2,column=3,message='width differs')
        self.sha={'examples/x/rtl/x.sv':'digest'}
        self.b=dict(source_sha256=self.sha,diagnostics=[dict(diagnostic=self.d,count=1,disposition='known-debt',reason='width debt retained',impact='needs review',reviewer='automated test',method='fixture',expires='source/tool/config change')])
    def test_actual_warning_location_and_rule(self):
        log=f'%Warning-WIDTHTRUNC: {ROOT}/examples/x/rtl/x.sv:2:3: width differs\n  2 | assign q=a;\n'
        self.assertEqual(L.diagnostics(log),[self.d])
    def test_malformed_warning_never_means_clean(self):
        for line in ('%Warning-WIDTHTRUNC bad syntax','%Warning: no rule/location','%Unrecognized: thing'):
            with self.subTest(line=line),self.assertRaises(ValueError):L.diagnostics(line)
    def test_outside_source_rejected(self):
        with self.assertRaises(ValueError):L.diagnostics('%Warning-WIDTH: /tmp/outside.sv:2:1: mismatch')
    def test_errors_preserved(self):
        self.assertEqual(L.diagnostics('%Error: Cannot elaborate')[0]['severity'],'Error')
    def test_unchanged_debt_is_not_new(self):
        self.assertFalse(any(L.changes([self.d],self.b,self.sha).values()))
    def test_warning_count_growth_is_new(self):
        self.assertEqual(L.changes([self.d,self.d],self.b,self.sha)['new'][0]['count'],1)
    def test_resolved_warning_needs_baseline_update(self):
        self.assertTrue(L.changes([],self.b,self.sha)['resolved'])
    def test_source_edit_invalidates_waiver(self):
        self.b['diagnostics'][0]['disposition']='waived'
        self.assertTrue(L.changes([self.d],self.b,dict(self.sha,extra='digest'))['source_changed'])
    def test_unreviewed_candidate_cannot_be_baseline(self):
        self.b['diagnostics'][0]['reason']='REVIEW REQUIRED'
        with self.assertRaises(ValueError):L.changes([self.d],self.b,self.sha)
    def test_duplicate_warning_approval_rejected(self):
        self.b['diagnostics'].append(copy.deepcopy(self.b['diagnostics'][0]))
        with self.assertRaises(ValueError):L.changes([self.d],self.b,self.sha)
    def test_missing_new_or_unbound_module_fails_inventory(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);p=root/'examples/local-x/rtl/x.sv';p.parent.mkdir(parents=True);p.write_text('module x; endmodule\n')
            (p.parent.parent/'run.py').touch();f=str(p.relative_to(root))
            catalog=dict(schema_version=1,rtl_files=[f],targets=[dict(id='x/default',file=f,top='x',sources=[f],parameters={})],examples={'local-x':dict(scope='dut',targets=['x/default'],reason='DUT')})
            self.assertEqual(len(L.validate_catalog(catalog,root)),1)
            p.write_text('module x; endmodule\nmodule forgotten; endmodule\n')
            with self.assertRaises(ValueError):L.validate_catalog(catalog,root)
            (p.parent/'new.sv').write_text('module added; endmodule\n')
            with self.assertRaises(ValueError):L.validate_catalog(catalog,root)

class LintGateTests(unittest.TestCase):
    """Run the real gate against one clean DUT target and a scripted Verilator."""
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        catalog=json.loads((ROOT/'tools/lint_targets.json').read_text());baseline=json.loads((ROOT/'tools/lint_baseline.json').read_text())
        self.target=next(t for t in catalog['targets'] if not baseline['targets'][t['id']]['diagnostics'])
        self.catalog=self.root/'catalog.json';self.catalog.write_text(json.dumps(dict(catalog,rtl_files=self.target['sources'],blackbox_sources={})))
        self.baseline=self.root/'baseline.json';self.baseline.write_text(json.dumps(dict(baseline,targets={self.target['id']:baseline['targets'][self.target['id']]})))
    def run_gate(self,lint='exit 0',version='Verilator 5.052 2026-09-05 rev fixture',timeout=10):
        tool=self.root/'verilator';tool.write_text(f'#!/bin/sh\nif [ "$1" = --version ]; then echo "{version}"; exit 0; fi\n{lint}\n');tool.chmod(0o755)
        a=SimpleNamespace(verilator=str(tool),timeout=timeout,out=self.root/'out',catalog=self.catalog,baseline=self.baseline,profile='smoke',seed=17)
        with patch.object(L,'validate_catalog',return_value=[self.target]),redirect_stdout(io.StringIO()):rc=L.run(a)
        return rc,{r['id']:r for r in json.loads((a.out/'summary.json').read_text())['results']}
    def failures(self,rows):return sorted(k for k,r in rows.items() if r['status']=='fail')
    def test_clean_target_passes(self):
        rc,rows=self.run_gate();self.assertEqual(rc,0);self.assertEqual(self.failures(rows),[])
    def test_nonzero_exit_without_diagnostics_fails_the_target(self):
        rc,rows=self.run_gate('exit 3');self.assertEqual(rc,1);self.assertEqual(self.failures(rows),[self.target['id']])
    def test_timeout_fails_the_target(self):
        rc,rows=self.run_gate('exec sleep 30',timeout=.2);self.assertEqual(rc,1);self.assertEqual(rows[self.target['id']]['detail']['execution']['error'],'command timeout')
    def test_absent_tool_fails_every_check_that_uses_it(self):
        with patch.object(L,'validate_catalog',return_value=[self.target]),redirect_stdout(io.StringIO()):
            rc=L.run(SimpleNamespace(verilator=str(self.root/'absent'),timeout=10,out=self.root/'out',catalog=self.catalog,baseline=self.baseline,profile='smoke',seed=17))
        rows={r['id']:r for r in json.loads((self.root/'out/summary.json').read_text())['results']}
        self.assertEqual(rc,1);self.assertEqual(self.failures(rows),sorted(['tool-version',self.target['id']]))
    def test_new_warning_fails_the_target(self):
        source=ROOT/self.target['sources'][0]
        rc,rows=self.run_gate(f'echo "%Warning-WIDTHTRUNC: {source}:1:1: width differs"');self.assertEqual(rc,1);self.assertEqual(self.failures(rows),[self.target['id']])
        self.assertEqual(rows[self.target['id']]['detail']['changes']['new'][0]['diagnostic']['rule'],'WIDTHTRUNC')
    def test_other_tool_release_fails_version_and_target(self):
        rc,rows=self.run_gate(version='Verilator 5.050 2026-08-01 rev fixture');self.assertEqual(rc,1);self.assertEqual(self.failures(rows),sorted(['tool-version',self.target['id']]))
    def test_baseline_inventory_difference_fails_inventory_and_target(self):
        baseline=json.loads(self.baseline.read_text());baseline['targets']['unexpected/target']=dict(diagnostics=[]);self.baseline.write_text(json.dumps(baseline))
        rc,rows=self.run_gate();self.assertEqual(rc,1);self.assertEqual(self.failures(rows),sorted(['inventory',self.target['id']]))
    def test_input_changed_during_lint_fails_source_freshness(self):
        rc,rows=self.run_gate(f'echo "\n" >> "{self.catalog}"');self.assertEqual(rc,1);self.assertEqual(self.failures(rows),['source-freshness'])
if __name__=='__main__':unittest.main()

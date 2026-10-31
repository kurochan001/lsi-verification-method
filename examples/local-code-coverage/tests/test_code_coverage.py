from pathlib import Path
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'local-common'))
from local_test_support import load_example,read_json
P=load_example('local-code-coverage')

class CodeCoverageTests(unittest.TestCase):
    def fixture(self):
        return {P.point_id(m):dict(metadata=m,count=2) for kind in P.KINDS for m in [dict(t=kind,l='1',n='1',o=kind,h='TOP.command_unit')]}
    def contract(self,points):
        return dict(counts=dict(P.Counter(p['metadata']['t'] for p in points.values())),inventory_sha256=P.inventory_hash(points),not_required={})
    def test_modular_arithmetic_xor_and_denied_requests(self):
        for op,a,b,en,auth,expected,error in ((0,255,1,1,1,0,0),(1,0xaa,0x55,1,1,255,0),(0,255,1,0,1,0,1),(1,1,2,1,0,0,1)):
            p=P.Plan(8);p.cycle(rst=0);p.transfer(op,a,b,en,auth)
            responses=[r for r in p.rows if r[9]];self.assertEqual([(r[10],r[11]) for r in responses],[(expected,error)])
    def test_response_hold_and_busy_input_changes_preserve_transaction(self):
        p=P.Plan(8);p.cycle(rst=0);p.transfer(0,7,8,hold=3)
        responses=[r for r in p.rows if r[9]]
        self.assertEqual([(r[7],r[10]) for r in responses],[(0,15),(0,15),(0,15),(1,15)])
    def test_reset_cancels_work_and_restart_has_no_old_result(self):
        p=P.Plan(8);p.cycle(rst=0);p.cycle(req=(0,7,8,1,1));p.cycle(rst=0);p.transfer(1,0x55,0xff)
        self.assertEqual([r[10] for r in p.rows if r[9]],[0xaa])
    def test_random_stimulus_reproduces_with_seed(self):
        self.assertEqual(P.vectors(8,17,8,True),P.vectors(8,17,8,True));self.assertNotEqual(P.vectors(8,17,8,True),P.vectors(8,18,8,True))
    def test_counter_merge_is_additive_and_rejects_different_inventory(self):
        a=self.fixture();b=self.fixture();first=next(iter(b));b[first]['count']=7
        self.assertEqual(P.merge_counts([a,b])[first],9)
        del b[first]
        with self.assertRaisesRegex(ValueError,'incompatible'):P.merge_counts([a,b])
        with self.assertRaisesRegex(ValueError,'empty'):P.merge_counts([])
    def test_native_parser_rejects_duplicate_foreign_or_malformed_records(self):
        row="C '\x01f\x02"+str(P.RTL)+"\x01t\x02line\x01l\x021\x01n\x021\x01o\x02block' 1\n"
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'coverage.dat';path.write_text(row);self.assertEqual(len(P.read_native(path)),1)
            for bad in (row+row,row.replace(str(P.RTL),'/other.sv'),row.replace("' 1","' -1"),''):
                path.write_text(bad)
                with self.assertRaises(ValueError):P.read_native(path)
    def test_missing_instrumentation_or_changed_point_identity_fails(self):
        points=self.fixture();contract=self.contract(points)
        changed=dict(points);key=next(iter(changed));del changed[key]
        with self.assertRaisesRegex(ValueError,'CODE_INVENTORY'):P.validate_inventory(changed,contract)
        changed=dict(points);changed[key+'unexpected']=changed.pop(key)
        with self.assertRaisesRegex(ValueError,'CODE_INVENTORY'):P.validate_inventory(changed,contract)
        with tempfile.TemporaryDirectory() as tmp:
            source=Path(tmp)/'input';source.write_text('original')
            manifest=Path(tmp)/'manifest.json';manifest.write_text(json.dumps({'source_sha256':{str(source):P.hashlib.sha256(source.read_bytes()).hexdigest()}}))
            P.check_sources(manifest);source.write_text('changed')
            with self.assertRaisesRegex(ValueError,'source changed'):P.check_sources(manifest)
    def test_zero_required_points_and_empty_metrics_do_not_pass(self):
        points=self.fixture();contract=self.contract(points);points[next(iter(points))]['count']=0
        with self.assertRaisesRegex(ValueError,'CODE_UNCOVERED'):P.require_covered(points,contract)
        contract['not_required']=dict.fromkeys(points,'exclude everything')
        with self.assertRaisesRegex(ValueError,'CODE_UNCOVERED'):P.require_covered(points,contract)
    def test_coverage_success_does_not_override_functional_failure(self):
        points=self.fixture();P.require_covered(points,self.contract(points))
        with tempfile.TemporaryDirectory() as tmp:
            wave=Path(tmp)/'wave.vcd';wave.write_text('$enddefinitions $end\n')
            log='COUNT steps=1\nCHECK_FAIL CODE_DATA\nRESULT FAIL checks=1 failures=1\n'
            ex=dict(error=None,returncode=1)
            with self.assertRaisesRegex(ValueError,'functional'):P.check_simulation(ex,log,[[0]],wave)
            P.check_simulation(ex,log,[[0]],wave,expect_data_error=True)
    def test_real_native_merge_annotation_and_negative_controls(self):
        if not (shutil.which('verilator') and shutil.which('verilator_coverage')):self.skipTest('Verilator required')
        with tempfile.TemporaryDirectory() as tmp:
            out=Path(tmp)/'out'
            r=subprocess.run([sys.executable,str(P.HERE/'run.py'),'--configuration','width8','--out',str(out)],capture_output=True,text=True,timeout=120)
            self.assertEqual(r.returncode,0,r.stdout+r.stderr)
            self.assertTrue(read_json(out/'summary.json')['success'])
            records=read_json(out/'executions.json');self.assertEqual(sum(r['credited'] for r in records),2)
            self.assertTrue(all(not r['credited'] for r in records if r['mode']!='normal'))
            metrics=read_json(out/'width8-coverage.json')['metrics'];self.assertEqual(set(metrics),P.KINDS)
            self.assertTrue(all(not p['missing'] for p in metrics.values()))
            self.assertTrue((out/'width8-annotated/command_unit.sv').is_file())

if __name__=='__main__':unittest.main()

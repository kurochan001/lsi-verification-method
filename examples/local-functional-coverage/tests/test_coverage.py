from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'local-common'))
from local_test_support import load_example,read_json
P=load_example('local-functional-coverage')

class CoverageTests(unittest.TestCase):
    def fixture(self,example='sha256'):
        source=P.HERE/'tb'/f'{example}.sv'
        return ''.join("C '\x01t\x02covergroup\x01f\x02"+str(source)+"\x01h\x02"+name+('\x01cross\x021' if cross else '')+"' 2\n" for name,cross in P.inventory(example).items())

    def test_fixed_plans_hit_every_required_bin_in_every_configuration(self):
        args=SimpleNamespace(profile='smoke',seed=17)
        self.assertEqual({n:len(P.inventory(n)) for n in P.EXAMPLES},{'dram':18,'sha256':17,'packet-switch':14})
        for name,directory in P.EXAMPLES.items():
            plugin=load_example(directory)
            for config,parameters in plugin.CONFIGS.items():
                rows=P.plans(name,plugin,args,parameters)[0][1]
                counts=P.expected_bins(name,rows)
                self.assertTrue(all(n>0 for n in counts.values()),(name,config,counts))
                self.assertTrue(any('_x_' in n for n in counts))

    def test_length_boundary_classification_and_response_cross_counts(self):
        rows=[]
        for n in (0,54,55,56,63,64,65,118,119,120,127):rows.append([1,1,n,0,0,1,1,0,0,0,0])
        for error in (0,1):
            for ready in (0,1):rows.append([1,0,0,0,0,ready,0,0,1,error,0])
        c=P.expected_bins('sha256',rows)
        self.assertEqual(c['lengths.length.short_message'],1)
        self.assertEqual(c['lengths.length.above_block'],2)
        self.assertEqual(c['lengths.length.rejected'],2)
        self.assertEqual(c['responses.result_ready.rejected_x_held'],1)
        self.assertEqual(c['responses.ready_state.accepted'],2)

    def test_native_parser_preserves_full_inventory_and_cross_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'coverage.dat';path.write_text(self.fixture())
            self.assertEqual(P.native(path,'sha256'),dict.fromkeys(P.inventory('sha256'),2))

    def test_missing_duplicate_unknown_and_malformed_native_bins_fail(self):
        good=self.fixture();lines=good.splitlines(True)
        for bad in (''.join(lines[1:]),good+lines[0],good.replace('lengths.length.empty','lengths.length.unknown'),good.replace("' 2\n","' -1\n",1)):
            with self.subTest(bad=bad[:100]),tempfile.TemporaryDirectory() as tmp:
                path=Path(tmp)/'coverage.dat';path.write_text(bad)
                with self.assertRaises(ValueError):P.native(path,'sha256')

    def test_wrong_source_or_cross_metadata_cannot_supply_coverage(self):
        for bad in (self.fixture().replace('sha256.sv','other.sv'),self.fixture().replace('\x01cross\x021','')):
            with self.subTest(bad=bad[:100]),tempfile.TemporaryDirectory() as tmp:
                path=Path(tmp)/'coverage.dat';path.write_text(bad)
                with self.assertRaisesRegex(ValueError,'NATIVE_IDENTITY'):P.native(path,'sha256')

    def test_zero_or_wrong_positive_counts_fail_even_with_all_bin_names(self):
        expected=dict.fromkeys(P.inventory('sha256'),2)
        for value,label in ((0,'NATIVE_COVERAGE'),(3,'NATIVE_COUNTS')):
            bad=dict(expected);bad[next(iter(bad))]=value
            with self.assertRaisesRegex(ValueError,label):P.validate_bins('sha256',bad,expected)

    def test_functional_failure_and_wrong_completion_cannot_credit_bins(self):
        rows=[[0]];normal='COUNT steps=1\nRESULT PASS checks=1\n'
        with tempfile.TemporaryDirectory() as tmp:
            wave=Path(tmp)/'wave.vcd';wave.write_text('$enddefinitions $end\n')
            P.checked_execution({'error':None,'returncode':0},normal,rows,wave)
            for ex,log in (({'error':None,'returncode':-6},normal),({'error':None,'returncode':0},normal.replace('steps=1','steps=2')),({'error':None,'returncode':0},normal+'COUNT steps=1\n')):
                with self.assertRaises(ValueError):P.checked_execution(ex,log,rows,wave)

    def test_real_native_bins_and_sampling_diagnostics(self):
        if not shutil.which('verilator'):self.skipTest('Verilator required')
        with tempfile.TemporaryDirectory() as tmp:
            out=Path(tmp)/'out'
            r=subprocess.run([sys.executable,str(P.HERE/'run.py'),'--example','packet-switch','--out',str(out)],capture_output=True,text=True,timeout=120)
            self.assertEqual(r.returncode,0,r.stdout+r.stderr)
            summary=read_json(out/'summary.json');self.assertTrue(summary['success']);self.assertEqual(summary['planned'],12)
            records=read_json(out/'executions.json')
            self.assertEqual(sum(r['credited'] for r in records),4)
            self.assertEqual(sum(r['diagnostic'] for r in records),4)
            self.assertTrue(all(not r['credited'] for r in records if r['diagnostic']))
            self.assertTrue(all(r['success'] for r in records))

if __name__=='__main__':unittest.main()

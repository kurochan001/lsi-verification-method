"""Exercise the HDL comparison and its negative/four-state checking paths."""
import importlib.util
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

HERE=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('tmr_comparison_runner',HERE/'run.py')
R=importlib.util.module_from_spec(spec);spec.loader.exec_module(R)


@unittest.skipUnless(shutil.which('iverilog') and shutil.which('vvp'),'Icarus Verilog required')
class ComparisonTests(unittest.TestCase):
    def simulate(self,width=8,seed=17,mutation=0,x_probe=False):
        with tempfile.TemporaryDirectory() as name:
            d=Path(name);binary=d/'comparison.vvp';top='tmr_compare_tb';extra=[]
            if x_probe:
                top='x_probe'
                harness=d/'x_probe.sv'
                harness.write_text("`timescale 1ns/1ps\nmodule x_probe;\n"
                                   "tmr_compare_tb #(.WIDTH(8)) tb();\n"
                                   "initial begin #90; force tb.auto_repair.q0='x; end\nendmodule\n")
                extra=[harness]
            command=['iverilog','-g2012','-s',top,'-o',str(binary)]
            if not x_probe:
                command += [f'-Ptmr_compare_tb.WIDTH={width}',f'-Ptmr_compare_tb.MUTATION={mutation}']
            built=subprocess.run([*command,*map(str,R.COMPARE_SOURCES+extra)],capture_output=True,text=True,timeout=30)
            self.assertEqual(built.returncode,0,built.stdout+built.stderr)
            return subprocess.run(['vvp',str(binary),f'+SEED={seed}','+STEPS=12'],
                                  capture_output=True,text=True,timeout=30)

    def test_all_widths_complete_with_seed_zero(self):
        for width in R.COMPARE_WIDTHS:
            with self.subTest(width=width):
                result=self.simulate(width,seed=0)
                self.assertEqual(result.returncode,0,result.stdout+result.stderr)
                counts=R.comparison_completion(result.stdout,width,12)['counts']
                self.assertEqual(counts['single_trials'],3*width)
                self.assertIn('PASS stuck_at value=0',result.stdout)
                self.assertIn('PASS stuck_at value=1',result.stdout)

    def test_seed_replays_and_another_seed_changes_random_trace(self):
        runs=[self.simulate(seed=seed) for seed in (17,17,18)]
        for run in runs:self.assertEqual(run.returncode,0,run.stdout+run.stderr)
        traces=[re.findall(r'^RANDOM .*$',run.stdout,re.M) for run in runs]
        self.assertEqual(len(traces[0]),12)
        self.assertEqual(traces[0],traces[1])
        self.assertNotEqual(traces[0],traces[2])

    def test_broken_vote_repair_and_diagnosis_fail_with_context(self):
        for mutation in (1,2,4):
            with self.subTest(mutation=mutation):
                result=self.simulate(mutation=mutation)
                self.assertNotEqual(result.returncode,0)
                for token in ('CHECK_FAIL TMR_COMPARE','seed=17 cycle=','configuration=',
                              'last_masks','expected=','vote_only q0=','auto_repair q0='):
                    self.assertIn(token,result.stdout)
                self.assertNotIn('RESULT PASS',result.stdout)

    def test_unknown_internal_state_is_a_failure(self):
        result=self.simulate(x_probe=True)
        self.assertNotEqual(result.returncode,0)
        self.assertIn('CHECK_FAIL TMR_COMPARE internal state',result.stdout)
        self.assertRegex(result.stdout,r'auto_repair q0=x+')


class ComparisonEvidenceTests(unittest.TestCase):
    def test_completion_rejects_missing_duplicate_and_zero_evidence(self):
        log=('EXPECTED_LIMITATION same_bit_two_lanes detail\n'
             'EXPECTED_LIMITATION wrong_repair detail\n'
             'EXPECTED_LIMITATION three_lanes_same_error detail\n'
             'COUNT normal_patterns=4\nCOUNT single_trials=24\nCOUNT multi_trials=2\n'
             'COUNT limit_trials=3\nCOUNT stuck_trials=2\nCOUNT random_steps=12\n'
             'RESULT PASS checks=100\n')
        self.assertEqual(R.comparison_completion(log,8,12)['checks'],100)
        for bad in (log.replace('RESULT PASS checks=100','RESULT PASS checks=0'),
                    log+'RESULT PASS checks=100\n',log+'CHECK_FAIL hidden\n',
                    log.replace('COUNT stuck_trials=2\n',''),
                    log+'COUNT stuck_trials=2\n',
                    log.replace('EXPECTED_LIMITATION wrong_repair detail\n','')):
            with self.assertRaises(ValueError):R.comparison_completion(bad,8,12)


if __name__=='__main__':unittest.main()

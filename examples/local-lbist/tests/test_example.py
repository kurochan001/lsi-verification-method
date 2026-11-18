from pathlib import Path
import tempfile
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'local-common'))
from local_test_support import load_example, simulate_vectors, run_example, assert_evidence
from system_test_support import SystemContract

P=load_example('local-lbist')


class LbistTests(SystemContract,unittest.TestCase):
    EXAMPLE='local-lbist'
    GOALS=17

    def test_real_rtl_all_configurations_and_mutants(self):
        with tempfile.TemporaryDirectory() as tmp:
            out=Path(tmp)/'out'; result=run_example(self.EXAMPLE,out,'--iterations','2')
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            assert_evidence(self,out,P.CONFIGS,self.GOALS,14,diagnostics=2)

    def test_nonzero_prpg_has_full_period_for_every_seed(self):
        for seed in range(1,256):
            seen=set(); value=seed
            for _ in range(255):
                self.assertNotIn(value,seen); self.assertNotEqual(value,0)
                seen.add(value); value=P.M.prpg_step(value)
            self.assertEqual(value,seed)
        self.assertEqual(P.M.prpg_step(0),0)

    def test_known_signatures_for_both_lengths(self):
        for count, expected in ((16,(0x62,0x46,0x65)),(32,(0x04,0xc0,0xbc))):
            for seed, signature in zip((1,0x5a,0xa7),expected):
                self.assertEqual(P.M.signature(seed,count),signature)
                plan=P.Plan(count); plan.cycle(reset=0); plan.transaction(seed=seed)
                self.assertEqual(plan.sig,signature)
                result=simulate_vectors(P,plan.rows,{'PATTERNS':count})
                self.assertEqual(result.returncode,0,result.stdout)

    def test_truth_table_and_all_eight_faults_on_rtl(self):
        plan=P.Plan(16); plan.cycle(reset=0)
        for fault in (None,*P.M.FAULTS):
            for value in range(16):
                plan.cycle(mode=0,normal=value,fault=fault)
        result=simulate_vectors(P,plan.rows,{'PATTERNS':16})
        self.assertEqual(result.returncode,0,result.stdout)
        for count in (16,32):
            good=P.M.signature(1,count)
            self.assertTrue(all(P.M.signature(1,count,f)!=good for f in P.M.FAULTS))

    def test_alias_changes_raw_responses_but_not_final_signature_on_rtl(self):
        for count in (16,32):
            good=P.M.responses(1,count); alias=P.M.responses(1,count,alias=True)
            self.assertEqual(sum(a!=b for a,b in zip(good,alias)),2)
            self.assertEqual(P.M.signature(1,count),P.M.signature(1,count,alias=True))
            plan=P.vectors(17,0,count,alias=True)
            self.assertEqual(plan.counts()['alias_changes'],2)
            result=simulate_vectors(P,plan.rows,{'PATTERNS':count})
            self.assertEqual(result.returncode,0,result.stdout)
            self.assertIn('COUNT alias_changes=2',result.stdout)

    def test_two_response_errors_can_cancel_for_every_initial_misr(self):
        for initial in range(256):
            good=P.M.compact(P.M.compact(initial,9),4)
            bad=P.M.compact(P.M.compact(initial,9^1),4^2)
            self.assertEqual(good,bad)

    def test_checker_rejects_test_response_leaking_to_functional_output(self):
        plan=P.vectors(17,0,16)
        result=simulate_vectors(P,plan.rows,{'PATTERNS':16},replacements={
            'lbist.sv':[('assign normal_out = test_mode ? 4\'b0000 : logic_response;',
                         'assign normal_out = logic_response;')]})
        self.assertNotEqual(result.returncode,0)
        self.assertIn('CHECK_FAIL LBIST_ISOLATION',result.stdout)

    def test_checker_rejects_comparison_before_final_response(self):
        plan=P.vectors(17,0,16)
        result=simulate_vectors(P,plan.rows,{'PATTERNS':16},replacements={
            'lbist.sv':[('next_signature!=expected_latched','signature!=expected_latched')]})
        self.assertNotEqual(result.returncode,0)
        self.assertIn('CHECK_FAIL LBIST_RESULT',result.stdout)


if __name__=='__main__':unittest.main()

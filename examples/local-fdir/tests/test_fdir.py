import importlib.util
from itertools import combinations
from pathlib import Path
import unittest
HERE=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('fdir_unit_cases',HERE/'cases.py');C=importlib.util.module_from_spec(spec);spec.loader.exec_module(C);M=C.M
PARS=[dict(DEPTH=4,WD_LIMIT=5,TRIP=3),dict(DEPTH=8,WD_LIMIT=9,TRIP=2)]

class EccTests(unittest.TestCase):
    def test_known_codewords_and_minimum_distance(self):
        self.assertEqual(M.CODES[:2],(0,0x1007));self.assertEqual(min((a^b).bit_count() for a,b in combinations(M.CODES,2)),4)
    def test_all_single_faults_correct_and_double_faults_detect(self):
        for value,code in enumerate(M.CODES):
            for b in range(13):self.assertEqual(M.decode(code^(1<<b)),(value,1,0,code))
            for a,b in combinations(range(13),2):self.assertEqual(M.decode(code^(1<<a)^(1<<b))[1:3],(0,1))
    def test_outside_guarantee_has_miscorrection_and_undetected_values(self):
        self.assertEqual(M.decode(7)[:3],(1,1,0));self.assertEqual(M.decode(M.CODES[1])[:3],(1,0,0))

class CampaignTests(unittest.TestCase):
    def test_all_campaigns_drain_and_account_for_every_admission(self):
        for p in PARS:
            for name in (*C.NAMES,'random'):
                rows,oracle,n=C.make(name,p)
                self.assertEqual(n['rows'],len(rows));self.assertEqual(len(rows),len(oracle));self.assertEqual(n['accepted'],n['commits']+n['cancels']+n['reset_cancels']+n['rejected']);self.assertEqual(oracle[-1][0],1)
    def test_single_faults_do_not_enter_safe(self):
        for p in PARS:
            for name in ('single-bit','scrub','write-upset','scrub-write-collision'):
                rows,oracle,n=C.make(name,p);self.assertTrue(all(o[0] in (0,1) for o in oracle));self.assertEqual(n['cancels'],0)
    def test_fatal_fault_cancels_pending_and_ack_does_not_recover(self):
        for p in PARS:
            rows,oracle,n=C.make('watchdog',p);self.assertEqual(n['cancels'],1);self.assertEqual(n['recoveries'],1)
            self.assertTrue(any(o[0]==2 and o[1]==4 and o[2]==0 for o in oracle))
    def test_recovery_reads_last_word_and_requires_maintenance(self):
        for p in PARS:
            rows,oracle,n=C.make('recovery-ecc',p);self.assertEqual(n['failures'],1);self.assertEqual(n['recoveries'],1);self.assertEqual(n['cancels'],1)
    def test_config_mismatch_blocks_recovery_until_rewritten(self):
        for p in PARS:
            rows,oracle,n=C.make('recovery-cfg',p);self.assertTrue(any(o[0]==2 and o[12] for o in oracle));self.assertEqual(n['recoveries'],1);self.assertEqual(oracle[-1][9],60)
    def test_reset_cancels_without_counting_as_commit(self):
        rows,oracle,n=C.make('reset-pending',PARS[0]);self.assertEqual((n['reset_cancels'],n['resets'],n['commits']),(1,1,1));self.assertEqual(oracle[-1][9],0)
    def test_sequence_wrap_is_exercised(self):
        rows,oracle,n=C.make('sequence-wrap',PARS[0]);self.assertEqual(n['commits'],261);self.assertEqual(oracle[-1][3],5)
    def test_write_upset_preserves_new_payload(self):
        rows,oracle,n=C.make('write-upset',PARS[0]);self.assertEqual(oracle[-1][9],123)
    def test_simultaneous_causes_are_retained(self):
        for p in PARS:
            rows,oracle,n=C.make('simultaneous',p);self.assertTrue(any(o[0]==2 and o[1]==5 and o[2]==1 for o in oracle));self.assertEqual(n['cancels'],1)
    def test_random_inputs_are_reproducible(self):
        self.assertEqual(C.make('random',PARS[0],17),C.make('random',PARS[0],17));self.assertNotEqual(C.make('random',PARS[0],17)[0],C.make('random',PARS[0],18)[0])
if __name__=='__main__':unittest.main()

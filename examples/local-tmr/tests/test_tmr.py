import importlib.util
from pathlib import Path
import unittest
HERE=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('tmr_unit_runner',HERE/'run.py');R=importlib.util.module_from_spec(spec);spec.loader.exec_module(R)

class VoterTests(unittest.TestCase):
    def test_all_single_lane_bit_positions_preserve_data(self):
        for width in (8,16):
            for value in (0,0x55,0xaa,(1<<width)-1):
                for lane in range(3):
                    for mask in [*[1<<i for i in range(width)],(1<<width)-1]:
                        m=R.M.Register(width);m.step([1,1,value,0,0,0,0]);fault=[0,0,0];fault[lane]=mask
                        out=m.step([1,0,0,0,*fault]);self.assertEqual(out[:2],[value,1]);self.assertEqual(m.step([1,0,0,1,0,0,0])[:3],[value,0,1])
    def test_two_matching_faults_can_vote_wrong_and_repair_wrong(self):
        m=R.M.Register();self.assertEqual(m.step([1,0,0,0,1,1,0])[:2],[1,1]);self.assertEqual(m.step([1,0,0,1,0,0,0])[:2],[1,0])
    def test_common_cause_is_not_detected(self):self.assertEqual(R.M.Register().step([1,0,0,0,2,2,2])[:2],[2,0])
    def test_reset_dominates_write_repair_and_faults(self):self.assertEqual(R.M.Register().step([0,1,255,1,255,255,255]),[0]*6)
    def test_write_wins_and_injection_changes_new_state(self):
        m=R.M.Register();m.step([1,0,0,0,1,0,0]);self.assertEqual(m.step([1,1,0xaa,1,0,0,1]),[0xaa,1,0,0xaa,0xaa,0xab])
    def test_stimulus_is_reproducible_and_has_active_reset(self):
        a=R.stimuli(8,17);self.assertEqual(a,R.stimuli(8,17));self.assertNotEqual(a,R.stimuli(8,18));self.assertEqual(R.expected(a,8)[1]['resets'],1)
    def test_completion_rejects_missing_extra_and_duplicate_counts(self):
        for log in ('COUNT rows=1\n','COUNT rows=1\nCOUNT rows=1\n','COUNT rows=1\nCOUNT extra=0\n'):
            with self.assertRaises(ValueError):R.S.completion(log,dict(rows=2))
        self.assertEqual(R.S.completion('COUNT rows=2\n',dict(rows=2)),dict(rows=2))
if __name__=='__main__':unittest.main()

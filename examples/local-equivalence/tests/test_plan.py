from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'local-common'))
from local_test_support import load_example
P=load_example('local-equivalence')
class PlanTest(unittest.TestCase):
    def test_normal_proof_and_mutants_have_different_invariant_scopes(self):
        plan=P.plan(12,0);self.assertEqual(len(plan),8)
        self.assertEqual(plan[0]['mode'],'prove');self.assertEqual(plan[0]['parameters']['AUXILIARY'],1)
        for case in plan[2:6]:
            self.assertEqual(case['mode'],'bmc');self.assertEqual(case['expect'],'FAIL')
            self.assertEqual(case['parameters']['AUXILIARY'],0)
    def test_normal_covers_use_original_rtl_and_diagnostics_stay_separate(self):
        plan=P.plan(12,4)
        self.assertEqual(plan[0]['parameters']['MUTATION'],4)
        self.assertEqual(plan[1]['parameters']['MUTATION'],0)
        self.assertEqual(plan[-1]['category'],'diagnostic')
        self.assertEqual(plan[-1]['parameters']['LOCK_RESET'],1)
if __name__=='__main__':unittest.main()

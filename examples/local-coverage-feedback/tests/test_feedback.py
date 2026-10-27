from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'local-common'))
from local_test_support import load_example
P=load_example('local-coverage-feedback');AXIS=load_example('local-axis')
class FeedbackTests(unittest.TestCase):
    def test_seed_and_exact_budget(self):
        first=P.random_rows(AXIS,17,128);self.assertEqual(first,P.random_rows(AXIS,17,128));self.assertEqual(len(first),128)
        self.assertNotEqual(first,P.random_rows(AXIS,18,128))
    def test_targets_fit_and_unknown_goal_is_rejected(self):
        _,required=P.E.C.catalog(P.HERE.parent/'local-axis/requirements.json')
        self.assertEqual(len(P.target_rows(AXIS,sorted(required),17,128)),128)
        with self.assertRaises(ValueError):P.target_rows(AXIS,['not-a-goal'],17,128)
    def test_insufficient_target_budget_is_rejected(self):
        with self.assertRaises(ValueError):P.target_rows(AXIS,['reset/partial-output'],17,1)
    def test_feedback_uses_only_successful_observations(self):
        class Simulator:
            plugin=AXIS
            def execute(self,*args):return dict(id=args[0],status='error',coverage=['fake'])
        result=P.comparison(Simulator(),'feedback',17,2,{'keep/full'})
        self.assertFalse(result['success']);self.assertEqual(result['goals'],[]);self.assertEqual(result['checks'],256)
        self.assertEqual(result['decisions'][1]['mode'],'targeted')
if __name__=='__main__':unittest.main()

from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'local-common'))
from local_test_support import load_example
P=load_example('local-progress')
class PlanTest(unittest.TestCase):
    def test_bounded_ready_assumption_is_explicit(self):
        plan=P.plan(24,0);self.assertEqual(len(plan),8)
        self.assertIn('as_receiver_fair',P.properties({},plan[0])['assume'])
        self.assertIn('ap_accept',P.properties({},plan[0])['assert'])
    def test_unfair_safety_and_missing_fairness_have_different_claims(self):
        safety,counterexample=P.plan(24,0)[-2:]
        self.assertNotIn('as_receiver_fair',P.properties({},safety)['assume'])
        self.assertNotIn('ap_completion',P.properties({},safety)['assert'])
        self.assertEqual(counterexample['category'],'counterexample');self.assertEqual(counterexample['failure'],'ap_completion')
        self.assertIn('as_no_receiver',P.properties({},counterexample)['assume'])
    def test_diagnostics_do_not_inherit_demo_fault(self):
        plan=P.plan(24,4);self.assertEqual(plan[0]['parameters']['MUTATION'],4)
        self.assertEqual(plan[-1]['parameters']['MUTATION'],0);self.assertEqual(plan[1]['parameters']['MUTATION'],0)
if __name__=='__main__':unittest.main()

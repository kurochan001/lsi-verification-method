from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'local-common'))
from local_test_support import load_example
P=load_example('local-axi4-formal')
class PlanTest(unittest.TestCase):
    def test_control_proof_data_bmc_and_concurrent_cover_are_distinct(self):
        plan=P.plan(12,0);self.assertEqual(len(plan),9)
        proof,data,cover=plan[:3]
        self.assertEqual((proof['mode'],proof['parameters']['CHECK_DATA']),('prove',0))
        self.assertEqual((data['mode'],data['parameters']['SERIAL_DATA']),('bmc',1))
        self.assertEqual((cover['mode'],cover['parameters']['SERIAL_DATA']),('cover',0))
        props=P.properties({},data)
        self.assertIn('as_serial_aw',props['assume']);self.assertIn('ap_data',props['assert'])
        self.assertNotIn('as_serial_aw',P.properties({},cover)['assume'])
    def test_each_mutant_targets_ids_last_or_data(self):
        cases=P.plan(12,0)[3:7]
        self.assertEqual([c['failure'] for c in cases],['ap_data','ap_ids','ap_last','ap_data'])
        self.assertTrue(all(c['parameters']['AUXILIARY']==0 for c in cases))
    def test_all_configurations_and_assumptions_are_explicit(self):
        self.assertEqual({v['MEM_BYTES'] for v in P.CONFIGS.values()},{16,32})
        plan=P.plan(12,1)
        self.assertEqual(plan[0]['parameters']['MUTATION'],1)
        self.assertEqual(plan[2]['parameters']['MUTATION'],0)
        self.assertNotIn('as_lock_reset',P.properties({},plan[0])['assume'])
        self.assertIn('as_lock_reset',P.properties({},plan[-1])['assume'])
if __name__=='__main__':unittest.main()

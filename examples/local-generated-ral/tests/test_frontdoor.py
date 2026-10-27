from pathlib import Path
import sys,unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'local-common'))
from local_test_support import load_example
P=load_example('local-generated-ral')
class FrontdoorTests(unittest.TestCase):
 def test_native_report_requires_counts_goals_and_severities(self):
  log='COUNT transactions=14\nCOUNT reads=9\nCOUNT writes=5\nCOUNT errors=2\nUVM_ERROR : 0\nUVM_FATAL : 0\nUVM_WARNING : 5\nUVM_WARNING x [NO_DPI_USED]\nUVM_WARNING x [NO_VISIT_CHECK]\n'+'UVM_WARNING x [UVM/FLD/GET_MIRRORED_VAL/VOL]\n'*3+''.join('COVER '+g+'\n' for g in P.GOALS)
  self.assertTrue(P.native_counts(log,1));self.assertFalse(P.native_counts(log+'COUNT reads=9\n',1));self.assertFalse(P.native_counts(log.replace('UVM_ERROR : 0','UVM_ERROR : 1'),1))
 def test_missing_goal_cannot_pass(self):
  self.assertFalse(P.native_counts('RESULT PASS checks=36\n',12))
if __name__=='__main__':unittest.main()

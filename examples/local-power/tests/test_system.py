from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'local-common'))
from local_test_support import load_example
from system_test_support import SystemContract
P=load_example('local-power')

class SystemTest(SystemContract,unittest.TestCase):
    EXAMPLE='local-power';GOALS=10

    def test_retention_and_drain_preserve_completed_operations(self):
        p=P.Plan(3);p.cycle(rst=0);p.operation(0x31);p.nap(1,pending=True)
        self.assertEqual(p.model.acc,0x38)
        self.assertIsNone(p.model.due)
        p.nap(0);self.assertEqual(p.model.acc,0)

    def test_sleep_refuses_new_work_and_reset_clears_saved_state(self):
        p=P.Plan(1);p.cycle(rst=0);p.operation(0x55)
        r=p.cycle(sleep=1,retain=1,valid=1,data=1)
        self.assertEqual(r[6],0)
        p.idle(8,sleep=1);p.cycle(rst=0)
        self.assertEqual((p.model.acc,p.model.saved,p.model.mode),(0,0,0))

if __name__=='__main__':unittest.main()

from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'local-common'))
from local_test_support import load_example
from system_test_support import SystemContract
P=load_example('local-credit-link')
class CircuitTests(SystemContract,unittest.TestCase):
    EXAMPLE='local-credit-link';GOALS=10
    def test_blocked_source_holds_channel_and_data(self):
        p=P.Plan(2);p.cycle(rst=0)
        for i in range(10):p.cycle(valid=1,data=i)
        blocked=p.rows[-1];self.assertEqual(blocked[5],0)
        p.cycle(valid=0,channel=1,data=99);self.assertEqual(p.rows[-1][1:4],blocked[1:4])
        p.drain();self.assertIsNone(p.offer)
    def test_credit_conservation_and_invalid_returns(self):
        p=P.Plan(2);p.cycle(rst=0);p.cycle(returns=3);p.cycle();self.assertEqual(p.rows[-1][-1],1)
        p.cycle(valid=1,data=1);p.cycle();self.assertEqual(p.outstanding,[1,0])
        p.cycle(returns=1);self.assertEqual(p.outstanding,[0,0]);self.assertEqual(p.bad,0)

if __name__=='__main__':unittest.main()

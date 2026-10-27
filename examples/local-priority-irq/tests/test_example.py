from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'local-common'))
from local_test_support import load_example
from system_test_support import SystemContract
P=load_example('local-priority-irq')
class CircuitTests(SystemContract,unittest.TestCase):
    EXAMPLE='local-priority-irq';GOALS=12
    def test_claim_is_independent_of_irq_threshold_and_ties_use_low_id(self):
        p=P.Plan(1,1);p.cycle(rst=0)
        for i in range(4):p.transfer(32+4*i,1,2)
        p.transfer(0,1,15);p.transfer(4,1,2);p.pulse(15)
        self.assertEqual(p.cycle()[2],False);self.assertEqual(p.rows[-1][9],0)
        self.assertEqual(p.transfer(16),1);self.assertEqual(p.transfer(16),2)
    def test_service_blocks_edges_until_complete(self):
        p=P.Plan(0,0);p.cycle(rst=0);p.transfer(32,1,1);p.transfer(0,1,1);p.pulse(1)
        self.assertEqual(p.transfer(16),1);p.pulse(1);self.assertEqual(p.transfer(16),0)
        p.transfer(16,1,1);p.pulse(1);self.assertEqual(p.transfer(16),1)

if __name__=='__main__':unittest.main()

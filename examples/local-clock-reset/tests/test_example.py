from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'local-common'))
from local_test_support import load_example
from system_test_support import SystemContract
P=load_example('local-clock-reset')
class CircuitTests(SystemContract,unittest.TestCase):
    EXAMPLE='local-clock-reset';GOALS=10
    def test_release_needs_work_clock_edges(self):
        p=P.Plan(3,4);p.cycle(rst=0);p.idle(5);p.nap(True)
        rows=p.rows;self.assertTrue(any(r[7] and not r[8] and r[1] and not r[9] for r in rows))
        for r in rows:
            if r[6]:self.assertEqual((r[7],r[8],r[9]),(0,1,1))
    def test_pending_work_drains_before_stop(self):
        p=P.Plan(2,4);p.cycle(rst=0);p.idle(4);p.operation(35);p.nap()
        stopped=[r for r in p.rows if r[7]]
        self.assertTrue(stopped);self.assertEqual(stopped[0][10:],[35,1])

if __name__=='__main__':unittest.main()

from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'local-common'))
from local_test_support import load_example
from system_test_support import SystemContract
P=load_example('local-dsp')

class SystemTest(SystemContract,unittest.TestCase):
    EXAMPLE='local-dsp';GOALS=10

    def test_ties_round_away_from_zero(self):
        self.assertEqual(P.quantize(4,3),(1,0));self.assertEqual(P.quantize(-4,3),(255,0))
        self.assertEqual(P.quantize(3,3),(0,0));self.assertEqual(P.quantize(-3,3),(0,0))
    def test_signed_saturation_is_before_narrowing(self):
        for f in (3,4):
            self.assertEqual(P.quantize(127*(1<<f),f),(127,0));self.assertEqual(P.quantize(-128*(1<<f),f),(128,0))
        self.assertEqual(P.quantize(32768,4),(127,1));self.assertEqual(P.quantize(-32768,4),(128,1))
    def test_history_changes_only_on_accept_and_reset_clears_it(self):
        p=P.Plan(3,1);p.cycle(rst=0);p.operation(7,0,0);p.operation(0,0,8)
        values=[r[8] for r in p.rows if r[7] and r[5]];self.assertEqual(values,[0,7])
        p.cycle(rst=0);p.operation(0,0,127)
        self.assertEqual([r[8] for r in p.rows if r[7] and r[5]][-1],0)

if __name__=='__main__':unittest.main()

from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'local-common'))
from local_test_support import load_example
from system_test_support import SystemContract
P=load_example('local-width-converter')
class CircuitTests(SystemContract,unittest.TestCase):
    EXAMPLE='local-width-converter';GOALS=15
    def test_error_does_not_roll_back_other_half(self):
        p=P.Plan();p.op(1,0,0x1122334455667788,error=4);p.op(2,0)
        self.assertEqual(p.rows[-1][8],0x55667788);self.assertEqual(p.rows[0][9],2)
    def test_zero_strobes_and_interrupted_write(self):
        p=P.Plan();p.op(1,0,0xffffffffffffffff,strb=0)
        self.assertEqual(p.rows[-1][-1],0);self.assertFalse(any(p.memory))
        p.op(3,0,0x12345678aabbccdd);p.op(2,0)
        self.assertEqual(p.rows[-1][8],0xaabbccdd)

if __name__=='__main__':unittest.main()

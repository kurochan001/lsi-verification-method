from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'local-common'))
from local_test_support import load_example
from system_test_support import SystemContract
P=load_example('local-interconnect')

class SystemTest(SystemContract,unittest.TestCase):
    EXAMPLE='local-interconnect';GOALS=12

    def test_byte_strobes_preserve_other_bytes(self):
        p=P.Plan();p.batch(P.request(1,0,seed=0x11223344))
        p.batch(P.request(1,0,seed=0xaabbccdd,mode=1));p.batch(P.request(2,0))
        self.assertEqual(p.rows[-1][10],0x11bb33dd)
        p.batch(P.request(1,0,seed=0,mode=2));p.batch(P.request(2,0))
        self.assertEqual(p.rows[-1][10],0x11bb33dd)

    def test_cross_master_collisions_are_explicitly_excluded(self):
        with self.assertRaises(ValueError):P.Plan().batch(P.request(1,0),P.request(2,0))

    def test_unmapped_and_illegal_boundary_have_different_responses(self):
        p=P.Plan();p.batch(P.request(2,16384),P.request(2,4092,2))
        self.assertEqual((p.rows[-1][9],p.rows[-1][23]),(3,2))

if __name__=='__main__':unittest.main()

from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'local-common'))
from local_test_support import load_example
from system_test_support import SystemContract
P=load_example('local-access-control')
class CircuitTests(SystemContract,unittest.TestCase):
    EXAMPLE='local-access-control';GOALS=14
    def test_deny_preserves_secret_and_hides_read(self):
        p=P.Plan(0);p.cycle(rst=0);p.transfer(16,1,123);p.transfer(16,1,999,prot=3)
        self.assertEqual(p.values[16],123);p.transfer(16,prot=3)
        reads=[r for r in p.rows if r[1] and r[2] and not r[3] and r[4]==16]
        self.assertEqual(reads[-1][8:10],[1,0])
    def test_lock_only_reset_reopens(self):
        p=P.Plan(2);p.cycle(rst=0);p.transfer(20,1,1);p.transfer(20,1,0);p.transfer(16,1,99)
        self.assertEqual((p.values[20],p.values[16]),(1,0))
        p.cycle(rst=0);p.transfer(16,1,99);self.assertEqual(p.values[16],99)

if __name__=='__main__':unittest.main()

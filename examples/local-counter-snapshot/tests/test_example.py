from pathlib import Path
import sys,unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'local-common'))
from system_test_support import SystemContract
from local_test_support import load_example
P=load_example('local-counter-snapshot')
class ExampleTests(SystemContract,unittest.TestCase):
    EXAMPLE='local-counter-snapshot';GOALS=10
    def test_snapshot_survives_word_rollover(self):
        p=P.Plan(0);p.cycle(rst=0);p.load_count(0x5fffffffe);p.access(0);p.access(24,1,1)
        for _ in range(8):p.cycle()
        self.assertEqual(p.snap,5);self.assertEqual(p.count>>32,6)
    def test_low_write_is_staged(self):
        p=P.Plan(0);p.cycle(rst=0);p.access(8,1,0x12345678);self.assertEqual(p.count,0)
        p.access(12,1,2);self.assertEqual(p.count,0x212345678)
if __name__=='__main__':unittest.main()

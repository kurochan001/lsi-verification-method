from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'local-common'))
from local_test_support import load_example
from system_test_support import SystemContract
P=load_example('local-cache-dma')
class CircuitTests(SystemContract,unittest.TestCase):
    EXAMPLE='local-cache-dma';GOALS=15
    def test_clean_and_invalidate_make_dma_changes_visible(self):
        p=P.Plan(2,1);p.cycle(rst=0);p.command(2,0,0x11223344);self.assertEqual(p.memory[0],0)
        p.command(3,0);self.assertEqual(p.memory[0],0x11223344)
        p.command(6,0,0xaabbccdd);self.assertEqual(p.cache[0][1],0x11223344)
        p.command(4,0);p.command(1,0);self.assertEqual(p.cache[0][1],0xaabbccdd)
    def test_partial_bytes_and_dirty_invalidate_policy(self):
        self.assertEqual(P.merge(0x11223344,0xaabbccdd,5),0x11bb33dd)
        p=P.Plan(1,1);p.cycle(rst=0);p.command(2,0,7);p.command(4,0)
        self.assertIn(0,p.cache);self.assertTrue(p.cache[0][2]);self.assertEqual(p.memory[0],0)

if __name__=='__main__':unittest.main()

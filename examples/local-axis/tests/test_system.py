from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'local-common'))
from local_test_support import load_example
from system_test_support import SystemContract
P=load_example('local-axis')

class SystemTest(SystemContract,unittest.TestCase):
    EXAMPLE='local-axis';GOALS=11

    def test_full_fifo_can_pop_and_push_on_same_edge(self):
        m=P.Oracle(2);m.step([0,0,0,0,0,0]);m.step([1,1,1,15,0,0]);m.step([1,1,2,15,1,0])
        row=m.step([1,1,3,15,1,1]);self.assertEqual(row[6:11],[1,1,1,15,0])
        self.assertEqual(list(m.queue),[(2,15,1),(3,15,1)])
    def test_null_and_sparse_byte_lanes(self):
        self.assertEqual(P.mask(0),0);self.assertEqual(P.mask(5),0x00ff00ff)
        rows=P.boundary_vectors(2);self.assertTrue(any(r[7] and r[9]==0 for r in rows))
    def test_partial_packet_is_flushed_even_if_fifo_is_empty(self):
        p=P.Plan(2);p.cycle(rst=0);p.beat(1,15,0);p.drain()
        self.assertFalse(p.model.queue);self.assertTrue(p.model.out_open)
        self.assertEqual(p.cycle(rst=0)[11],1);self.assertFalse(p.model.out_open)

if __name__=='__main__':unittest.main()

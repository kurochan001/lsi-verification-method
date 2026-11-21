from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'local-common'))
from local_test_support import load_example
from system_test_support import SystemContract
P=load_example('local-descriptor-dma')
class CircuitTests(SystemContract,unittest.TestCase):
    EXAMPLE='local-descriptor-dma';GOALS=16
    def test_wrapping_ring_and_fault_prefix(self):
        row=P.row(4,3,4);self.assertEqual(row[7:],[4,0,0,4,15,4])
        row=P.row(4,3,4,fault=1,position=2);self.assertEqual(row[7:],[2,1,0,3,9,2])
    def test_write_error_keeps_committed_bytes_and_abort_does_not_write(self):
        row=P.row(4,0,4,fault=4,position=1);self.assertEqual(row[7:],[1,1,0,2,3,2])
        row=P.row(4,0,4,abort=2,position=1);self.assertEqual(row[7:],[1,0,1,2,1,2])
    def test_only_an_abort_after_the_start_write_lets_a_copy_read_out(self):
        # complete, error, aborted, fetches, written slots, copy read bursts
        for abort in (1,3,4,5):self.assertEqual(P.row(4,0,4,abort=abort,position=1)[7:],[1,0,1,2,1,1],abort)
        self.assertEqual(P.row(4,0,4,abort=2,position=1)[7:],[1,0,1,2,1,2])
        self.assertEqual(P.row(4,0,4,fault=3,position=1)[12],2);self.assertEqual(P.row(4,0,4,fault=2,position=1)[12],1)
        fixed=P.vectors(17,0,4,True);self.assertEqual(sorted({r[5] for r in fixed}),[0,1,2,3,4,5])
        self.assertEqual({r[5] for r in P.vectors(17,160,4)},{0,1,2,3,4,5})

if __name__=='__main__':unittest.main()

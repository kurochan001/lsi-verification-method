from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'local-common'))
from local_test_support import load_example
from system_test_support import SystemContract
P=load_example('local-descriptor-dma')
class CircuitTests(SystemContract,unittest.TestCase):
    EXAMPLE='local-descriptor-dma';GOALS=13
    def test_wrapping_ring_and_fault_prefix(self):
        row=P.row(4,3,4);self.assertEqual(row[7:],[4,0,0,4,15])
        row=P.row(4,3,4,fault=1,position=2);self.assertEqual(row[7:],[2,1,0,3,9])
    def test_write_error_keeps_committed_bytes_and_abort_does_not_write(self):
        row=P.row(4,0,4,fault=4,position=1);self.assertEqual(row[7:],[1,1,0,2,3])
        row=P.row(4,0,4,abort=2,position=1);self.assertEqual(row[7:],[1,0,1,2,1])

if __name__=='__main__':unittest.main()

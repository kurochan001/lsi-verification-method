from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'local-common'))
from local_test_support import load_example
from system_test_support import SystemContract
P=load_example('local-dma')

class SystemTest(SystemContract,unittest.TestCase):
    EXAMPLE='local-dma';GOALS=12

    def test_source_and_destination_boundary_splits(self):
        for a,b in ((4092,512),(64,4092)):
            row=P.vector(a,b,6)
            self.assertEqual(row[10:14],[6,6,3,3])

    def test_error_and_abort_have_distinct_partial_write_contracts(self):
        for fault,abort,written,read in ((1,0,0,4),(2,0,4,4),(0,1,0,4),(0,2,4,4)):
            row=P.vector(fault=fault,abort=abort)
            self.assertEqual(row[10:12],[written,read])
            self.assertEqual(row[8:10],[int(bool(fault)),int(bool(abort))])

    def test_invalid_configuration_has_no_bus_effects(self):
        for row in (P.vector(src=3),P.vector(dst=4),P.vector(src=8188,words=2),P.vector(words=33)):
            self.assertEqual(row[8:14],[1,0,0,0,0,0])
        # Each rejection rule needs a fixed row that breaks that rule alone; an unaligned
        # destination that also overlapped the source would be rejected by the overlap rule.
        def only(src,dst,words):
            return [bool(src%4),bool(dst%4),words>32,src+4*words>8192,dst+4*words>8192,
                    bool(words and src<dst+4*words and dst<src+4*words)]
        alone={tuple(only(*row[:3])) for row in P.boundary_vectors() if sum(only(*row[:3]))==1}
        self.assertEqual(len(alone),6,alone)

if __name__=='__main__':unittest.main()

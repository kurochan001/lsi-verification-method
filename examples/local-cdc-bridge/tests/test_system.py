from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'local-common'))
from local_test_support import load_example
from system_test_support import SystemContract
P=load_example('local-cdc-bridge')

class SystemTest(SystemContract,unittest.TestCase):
    EXAMPLE='local-cdc-bridge';GOALS=7

    def test_checksum_is_independent_of_clock_configuration(self):
        checksum,errors=P.expected(5,0x12345678)
        value=0x12345678;expected=0
        for tag,data,error in [(1,0,0),(2,value,0),(3,0x41504233,0),(4,0,1),(5,0,1)]:
            expected=((expected*33)^data^error^tag)&0xffffffff
        self.assertEqual((checksum,errors),(expected,2))

    def test_reset_prefix_is_flushed_and_counted_separately(self):
        row=P.vector(5,17,reset=2,stall=7)
        self.assertEqual(P.counts([row]),dict(requests=6,responses=5,apb=6,errors=2,flushes=1))

if __name__=='__main__':unittest.main()

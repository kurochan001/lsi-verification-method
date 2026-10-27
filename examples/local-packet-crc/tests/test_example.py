from pathlib import Path
import sys,unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'local-common'))
from system_test_support import SystemContract
from local_test_support import load_example
P=load_example('local-packet-crc')
class ExampleTests(SystemContract,unittest.TestCase):
    EXAMPLE='local-packet-crc';GOALS=8
    def test_known_crc_and_empty_message(self):
        self.assertEqual(P.reference(b'123456789',0),0xf4)
        self.assertEqual(P.reference(b'',0xff),0xff)
    def test_sparse_lanes_equal_message_bytes(self):
        p=P.Plan(0);p.cycle(rst=0);p.packet([(0x44332211,5)])
        self.assertEqual(p.rows[-2][10],P.reference([0x11,0x33],0))
if __name__=='__main__':unittest.main()

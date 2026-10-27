from pathlib import Path
import sys,unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'local-common'))
from system_test_support import SystemContract
from local_test_support import load_example
P=load_example('local-stream-dma')
class ExampleTests(SystemContract,unittest.TestCase):
    EXAMPLE='local-stream-dma';GOALS=12
    def test_error_residual_ranges(self):
        self.assertEqual(P.row(0,256,12,mode=1,position=1)[-1],4)
        self.assertEqual(P.row(1,256,12,mode=2,position=1)[-1],8)
        self.assertEqual(P.row(1,256,12,mode=3,position=1)[-1],4)
    def test_partial_and_invalid_requests(self):
        self.assertEqual(P.row(1,256,5)[-1],5)
        self.assertEqual(P.row(0,257,4)[6:], [1,0])
if __name__=='__main__':unittest.main()

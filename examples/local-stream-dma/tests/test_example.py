from pathlib import Path
import sys,unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'local-common'))
from system_test_support import SystemContract
from local_test_support import load_example,simulate_vectors
P=load_example('local-stream-dma')
class ExampleTests(SystemContract,unittest.TestCase):
    EXAMPLE='local-stream-dma';GOALS=13
    def test_error_residual_ranges(self):
        self.assertEqual(P.row(0,256,12,mode=1,position=1)[-1],4)
        self.assertEqual(P.row(1,256,12,mode=2,position=1)[-1],8)
        self.assertEqual(P.row(1,256,12,mode=3,position=1)[-1],4)
    def test_partial_and_invalid_requests(self):
        self.assertEqual(P.row(1,256,5)[-1],5)
        self.assertEqual(P.row(0,257,4)[6:], [1,0])
    def test_w_can_be_accepted_before_aw(self):
        for parameters in P.CONFIGS.values():
            with self.subTest(parameters=parameters):
                result=simulate_vectors(P,[P.row(1,512,5,mode=6),P.row(1,512,31,mode=6)],parameters)
                self.assertEqual(result.returncode,0,result.stdout+result.stderr)
                self.assertIn('COVER write/w-before-aw',result.stdout)
    def test_completion_without_b_response_is_rejected(self):
        result=simulate_vectors(P,[P.row(1,512,4)],replacements={'stream_dma.sv':[('state<=RESP;','finish(0);')]})
        self.assertNotEqual(result.returncode,0,result.stdout)
        self.assertIn('CHECK_FAIL STREAM_COUNT',result.stdout)

if __name__=='__main__':unittest.main()

from pathlib import Path
import sys,unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'local-common'))
from system_test_support import SystemContract
from local_test_support import load_example
P=load_example('local-mbist')
class ExampleTests(SystemContract,unittest.TestCase):
    EXAMPLE='local-mbist';GOALS=9
    def test_exact_march_length_and_directions(self):
        for depth in (8,16):
            trace=P.march(depth);self.assertEqual(len(trace),10*depth)
            self.assertEqual(trace[5*depth][0],depth-1);self.assertEqual(trace[-1],(depth-1,0,0))
    def test_fault_models_are_detectable(self):
        for fault in range(1,5):
            for kind in (0,1):self.assertEqual(P.oracle(8,fault,1,0,kind)[0],1)
if __name__=='__main__':unittest.main()

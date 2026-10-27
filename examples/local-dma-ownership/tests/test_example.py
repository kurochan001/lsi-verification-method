from pathlib import Path
import sys,unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'local-common'))
from system_test_support import SystemContract
from local_test_support import load_example
P=load_example('local-dma-ownership')
class ExampleTests(SystemContract,unittest.TestCase):
    EXAMPLE='local-dma-ownership';GOALS=11
    def test_completion_memory_digest_changes_with_reuse(self):
        self.assertNotEqual(P.row(2,turns=2)[-1],P.row(2,turns=3)[-1])
    def test_error_keeps_destination_unchanged(self):
        self.assertNotEqual(P.row(2,turns=1,invalid=0)[-1],P.row(2,turns=1,invalid=1)[-1])
if __name__=='__main__':unittest.main()

from pathlib import Path
import sys,unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'local-common'))
from system_test_support import SystemContract
from local_test_support import load_example,simulate_vectors
P=load_example('local-dma-ownership')
class ExampleTests(SystemContract,unittest.TestCase):
    EXAMPLE='local-dma-ownership';GOALS=11
    def test_completion_memory_digest_changes_with_reuse(self):
        self.assertNotEqual(P.row(2,turns=2)[4],P.row(2,turns=3)[4])
    def test_error_keeps_destination_unchanged(self):
        self.assertNotEqual(P.row(2,turns=1,invalid=0)[4],P.row(2,turns=1,invalid=1)[4])
    def test_external_copy_source_overlaps_internal_descriptor_addresses(self):
        for parameters in P.CONFIGS.values():
            with self.subTest(parameters=parameters):
                result=simulate_vectors(P,[P.row(parameters['DEPTH'],source_base=6144)],parameters)
                self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        # A copy into the original destination must change even a single word.
        self.assertNotEqual(P.row(2,turns=1)[4],P.row(2,turns=0)[4])

if __name__=='__main__':unittest.main()

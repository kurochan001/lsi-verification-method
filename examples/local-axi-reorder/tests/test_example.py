from pathlib import Path
import sys,unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'local-common'))
from system_test_support import SystemContract
from local_test_support import load_example
P=load_example('local-axi-reorder')
class ExampleTests(SystemContract,unittest.TestCase):
    EXAMPLE='local-axi-reorder';GOALS=10
    def test_per_id_order_is_preserved(self):
        ids=[0,1,0,1];result=P.order(ids)
        self.assertEqual(result,[1,3,0,2])
        for ident in (0,1):self.assertEqual([i for i in result if ids[i]==ident],[i for i,x in enumerate(ids) if x==ident])
    def test_distinct_ids_reorder(self):self.assertEqual(P.order([0,1]),[1,0])
if __name__=='__main__':unittest.main()

from pathlib import Path
import sys,unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'local-common'))
from local_test_support import load_example
P=load_example('local-soc-regression')
class AggregateTests(unittest.TestCase):
    def test_missing_or_empty_plan_cannot_pass(self):
        for d in ({},dict(success=True,complete=True,planned=0,results=[]),dict(success=True,complete=True,planned=True,results=1)):
            self.assertFalse(P.child_success(d))
    def test_list_plan_requires_every_check(self):
        d=dict(success=True,complete=True,planned=1,results=[dict(status='pass')]);self.assertTrue(P.child_success(d))
        self.assertFalse(P.child_success(dict(d,results=['pass'])));self.assertFalse(P.child_success(dict(d,results=[])))
    def test_integer_plan_requires_completion(self):
        d=dict(success=True,complete=True,planned=6,results=6);self.assertTrue(P.child_success(d))
        self.assertFalse(P.child_success(dict(d,complete=False)));self.assertFalse(P.child_success(dict(d,results=5)))
if __name__=='__main__':unittest.main()

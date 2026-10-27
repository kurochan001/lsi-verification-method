from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'local-common'))
from local_test_support import load_example
P=load_example('local-workflow-regression')
class AggregateTests(unittest.TestCase):
    def test_integer_result_contract(self):
        d=dict(success=True,complete=True,planned=6,results=6);self.assertTrue(P.child_success(d))
        self.assertFalse(P.child_success(dict(d,results=5)));self.assertFalse(P.child_success(dict(d,planned=True)))
    def test_list_result_contract(self):
        d=dict(success=True,complete=True,planned=1,results=[dict(status='pass')]);self.assertTrue(P.child_success(d))
        self.assertFalse(P.child_success(dict(d,results=[dict(status='fail')])));self.assertFalse(P.child_success(dict(d,complete=False)))
    def test_empty_or_missing_plan_rejected(self):
        self.assertFalse(P.child_success(dict(success=True,complete=True,planned=0,results=[])))
        self.assertFalse(P.child_success(dict(success=True)))
if __name__=='__main__':unittest.main()

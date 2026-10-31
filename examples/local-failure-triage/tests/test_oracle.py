import importlib.util
from pathlib import Path
import unittest
s=importlib.util.spec_from_file_location('triage_under_test',Path(__file__).resolve().parents[1]/'support.py');S=importlib.util.module_from_spec(s);s.loader.exec_module(S)
ROWS=[[0,0,0,0],[1,1,1,1]]
RESET='TRACE cycle=0 rst=0 event=0 clear=0 enable=0 pend=0 irq=0 expected=0\n'
class OracleTests(unittest.TestCase):
    def test_correct_event_priority(self):
        r=S.oracle(RESET+'TRACE cycle=1 rst=1 event=1 clear=1 enable=1 pend=1 irq=1 expected=1\n',ROWS,True)
        self.assertFalse(r['rtl_mismatches'] or r['model_mismatches'])
    def test_correlated_error_survives_comparison_but_not_oracle(self):
        r=S.oracle(RESET+'TRACE cycle=1 rst=1 event=1 clear=1 enable=1 pend=0 irq=0 expected=0\n',ROWS,True)
        self.assertEqual(r['rtl_mismatches'],[1]);self.assertEqual(r['model_mismatches'],[1])
    def test_wrong_reference_is_separate(self):
        r=S.oracle(RESET+'TRACE cycle=1 rst=1 event=1 clear=1 enable=1 pend=1 irq=1 expected=0\n',ROWS,True)
        self.assertFalse(r['rtl_mismatches']);self.assertEqual(r['model_mismatches'],[1])
    def test_incomplete_run_is_not_success(self):
        with self.assertRaises(ValueError):S.oracle(RESET,ROWS,True)
    def test_duplicate_or_changed_input_is_rejected(self):
        for bad in (RESET+RESET,RESET.replace('rst=0','rst=1')):
            with self.subTest(log=bad),self.assertRaises(ValueError):S.oracle(bad,ROWS)
    def test_unknown_value_is_not_ignored(self):
        with self.assertRaises(ValueError):S.oracle(RESET.replace('pend=0','pend=x'),ROWS)
    def test_unrelated_failure_is_unclassified(self):
        r=dict(execution={'error':None},problems=[],status='error',oracle=None,sva_off=0,native=None)
        self.assertEqual(S.diagnose(r,'unexpected crash'),'unclassified')
if __name__=='__main__':unittest.main()

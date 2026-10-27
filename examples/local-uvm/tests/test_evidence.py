from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'local-common'))
from local_test_support import load_example
P=load_example('local-uvm')
class EvidenceTests(unittest.TestCase):
    def setUp(self):
        self.case=dict(checks=16,iterations=3,expected_failure=None);self.execution=dict(error=None,returncode=0)
        self.log='''Accellera:1800.2:UVM:2020.3.2
UVM_WARNING a [NO_DPI_USED] expected
UVM_WARNING b [NO_VISIT_CHECK] expected
COUNT transactions=16
COUNT reads=9
COUNT writes=7
COUNT errors=2
RESULT PASS checks=16
UVM_WARNING : 2
UVM_ERROR : 0
UVM_FATAL : 0
'''
    def test_native_summary_and_counts_required(self):
        self.assertTrue(P.evaluate(self.case,self.execution,self.log)[0])
        self.assertFalse(P.evaluate(self.case,self.execution,self.log.replace('COUNT reads=9\n',''))[0])
    def test_native_error_rejects_zero_exit(self):
        self.assertFalse(P.evaluate(self.case,self.execution,self.log.replace('UVM_ERROR : 0','UVM_ERROR : 1'))[0])
    def test_duplicate_counts_and_unknown_warning_rejected(self):
        for extra in ('COUNT reads=9\n','UVM_WARNING c [OTHER] unexpected\n'):
            self.assertFalse(P.evaluate(self.case,self.execution,self.log+extra)[0])
    def test_expected_failure_requires_nonzero_and_exact_label(self):
        c=dict(self.case,expected_failure='UVM_CONFIG');log='CHECK_FAIL UVM_CONFIG\n'
        self.assertFalse(P.evaluate(c,self.execution,log)[0])
        self.assertTrue(P.evaluate(c,dict(error=None,returncode=1),log)[0])
        self.assertFalse(P.evaluate(c,dict(error='timeout',returncode=1),log)[0])
        self.assertFalse(P.evaluate(c,dict(error=None,returncode=1),'CHECK_FAIL OTHER\n')[0])
    def test_wrong_library_version_rejected(self):
        self.assertFalse(P.evaluate(self.case,self.execution,self.log.replace('2020.3.2','2020.3.1'))[0])
if __name__=='__main__':unittest.main()

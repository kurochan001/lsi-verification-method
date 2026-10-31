import importlib.util
from pathlib import Path
import tempfile
import unittest
HERE=Path(__file__).resolve().parents[1];S=importlib.util.spec_from_file_location('hierarchy_test_python',HERE/'run.py');P=importlib.util.module_from_spec(S);S.loader.exec_module(P)
class HierarchyTests(unittest.TestCase):
    def log(self,n=4):
        return '\n'.join(['Accellera:1800.2:UVM:2020.3.2','HIER_OWNERSHIP active_drivers=1 passive_children=2',f'HIER_COMPLETE bank0={3*n+6} bank1={3*n+6}',f'RESULT PASS checks={2*n+9}','UVM_WARNING x [NO_DPI_USED] x','UVM_WARNING x [NO_VISIT_CHECK] x','UVM_WARNING : 2','UVM_ERROR : 0','UVM_FATAL : 0',*['COVER '+g for g in P.GOALS]])+'\n'
    def test_independent_counts_ownership_goals_and_native_summary_are_required(self):
        c=dict(iterations=4,checks=17,expected_failure=None);ex=dict(error=None,returncode=0);log=self.log();self.assertTrue(P.evaluate(c,ex,log)[0])
        for text in (log.replace('bank1=18','bank1=0'),log.replace('active_drivers=1','active_drivers=2'),log.replace('UVM_ERROR : 0','UVM_ERROR : 1'),log.replace('COVER hierarchy/b1/reset','MISSING'),log.replace('RESULT PASS checks=17','RESULT PASS checks=0')):
            self.assertFalse(P.evaluate(c,ex,text)[0])
    def test_unrelated_crash_never_counts_as_mutation_detection(self):
        c=dict(iterations=4,checks=17,expected_failure='HIER_READ')
        self.assertFalse(P.evaluate(c,dict(error=None,returncode=1),'unrelated crash\n')[0])
        self.assertTrue(P.evaluate(c,dict(error=None,returncode=1),'CHECK_FAIL HIER_READ\n')[0])
    def test_native_cover_inventory_cannot_be_empty(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'coverage.dat';p.write_text('# no counters\n')
            with self.assertRaises(ValueError):P.native(p,'')
if __name__=='__main__':unittest.main()

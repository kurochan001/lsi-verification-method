from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'local-common'))
from local_test_support import load_example,simulate_vectors
from system_test_support import SystemContract
P=load_example('local-scan-atpg')


class ScanTests(SystemContract,unittest.TestCase):
    EXAMPLE='local-scan-atpg';GOALS=10

    def test_collapsed_spec_agrees_for_every_fault_free_assignment(self):
        for q in range(16):
            for x in range(4):self.assertEqual(P.A.functional(q,x),P.A.faulty(q,x))

    def test_generated_patterns_cover_exactly_thirteen_detectable_faults(self):
        report=P.A.report();self.assertEqual(report['redundant'],[[5,0]])
        self.assertEqual((report['assignments'],report['faults'],report['detectable']),(64,14,13))
        detected={f for f in P.A.FAULTS for q,x in report['patterns'] if P.A.faulty(q,x,f)!=P.A.functional(q,x)}
        self.assertEqual(detected,set(P.A.FAULTS)-{(5,0)})
        self.assertEqual(len(report['patterns']),3) # deterministic greedy set cover, not a minimality claim

    def test_every_single_fault_at_every_assignment_on_rtl(self):
        for reverse in (0,1):
            p=P.Plan(reverse);p.cycle(rst=0)
            for fault in P.A.FAULTS:
                for q in range(16):
                    for x in range(4):p.pattern(q,x,fault)
            p.cycle(rst=0)
            result=simulate_vectors(P,p.rows,{'REVERSE':reverse})
            self.assertEqual(result.returncode,0,result.stdout[-1000:])
            self.assertIn('COUNT detectable_faults=13',result.stdout)

    def test_scan_serialization_for_non_palindromic_state(self):
        for reverse,expected in ((0,[1,1,0,0]),(1,[0,0,1,1])):
            p=P.Plan(reverse);p.cycle(rst=0)
            order=range(4) if reverse else range(3,-1,-1)
            for bit in order:p.cycle(se=1,si=(12>>bit)&1,phase=1)
            observed=[]
            for _ in range(4):p.cycle(se=1,phase=3);observed.append(p.rows[-1][8])
            self.assertEqual(observed,expected)
            result=simulate_vectors(P,p.rows,{'REVERSE':reverse})
            self.assertEqual(result.returncode,0,result.stdout)


if __name__=='__main__':unittest.main()

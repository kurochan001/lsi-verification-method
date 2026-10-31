from itertools import combinations
from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'local-common'))
from local_test_support import load_example,simulate_vectors
from system_test_support import SystemContract
P=load_example('local-store-buffer')


class OrderingTests(SystemContract,unittest.TestCase):
    EXAMPLE='local-store-buffer';GOALS=18

    def test_store_buffering_outcomes_differ_from_sequential_consistency(self):
        sc=set()
        for positions in combinations(range(4),2):
            pc=[0,0];memory=[0,0];results=[None,None]
            for c in [0 if i in positions else 1 for i in range(4)]:
                if pc[c]==0:memory[c]=1
                else:results[c]=memory[1-c]
                pc[c]+=1
            sc.add(tuple(results))
        self.assertEqual(sc,{(0,1),(1,0),(1,1)})
        self.assertEqual(set(P.L.explore(False)['witnesses']),sc|{(0,0)})
        self.assertEqual(set(P.L.explore(True)['witnesses']),sc)

    def test_youngest_matching_store_is_forwarded_before_visibility(self):
        p=P.Plan(3);p.cycle(rst=0)
        for addr,value in ((0,11),(1,22),(0,33)):p.transfer(0,1,addr,value)
        p.transfer(0,0,0);self.assertEqual(p.response,(0,0,33));self.assertEqual(p.memory[0],0)
        p.transfer(1,0,0);self.assertEqual(p.response,(1,0,0))
        p.cycle(drain=0);p.transfer(1,0,0);self.assertEqual(p.response,(1,0,11))
        result=simulate_vectors(P,p.rows,{'DEPTH':3});self.assertEqual(result.returncode,0,result.stdout)

    def test_last_store_can_drain_in_the_same_cycle_as_fence_acceptance(self):
        p=P.Plan(2);p.cycle(rst=0);p.transfer(0,1,0,123)
        self.assertEqual(p.cycle(valid=1,core=0,op=2),0)
        self.assertEqual(p.cycle(valid=1,core=0,op=2,drain=0),1)
        p.cycle();self.assertEqual((p.memory[0],p.queue[0]),(123,[]))
        result=simulate_vectors(P,p.rows);self.assertEqual(result.returncode,0,result.stdout)

    def test_silently_discarded_accepted_store_is_rejected(self):
        p=P.Plan(2);p.cycle(rst=0);p.transfer(0,1,0,123);p.transfer(0,0,0)
        result=simulate_vectors(P,p.rows,replacements={'store_buffer.sv':[("count[core]<=after_count+1'b1;","count[core]<=after_count;")]})
        self.assertNotEqual(result.returncode,0);self.assertIn('CHECK_FAIL ORDER_FLOW',result.stdout)


if __name__=='__main__':unittest.main()

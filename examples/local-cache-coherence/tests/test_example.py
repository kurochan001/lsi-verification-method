from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'local-common'))
from local_test_support import load_example,simulate_vectors
from system_test_support import SystemContract
P=load_example('local-cache-coherence')


class CoherenceTests(SystemContract,unittest.TestCase):
    EXAMPLE='local-cache-coherence';GOALS=12

    def test_dirty_owner_handoff_then_eviction_keeps_latest_write(self):
        p=P.Plan(1);p.cycle(rst=0)
        for core,value in ((0,0xaabbccdd),(1,0x76543210),(0,0xdeadbeef)):
            p.transfer(core,4,1,value);p.transfer(1-core,4)
            self.assertEqual(p.data,value)
        p.transfer(0,5);p.transfer(1,6);p.transfer(0,4)
        self.assertEqual(p.data,0xdeadbeef)
        result=simulate_vectors(P,p.rows);self.assertEqual(result.returncode,0,result.stdout)

    def test_request_blocked_until_delayed_held_response_consumed(self):
        p=P.Plan(3);p.cycle(rst=0);self.assertEqual(p.cycle(valid=1,write=1,addr=1,data=99),1)
        for _ in range(8):
            self.assertEqual(p.cycle(valid=1,core=1,write=1,addr=1,data=100,ready=0),0)
        self.assertEqual((p.memory[1],p.data,p.valid),(99,99,1))
        p.cycle();self.assertEqual(p.cycle(),1)
        result=simulate_vectors(P,p.rows,{'LATENCY':3});self.assertEqual(result.returncode,0,result.stdout)

    def test_reset_cancels_pending_and_clears_both_caches_and_memory(self):
        p=P.Plan(3);p.cycle(rst=0);p.cycle(valid=1,write=1,addr=2,data=123)
        p.cycle(rst=0);p.transfer(1,2)
        self.assertEqual((p.data,p.memory[2]),(0,0))
        result=simulate_vectors(P,p.rows,{'LATENCY':3});self.assertEqual(result.returncode,0,result.stdout)

    def test_resident_line_checker_uses_architectural_memory(self):
        p=P.Plan(1);p.cycle(rst=0);p.transfer(0,4,1,123);p.cycle()
        p.rows[-1][-1]^=1<<(32*4) # stale architectural expectation, response already consumed
        result=simulate_vectors(P,p.rows)
        self.assertNotEqual(result.returncode,0);self.assertIn('CHECK_FAIL CACHE_DATA',result.stdout)


if __name__=='__main__':unittest.main()

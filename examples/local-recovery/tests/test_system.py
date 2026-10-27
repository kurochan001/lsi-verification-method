from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'local-common'))
from local_test_support import load_example
from system_test_support import SystemContract
P=load_example('local-recovery')

class SystemTest(SystemContract,unittest.TestCase):
    EXAMPLE='local-recovery';GOALS=10

    def test_late_response_cannot_complete_a_new_request(self):
        p=P.Plan(4);p.cycle(rst=0);old=p.begin(1);p.wait_result();p.finish()
        current=p.begin(2);p.cycle(rv=1,tag=old,response=99)
        self.assertIsNone(p.model.result);self.assertEqual(p.model.drop,1)
        p.cycle(rv=1,tag=current,response=88);self.assertEqual(p.model.result,(0,88))

    def test_matching_response_wins_exact_timeout_boundary(self):
        p=P.Plan(4);p.cycle(rst=0);p.transaction(0x33,delay=4)
        self.assertEqual(P.counts(p.rows)['timeouts'],0)

    def test_tags_stop_before_reuse_and_restart_requires_flush(self):
        p=P.Plan(4);p.cycle(rst=0)
        for _ in range(15):p.transaction(1)
        rows=[p.cycle(uv=1,data=3) for _ in range(3)]
        self.assertTrue(all(r[8]==0 for r in rows));self.assertEqual(p.model.serial,15)
        p.cycle(rst=0);self.assertEqual(p.begin(4),1)

if __name__=='__main__':unittest.main()

from pathlib import Path
import sys, unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'local-common'))
from system_test_support import SystemContract
from local_test_support import load_example, simulate_vectors

P = load_example('local-performance-monitor')


class ExampleTests(SystemContract, unittest.TestCase):
    EXAMPLE = 'local-performance-monitor'
    GOALS = 13

    def test_latency_and_window_boundary(self):
        p = P.Plan(4)
        p.step(rst=0)
        p.step(start=1)
        p.step(req_valid=1, req_tag=0)
        p.step()
        p.step()
        p.step(resp_valid=1, resp_tag=0)
        p.step()
        self.assertEqual(p.rows[-1][9], 3)
        self.assertEqual(p.rows[-1][10], 1)
        p.step(req_valid=1, req_tag=1)
        p.step(stop=1, resp_valid=1, resp_tag=1)
        p.step()
        self.assertEqual(p.rows[-1][10], 2)

    def test_invalid_response_sets_and_start_clears_error(self):
        p = P.Plan(2)
        p.step(rst=0)
        p.step(resp_valid=1, resp_tag=0)
        p.step()
        self.assertEqual(p.rows[-1][14], 1)
        p.step(start=1)
        p.step()
        self.assertEqual(p.rows[-1][14], 0)


    def test_out_of_range_tags_do_not_create_hidden_transactions(self):
        p=P.Plan(2);p.step(rst=0)
        for tag in (2,3):
            p.step(req_valid=1,req_tag=tag)
            self.assertEqual(p.rows[-1][7],0)
            p.step(resp_valid=1,resp_tag=tag);p.step()
            self.assertEqual(p.rows[-1][8],0);self.assertEqual(p.rows[-1][13],0)
            self.assertEqual(p.rows[-1][14],1)
        result=simulate_vectors(P,p.rows,{'SLOTS':2})
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)

    def test_long_latencies_saturate_instead_of_wrapping(self):
        p=P.Plan(4)
        for wait in (253,254,255,300):
            p.step(rst=0);p.step(start=1)
            p.step(req_valid=1,req_tag=0)
            for _ in range(wait):p.step()
            p.step(resp_valid=1,resp_tag=0);p.step()
            self.assertEqual(p.rows[-1][9],min(wait+1,255))
        result=simulate_vectors(P,p.rows,{'SLOTS':4})
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)


if __name__ == '__main__':
    unittest.main()

from pathlib import Path
import sys, unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'local-common'))
from system_test_support import SystemContract
from local_test_support import load_example

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


if __name__ == '__main__':
    unittest.main()

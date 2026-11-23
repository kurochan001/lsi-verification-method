from pathlib import Path
import sys, unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'local-common'))
from system_test_support import SystemContract
from local_test_support import load_example, simulate_vectors

P = load_example('local-mul-pipe')


class ExampleTests(SystemContract, unittest.TestCase):
    EXAMPLE = 'local-mul-pipe'
    GOALS = 10

    def test_output_appears_exactly_after_the_pipeline_depth(self):
        for stages in (2, 3):
            p = P.Plan(stages)
            p.step(rst=0)
            p.mul(5, 9)
            for _ in range(stages - 1):
                p.idle()
                self.assertEqual((p.rows[-1][4], p.rows[-1][5]), (0, 0))
            p.idle()
            self.assertEqual((p.rows[-1][4], p.rows[-1][5]), (1, 45))
            p.idle()
            self.assertEqual(p.rows[-1][4], 0)  # the pulse is over: the queue is drained

    def test_back_to_back_products_keep_their_lanes(self):
        p = P.Plan(3)
        p.step(rst=0)
        p.mul(255, 255)
        p.mul(1, 1)
        p.idle(4)
        seen = [row[5] for row in p.rows[-4:] if row[4]]
        self.assertEqual(seen, [0xfe01, 1])

    def test_max_product_reaches_the_real_rtl(self):
        p = P.Plan(3)
        p.step(rst=0)
        p.mul(255, 255)
        p.idle(4)
        result = simulate_vectors(P, p.rows, {'STAGES': 3})
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_lane_truncation_is_detected(self):
        p = P.Plan(3)
        p.step(rst=0)
        p.mul(255, 255)
        p.idle(4)
        result = simulate_vectors(P, p.rows, {'STAGES': 3}, replacements={'mul_pipe.sv': [
            ("out <= MUTATION == 4 ? {8'b0, sum_final[7:0]} : sum_final;",
             "out <= {8'b0, sum_final[7:0]};")]})
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertIn('CHECK_FAIL MUL_DATA', result.stdout)


if __name__ == '__main__':
    unittest.main()

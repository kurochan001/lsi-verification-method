from pathlib import Path
import sys, unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'local-common'))
from system_test_support import SystemContract
from local_test_support import load_example, simulate_vectors

P = load_example('local-rvwmo-litmus')


class ExampleTests(SystemContract, unittest.TestCase):
    EXAMPLE = 'local-rvwmo-litmus'
    GOALS = 7

    def test_fenced_symmetric_run_finishes_with_both_one(self):
        p = P.Plan(2)
        p.litmus(fence=1)
        self.assertEqual(p.outcome(), (1, 1, 1, 1))  # fence: only the SC outcomes survive

    def test_relaxed_symmetric_run_allows_both_zero(self):
        p = P.Plan(3)
        p.litmus(fence=0)
        self.assertEqual(p.outcome(), (1, 1, 0, 0))  # each load beats the other's store

    def test_the_model_never_allows_both_zero_when_fenced(self):
        for drain in (2, 3):
            p = P.Plan(drain)
            p.fixed()
            outcomes = [row[17:19] for row in p.rows if row[19] and all(row[15:17])]
            self.assertTrue(outcomes)
            self.assertNotIn([0, 0], outcomes)

    def test_real_rtl_fenced_matches_the_model(self):
        rows = P.vectors(7, 0, {'DRAIN': 2}, boundary=True)
        result = simulate_vectors(P, rows, {'DRAIN': 2})
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_real_rtl_relaxed_reaches_both_zero(self):
        p = P.Plan(3)
        p.litmus(fence=0)
        self.assertEqual(p.outcome(), (1, 1, 0, 0))
        result = simulate_vectors(P, p.rows, {'DRAIN': 3})
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_fence_bypass_is_detected_as_an_ordering_failure(self):
        rows = P.vectors(7, 0, {'DRAIN': 2}, boundary=True)
        result = simulate_vectors(P, rows, {'DRAIN': 2, 'MUTATION': 1})
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertIn('CHECK_FAIL MEM_ORD', result.stdout)


if __name__ == '__main__':
    unittest.main()

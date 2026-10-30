from pathlib import Path
import sys, unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'local-common'))
from system_test_support import SystemContract
from local_test_support import load_example

P = load_example('local-systolic-array')


def results(rows, n):
    """Column values of every completed result, decoded from the expected outputs."""
    out = []
    for row in rows:
        if row[0] and row[9] and row[6]:
            value = row[10]
            out.append([((value >> (32 * c)) & 0xffffffff) - ((value >> (32 * c + 31)) & 1) * (1 << 32)
                        for c in range(n)])
    return out


class ExampleTests(SystemContract, unittest.TestCase):
    EXAMPLE = 'local-systolic-array'
    GOALS = 18

    def test_isolated_vector_appears_two_n_minus_one_rows_after_acceptance(self):
        for n in (2, 4):
            with self.subTest(n=n):
                p = P.Plan(n)
                p.cycle(rst=0)
                p.load(P.mixed_matrix(n))
                start = len(p.rows)
                p.send([3] * n)
                p.drain()
                valid = [i for i, row in enumerate(p.rows) if row[9]]
                self.assertEqual(valid, [start + 2 * n - 1])

    def test_weight_write_waits_until_in_flight_results_leave(self):
        p = P.Plan(2)
        p.cycle(rst=0)
        p.load([[1, 2], [3, 4]])
        p.send([1, 1])
        first = len(p.rows)
        p.write(0, [10, 20])
        blocked = [row[7] for row in p.rows[first:]]
        self.assertEqual(blocked, [0, 0, 0, 1])
        p.send([1, 1])
        p.drain()
        self.assertEqual(results(p.rows, 2), [[4, 6], [13, 24]])

    def test_reset_discards_in_flight_vectors_and_clears_weights(self):
        p = P.Plan(4)
        p.cycle(rst=0)
        p.load(P.mixed_matrix(4))
        for value in (1, 2, 3):
            p.send([value] * 4)
        p.cycle(rst=0)
        p.send([5] * 4)
        p.drain()
        self.assertEqual(results(p.rows, 4), [[0] * 4])

    def test_only_the_fixed_scenario_exceeds_16_bits_for_n2(self):
        # With N=2 a 16-bit accumulator is wrong only for (-128*-128)*2; random stimulus misses it.
        self.assertTrue(any(max(map(abs, r)) > 32767 for r in results(P.boundary_vectors(2), 2)))
        for seed in (17, 18, 19):
            self.assertFalse(any(max(map(abs, r)) > 32767 for r in results(P.random_vectors(seed, 96, 2), 2)))


if __name__ == '__main__':
    unittest.main()

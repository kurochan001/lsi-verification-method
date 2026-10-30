from pathlib import Path
import random, sys, unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'local-common'))
from system_test_support import SystemContract
from local_test_support import load_example

P = load_example('local-requantize')


def integer_procedure(x, m, s, zp, lo, hi):
    """The nudge/truncate and mask/threshold steps, as an integer pipeline would write them."""
    ab = x * m
    nudged = ab + ((1 << 30) if ab >= 0 else 1 - (1 << 30))
    t = abs(nudged) >> 31 if nudged >= 0 else -(abs(nudged) >> 31)
    mask = (1 << s) - 1
    q = (t >> s) + ((t & mask) > (mask >> 1) + (t < 0))
    u = q + zp
    return max(lo, min(hi, u)), int(not lo <= u <= hi)


def accepted_values(rows):
    """(x, m, s, zp) of every accepted value, replaying the parameter writes of a plan."""
    params, out = {}, []
    for row in rows:
        if not row[0]:
            params = {}
            continue
        if row[6] and row[10]:
            out.append((row[8] - (row[8] >> 31) * (1 << 32), *params.get(row[7], (0, 0, 0))))
        if row[1]:
            params[row[2]] = (row[3], row[4], row[5] - (row[5] >> 7) * 256)
    return out


def negative_ties(rows, lo, hi):
    """Negative ties of the first rounding, and those whose direction changes the output."""
    ties = [v for v in accepted_values(rows) if v[0] * v[1] < 0 and v[0] * v[1] % (1 << 31) == 1 << 30]
    visible = [v for v in ties if P.requantize(*v, lo, hi)[0] !=
               max(lo, min(hi, P.round_half_away(P.round_half_away(v[0] * v[1], 1 << 31), 1 << v[2]) + v[3]))]
    return len(ties), len(visible)


class ExampleTests(SystemContract, unittest.TestCase):
    EXAMPLE = 'local-requantize'
    GOALS = 19

    def test_rounding_rules_match_the_integer_procedure(self):
        rng = random.Random(5)
        cases = [(x, m, s) for x in (P.INT32[0], P.INT32[1], -5, -3, -1, 0, 1, 3, 5)
                 for m in (0, 1, P.HALF, P.MAX_MULT) for s in (0, 1, 2, 30, 31)]
        cases += [(rng.randrange(*P.INT32), rng.randrange(P.MAX_MULT + 1), rng.randrange(32)) for _ in range(20000)]
        for x, m, s in cases:
            for zp, lo, hi in ((0, -128, 127), (-128, -20, 100), (127, -128, 127)):
                self.assertEqual(P.requantize(x, m, s, zp, lo, hi), integer_procedure(x, m, s, zp, lo, hi))

    def test_first_rounding_ties_go_up_and_second_rounding_ties_go_away_from_zero(self):
        self.assertEqual([P.round_half_up(v, 2) for v in (3, -3, 1, -1)], [2, -1, 1, 0])
        self.assertEqual([P.round_half_away(v, 4) for v in (6, -6, 2, -2)], [2, -2, 1, -1])

    def test_two_roundings_differ_from_rounding_the_exact_value_once(self):
        self.assertEqual(P.requantize(5, P.HALF, 1, 0, -128, 127), (2, 0))
        self.assertEqual(P.round_half_away(5 * P.HALF, 1 << 32), 1)

    def test_random_negative_ties_of_the_first_rounding_are_masked_downstream(self):
        # Random values do hit these ties, but the second rounding or the clamp hides the
        # tie direction; only the fixed scenario (s=0) makes it visible at the output.
        for ch, lo, hi in ((2, -128, 127), (4, -20, 100)):
            self.assertGreater(negative_ties(P.boundary_vectors(ch, lo, hi), lo, hi)[1], 0)
            for seed in (17, 18, 19):
                ties, visible = negative_ties(P.random_vectors(seed, 200, ch, lo, hi), lo, hi)
                self.assertGreater(ties, 0)
                self.assertEqual(visible, 0)

    def test_a_write_on_the_accepting_edge_does_not_reach_that_value(self):
        p = P.Plan(2, -128, 127)
        p.cycle(rst=0)
        p.configure(0, P.HALF, 2, 10)
        p.send(0, 400, cfg=(0, P.HALF, 1, -10))
        p.send(0, 200)
        p.drain()
        self.assertEqual([row[12] for row in p.rows if row[11] and row[9]], [60, 40])

    def test_empty_stages_still_accept_while_the_output_is_stalled(self):
        p = P.Plan(2, -128, 127)
        p.cycle(rst=0)
        p.send(0, 1)
        p.cycle()
        p.cycle()
        ready = [p.cycle(value=(0, i), ready=0)[10] for i in range(4)]
        self.assertEqual(ready, [1, 1, 0, 0])


if __name__ == '__main__':
    unittest.main()

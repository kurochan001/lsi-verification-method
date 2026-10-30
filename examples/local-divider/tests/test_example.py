import importlib.util
from pathlib import Path
import random, re, sys, unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'local-common'))
from system_test_support import SystemContract
from local_test_support import load_example

P = load_example('local-divider')
HERE = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('divider_formal', HERE / 'formal.py')
F = importlib.util.module_from_spec(spec)
spec.loader.exec_module(F)


def flushes_on_last_step(rows, w):
    """Flushes that arrive on the last restoring step of a multi-cycle division."""
    hits, age, normal = 0, None, False
    for row in rows:
        rst_n, flush, valid, signed, a, b, _, in_ready = row[:8]
        if not rst_n:
            age = None
            continue
        if age is not None:
            age += 1
            if flush and normal and age == w:
                hits += 1
            if flush or row[8]:
                age = None
        if valid and in_ready:
            age, normal = 0, not P.short(a, b, signed, w)
    return hits


class ExampleTests(SystemContract, unittest.TestCase):
    EXAMPLE = 'local-divider'
    GOALS = 16

    def test_special_cases_follow_the_risc_v_table(self):
        for w in (4, 8, 32):
            mask, top = (1 << w) - 1, 1 << (w - 1)
            for signed in (0, 1):
                for a in P.edges(w):
                    self.assertEqual(P.reference(a, 0, signed, w), (mask, a))
            self.assertEqual(P.reference(top, mask, 1, w), (top, 0))
            self.assertEqual(P.reference(top, mask, 0, w), (0, top))

    def test_quotient_rounds_toward_zero_and_remainder_takes_the_dividend_sign(self):
        signed = lambda x: P.to_signed(x, 8)
        cases = {(7, -2): (-3, 1), (-7, 2): (-3, -1), (-7, -2): (3, -1), (7, 2): (3, 1)}
        for (a, b), expected in cases.items():
            q, r = P.reference(a & 0xff, b & 0xff, 1, 8)
            self.assertEqual((signed(q), signed(r)), expected)
        rng = random.Random(3)
        for _ in range(20000):
            w = rng.choice((8, 32))
            a, b, s = rng.getrandbits(w), rng.getrandbits(w) or 1, rng.randrange(2)
            q, r = P.reference(a, b, s, w)
            x, y = (P.to_signed(a, w), P.to_signed(b, w)) if s else (a, b)
            qq, rr = (P.to_signed(q, w), P.to_signed(r, w)) if s else (q, r)
            if s and x == -(1 << (w - 1)) and y == -1:
                continue
            self.assertEqual(qq * y + rr, x)
            self.assertLess(abs(rr), abs(y))
            self.assertTrue(rr == 0 or (rr < 0) == (x < 0))

    def test_latency_is_one_cycle_for_the_short_cases_and_w_plus_one_otherwise(self):
        for w, (a, b, s), latency in ((8, (100, 7, 1), 9), (8, (3, 7, 0), 1), (32, (100, 0, 1), 1), (32, (100, 7, 0), 33)):
            p = P.Plan(w)
            p.cycle(rst_n=0)
            p.accept(a, b, s)
            start = len(p.rows)
            while not p.model.valid:
                p.cycle(ready=0)
            self.assertEqual(len(p.rows) - start + 1, latency)

    def test_only_the_fixed_scenario_flushes_on_the_last_step_at_32_bits(self):
        self.assertEqual(flushes_on_last_step(P.boundary_vectors(32), 32), 1)
        for seed in (17, 18, 19):
            self.assertEqual(flushes_on_last_step(P.random_vectors(32, seed, 200), 32), 0)

    def test_formal_plan_and_properties_match_the_rtl(self):
        plan = F.plan(F.BOUND, 0)
        self.assertEqual([c['id'] for c in plan], ['divider-proof', 'scenario-cover'] +
                         [f'detect-mutation{m}' for m in range(1, 5)])
        self.assertEqual(plan[0]['depth'], F.PROOF_DEPTH)
        self.assertEqual(F.plan(F.BOUND, 2)[0]['parameters'], {'MUTATION': 2})
        text = (HERE / 'rtl/divider.sv').read_text()
        labels = set(re.findall(r'\b((?:ap|ai|cp|as)_\w+):', text))
        self.assertEqual(labels, F.ASSERTS | F.COVERS | {'as_initial_reset'})
        self.assertTrue(set(F.FAILURES.values()) <= F.ASSERTS)


if __name__ == '__main__':
    unittest.main()

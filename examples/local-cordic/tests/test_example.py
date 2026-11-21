import math
from pathlib import Path
import random
import re
import shutil
import sys
import tempfile
from types import SimpleNamespace
import unittest
import xml.etree.ElementTree as ET
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'local-common'))
from local_test_support import load_example, read_json, run_example, simulate_vectors

P = load_example('local-cordic')
M = P.M
HERE = Path(__file__).resolve().parents[1]
ICARUS = shutil.which('iverilog') and shutil.which('vvp')
GOALS = 27
BIG = P.CONFIGS['w16-i16-g4']
SMALL = P.CONFIGS['w12-i12-g2']


def shape(parameters):
    return parameters['WIDTH'], parameters['ITER'], parameters['GUARD']


def args(profile='smoke', seed=17, iterations=4, demo_bug=0):
    return SimpleNamespace(profile=profile, seed=seed, iterations=iterations, demo_bug=demo_bug)


class ModelTests(unittest.TestCase):
    def test_constants_in_the_rtl_are_the_ones_the_model_computes(self):
        rtl = (HERE / 'rtl/cordic.sv').read_text()
        table = {int(i): int(v) for i, v in re.findall(r"(\d+): atan32 = 32'd(\d+);", rtl)}
        self.assertEqual(table, {i: M.ATAN32[i] for i in range(19)})
        self.assertEqual(int(re.search(r"default: atan32 = 32'd(\d+);", rtl)[1]), M.ATAN32[19])
        gains = {int(i): int(v) for i, v in re.findall(r"(\d+): gain_inverse = 18'd(\d+);", rtl)}
        self.assertEqual(gains, {n: M.gain_inverse(n) for n in range(1, 9)})
        default = int(re.search(r"default: gain_inverse = 18'd(\d+);", rtl)[1])
        self.assertEqual({M.gain_inverse(n) for n in range(9, 21)}, {default})   # the gain has settled by then
        self.assertAlmostEqual(M.gain(16), 1.6467602578654548, places=12)

    def test_known_results_are_within_the_bound_and_not_always_exact(self):
        w, n, g = shape(BIG)
        top = 32767
        self.assertEqual(M.reference(0, top, 0, 0x4000), (0, top, 0))
        self.assertEqual(M.reference(0, top, 0, 0x8000), (-top, 0, 0))
        self.assertEqual(M.reference(1, 3, 4, 0), (5, 0, round(math.atan2(4, 3) / (2 * math.pi) * 65536)))
        self.assertEqual(M.reference(1, -1, 0, 0), (1, 0, 0x8000))
        for mode, x, y, z in ((0, top, 0, 0), (0, top, 0, 0x2000), (0, top, top, 0xe000), (0, -32768, -32768, 0x2000),
                              (1, top, top, 0), (1, -32768, 0, 0), (1, 0, -32768, 0), (1, 12345, -23456, 0)):
            error, limit = M.errors(mode, x, y, z, w, n, g), M.tolerance(mode, x, y, w, n, g)
            self.assertTrue(all(e <= t for e, t in zip(error, limit)), (mode, x, y, z, error, limit))
        # The integer result is not the rounded mathematical result: that is why there are two checks.
        self.assertNotEqual(M.cordic(0, top, 0, 0x1555, w, n, g)[:2], M.reference(0, top, 0, 0x1555)[:2])
        with self.assertRaises(ValueError):
            M.cordic(0, 32768, 0, 0, w, n, g)

    def test_the_angle_left_after_every_iteration_stays_within_its_bound_for_every_angle(self):
        for parameters in (BIG, SMALL):
            w, n, g = shape(parameters)
            bounds = [M.residual_bound(i, n, g) for i in range(n + 1)]
            self.assertEqual(bounds[0], 0x4000 << g)
            self.assertTrue(all(a >= b for a, b in zip(bounds, bounds[1:])))
            worst = [0] * (n + 1)
            for z in range(M.TURN):
                trace = []
                M.cordic(0, 1, 0, z, w, n, g, trace)
                worst = [max(a, abs(t[2])) for a, t in zip(worst, trace)]
            self.assertTrue(all(a <= b for a, b in zip(worst, bounds)), (worst, bounds))
            self.assertEqual(worst[0], bounds[0])              # a quarter turn is reached exactly
            self.assertGreaterEqual(worst[n] * 2, bounds[n])   # and the last bound is not loose

    def test_the_derived_bound_covers_every_16_bit_rotation_angle_and_is_not_vacuous(self):
        for parameters in (BIG, SMALL):
            w, n, g = shape(parameters)
            radius = (1 << (w - 1)) - 1
            limit = M.tolerance(0, radius, 0, w, n, g)
            seen = [0, 0, 0]
            for z in range(M.TURN):
                seen = [max(a, b) for a, b in zip(seen, M.errors(0, radius, 0, z, w, n, g))]
            self.assertTrue(all(a <= b for a, b in zip(seen, limit)), (seen, limit))
            self.assertGreaterEqual(max(seen[:2]) * 3, limit[0], (seen, limit))   # within a factor of three
            self.assertEqual(P.observed_limit(parameters), max(seen[:2]))        # the probe set finds the same worst case

    def test_the_bound_holds_for_random_operands_of_both_modes(self):
        rng = random.Random(20261121)
        for parameters in (BIG, SMALL):
            w, n, g = shape(parameters)
            span = 1 << (w - 1)
            for _ in range(30000):
                mode, z = rng.randrange(2), rng.randrange(M.TURN)
                limit_xy = 5 if rng.random() < 0.2 else span
                x, y = rng.randrange(-limit_xy, limit_xy), rng.randrange(-limit_xy, limit_xy)
                error, limit = M.errors(mode, x, y, z, w, n, g), M.tolerance(mode, x, y, w, n, g)
                self.assertTrue(all(e <= t for e, t in zip(error, limit)), (mode, x, y, z, error, limit))

    def test_the_angle_bound_of_vectoring_grows_as_the_vector_gets_shorter(self):
        w, n, g = shape(BIG)
        self.assertEqual(M.tolerance(1, 0, 0, w, n, g)[2], M.TURN // 2)      # no direction at all
        self.assertEqual(M.tolerance(1, 1, 0, w, n, g)[2], M.TURN // 2)      # shorter than the shift error
        angles = [M.tolerance(1, r, 0, w, n, g)[2] for r in (4, 16, 256, 4096, 32767)]
        self.assertEqual(angles, sorted(angles, reverse=True))
        self.assertLess(angles[-1], 8)
        self.assertGreater(angles[0], 1000)
        self.assertGreater(M.truncation(16), M.truncation(12))
        self.assertLess(M.truncation(16) / 16, 2)                             # under two output units with four guard bits


class PlanTests(unittest.TestCase):
    def test_a_result_appears_iter_plus_two_rows_after_its_operands_and_reset_drops_it(self):
        for parameters in (BIG, SMALL):
            w, n, g = shape(parameters)
            p = P.Plan(parameters)
            head = len(p.rows)
            self.assertEqual([r[:3] for r in p.rows], [[1, i, M.residual_bound(i, n, g)] for i in range(n + 1)])
            p.op(0, 100, 0, 0x2000)
            p.drain()
            valid = [r[7] for r in p.rows[head:]]
            self.assertEqual(valid.index(1), n + 2)
            self.assertEqual(sum(valid), 1)
            row = p.rows[head + n + 2]
            self.assertEqual(row[8:11], [v & P.MASK for v in M.cordic(0, 100, 0, 0x2000, w, n, g)[:2]] + [M.cordic(0, 100, 0, 0x2000, w, n, g)[2]])
            q = P.Plan(parameters)
            q.op(1, 5, 5)
            q.cycle(rst=0)
            q.drain()
            self.assertEqual(sum(r[7] for r in q.rows[head:]), 0)

    def test_fixed_rows_hold_each_boundary_and_one_past_it(self):
        for parameters in (BIG, SMALL):
            rows = [r for r in P.boundary_vectors(parameters) if r[0] == 0 and r[1] and r[2]]
            angles = {r[6] for r in rows if not r[3]}
            self.assertLessEqual({0x3fff, 0x4000, 0x4001, 0x7fff, 0x8000, 0x8001, 0xbfff, 0xc000, 0xc001, 0, 0xffff}, angles)
            w = parameters['WIDTH']
            low, top = (1 << (w - 1)) | (P.MASK ^ ((1 << w) - 1)), (1 << (w - 1)) - 1
            vectors = {(r[4], r[5]) for r in rows if r[3]}
            self.assertLessEqual({(0, 0), (top, 0), (low, 0), (0, top), (0, low), (1, 1), (top, top), (low, low)}, vectors)
            c = P.counts(P.boundary_vectors(parameters))
            dropped = c['accepted'] - c['completed']                # the reset empties a pipeline that is partly full
            self.assertTrue(2 <= dropped <= parameters['ITER'] + 2, dropped)
            self.assertEqual(c['accepted'], c['rotations'] + c['vectorings'])

    def test_plan_names_sweep_sizes_and_seed(self):
        smoke, nightly = P.make_cases(args(), BIG), P.make_cases(args('nightly'), BIG)
        names = ['boundaries', 'sweep-rotation', 'sweep-vectoring', 'random-seed17', 'limit-observed', 'limit-one-less',
                 *[f'detect-mutation{m}' for m in range(1, 7)]]
        self.assertEqual([c['id'] for c in smoke], names)
        self.assertEqual([c['id'] for c in nightly], names[:4] + ['random-seed18', 'random-seed19'] + names[4:])
        by = {c['id']: c for c in nightly}
        self.assertEqual(by['sweep-rotation']['counts']['rotations'], 65536)       # every 16-bit angle
        self.assertEqual(by['sweep-vectoring']['counts']['vectorings'], 16384)
        self.assertEqual({c['id']: c['counts']['accepted'] for c in smoke if c['id'].startswith('sweep')},
                         {'sweep-rotation': 4096, 'sweep-vectoring': 4096})
        self.assertEqual({c['id']: (c['category'], c['expected_failure']) for c in smoke if c['expected_failure']},
                         {'limit-one-less': ('diagnostic', 'CORDIC_TOLERANCE'),
                          **{f'detect-mutation{m}': ('mutation', P.LABELS[m]) for m in range(1, 7)}})
        self.assertEqual(smoke, P.make_cases(args(), BIG))
        other = P.make_cases(args(seed=18), BIG)
        self.assertNotEqual(smoke[3]['vectors'], other[3]['vectors'])
        self.assertNotEqual(smoke[1]['vectors'], other[1]['vectors'])               # the thinned sweep moves with the seed
        self.assertEqual(smoke[0]['vectors'], other[0]['vectors'])

    def test_the_two_tightened_cases_differ_by_exactly_one_unit(self):
        for parameters in (BIG, SMALL):
            cases = {c['id']: c for c in P.make_cases(args(), parameters)}
            limit = P.observed_limit(parameters)
            for name, value in (('limit-observed', limit), ('limit-one-less', limit - 1)):
                done = [r for r in cases[name]['vectors'] if r[0] == 0 and r[7]]
                self.assertEqual({(r[14], r[15]) for r in done}, {(value, value)}, name)
            self.assertGreater(limit, 0)
            self.assertLess(limit, M.tolerance(0, (1 << (parameters['WIDTH'] - 1)) - 1, 0, *shape(parameters))[0])


@unittest.skipUnless(ICARUS, 'Icarus required')
class RtlTests(unittest.TestCase):
    def rows(self, edit=None, parameters=SMALL):
        p = P.Plan(parameters)
        p.cycle(rst=0)
        for z in (0x0100, 0x2345, 0x6000, 0xc000):
            p.op(0, 2000, -300, z)
        p.op(1, -700, 900)
        p.drain()
        rows = [list(r) for r in p.rows]
        if edit:
            edit(rows, [i for i, r in enumerate(rows) if r[0] == 0 and r[7]])
        return rows

    def run_rows(self, edit=None, replacements=None):
        return simulate_vectors(P, self.rows(edit), SMALL, replacements).stdout

    def test_each_check_of_the_testbench_fails_alone(self):
        self.assertIn(f'RESULT PASS checks={len(self.rows())}', self.run_rows())

        def exact_only(rows, done):          # one unit off, still inside the tolerance
            rows[done[0]][8] = (rows[done[0]][8] + 1) & P.MASK
        self.assertIn('CHECK_FAIL CORDIC_DATA', self.run_rows(exact_only))

        def angle_only(rows, done):          # the vectoring angle, one unit off
            rows[done[-1]][10] = (rows[done[-1]][10] + 1) & 0xffff
        self.assertIn('CHECK_FAIL CORDIC_DATA', self.run_rows(angle_only))

        def far(rows, done):                 # the reference moved away: tolerance fails before the exact check
            rows[done[1]][12] = (rows[done[1]][12] + 40) & P.MASK
        self.assertIn('CHECK_FAIL CORDIC_TOLERANCE', self.run_rows(far))

        def angle_far(rows, done):
            rows[done[-1]][13] = (rows[done[-1]][13] + 0x4000) & 0xffff
        self.assertIn('CHECK_FAIL CORDIC_TOLERANCE', self.run_rows(angle_far))

        def early(rows, done):
            rows[done[0] - 1][7] = 1
        self.assertIn('CHECK_FAIL CORDIC_VALID', self.run_rows(early))

        def missing(rows, done):
            rows[done[2]][7] = 0
        self.assertIn('CHECK_FAIL CORDIC_VALID', self.run_rows(missing))

        def narrow(rows, done):              # the bound of stage 3 made too small
            rows[3][2] = 1
        self.assertIn('CHECK_FAIL CORDIC_RESIDUAL', self.run_rows(narrow))

    def test_an_unknown_output_is_not_a_pass(self):
        unknown = {'cordic.sv': [('y_out <= y_scaled[KF+GUARD+WIDTH:KF+GUARD];', "y_out <= 'x;")]}
        self.assertIn('CHECK_FAIL CORDIC_UNKNOWN', self.run_rows(replacements=unknown))

    def test_real_rtl_all_configurations_mutants_and_the_tightened_limit(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / 'out'
            result = run_example('local-cordic', out, '--iterations', '20')
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            summary = read_json(out / 'summary.json')
            self.assertEqual((summary['success'], summary['complete'], summary['planned'], summary['results']), (True, True, 24, 24))
            self.assertEqual((summary['functional_pass'], summary['mutations_detected'], summary['diagnostics_pass']), (10, 14, 0))
            coverage = read_json(out / 'coverage.json')
            self.assertEqual({k: (v['hit'], v['missing']) for k, v in coverage.items()}, {k: (GOALS, []) for k in P.CONFIGS})
            suite = ET.parse(out / 'junit.xml').getroot()
            self.assertEqual((suite.get('tests'), suite.get('failures'), suite.get('errors')), ('26', '0', '0'))
            for name in P.CONFIGS:
                for m, label in P.LABELS.items():
                    record = read_json(out / f'{name}-detect-mutation{m}/result.json')
                    self.assertEqual((record['status'], record['credited_coverage']), ('detected', []), (name, m))
                    self.assertIn(label, record['message'])
                tight = read_json(out / f'{name}-limit-one-less/result.json')
                self.assertEqual((tight['status'], tight['category']), ('detected', 'diagnostic'))
                self.assertIn('error/at-limit', read_json(out / f'{name}-limit-observed/result.json')['credited_coverage'])
                self.assertNotIn('error/at-limit', read_json(out / f'{name}-boundaries/result.json')['observed_coverage'])
                self.assertIn('$enddefinitions', (out / f'{name}-sweep-rotation/wave.vcd').read_text())

    def test_demo_faults_make_the_normal_regression_fail(self):
        with tempfile.TemporaryDirectory() as tmp:
            for fault in range(1, P.MUTANTS + 1):
                out = Path(tmp) / str(fault)
                result = run_example('local-cordic', out, '--configuration', 'w12-i12-g2', '--iterations', '2', '--demo-bug', str(fault))
                self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                record = read_json(out / 'w12-i12-g2-boundaries/result.json')
                self.assertEqual(record['status'], 'fail')
                self.assertIn(P.LABELS[fault], record['message'])
                self.assertEqual(read_json(out / 'w12-i12-g2-limit-one-less/result.json')['status'], 'detected')   # always the correct circuit


if __name__ == '__main__':
    unittest.main()

import json
from pathlib import Path
import random
import shutil
import sys
import tempfile
from types import SimpleNamespace
import unittest
import xml.etree.ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'local-common'))
from local_test_support import load_example, read_json, run_example, simulate_vectors

P = load_example('local-iir-biquad')
M = P.M
FINE = P.CONFIGS['sat-nearest']
GOALS = 20


def args(**changes):
    return SimpleNamespace(**{**dict(profile='smoke', seed=17, iterations=4, demo_bug=0), **changes})


def outputs(rows):
    return [P.signed24(r[11]) for r in rows if r[0] and r[10] and r[7]]


class ModelTest(unittest.TestCase):
    def test_the_three_rounding_modes_differ_only_where_they_should(self):
        half = 1 << 13
        table = {half: (0, 1, 0), -half: (-1, 0, 0), 3 * half: (1, 2, 1), -3 * half: (-2, -1, -1),
                 2 * half: (1, 1, 1), -2 * half: (-1, -1, -1), 1: (0, 0, 0), -1: (-1, 0, 0)}
        for acc, expected in table.items():
            self.assertEqual(tuple(M.quantize(acc, 14, mode) for mode in (M.FLOOR, M.NEAREST, M.TOWARD_ZERO)), expected, acc)

    def test_limits_are_exact_at_the_ends_and_flagged_one_past_them(self):
        self.assertEqual(M.limit(M.MAX, True), (M.MAX, 0, 0))
        self.assertEqual(M.limit(M.MIN, True), (M.MIN, 0, 0))
        self.assertEqual(M.limit(M.MAX + 1, True), (M.MAX, 1, 0))
        self.assertEqual(M.limit(M.MIN - 1, True), (M.MIN, 0, 1))
        self.assertEqual(M.limit(M.MAX + 1, False), (M.MIN, 1, 0))
        self.assertEqual(M.limit(M.MIN - 1, False), (M.MAX, 0, 1))

    def test_the_integer_model_equals_exact_rational_arithmetic_when_nothing_is_rounded(self):
        # Integer coefficients (frac such that every product is a multiple of 2**frac): no rounding at all.
        rng = random.Random(3)
        for _ in range(200):
            coefficients = [rng.randint(-3, 3) << 6 for _ in range(5)]
            samples = [rng.randint(-50, 50) for _ in range(12)]
            x1 = x2 = y1 = y2 = 0
            expected = []
            for x in samples:
                y = (coefficients[0] * x + coefficients[1] * x1 + coefficients[2] * x2 - coefficients[3] * y1 - coefficients[4] * y2) // 64
                y = max(M.MIN, min(M.MAX, y))
                expected.append(y)
                x2, x1, y2, y1 = x1, x, y1, y
            for mode in (M.FLOOR, M.NEAREST, M.TOWARD_ZERO):
                self.assertEqual([v for v, _, _ in M.run(coefficients, samples, 6, mode, True)], expected)

    def test_coefficient_rounding_bound_holds_for_many_designs(self):
        rng = random.Random(5)
        for _ in range(60):
            design = M.design_lowpass(rng.uniform(0.02, 0.45), rng.uniform(0.5, 10))
            for frac in (6, 10, 14):
                fixed = M.to_fixed(design, frac)
                if M.pole_radius(M.to_real(fixed, frac)) >= 1:
                    continue
                for omega in M.grid(32):
                    error = abs(M.response(M.to_real(fixed, frac), omega) - M.response(design, omega))
                    self.assertLessEqual(error, M.coefficient_bound(design, fixed, frac, omega) * (1 + 1e-9))

    def test_measurement_bound_holds_for_many_stable_designs_and_all_rounding_modes(self):
        rng = random.Random(7)
        for _ in range(25):
            design = M.design_lowpass(rng.uniform(0.05, 0.4), rng.uniform(0.5, 3))
            fixed = M.to_fixed(design, 14)
            real = M.to_real(fixed, 14)
            for mode in (M.FLOOR, M.NEAREST, M.TOWARD_ZERO):
                result = M.run(fixed, [P.IMPULSE_AMPLITUDE] + [0] * (P.IMPULSE_LENGTH - 1), 14, mode, True)
                self.assertFalse(any(high or low for _, high, low in result))
                bound = M.measurement_bound(fixed, 14, mode, P.IMPULSE_AMPLITUDE, P.IMPULSE_LENGTH)['total']
                for omega in M.grid(16):
                    measured = M.dft([y for y, _, _ in result], omega) / P.IMPULSE_AMPLITUDE
                    self.assertLessEqual(abs(measured - M.response(real, omega)), bound)

    def test_the_low_pass_has_unit_gain_at_dc_and_a_coefficient_word_can_hold_it(self):
        self.assertAlmostEqual(abs(M.response(P.LOWPASS, 0.0)), 1.0, places=12)
        with self.assertRaises(ValueError):
            M.to_fixed([2.0, 0, 0, 0, 0], 14)


class PlanTest(unittest.TestCase):
    def test_the_plan_is_fixed_and_equivalent_mutants_are_named_as_such(self):
        for name, parameters in P.CONFIGS.items():
            cases = P.make_cases(args(), parameters)
            ids = [c['id'] for c in cases]
            self.assertEqual(ids[:5], ['boundaries', 'impulse', 'limit-cycle', 'overflow', 'random-seed17'])
            equivalents = [i for i in ids if i.startswith('equivalent')]
            expected = (['equivalent-mutation7'] if not parameters['SAT'] else []) + \
                       (['equivalent-mutation8'] if parameters['ROUND'] == M.FLOOR else [])
            self.assertEqual(equivalents, expected, name)
            self.assertEqual(len(ids), 5 + P.MUTANTS)
            self.assertEqual(len(P.make_cases(args(profile='nightly'), parameters)), 7 + P.MUTANTS)

    def test_seed_reproduces_and_changes_the_random_stimulus(self):
        first = P.make_cases(args(), FINE)
        self.assertEqual(first, P.make_cases(args(), FINE))
        self.assertNotEqual(first[4]['vectors'], P.make_cases(args(seed=18), FINE)[4]['vectors'])

    def test_a_changed_phenomenon_stops_the_run_before_any_simulation(self):
        saved = dict(P.PHENOMENA['sat-zero'])
        try:
            P.PHENOMENA['sat-zero']['limit_tail_nonzero'] = 1
            with self.assertRaisesRegex(ValueError, 'pinned behaviour'):
                P.make_cases(args(), P.CONFIGS['sat-zero'])
        finally:
            P.PHENOMENA['sat-zero'] = saved

    def test_fixed_scenario_alone_reaches_the_goals_it_owns(self):
        # Every goal except the three window goals is reached by the fixed scenario, not by luck.
        rows = P.boundary_vectors(FINE)
        counts = P.counts(rows)
        self.assertEqual((counts['overflow_pos'], counts['overflow_neg']), (1, 1))
        self.assertEqual(counts['accepted'], counts['completed'] + 1)  # one result is dropped by the reset
        self.assertTrue(any(r[1] and r[5] for r in rows))              # clear with an offered sample
        self.assertTrue(any(r[2] and r[3] > 4 for r in rows))          # ignored address
        self.assertTrue(any(r[5] and not r[9] and not r[1] for r in rows))  # an offer that must wait
        self.assertTrue(any(r[9] and not r[5] for r in rows))          # ready without an offer


class BehaviourTest(unittest.TestCase):
    def test_wrapping_sustains_a_large_oscillation_that_saturation_ends(self):
        wrap = outputs(P.overflow_vectors(P.CONFIGS['wrap-nearest']))[-P.TAIL:]
        sat = outputs(P.overflow_vectors(P.CONFIGS['sat-nearest']))[-P.TAIL:]
        self.assertTrue(all(abs(v) >= P.LARGE for v in wrap))
        self.assertGreater(max(map(abs, wrap)), 6 * P.LARGE)   # about 0.8 of full scale, with zero input
        self.assertLessEqual(max(map(abs, sat)), 8)             # only the small limit cycle is left

    def test_limit_cycle_depends_on_the_rounding_mode(self):
        tails = {name: outputs(P.limit_vectors(P.CONFIGS[name]))[-P.TAIL:] for name in ('sat-nearest', 'sat-floor', 'sat-zero')}
        self.assertEqual(set(tails['sat-zero']), {0})                         # magnitude truncation: dies out
        self.assertTrue(min(tails['sat-nearest']) < 0 < max(tails['sat-nearest']))
        self.assertLessEqual(max(map(abs, tails['sat-nearest'])), 4)
        self.assertNotIn(0, tails['sat-floor'])                               # floor: never rests at zero
        self.assertLessEqual(max(map(abs, tails['sat-floor'])), 8)
        self.assertEqual({n: P.phenomena(p) for n, p in P.CONFIGS.items()}, P.PHENOMENA)

    def test_clear_restarts_the_response_and_reset_also_clears_the_coefficients(self):
        p = P.Plan(FINE)
        p.cycle(rst=0)
        p.load(P.fixed(P.RESONANT, 14))
        burst = [100000, -50000, 25000, 0]
        p.run(burst)
        p.cycle()
        first = outputs(p.rows)
        p.cycle(clear=1)
        p.run(burst)
        p.cycle()
        self.assertEqual(outputs(p.rows)[len(first):], first)
        p.cycle(rst=0)
        p.run([12345])
        p.flush()
        self.assertEqual(outputs(p.rows)[-1], 0)

    def test_a_coefficient_written_with_a_sample_applies_from_the_next_sample(self):
        p = P.Plan(FINE)
        p.cycle(rst=0)
        p.load([1 << 14, 0, 0, 0, 0])
        p.cycle(we=1, addr=0, data=2 << 13 << 1 >> 1, valid=1, x=100)  # same word: unity
        p.cycle(we=1, addr=0, data=1 << 13, valid=1, x=100)            # half gain, written with this sample
        p.run([100])
        p.flush()
        self.assertEqual(outputs(p.rows), [100, 100, 50])


class FrequencyTest(unittest.TestCase):
    def samples(self, parameters, scale=1.0):
        result = M.run(P.fixed(P.LOWPASS, parameters['FRAC']), [P.IMPULSE_AMPLITUDE] + [0] * (P.IMPULSE_LENGTH - 1),
                       parameters['FRAC'], parameters['ROUND'], bool(parameters['SAT']))
        return [int(y * scale) for y, _, _ in result]

    def test_every_configuration_meets_its_pinned_result(self):
        for name, parameters in P.CONFIGS.items():
            report = P.frequency_report(self.samples(parameters), parameters, P.DESIGN_MET[name])
            self.assertTrue(report['success'], (name, report['problems']))
            self.assertEqual(report['design_guaranteed'], name != 'coarse')
        coarse = P.frequency_report(self.samples(P.CONFIGS['coarse']), P.CONFIGS['coarse'], True)
        self.assertIn('design tolerance result differs from the pinned expectation', coarse['problems'])

    def test_a_gain_error_a_missing_sample_and_a_wrong_filter_are_rejected(self):
        good = self.samples(FINE)
        self.assertIn('measured response is outside the rounding bound', P.frequency_report(self.samples(FINE, 1.001), FINE)['problems'])
        self.assertIn('impulse response has the wrong length', P.frequency_report(good[:-1], FINE)['problems'])
        delayed = [0] + good[:-1]
        self.assertFalse(P.frequency_report(delayed, FINE)['success'])

    def test_one_coefficient_lsb_is_below_the_tolerance_check_but_not_below_the_bit_match(self):
        # The tolerance check cannot replace the bit-exact comparison: this is why both exist.
        fixed = P.fixed(P.LOWPASS, 14)
        off = list(fixed)
        off[3] += 1
        wrong = [y for y, _, _ in M.run(off, [P.IMPULSE_AMPLITUDE] + [0] * (P.IMPULSE_LENGTH - 1), 14, M.NEAREST, True)]
        self.assertNotEqual(wrong, self.samples(FINE))
        self.assertTrue(P.frequency_report(wrong, FINE)['success'])


class CheckerTest(unittest.TestCase):
    """The bench must report each kind of difference under its own label."""

    def small(self):
        p = P.Plan(FINE)
        p.cycle(rst=0)
        p.load([1 << 14, 1 << 14, 0, 0, 0])
        p.sample(5, stall=2)
        p.run([M.MAX, M.MIN, -1])
        p.flush()
        return p.rows

    def label(self, rows, replacements=None):
        result = simulate_vectors(P, rows, FINE, replacements)
        failures = [line for line in result.stdout.splitlines() if line.startswith('CHECK_FAIL')]
        return failures[0].split()[1] if failures else ('PASS' if 'RESULT PASS' in result.stdout else 'NONE')

    def test_untouched_vectors_pass(self):
        self.assertEqual(self.label(self.small()), 'PASS')

    def test_each_expected_value_is_compared(self):
        for column, expected in ((11, 'IIR_DATA'), (12, 'IIR_FLAG'), (13, 'IIR_FLAG'), (9, 'IIR_CONTROL'), (10, 'IIR_CONTROL')):
            rows = [list(r) for r in self.small()]
            index = next(i for i, r in enumerate(rows) if r[10] and r[7])
            rows[index][column] ^= 1
            self.assertEqual(self.label(rows), expected, column)

    def test_an_unknown_output_is_a_failure(self):
        edit = {'iir_biquad.sv': [("result<=limited;", "result<=24'bx;")]}
        self.assertEqual(self.label(self.small(), edit), 'IIR_DATA')
        edit = {'iir_biquad.sv': [("ovf_pos<=high;", "ovf_pos<=1'bx;")]}
        self.assertEqual(self.label(self.small(), edit), 'IIR_FLAG')

    def test_a_stalled_result_that_changes_is_reported_as_a_hold_failure(self):
        # The circuit increments a waiting result; the expected values are bent to follow it, so
        # only the bench's own memory of the stalled value can notice.
        edit = {'iir_biquad.sv': [("end else if(out_valid && out_ready)out_valid<=1'b0;",
                                   "end else if(out_valid && out_ready)out_valid<=1'b0;\n   else if(out_valid)result<=result+24'sd1;")]}
        rows = [list(r) for r in self.small()]
        stalled = [i for i, r in enumerate(rows) if r[10] and not r[7]]
        for extra, index in enumerate(stalled):
            rows[index][11] += extra
        rows[stalled[-1] + 1][11] += len(stalled)
        self.assertEqual(self.label(rows, edit), 'IIR_HOLD')

    def test_the_watchdog_has_its_own_label(self):
        edit = {'iir_biquad_tb.sv': [('#50000000;', '#30;')]}
        self.assertEqual(self.label(self.small(), edit), 'IIR_TIMEOUT')


class RunnerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not (shutil.which('iverilog') and shutil.which('vvp')):
            raise RuntimeError('Icarus Verilog is required for this example')
        cls.tmp = tempfile.TemporaryDirectory()
        cls.out = Path(cls.tmp.name) / 'out'
        cls.result = run_example('local-iir-biquad', cls.out, '--iterations', '6')

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_whole_plan_passes_with_complete_evidence(self):
        self.assertEqual(self.result.returncode, 0, self.result.stdout + self.result.stderr)
        summary = read_json(self.out / 'summary.json')
        self.assertTrue(summary['success'] and summary['complete'])
        self.assertEqual((summary['planned'], summary['results']), (70, 70))
        self.assertEqual((summary['functional_pass'], summary['mutations_detected'], summary['diagnostics_pass']), (25, 43, 2))
        self.assertEqual(set(summary['frequency_response']), set(P.CONFIGS))
        coverage = read_json(self.out / 'coverage.json')
        self.assertEqual({name: item['hit'] for name, item in coverage.items()}, {name: GOALS for name in P.CONFIGS})
        suite = ET.parse(self.out / 'junit.xml').getroot()
        self.assertEqual((suite.get('tests'), suite.get('failures'), suite.get('errors')), ('80', '0', '0'))
        self.assertEqual(len(suite.findall('testcase')), 80)
        report = read_json(self.out / 'frequency-response.json')
        self.assertFalse(report['coarse']['design_within_tolerance'])
        self.assertTrue(report['sat-nearest']['design_within_tolerance'])
        manifest = read_json(self.out / 'manifest.json')
        self.assertIn('examples/local-iir-biquad/model.py', manifest['source_sha256'])

    def test_fixed_scenario_reaches_every_goal_but_the_window_goals(self):
        hits = read_json(self.out / 'coverage.json')['sat-nearest']['hits']
        elsewhere = {'impulse/sample', 'limit/zero-input-tail', 'overflow/zero-input-tail'}
        missing = [goal for goal, cases in hits.items() if goal not in elsewhere and 'sat-nearest-boundaries' not in cases]
        self.assertEqual(missing, [])

    def test_a_bent_impulse_response_fails_the_frequency_check_and_the_evidence(self):
        copy = Path(self.tmp.name) / 'copy'
        shutil.copytree(self.out, copy)
        log = copy / 'sat-nearest-impulse/simulation.log'
        lines = log.read_text().splitlines()
        first = next(i for i, line in enumerate(lines) if 'phase=3' in line)
        lines[first] = lines[first].rsplit('=', 1)[0] + '=' + str(int(lines[first].rsplit('=', 1)[1]) + 50000)
        log.write_text('\n'.join(lines) + '\n')
        self.assertFalse(P.judge_frequency(copy, P.CONFIGS))
        self.assertFalse(read_json(copy / 'summary.json')['success'])
        suite = ET.parse(copy / 'junit.xml').getroot()
        self.assertEqual(suite.get('failures'), '1')
        self.assertEqual(len(suite.findall('testcase')), 80)

    def test_demo_bug_fails_where_it_applies_and_is_harmless_where_it_is_equivalent(self):
        applies = run_example('local-iir-biquad', Path(self.tmp.name) / 'bug', '--configuration', 'sat-nearest',
                              '--iterations', '3', '--demo-bug', '7')
        self.assertEqual(applies.returncode, 1, applies.stdout + applies.stderr)
        self.assertEqual(read_json(Path(self.tmp.name) / 'bug/sat-nearest-boundaries/result.json')['status'], 'fail')
        same = run_example('local-iir-biquad', Path(self.tmp.name) / 'same', '--configuration', 'wrap-nearest',
                           '--iterations', '3', '--demo-bug', '7')
        self.assertEqual(same.returncode, 0, same.stdout + same.stderr)

    def test_every_mutant_fails_the_ordinary_run_of_a_configuration_it_changes(self):
        for mutant in range(1, P.MUTANTS + 1):
            with self.subTest(mutant=mutant):
                out = Path(self.tmp.name) / f'm{mutant}'
                result = run_example('local-iir-biquad', out, '--configuration', 'sat-nearest', '--iterations', '2',
                                     '--demo-bug', str(mutant))
                self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                self.assertEqual(read_json(out / 'sat-nearest-boundaries/result.json')['status'], 'fail')


if __name__ == '__main__':
    unittest.main()

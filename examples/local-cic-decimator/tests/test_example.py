from pathlib import Path
import random
import shutil
import sys
import tempfile
from types import SimpleNamespace
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'local-common'))
from local_test_support import assert_evidence, load_example, read_json, run_example, simulate_vectors

P = load_example('local-cic-decimator')
SHAPES = {name: (c['STAGES'], c['RATE'], c['DELAY']) for name, c in P.CONFIGS.items()}
GOALS = 14


def signed(value, width):
    value &= (1 << width) - 1
    return value - (1 << width) if value >> (width - 1) else value


def fir_coefficients(stages, rate, delay):
    """Coefficients of (1 + z + ... + z**(rate*delay-1)) ** stages."""
    taps = [1]
    for _ in range(stages):
        taps = [sum(taps[i - j] for j in range(rate * delay) if 0 <= i - j < len(taps))
                for i in range(len(taps) + rate * delay - 1)]
    return taps


def integrator_comb(samples, stages, rate, delay, width):
    """The hardware structure in modular arithmetic: integrators, decimation, combs."""
    integ, lines, outputs = [0] * stages, [[0] * delay for _ in range(stages)], []
    for index, sample in enumerate(samples):
        carry = sample
        for i in range(stages):
            integ[i] = signed(integ[i] + carry, width)
            carry = integ[i]
        if (index + 1) % rate == 0:
            for i in range(stages):
                carry, lines[i] = signed(carry - lines[i][-1], width), [carry] + lines[i][:-1]
            outputs.append(carry)
    return outputs


def outputs(rows, width):
    return [signed(r[5], width) for r in rows if r[4]]


class ModelTests(unittest.TestCase):
    def test_impulse_response_is_the_power_of_the_moving_sum(self):
        for shape in SHAPES.values():
            stages, rate, delay = shape
            taps = fir_coefficients(*shape)
            self.assertEqual(sum(taps), P.gain(*shape))
            for offset in range(rate):                      # every decimation phase of the impulse
                model = P.Model(*shape)
                got = [model.accept(int(n == offset)) for n in range(len(taps) + 2 * rate)]
                want = [taps[n - offset] if 0 <= n - offset < len(taps) else 0
                        for n in range(len(got)) if (n + 1) % rate == 0]
                self.assertEqual([v for v in got if v is not None], want)

    def test_wrapping_integrators_and_combs_give_the_exact_sum(self):
        rng = random.Random(7)
        for shape in SHAPES.values():
            width = P.output_width(*shape)
            for constant in (P.LOW, P.HIGH):
                # The first integrator alone holds the running sum, so here it goes around more than once.
                self.assertGreater(abs(400 * constant), 2 << (width - 1))
            for samples in ([P.LOW] * 400, [P.HIGH] * 400, [rng.randrange(P.LOW, P.HIGH + 1) for _ in range(600)]):
                model = P.Model(*shape)
                exact = [v for v in (model.accept(s) for s in samples) if v is not None]
                self.assertEqual(integrator_comb(samples, *shape, width), exact)

    def test_the_width_is_needed_and_enough(self):
        for shape in SHAPES.values():
            width, g = P.output_width(*shape), P.gain(*shape)
            self.assertLessEqual(-(1 << (width - 1)), P.LOW * g)
            self.assertLess(P.HIGH * g, 1 << (width - 1))
            self.assertLess(P.LOW * g, -(1 << (width - 2)))           # one bit less is not enough
            model = P.Model(*shape)
            steady = [v for v in (model.accept(P.LOW) for _ in range(40 * shape[1])) if v is not None][-1]
            self.assertEqual(steady, P.LOW * g)
        self.assertEqual(P.output_width(3, 4, 1), 14)                 # 8 + log2(64)
        self.assertEqual(P.output_width(2, 5, 2), 15)                 # 8 + ceil(log2(100))

    def test_fitting_amplitudes_are_exactly_at_the_edge_of_one_bit_less(self):
        for shape in SHAPES.values():
            half, g = 1 << (P.output_width(*shape) - 2), P.gain(*shape)
            low, high = P.fitting_amplitudes(*shape)
            self.assertTrue(-half <= low * g and (low - 1) * g < -half)
            self.assertTrue(high * g <= half - 1 and (high + 1) * g > half - 1)
            self.assertTrue(P.LOW < low - 1 and high + 1 < P.HIGH)

    def test_a_restart_discards_history_and_realigns_the_phase(self):
        shape = SHAPES['n3-r4-m1']
        plan = P.Plan(*shape)
        plan.reset()
        plan.samples([100] * 6)                       # one output, two samples into the next period
        plan.sync(with_sample=True)                   # the sample offered with sync is not accepted
        plan.samples([1] * 4)
        plan.flush()
        self.assertEqual(outputs(plan.rows, plan.model.width), [2000, 20])   # (1+3+6+10) times 100, then times 1
        self.assertEqual(P.counts(plan.rows), dict(accepted=10, outputs=2))

    def test_idle_cycles_do_not_count_and_their_data_is_ignored(self):
        shape = SHAPES['n2-r5-m2']
        a, b = P.Plan(*shape), P.Plan(*shape)
        values = [5, -6, 7, -8, 9, 10, -11, 12, 13, -14]
        a.reset(); a.samples(values); a.flush()
        b.reset(); b.samples(values, gaps={1: 2, 4: 1, 9: 3}); b.flush()
        self.assertEqual(outputs(a.rows, a.model.width), outputs(b.rows, b.model.width))
        self.assertTrue(all(r[3] == P.IDLE_DATA for r in b.rows if r[0] and not r[1] and not r[2]))


class PlanTests(unittest.TestCase):
    def cases(self, name, profile='smoke', seed=17, iterations=5):
        args = SimpleNamespace(profile=profile, seed=seed, iterations=iterations, demo_bug=0)
        return P.make_cases(args, P.CONFIGS[name])

    def test_plan_names_labels_and_seed(self):
        for name in P.CONFIGS:
            cases = self.cases(name)
            self.assertEqual([c['id'] for c in cases],
                             ['boundaries', 'small-signal', 'random-seed17', *[f'detect-mutation{m}' for m in range(1, 8)],
                              'survive-mutation1-small-signal', 'detect-mutation7-small-signal'])
            self.assertEqual([c['expected_failure'] for c in cases[3:10]], [P.LABELS[m] for m in range(1, 8)])
            self.assertEqual((cases[10]['category'], cases[10]['expected_failure'], cases[10]['mutation']), ('diagnostic', None, 1))
            self.assertEqual(len(self.cases(name, 'nightly')), len(cases) + 2)
            self.assertEqual(cases, self.cases(name))
            self.assertNotEqual(cases[2]['vectors'], self.cases(name, seed=18)[2]['vectors'])

    def test_fixed_scenarios_stay_on_their_side_of_the_narrow_range(self):
        for name, shape in SHAPES.items():
            width = P.output_width(*shape)
            half = 1 << (width - 2)
            small = outputs(P.small_signal_vectors(*shape), width)
            self.assertTrue(all(-half <= v < half for v in small))
            for amplitude in P.fitting_amplitudes(*shape):
                self.assertIn(amplitude * P.gain(*shape), small)
            big = outputs(P.boundary_vectors(*shape), width)
            self.assertIn(P.LOW * P.gain(*shape), big)
            self.assertIn(P.HIGH * P.gain(*shape), big)
            low, high = P.fitting_amplitudes(*shape)
            for value in ((high + 1) * P.gain(*shape), (low - 1) * P.gain(*shape), high * P.gain(*shape), low * P.gain(*shape)):
                self.assertIn(value, big)

    def test_the_crossing_segment_passes_half_range_on_an_output_sample(self):
        for shape in SHAPES.values():
            half = 1 << (P.output_width(*shape) - 2)
            for amplitude in (P.HIGH, P.LOW, *P.fitting_amplitudes(*shape)):
                total, first = 0, None
                for index, value in enumerate(P.crossing(amplitude, *shape)):
                    total += value
                    if first is None and not -half <= total < half:
                        first = index
                self.assertEqual((first + 1) % shape[1], 0, (shape, amplitude))

    def test_fixed_scenario_has_every_rule_on_its_own_row(self):
        for shape in SHAPES.values():
            rows = P.boundary_vectors(*shape)
            self.assertTrue(any(r[0] and r[2] and r[1] for r in rows))            # sync with a sample
            self.assertTrue(any(r[0] and r[2] and not r[1] for r in rows))        # sync alone
            self.assertTrue(any(r[0] and not r[1] and not r[2] for r in rows))    # idle
            self.assertGreaterEqual(sum(not r[0] for r in rows), 2)               # reset twice


class RtlTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(shutil.which('iverilog') and shutil.which('vvp'), 'Icarus Verilog is required')

    def test_all_configurations_mutants_and_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / 'out'
            result = run_example('local-cic-decimator', out, '--iterations', '4')
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            assert_evidence(self, out, P.CONFIGS, GOALS, 12 * len(P.CONFIGS), diagnostics=len(P.CONFIGS), mutants=8)
            for name in P.CONFIGS:
                hits = read_json(out / 'coverage.json')[name]['hits']
                self.assertTrue(all(f'{name}-boundaries' in cases for cases in hits.values()), hits)
                self.assertEqual(read_json(out / f'{name}-survive-mutation1-small-signal/result.json')['status'], 'pass')

    def test_demo_faults_make_the_normal_regression_fail(self):
        with tempfile.TemporaryDirectory() as tmp:
            for fault in range(1, P.MUTANTS + 1):
                with self.subTest(fault=fault):
                    out = Path(tmp) / str(fault)
                    result = run_example('local-cic-decimator', out, '--configuration', 'n2-r5-m2', '--iterations', '2', '--demo-bug', str(fault))
                    self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                    record = read_json(out / 'n2-r5-m2-boundaries/result.json')
                    self.assertEqual((record['status'], record['message']), ('fail', 'checker failure: ' + P.LABELS[fault]))

    def test_the_checker_reports_a_wrong_value_a_wrong_time_and_an_unknown_output(self):
        shape = SHAPES['n3-r4-m1']
        rows = P.boundary_vectors(*shape)[:60]
        good = simulate_vectors(P, rows, P.CONFIGS['n3-r4-m1'])
        self.assertIn('RESULT PASS checks=60', good.stdout, good.stdout + good.stderr)
        first = next(i for i, r in enumerate(rows) if r[4])
        wrong_value = [list(r) for r in rows]
        wrong_value[first][5] ^= 1
        wrong_time = [list(r) for r in rows]
        wrong_time[first][4] = 0
        for changed, label in ((wrong_value, 'CIC_DATA'), (wrong_time, 'CIC_VALID')):
            result = simulate_vectors(P, changed, P.CONFIGS['n3-r4-m1'])
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('CHECK_FAIL ' + label, result.stdout)
            self.assertNotIn('RESULT PASS', result.stdout)
        unknown = simulate_vectors(P, rows, P.CONFIGS['n3-r4-m1'],
                                   {'cic_decimator.sv': [('out_data <= diff[STAGES-1];', "out_data <= {OUT_W{1'bx}};")]})
        self.assertIn('CHECK_FAIL CIC_DATA', unknown.stdout)


if __name__ == '__main__':
    unittest.main()

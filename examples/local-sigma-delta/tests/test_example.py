import json
import re
import math
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'local-common'))
from local_test_support import load_example, read_json, run_example

P = load_example('local-sigma-delta')
M = P.M
GOALS = 14


def signed(value, width):
    value &= (1 << width) - 1
    return value - (1 << width) if value >> (width - 1) else value


def integrator_comb(samples, stages, width):
    """The hardware structure in modular arithmetic: integrators, decimation, combs."""
    integ, combs, outputs = [0] * stages, [0] * stages, []
    for index, sample in enumerate(samples):
        carry = sample
        for i in range(stages):
            integ[i] = signed(integ[i] + carry, width)
            carry = integ[i]
        if (index + 1) % M.RATE == 0:
            for i in range(stages):
                carry, combs[i] = signed(carry - combs[i], width), carry
            outputs.append(carry)
    return outputs


def write_log(directory, window, peak):
    directory.mkdir(parents=True)
    lines = [f'OBS SD y={v}' for v in window] + [f'OBS SD peak_milli={round(peak * 1000)}']
    (directory / 'simulation.log').write_text('\n'.join(lines) + '\n')


def fake_evidence(root, name, parameters, change=None):
    """The four logs the SNR judgment reads, written from the model (optionally altered)."""
    order, stages = parameters['ORDER'], parameters['STAGES']
    cases = {'sine-nominal': (stages, M.sine_codes(M.NOMINAL_AMPLITUDE, stages)),
             'dc-idle': (stages, M.dc_codes(M.IDLE_DC_CODE, stages)),
             'overload': (stages, M.sine_codes(M.OVERLOAD_AMPLITUDE, stages)),
             'shared-fewer-stages': (stages - 1, M.sine_codes(M.NOMINAL_AMPLITUDE, stages - 1))}
    for case, (used, codes) in cases.items():
        window = P.model_window(order, used, codes)
        peak = {1: 1.0, 2: 4.0}[order] if case != 'overload' else {1: 1.98, 2: 66.7}[order]
        if change:
            window, peak = change(case, window, peak)
        write_log(root / f'{name}-{case}', window, peak)


class ModelTests(unittest.TestCase):
    def test_every_modulator_value_is_an_exact_dyadic_rational(self):
        # This is why the testbench's reals and Python's floats give the same bits on any host.
        for order in (1, 2):
            m = M.Modulator(order)
            for code in M.sine_codes(M.OVERLOAD_AMPLITUDE, order + 1)[:4000]:
                y = m.decide()
                m.advance(code, y)
                for value in (m.s1, m.s2):
                    self.assertEqual(value * M.SCALE, int(value * M.SCALE))
                    self.assertLess(abs(value), 1 << 20)

    def test_the_two_loops_have_the_intended_noise_transfer(self):
        # y = z^-L x + (1 - z^-1)^L e: with e = y - (last state), the residue vanishes.
        for order in (1, 2):
            m = M.Modulator(order)
            xs, ys, es = [], [], []
            for code in M.sine_codes(0.3, order + 1)[:2000]:
                y = m.decide()
                es.append(y - m.last())
                xs.append(code / M.SCALE)
                ys.append(y)
                m.advance(code, y)
            for n in range(4, 2000):
                if order == 1:
                    rhs = xs[n - 1] + es[n] - es[n - 1]
                else:
                    rhs = xs[n - 2] + es[n] - 2 * es[n - 1] + es[n - 2]
                self.assertAlmostEqual(ys[n], rhs, places=9)

    def test_moving_sums_equal_integrators_and_combs_in_the_output_width(self):
        for stages in (1, 2, 3):
            bits = M.modulate(M.dc_codes(M.CODE_MAX // 2, 3)[:3000], 2)
            self.assertEqual(M.decimate(bits, stages), integrator_comb(bits, stages, M.output_width(stages)))
            self.assertEqual(M.output_width(stages), 2 + 5 * stages)

    def test_theory_and_linear_predictions(self):
        self.assertAlmostEqual(M.theory_db(1, 0.5), 35.72, places=2)
        self.assertAlmostEqual(M.theory_db(2, 0.5), 58.10, places=2)
        for order in (1, 2):
            self.assertAlmostEqual(M.linear_db(order, order + 1, 0.5), M.linear_db(order, order + 1, 0.5, steps=100000), places=3)
        # The CIC passes less in-band noise than an ideal low-pass only when it has enough stages.
        self.assertGreater(M.linear_db(1, 2, 0.5), M.theory_db(1, 0.5))
        self.assertLess(M.linear_db(2, 2, 0.5), M.linear_db(2, 3, 0.5) - 10)

    def test_snr_and_spur_arithmetic_on_synthetic_signals(self):
        n = M.WINDOW
        two = [3.0 * math.sin(2 * math.pi * 5 * i / n) + 0.03 * math.sin(2 * math.pi * 40 * i / n) for i in range(n)]
        self.assertAlmostEqual(M.snr_db(two), 40.0, places=6)
        # A DC offset is not noise: the CIC output of a DC input is mostly DC.
        self.assertAlmostEqual(M.snr_db([v + 2.0 for v in two]), 40.0, places=6)
        full = [M.gain(2) * math.sin(2 * math.pi * 9 * i / n) for i in range(n)]
        self.assertAlmostEqual(M.spur_dbfs(full, 2), 0.0, places=6)
        with self.assertRaises(ValueError):
            M.snr_db([math.sin(2 * math.pi * 5 * i / n) for i in range(n)])

    def test_the_recorded_envelope_is_what_the_model_gives(self):
        for order in (1, 2):
            self.assertEqual(M.recorded_envelope(order), M.ENVELOPE[order])


class PlanTests(unittest.TestCase):
    def test_the_measurement_window_marks_exactly_the_window_outputs(self):
        for name, parameters in P.CONFIGS.items():
            rows = P.measurement(parameters['ORDER'], parameters['STAGES'], M.dc_codes(M.IDLE_DC_CODE, parameters['STAGES']))
            marked = [r for r in rows if r[5]]
            self.assertEqual(sum(r[3] for r in marked), M.WINDOW, name)
            self.assertEqual({r[1] for r in marked}, {M.IDLE_DC_CODE})
            first = rows.index(marked[0])
            self.assertEqual(sum(r[3] for r in rows[:first]), M.settle(parameters['STAGES']))

    def test_the_cases_and_their_expected_failures(self):
        args = type('A', (), dict(seed=17, profile='smoke', iterations=200, demo_bug=0))()
        cases = P.make_cases(args, P.CONFIGS['order2'])
        self.assertEqual([c['id'] for c in cases], ['boundaries', 'sine-nominal', 'dc-idle', 'overload', 'random-seed17'] +
                         [f'detect-mutation{m}' for m in range(1, 9)] + ['shared-fewer-stages'])
        self.assertEqual({c['expected_failure'] for c in cases if c['category'] == 'mutation'}, {'SD_BITS', 'SD_CIC', 'SD_VALID'})
        shared = cases[-1]
        self.assertEqual((shared['mutation'], shared['category']), (P.FEWER_STAGES, 'diagnostic'))
        # The shared case expects the outputs of a CIC with one stage fewer, at its own width.
        self.assertLess(max(r[4] for r in shared['vectors']), 1 << M.output_width(2))

    def test_the_boundaries_reach_both_full_scale_codes_and_a_reset_with_history(self):
        rows = P.boundary_vectors(1, 2)
        codes = {r[1] for r in rows if r[0]}
        self.assertTrue({M.CODE_MAX, M.CODE_MIN & 0xffff} <= codes)
        resets = [i for i in range(1, len(rows)) if rows[i - 1][0] and not rows[i][0]]
        self.assertEqual(len(resets), 1)


class JudgeTests(unittest.TestCase):
    def judge(self, change=None, name='order2'):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            fake_evidence(out, name, P.CONFIGS[name], change)
            return P.judge(name, P.CONFIGS[name], out)

    def test_the_model_windows_pass_every_check(self):
        for name in P.CONFIGS:
            report, checks = self.judge(name=name)
            self.assertEqual(checks, {k: [] for k in ('snr-nominal', 'idle-tone', 'overload', 'shared-fewer-stages')}, name)
            self.assertTrue(report['shared_fewer_stages']['caught_by_snr'])

    def test_a_logged_window_that_differs_from_the_model_is_reported(self):
        def change(case, window, peak):
            if case == 'sine-nominal':
                window = list(window)
                window[7] += 1
            return window, peak
        _, checks = self.judge(change)
        self.assertTrue(any('differs from the model' in p for p in checks['snr-nominal']))

    def test_a_noisier_window_fails_the_lower_limit(self):
        def change(case, window, peak):
            if case == 'sine-nominal':
                window = [v + (300 if i % 3 == 0 else -150) for i, v in enumerate(window)]
            return window, peak
        _, checks = self.judge(change)
        self.assertTrue(any('outside' in p for p in checks['snr-nominal']))

    def test_overload_that_does_not_grow_or_collapse_is_reported(self):
        def change(case, window, peak):
            return (P.model_window(2, 3, M.sine_codes(M.NOMINAL_AMPLITUDE, 3)), 4.0) if case == 'overload' else (window, peak)
        _, checks = self.judge(change)
        self.assertEqual(len(checks['overload']), 3)

    def test_the_first_order_state_bound_is_enforced(self):
        def change(case, window, peak):
            return (window, 2.5) if case == 'overload' else (window, peak)
        _, checks = self.judge(change, name='order1')
        self.assertTrue(any('state' in p for p in checks['overload']))

    def test_a_missing_or_short_window_is_an_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            fake_evidence(out, 'order1', P.CONFIGS['order1'], lambda c, w, p: (w[:-1], p) if c == 'dc-idle' else (w, p))
            with self.assertRaises(ValueError):
                P.judge('order1', P.CONFIGS['order1'], out)

    def test_a_shared_error_that_keeps_the_snr_is_reported(self):
        def change(case, window, peak):
            if case == 'shared-fewer-stages':
                window = P.model_window(2, 2, M.sine_codes(M.NOMINAL_AMPLITUDE, 2))
            return window, peak
        _, checks = self.judge(change)
        self.assertEqual(checks['shared-fewer-stages'], [])
        # A window that stays above the limit would not be caught: show the check reads the SNR.
        def keep(case, window, peak):
            if case == 'shared-fewer-stages':
                window = [4 * v for v in P.model_window(2, 3, M.sine_codes(M.NOMINAL_AMPLITUDE, 3))]
            return window, peak
        _, checks = self.judge(keep)
        self.assertTrue(any('kept SNR' in p for p in checks['shared-fewer-stages']))


class RunTests(unittest.TestCase):
    def test_smoke_passes_with_every_check_and_a_demo_bug_fails(self):
        self.assertTrue(shutil.which('iverilog') and shutil.which('vvp'), 'Icarus Verilog is required')
        with tempfile.TemporaryDirectory() as tmp:
            run = run_example('local-sigma-delta', Path(tmp) / 'out')
            self.assertEqual(run.returncode, 0, run.stdout[-3000:] + run.stderr[-3000:])
            summary = read_json(Path(tmp) / 'out/summary.json')
            self.assertTrue(summary['success'])
            self.assertEqual((summary['planned'], summary['mutations_detected'], summary['diagnostics_pass']), (28, 16, 2))
            self.assertEqual(sorted(summary['snr']), sorted(f'{n}-check-{k}' for n in P.CONFIGS
                                                            for k in ('snr-nominal', 'idle-tone', 'overload', 'shared-fewer-stages')))
            junit = (Path(tmp) / 'out/junit.xml').read_text()
            self.assertEqual(junit.count('<testcase'), 38)
            names = re.findall(r'<testcase[^>]* name="([^"]+)"', junit)
            self.assertEqual(len(names), len(set(names)), 'a check must not reuse a case name')
            self.assertNotIn('<failure', junit)
            coverage = read_json(Path(tmp) / 'out/coverage.json')
            self.assertEqual({k: v['hit'] for k, v in coverage.items()}, {k: GOALS for k in P.CONFIGS})
            report = json.loads((Path(tmp) / 'out/snr.json').read_text())
            self.assertLess(report['order2']['overload']['snr'], report['order2']['nominal']['lower'])
            broken = run_example('local-sigma-delta', Path(tmp) / 'broken', '--demo-bug', '1', '--configuration', 'order1')
            self.assertEqual(broken.returncode, 1)
            self.assertFalse(read_json(Path(tmp) / 'broken/summary.json')['success'])


if __name__ == '__main__':
    unittest.main()

"""Self-tests of the SAR ADC example: the expectations, the refusals and one real run."""
from fractions import Fraction
import importlib.util
import json
import math
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest

HERE = Path(__file__).resolve().parents[1]
ROOT = HERE.parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


M = load('rnm_sar_model_under_test', HERE / 'model.py')
R = load('rnm_sar_runner_under_test', HERE / 'run.py')


def search(vin_uv, caps):
    """The usual successive approximation, as a second opinion on exact_code."""
    bits = len(caps) - 1
    code = 0
    for j in reversed(range(bits)):
        if Fraction(vin_uv) > M.threshold(code | 1 << j, caps):
            code |= 1 << j
    return code


class ExactModel(unittest.TestCase):
    def test_definition_and_search_agree_for_both_arrays(self):
        for bits in (3, 6):
            for caps in (M.nominal_caps(bits), M.mismatched_caps(bits)):
                step = M.VREF_UV // (16 << bits)
                for vin in range(-M.VREF_UV // 8, M.VREF_UV + M.VREF_UV // 8, step):
                    self.assertEqual(M.exact_code(vin + 1, caps), search(vin + 1, caps), (bits, vin))

    def test_nominal_thresholds_are_whole_steps_and_a_tie_does_not_keep_the_bit(self):
        caps = M.nominal_caps(6)
        self.assertEqual(M.threshold(1, caps), 16000)
        self.assertEqual(M.threshold(32, caps), 512000)
        self.assertEqual(M.exact_code(512000, caps), 31)   # exactly on the threshold
        self.assertEqual(M.exact_code(512001, caps), 32)   # just above it
        self.assertEqual(M.exact_code(-5, caps), 0)
        self.assertEqual(M.exact_code(2 * M.VREF_UV, caps), 63)

    def test_trials_and_decisions_describe_one_search(self):
        self.assertEqual(M.trials(0b101, 3), [0b100, 0b110, 0b101])
        self.assertEqual(M.decisions(0b101, 3), [1, 0, 1])

    def test_every_planned_input_keeps_the_guard(self):
        for bits in (6, 8):
            for caps in (M.nominal_caps(bits), M.mismatched_caps(bits)):
                inputs = M.ramp(caps) + M.edges(caps)
                self.assertTrue(inputs)
                self.assertGreaterEqual(min(M.margin_uv(v, caps) for v in inputs), M.guard_uv(bits))
        self.assertEqual(len(M.ramp(M.nominal_caps(6))), 4 * 64)
        self.assertEqual(len(M.edges(M.nominal_caps(6))), 2 * 63)

    def test_mismatch_loses_the_two_codes_below_mid_scale_and_stays_monotonic(self):
        for bits, lost in ((6, [30, 31]), (8, [126, 127])):
            caps = M.mismatched_caps(bits)
            report = M.linearity([(v, M.exact_code(v, caps)) for v in M.ramp(caps)], bits)
            self.assertEqual(report['missing'], lost)
            self.assertTrue(report['monotonic'])
        nominal = M.nominal_caps(6)
        report = M.linearity([(v, M.exact_code(v, nominal)) for v in M.ramp(nominal)], 6)
        self.assertEqual((report['missing'], set(report['hits'].values())), ([], {4}))

    def test_linearity_reports_a_backward_step(self):
        self.assertFalse(M.linearity([(1, 3), (2, 2), (3, 4)], 3)['monotonic'])


class Timeline(unittest.TestCase):
    def test_one_two_bit_conversion_written_out_by_hand(self):
        caps = M.nominal_caps(2)                       # thresholds 256, 512, 768 mV
        line = M.Timeline(2, caps)
        line.idle(1)
        self.assertEqual(line.convert(600000), 2)
        rows = line.finish()
        table = [(r['start'], r['ready'], r['sample'], r['dac'], r['busy'], r['done'], r['result'],
                  r['cmp'], r['check_cmp'], r['cmp_ext']) for r in rows]
        self.assertEqual(table, [
            (0, 1, 0, 0, 0, 0, 0, 0, 0, 0),            # idle
            (1, 0, 1, 0, 1, 0, 0, 0, 0, 0),            # start taken: sample cycle
            (0, 0, 0, 2, 1, 0, 0, 1, 1, 0),            # trial of bit 1: kept
            (0, 0, 0, 3, 1, 0, 0, 0, 1, 1),            # trial of bit 0: dropped
            (0, 1, 0, 0, 0, 1, 2, 0, 0, 0),            # done with the code
            (0, 1, 0, 0, 0, 0, 2, 0, 0, 0),
            (0, 1, 0, 0, 0, 0, 2, 0, 0, 0)])

    def test_fixed_scenario_reaches_every_logic_goal_and_every_code(self):
        digital = {'sar/sample-then-msb', 'sar/keep', 'sar/drop', 'sar/all-ones', 'sar/all-zeros',
                   'sar/done-pulse', 'start/idle-gap', 'start/held-while-busy', 'start/back-to-back',
                   'reset/mid-conversion', 'input/change-after-sample', 'input/track-until-sample-end'}
        for bits in (6, 8):
            caps = M.nominal_caps(bits)
            line = M.fixed_timeline(bits, caps, M.ramp(caps) + M.edges(caps) + M.outside(bits))
            self.assertEqual(line.goals, digital)
            self.assertEqual({code for _, _, code in line.conversions}, set(range(1 << bits)))

    def test_external_answers_replace_the_decisions(self):
        line = M.replay_timeline(3, M.nominal_caps(3), [100000], [[1, 1, 1]])
        self.assertEqual(line.conversions[0][2], 7)
        self.assertEqual([r['dac'] for r in line.rows[2:5]], [4, 6, 7])

    def test_random_timeline_is_reproducible_and_changes_with_the_seed(self):
        caps = M.nominal_caps(6)
        a, b, c = (M.random_timeline(6, caps, seed, 20).text(M.parasitic(6)) for seed in (5, 5, 6))
        self.assertEqual(a, b)
        self.assertNotEqual(a, c)

    def test_vector_file_carries_the_analogue_values_first(self):
        text = M.fixed_timeline(6, M.nominal_caps(6), [100000]).text(M.parasitic(6)).splitlines()
        self.assertEqual([line.split()[0] for line in text[:9]], ['0'] * 9)
        self.assertEqual(text[8].split()[1:3], ['fe', format(M.VREF_UV, 'x')])
        self.assertTrue(all(len(line.split()) == 13 for line in text))


class Settling(unittest.TestCase):
    def setUp(self):
        self.total = sum(M.nominal_caps(6)) * 1e-18
        self.cp = M.parasitic(6) * 1e-18

    def test_sampling_network_has_two_real_negative_poles_whose_product_matches(self):
        s1, s2, a = M.sampling_poles(self.total, self.cp)
        self.assertLess(s2, s1)
        self.assertLess(s1, 0)
        self.assertAlmostEqual(s1 * s2 * a, 1.0, places=9)
        self.assertAlmostEqual(-1 / s1, 1.336e-9, delta=2e-12)

    def test_shortfall_starts_at_one_and_decays_to_zero(self):
        values = [M.sampling_shortfall(t, self.total, self.cp) for t in (0, 1e-9, 5e-9, 40e-9)]
        self.assertAlmostEqual(values[0], 1.0, places=12)
        self.assertEqual(values, sorted(values, reverse=True))
        self.assertLess(values[-1], 1e-7)
        self.assertAlmostEqual(M.sampling_top(0, 0.7, self.total, self.cp), 0.0, places=12)

    def test_minimum_period_is_where_the_shortfall_meets_the_guard(self):
        for bits in (6, 8):
            total, cp = sum(M.nominal_caps(bits)) * 1e-18, M.parasitic(bits) * 1e-18
            period = M.minimum_period(bits, total, cp)
            self.assertAlmostEqual(M.sampling_shortfall(period, total, cp) * M.VREF_UV,
                                   M.guard_uv(bits), delta=1e-3)
            self.assertLess(period, M.SLOW_S / 2)
            self.assertGreater(period, M.FAST_S * 2)

    def test_trial_time_constant_comes_from_the_parasitic_alone(self):
        self.assertAlmostEqual(M.trial_tau(self.total, self.cp), M.TAU_S / 6, places=15)
        self.assertEqual(M.trial_tau(self.total, 0.0), 0.0)

    def test_a_short_sample_is_predicted_or_declared_unpredictable(self):
        caps = M.nominal_caps(6)
        self.assertEqual(M.predicted_code(408000, caps, 0.0), 25)
        self.assertEqual(M.predicted_code(408000, caps, 0.25), 19)   # 306 mV is taken instead
        self.assertIsNone(M.predicted_code(400000, caps, 0.2))       # 320 mV is a threshold


class Refusals(unittest.TestCase):
    def good(self):
        return [dict(code=5, answers=[1, 0, 1], tops=[-0.1, 0.05, -0.01], sample_top=0.0)]

    def test_a_complete_solution_is_accepted(self):
        self.assertEqual(M.check_solution(self.good(), 3, 1)[0]['code'], 5)

    def test_incomplete_inconsistent_or_non_finite_solutions_are_refused(self):
        cases = [[], self.good() * 2, [dict(self.good()[0], code=6)], [dict(self.good()[0], code=9)],
                 [dict(self.good()[0], answers=[1, 0])], [dict(self.good()[0], tops=[0.0, 0.0])],
                 [dict(self.good()[0], tops=[-0.1, float('nan'), -0.01])],
                 [dict(self.good()[0], sample_top=float('inf'))], [dict(self.good()[0], sample_top=None)],
                 [dict(self.good()[0], answers=[1, 2, 1])], [{}], 'text']
        for case in cases:
            with self.assertRaises(ValueError, msg=str(case)[:60]):
                M.check_solution(case, 3, 1)

    def test_model_comparison_names_a_code_or_a_voltage_difference(self):
        caps = M.nominal_caps(3)
        vin = 600000
        code = M.exact_code(vin, caps)
        tops = [M.ideal_top(vin, d, caps, M.parasitic(3)) for d in M.trials(code, 3)]
        item = dict(code=code, answers=M.decisions(code, 3), tops=tops, sample_top=0.0)
        records = {vin: dict(code=code, tops=list(tops))}
        self.assertLess(M.compare_models([vin], [item], records, caps), 1e-12)
        with self.assertRaises(M.Mismatch) as caught:
            M.compare_models([vin], [dict(item, code=code ^ 1)], records, caps)
        self.assertEqual(caught.exception.label, 'MODEL_CODE')
        moved = dict(item, tops=[tops[0] + 3 * M.VTOP_TOLERANCE_V, *tops[1:]])
        with self.assertRaises(M.Mismatch) as caught:
            M.compare_models([vin], [moved], records, caps)
        self.assertEqual(caught.exception.label, 'MODEL_VTOP')
        inside = dict(item, tops=[tops[0] + M.VTOP_TOLERANCE_V / 2, *tops[1:]])
        self.assertGreater(M.compare_models([vin], [inside], records, caps), 0)
        with self.assertRaises(ValueError):
            M.compare_models([vin], [item], {}, caps)

    def test_plan_has_the_documented_number_of_checks(self):
        self.assertEqual(len(R.plan_ids('smoke', 17)[0]), 47)
        self.assertEqual(len(R.plan_ids('nightly', 17)[0]), 51)
        goals = R.E.C.catalog(HERE / 'requirements.json')[1]
        self.assertEqual(len(goals), 28)
        planned = {g for names in R.ANALOG_GOALS.values() for g in names}
        self.assertTrue(planned <= goals)


class RealTools(unittest.TestCase):
    """These need Icarus Verilog and the pinned ngspice library; they fail without them."""

    def config(self):
        command = shutil.which('lsi-ngspice-config')
        self.assertIsNotNone(command, 'prepare ngspice and add install/bin to PATH for all selftests')
        self.assertIsNotNone(shutil.which('iverilog'), 'Icarus Verilog is required')
        return command

    def prefix(self):
        out = subprocess.run([self.config(), '--prefix'], capture_output=True, text=True, check=True)
        return Path(out.stdout.strip())

    def request(self, **changes):
        job = dict(kind='convert', circuit=M.circuit(6, M.nominal_caps(6)), options=R.OPTIONS,
                   period_s=M.SLOW_S, inputs_v=[0.3, 0.6])
        job.update(changes)
        return dict(jobs=[job])

    def solve(self, tmp, request):
        (Path(tmp) / 'request.json').write_text(json.dumps(request))
        return subprocess.run([sys.executable, str(HERE / 'solve.py'), str(self.prefix()),
                               str(Path(tmp) / 'request.json'), str(Path(tmp) / 'answer.json')],
                              capture_output=True, text=True, timeout=120)

    def test_solver_answers_two_conversions_and_refuses_bad_requests(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = self.solve(tmp, self.request())
            self.assertEqual(run.returncode, 0, run.stderr)
            answer = json.loads((Path(tmp) / 'answer.json').read_text())['results'][0]
            self.assertEqual([item['code'] for item in M.check_solution(answer, 6, 2)], [18, 37])
            missing = self.request()
            del missing['jobs'][0]['options']
            for bad in (self.request(broken=True), self.request(period_s=float('nan')),
                        self.request(kind='other'), self.request(period_s=-1e-9), missing):
                (Path(tmp) / 'answer.json').unlink(missing_ok=True)
                run = self.solve(tmp, bad)
                self.assertEqual(run.returncode, 1, str(bad)[:80])
                self.assertIn('SPICE_ERROR', run.stderr)
                self.assertFalse((Path(tmp) / 'answer.json').exists())

    def test_a_solver_that_runs_out_of_time_is_an_error_not_a_result(self):
        with tempfile.TemporaryDirectory() as tmp:
            args = SimpleNamespace(timeout=0.01, waves=False, iverilog='iverilog', vvp='vvp')
            runner = R.Runner(args, SimpleNamespace(out=Path(tmp)), self.prefix())
            with self.assertRaises(R.M.Mismatch) as caught:   # the runner's own copy of the model
                runner.convert('late', 6, M.nominal_caps(6), [300000, 600000])
            self.assertEqual(caught.exception.label, 'SPICE_ERROR')

    def test_smoke_passes_and_a_missing_ngspice_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / 'out'
            run = subprocess.run([sys.executable, str(HERE / 'run.py'), '--out', str(out)],
                                 capture_output=True, text=True, timeout=600)
            self.assertEqual(run.returncode, 0, run.stdout[-3000:] + run.stderr[-2000:])
            summary = json.loads((out / 'summary.json').read_text())
            self.assertTrue(summary['success'] and summary['complete'])
            self.assertEqual(summary['planned'], 47)
            detail = {r['id']: r['detail'] for r in summary['results']}
            for name in ('b6', 'b8'):
                self.assertEqual(detail[f'{name}/coverage']['missing'], [])
                self.assertLess(detail[f'{name}/spice-slow']['worst_top_difference_v'], M.VTOP_TOLERANCE_V)
                sweep = detail[f'{name}/settling-sweep']['sweep']
                self.assertGreater(sweep[0]['wrong_codes'], 0)
                self.assertEqual(sweep[-1]['wrong_codes'], 0)
                self.assertEqual(detail[f'{name}/detect-settling']['actual'], 'ANALOG_SETTLING')
                self.assertEqual(detail[f'{name}/detect-spice-error']['actual'], 'SPICE_ERROR')
            self.assertEqual(detail['b6/linearity']['mismatch']['missing'], [30, 31])
            self.assertTrue(math.isfinite(detail['b6/settling-analytic']['worst_sample_v']))
            self.assertEqual((out / 'junit.xml').read_text().count('<testcase'), 47)
            again = subprocess.run([sys.executable, str(HERE / 'run.py'), '--out', str(out)],
                                   capture_output=True, text=True, timeout=60)
            self.assertNotEqual(again.returncode, 0)            # an existing output is refused
            broken = subprocess.run([sys.executable, str(HERE / 'run.py'), '--ngspice-config',
                                     'no-such-ngspice-config', '--out', str(Path(tmp) / 'none')],
                                    capture_output=True, text=True, timeout=120)
            self.assertEqual(broken.returncode, 1)
            self.assertIn('RUNNER_ERROR', broken.stderr)


if __name__ == '__main__':
    unittest.main()

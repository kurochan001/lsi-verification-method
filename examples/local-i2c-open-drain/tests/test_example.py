"""Self-tests of the open-drain I2C example: the closed form, the judgement, the bench and the real tools."""
import copy
import importlib.util
import json
import math
from pathlib import Path
import re
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
    spec.loader.exec_module(module)
    return module


M = load('i2c_od_model_under_test', HERE / 'model.py')
RUN = load('i2c_od_run_under_test', HERE / 'run.py')
SOLVE = load('i2c_od_solve_under_test', HERE / 'solve.py')
LOADS = M.loads()
MID = M.CONFIGS['fm400-mid']


def voltage_after_rise(load, t_ns):
    vol = M.low_level(load['rp'])
    return M.VDD - (M.VDD - vol) * math.exp(-t_ns / M.rise_tau(load))


def record_from_closed_form(load, plan, shift_ns=0.0, initial=M.VDD, low=None):
    """A measurement record as solve.py writes it, built from the closed form, for the judgement tests."""
    events, _ = M.line(load, plan['drive'], plan['stop'])
    crossings = [dict(t=(t + shift_ns) * 1e-9, level='vih' if v else 'vil', direction=v) for t, v, _ in events]
    vol = M.low_level(load['rp']) if low is None else low
    windows = [dict(start=a * 1e-9, stop=b * 1e-9, min=vol, max=vol) for a, b in M.low_windows(load, plan['drive'], plan['stop'])]
    return dict(points=1000, stop=plan['stop'] * 1e-9, initial=initial, crossings=crossings, windows=windows)


class ClosedForm(unittest.TestCase):
    def test_levels_and_time_constants_follow_the_component_values(self):
        light = LOADS['light']
        self.assertAlmostEqual(M.low_level(1000.0), 3.3 * 50 / 1050)
        self.assertAlmostEqual(M.rise_tau(light), 50.0)
        self.assertAlmostEqual(M.fall_tau(light), 50e-12 * (1000 * 50 / 1050) * 1e9)
        for name in ('light', 'heavy', 'fm400-mid-inside'):
            self.assertAlmostEqual(voltage_after_rise(LOADS[name], M.rise_needed(LOADS[name])), M.VIH, places=9)

    def test_schedule_alternates_scl_and_samples_inside_the_high_phases(self):
        plan = M.schedule(MID, 0x5A)
        self.assertEqual(len(plan['edges']), 18)
        self.assertEqual([v for _, v in plan['edges']], [0, 1] * 8 + [0, 1])
        self.assertEqual(plan['edges'][0][0], M.E0_NS)
        highs = [(plan['edges'][i][0], plan['edges'][i + 1][0]) for i in range(1, 17, 2)]
        for s, (a, b) in zip(plan['samples'], highs):
            self.assertEqual(s - a, MID['SAMPLE'] * M.T_NS)
            self.assertLess(s, b)
        self.assertEqual(plan['bits'], [0, 1, 0, 1, 1, 0, 1, 0])
        self.assertEqual([on for _, on in plan['drive']], [True, False, True, False, True, False, True, False])
        self.assertEqual(plan['drive'][-1][0], M.E0_NS + 16 * MID['DIV'] * M.T_NS + M.THD_NS)
        self.assertEqual(M.schedule(MID, 0xFF)['drive'], [])

    def test_line_events_hysteresis_interruption_and_a_low_level_above_vil(self):
        plan = M.schedule(MID, 0x5A)
        events, _ = M.line(LOADS['light'], plan['drive'], plan['stop'])
        self.assertEqual([v for _, v, _ in events], [0, 1] * 4)
        self.assertEqual(M.line(LOADS['light'], [], 1000.0)[0], [])
        events, _ = M.line(LOADS['strong-fail'], plan['drive'], plan['stop'])
        self.assertEqual(events, [])
        _, segments = M.line(LOADS['heavy'], plan['drive'], plan['stop'])
        self.assertTrue(M.interrupted(segments))
        self.assertFalse(M.interrupted(M.line(LOADS['light'], plan['drive'], plan['stop'])[1]))

    def test_boundary_loads_sit_five_percent_either_side_of_each_window(self):
        for name, cfg in M.CONFIGS.items():
            for side, ratio in (('inside', 0.95), ('outside', 1.05)):
                found = M.rise_needed(LOADS[f'{name}-{side}']) / M.window(cfg)
                self.assertAlmostEqual(found, ratio, delta=0.001)
        self.assertEqual(M.window(MID), 125 * 10 - 100 + 62 * 10)

    def test_maximum_frequency_is_where_the_rise_fills_the_window(self):
        load = LOADS['fm400-mid-inside']
        f = M.max_frequency(load, 0.5)
        half_ns = 1e9 / (2 * f)
        self.assertAlmostEqual(half_ns - M.THD_NS + 0.5 * half_ns, M.rise_needed(load), places=6)

    def test_sampling_guard_and_outcome_classes(self):
        with self.assertRaisesRegex(ValueError, 'within'):
            M.sampled([(1000.5, 1)], [1001.0])
        self.assertEqual(M.sampled([(500.0, 0), (900.0, 1)], [400.0, 600.0, 1000.0]), [1, 0, 1])
        self.assertEqual(M.outcome([0, 1, 1], [0, 1, 1]), {'correct'})
        self.assertEqual(M.outcome([0, 1, 1], [0, 0, 1]), {'slow-rise'})
        self.assertEqual(M.outcome([0, 1], [1, 0]), {'slow-rise', 'low-too-high'})
        self.assertEqual(M.to_byte([0, 1, 0, 1, 1, 0, 1, 0]), 0x5A)

    def test_random_cases_repeat_by_seed_and_stay_clear_of_the_sampling_edges(self):
        for name in M.CONFIGS:
            self.assertEqual(M.random_case(name, 17), M.random_case(name, 17))
            load, data = M.random_case(name, 18)
            plan = M.schedule(M.CONFIGS[name], data)
            events, _ = M.line(load, plan['drive'], plan['stop'])
            self.assertTrue(all(abs(t - s) >= M.tol_ns(tau) + 5 for t, _, tau in events for s in plan['samples']))
        self.assertNotEqual(M.random_case('fm1m', 17), M.random_case('fm1m', 18))

    def test_netlist_filling_and_faults(self):
        template = (HERE / 'sda.cir.in').read_text()
        plan = M.schedule(MID, 0x5A)
        text = M.deck(template, LOADS['light'], plan['drive'])
        self.assertNotIn('@', text)
        self.assertIn('Rp vdd sda 1000', text)
        self.assertIn('ron=1000', M.deck(template, LOADS['light'], plan['drive'], 'ron-high'))
        self.assertIn('ic=0', M.deck(template, LOADS['light'], plan['drive'], 'no-initial'))
        self.assertIn(M.pwl(plan['drive'][:-1]), M.deck(template, LOADS['light'], plan['drive'], 'release-missing'))
        self.assertEqual(len(M.pwl(plan['drive'][:-1]).split()), len(M.pwl(plan['drive']).split()) - 4)
        with self.assertRaises(ValueError):
            M.deck(template, LOADS['light'], M.schedule(MID, 0xFF)['drive'], 'release-missing')
        with self.assertRaises(ValueError):
            M.deck(template, LOADS['light'], plan['drive'], 'unknown')
        with self.assertRaises(ValueError):
            M.deck('no placeholders', LOADS['light'], plan['drive'])
        # The switch turns at 0.6 ns on a 1 ns ramp, so each ramp starts 0.6 ns before the drive time.
        first = M.pwl(plan['drive']).split()
        self.assertAlmostEqual(float(first[2]) * 1e9, plan['drive'][0][0] - M.SWITCH_NS)


class Judgement(unittest.TestCase):
    def setUp(self):
        self.load, self.plan = LOADS['fm400-mid-inside'], M.schedule(MID, 0x5A)

    def test_the_closed_form_itself_passes_with_its_goals(self):
        goals, events, worst = M.check_analog(self.load, self.plan, record_from_closed_form(self.load, self.plan))
        self.assertEqual(goals, {'analog/rise-crossing', 'analog/fall-crossing', 'analog/low-level'})
        self.assertEqual(len(events), 8)
        self.assertLess(worst, 1e-9)
        goals, _, _ = M.check_analog(LOADS['heavy'], self.plan, record_from_closed_form(LOADS['heavy'], self.plan))
        self.assertIn('analog/interrupted-rise', goals)
        goals, _, _ = M.check_analog(LOADS['strong-fail'], self.plan, record_from_closed_form(LOADS['strong-fail'], self.plan))
        self.assertEqual(goals, {'analog/low-above-vil', 'analog/low-level'})

    def test_each_kind_of_wrong_measurement_has_its_label(self):
        def label(record):
            with self.assertRaises(M.Mismatch) as caught:
                M.check_analog(self.load, self.plan, record)
            return caught.exception.label
        good = record_from_closed_form(self.load, self.plan)
        missing = copy.deepcopy(good); del missing['initial']
        self.assertEqual(label(missing), 'ANALOG_MEASURE')
        nan = copy.deepcopy(good); nan['crossings'][0]['t'] = float('nan')
        self.assertEqual(label(nan), 'ANALOG_MEASURE')
        self.assertEqual(label(record_from_closed_form(self.load, self.plan, initial=0.0)), 'ANALOG_INITIAL')
        self.assertEqual(label(record_from_closed_form(self.load, self.plan, low=M.low_level(self.load['rp']) + 0.006)), 'ANALOG_LOW')
        fewer = copy.deepcopy(good); fewer['crossings'] = fewer['crossings'][:-1]
        self.assertEqual(label(fewer), 'ANALOG_COUNT')
        allowed = M.tol_ns(M.rise_tau(self.load))
        self.assertEqual(label(record_from_closed_form(self.load, self.plan, shift_ns=allowed + 0.01)), 'ANALOG_TIME')
        M.check_analog(self.load, self.plan, record_from_closed_form(self.load, self.plan, shift_ns=M.tol_ns(M.fall_tau(self.load)) - 0.01))

    def test_digitise_applies_the_hysteresis(self):
        crossings = [dict(t=1e-9, level='vih', direction=1), dict(t=2e-9, level='vil', direction=0),
                     dict(t=3e-9, level='vil', direction=1), dict(t=4e-9, level='vih', direction=0),
                     dict(t=5e-9, level='vih', direction=1)]
        self.assertEqual([(round(t, 6), v) for t, v in M.digitise(crossings)], [(2.0, 0), (5.0, 1)])

    def test_solver_settings_tolerance(self):
        good = record_from_closed_form(self.load, self.plan)
        allowed = M.tol_settings_ns(M.rise_tau(self.load))
        self.assertLess(M.check_settings(good, record_from_closed_form(self.load, self.plan, shift_ns=allowed - 0.01), self.load), allowed)
        with self.assertRaises(M.Mismatch):
            M.check_settings(good, record_from_closed_form(self.load, self.plan, shift_ns=allowed + 0.01), self.load)

    def test_measure_rejects_broken_solver_output(self):
        with self.assertRaises(ValueError):
            SOLVE.measure([0.0, 1e-9], [3.3], M.VIH, M.VIL, [])
        with self.assertRaises(ValueError):
            SOLVE.measure([0.0, 1e-9], [3.3, float('nan')], M.VIH, M.VIL, [])
        with self.assertRaises(ValueError):
            SOLVE.measure([0.0, 0.0], [3.3, 3.3], M.VIH, M.VIL, [])
        with self.assertRaises(ValueError):
            SOLVE.measure([0.0, 1e-9], [3.3, 3.2], M.VIH, M.VIL, [(5e-9, 6e-9)])
        found = SOLVE.measure([0.0, 1e-9, 2e-9], [3.3, 0.0, 3.3], M.VIH, M.VIL, [])
        self.assertEqual([(c['level'], c['direction']) for c in found['crossings']],
                         [('vih', 0), ('vil', 0), ('vil', 1), ('vih', 1)])

    def test_expected_file_for_the_bench(self):
        text = M.expected_lines(self.plan, self.plan['bits'])
        self.assertTrue(text.startswith('EDGES 18\n25.000 0\n'))
        self.assertIn('SAMPLES 8\n', text)
        self.assertIn(f"DONE {self.plan['done']:.3f} 5a\n", text)
        self.assertEqual(M.event_lines([(1.23456, 1)]), '1.235 1\n')

    def test_requirements_catalogue_matches_the_goals_the_runner_can_report(self):
        catalogue = json.loads((HERE / 'requirements.json').read_text())
        goals = {g for r in catalogue['requirements'] for g in r['goals']}
        source = (HERE / 'model.py').read_text() + (HERE / 'run.py').read_text()
        reported = set(re.findall(r"'((?:analog|boundary|sample|rtl|negative)/[a-z-]+)'", source))
        reported |= {f'outcome/{k}' for k in ('correct', 'slow-rise', 'low-too-high')}
        self.assertEqual(goals, reported)


class RealTools(unittest.TestCase):
    """These use the pinned ngspice library and Icarus Verilog; without them the tests fail, not skip."""

    @classmethod
    def setUpClass(cls):
        for tool in ('iverilog', 'vvp', 'lsi-ngspice-config'):
            if not shutil.which(tool):
                raise AssertionError(f'{tool} is required on PATH for these self-tests')
        cls.prefix = Path(subprocess.run(['lsi-ngspice-config', '--prefix'], capture_output=True, text=True, check=True).stdout.strip())

    def solve(self, deck_text, request, tmp):
        deck, req = Path(tmp) / 'd.cir', Path(tmp) / 'r.json'
        deck.write_text(deck_text)
        req.write_text(json.dumps(request))
        return subprocess.run([sys.executable, str(HERE / 'solve.py'), str(self.prefix), str(deck), str(req),
                               str(Path(tmp) / 'm.json'), str(Path(tmp) / 'w.csv')], capture_output=True, text=True)

    def test_solver_failures_are_errors_and_leave_no_measurement(self):
        plan = M.schedule(M.CONFIGS['fm1m'], 0x5A)
        good = M.deck((HERE / 'sda.cir.in').read_text(), LOADS['light'], plan['drive'])
        request = M.request(LOADS['light'], plan)
        broken = {'unknown-model-type': good.replace('.model swmod sw', '.model swmod nosuchtype'),
                  'unknown-element': good.replace('.end', 'Qbad a b\n.end'),
                  'no-sda-vector': good.replace('.save v(sda) v(drv)', '.save v(drv)')}
        for name, text in broken.items():
            with tempfile.TemporaryDirectory() as tmp:
                result = self.solve(text, request, tmp)
                self.assertEqual(result.returncode, 1, name)
                self.assertIn('SPICE_ERROR', result.stderr, name)
                self.assertFalse((Path(tmp) / 'm.json').exists(), name)
        with tempfile.TemporaryDirectory() as tmp:
            result = self.solve(good, dict(request, vil=3.0), tmp)
            self.assertEqual(result.returncode, 1)
            result = self.solve(good, request, tmp)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertRegex(result.stdout, r'SPICE_PASS points=\d+ crossings=\d+')

    def test_a_solver_time_out_is_an_error_not_a_pass_or_a_detection(self):
        with tempfile.TemporaryDirectory() as tmp:
            evidence = SimpleNamespace(out=Path(tmp), args=SimpleNamespace(timeout=0.01))
            runner = RUN.Runner(evidence, self.prefix)
            ok, detail, record, goals, events = runner.analog('t', LOADS['light'], M.schedule(MID, 0x5A), None, 'ANALOG_TIME')
            self.assertFalse(ok)
            self.assertIn('error', detail)
            self.assertIsNone(record)

    def test_smoke_passes_with_the_planned_checks_labels_and_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / 'out'
            run = subprocess.run([sys.executable, str(HERE / 'run.py'), '--out', str(out)], capture_output=True, text=True)
            self.assertEqual(run.returncode, 0, run.stdout[-2000:] + run.stderr[-2000:])
            summary = json.loads((out / 'summary.json').read_text())
            self.assertTrue(summary['success'] and summary['complete'])
            self.assertEqual(summary['planned'], 72)
            details = {r['id']: r['detail'] for r in summary['results']}
            self.assertEqual(details['rtl-fm400-mid-fm400-mid-outside']['read'], '08')
            self.assertEqual(details['rtl-fm400-late-fm400-mid-outside']['read'], '5a')
            self.assertEqual(details['rtl-fm400-mid-strong-fail']['read'], 'ff')
            self.assertEqual(details['detect-analog-cb-plus5']['label'], 'ANALOG_TIME')
            self.assertEqual(json.loads((out / 'coverage.json').read_text())['missing'], [])
            self.assertEqual((out / 'junit.xml').read_text().count('<testcase'), 72)
            broken = subprocess.run([sys.executable, str(HERE / 'run.py'), '--iverilog', 'no-such-iverilog',
                                     '--out', str(Path(tmp) / 'broken')], capture_output=True, text=True)
            self.assertNotEqual(broken.returncode, 0)

    def test_the_bench_fails_when_the_expected_values_are_wrong(self):
        plan = M.schedule(MID, 0x5A)
        events, _ = M.line(LOADS['light'], plan['drive'], plan['stop'])
        line = [(t, v) for t, v, _ in events]
        read = M.sampled(line, plan['samples'])
        with tempfile.TemporaryDirectory() as tmp:
            binary = Path(tmp) / 'tb.vvp'
            subprocess.run(['iverilog', '-g2012', '-s', RUN.TOP, f'-P{RUN.TOP}.DIV=125', f'-P{RUN.TOP}.SAMPLE=62', '-o', str(binary),
                            *map(str, RUN.SOURCES)], check=True)
            (Path(tmp) / 'e.txt').write_text(M.event_lines(line))

            def bench(expected):
                (Path(tmp) / 'x.txt').write_text(expected)
                result = subprocess.run(['vvp', '-N', str(binary), '+EVENTS=' + str(Path(tmp) / 'e.txt'),
                                         '+EXPECT=' + str(Path(tmp) / 'x.txt'), '+WAVE=' + str(Path(tmp) / 'w.vcd')],
                                        capture_output=True, text=True, cwd=tmp)
                return re.findall(r'^CHECK_FAIL (\w+)$', result.stdout, re.M), result.stdout

            labels, out = bench(M.expected_lines(plan, read))
            self.assertEqual(labels, [], out[-500:])
            self.assertIn('RESULT PASS checks=27', out)
            wrong_bit = list(read); wrong_bit[1] ^= 1
            self.assertEqual(bench(M.expected_lines(plan, wrong_bit))[0], ['I2C_BIT'])
            late = dict(plan, edges=[(t + (10 if i == 3 else 0), v) for i, (t, v) in enumerate(plan['edges'])])
            self.assertEqual(bench(M.expected_lines(late, read))[0], ['I2C_SCL'])
            shifted = dict(plan, samples=[s + 10 for s in plan['samples']])
            self.assertEqual(bench(M.expected_lines(shifted, read))[0], ['I2C_SAMPLE'])
            short = dict(plan, end=plan['done'] - 100)
            self.assertEqual(bench(M.expected_lines(short, read))[0], ['I2C_TIMEOUT'])


if __name__ == '__main__':
    unittest.main()

"""Self-tests of the power-on-reset example: the analytic model, the judgement, the reference and the real tools."""
import copy
import importlib.util
import json
import math
from pathlib import Path
import random
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


M = load('por_model_under_test', HERE / 'model.py')
RUN = load('por_run_under_test', HERE / 'run.py')
SOLVE = load('por_solve_under_test', HERE / 'solve.py')
A, B = M.CONFIGS['tau10-sync2'], M.CONFIGS['tau20-sync3']


def record(events, windows=(), initial=0.0, final=1.0):
    """A measurement record as solve.py writes it, for the judgement tests."""
    return dict(points=1000, stop=1e-3, initial_det=initial, final_det=final, windows=list(windows),
                events=[dict(t=t, value=v, vdd=vdd, vdiv=vdiv, vdd_max_before=1.8, vdd_min_before=0.0) for t, v, vdd, vdiv in events])


def simulate_flops(events, phase, cycles, cfg, inputs):
    """A third implementation: the flip-flops stepped through time, as the RTL is written."""
    stages, wait, timeout = (cfg[n] for n in M.DIGITAL)
    reset = dict(chain=[0] * stages, state='wait', count=0, cfg=0, flag=1)
    regs = copy.deepcopy(reset)
    timeline = sorted([(t, 0, v) for t, v in events] + [(phase + k * M.T_NS, 1, k) for k in range(cycles)] +
                      [(phase + k * M.T_NS + M.SAMPLE_NS, 2, k) for k in range(cycles)])
    power, rows = 0, []
    for _, kind, value in timeline:
        if kind == 0:
            power = value
            if not power:
                regs = copy.deepcopy(reset)
        elif kind == 1:
            released = regs['chain'][-1]
            regs['chain'] = [1, *regs['chain'][:-1]] if power else [0] * stages
            if not released:
                continue
            strap, done, clear = inputs[value]
            if clear:
                regs['flag'] = 0
            if regs['state'] == 'wait':
                if regs['count'] >= wait - 1:
                    regs['state'], regs['count'] = 'load', 0
                else:
                    regs['count'] += 1
            elif regs['state'] == 'load':
                regs['cfg'], regs['state'], regs['count'] = strap, 'cal', 0
            elif regs['state'] == 'cal':
                if done:
                    regs['state'] = 'ready'
                elif regs['count'] == timeout - 1:
                    regs['state'] = 'fail'
                else:
                    regs['count'] += 1
        else:
            rows.append(dict(rst_n=regs['chain'][-1], cfg_load=int(regs['state'] == 'load'), cal_start=int(regs['state'] == 'cal'),
                             ready=int(regs['state'] == 'ready'), init_fail=int(regs['state'] == 'fail'),
                             por_flag=regs['flag'], cfg=regs['cfg']))
    return rows


class AnalyticModel(unittest.TestCase):
    def test_thresholds_and_time_constant_follow_the_component_values(self):
        a = M.analog(A)
        self.assertAlmostEqual(a['tau'], 1e-5)
        self.assertEqual((round(a['rise_vdd'], 9), round(a['fall_vdd'], 9)), (1.6, 1.4))
        b = M.analog(B)
        self.assertAlmostEqual(b['tau'], 2e-5)
        self.assertEqual((round(b['rise_div'], 9), round(b['fall_div'], 9)), (0.83, 0.67))

    def test_step_delay_bounds_bracket_the_closed_form(self):
        low, high = M.step_delay(A)
        exact = 1e-5 * math.log(0.9 / 0.1)
        self.assertLess(low, exact)
        self.assertGreater(high, exact + 1e-6 * math.log(2))
        self.assertLess(high - low, 1.5e-6)

    def test_dip_boundary_and_classes_including_the_guard_band(self):
        self.assertTrue(math.isinf(M.dip_boundary(A, 1.5)))            # never reaches the falling threshold
        boundary = M.dip_boundary(A, 1.0)
        self.assertAlmostEqual(boundary, 1e-5 * math.log(2))
        self.assertEqual(M.classify_dip(A, 1.0, boundary - M.MAP_GUARD_S), 'ignored')
        self.assertIsNone(M.classify_dip(A, 1.0, boundary - M.MAP_GUARD_S + 1e-9))
        self.assertIsNone(M.classify_dip(A, 1.0, boundary + 1e-6 * math.log(2) + M.MAP_GUARD_S - 1e-9))
        self.assertEqual(M.classify_dip(A, 1.0, boundary + 1e-6 * math.log(2) + M.MAP_GUARD_S), 'reset')
        self.assertEqual(M.classify_dip(A, 1.5, 1.0), 'ignored')

    def test_minimum_pulse_is_the_climb_between_the_two_thresholds(self):
        self.assertAlmostEqual(M.minimum_pulse(A), 1e-5 * math.log(0.2 / 0.1))
        self.assertGreater(M.minimum_pulse(A), M.T_NS * 1e-9)          # longer than one clock period

    def test_netlist_filling_and_faults(self):
        template = (HERE / 'por.cir.in').read_text()
        spec = M.scenario('powerup', A)
        clean = M.deck(template, A, spec)
        self.assertNotIn('@', clean)
        self.assertIn('C1 vdiv 0 2e-10', clean)
        self.assertIn('C1 vdiv 0 4e-10', M.deck(template, A, spec, 'slow-rc'))
        self.assertIn('+0*(v(det)-0.5)', M.deck(template, A, spec, 'no-hysteresis').replace('0.0*', '0*'))
        with self.assertRaises(ValueError):
            M.deck(template, A, spec, 'unknown')
        with self.assertRaises(ValueError):
            M.deck(template.replace('@VTH@', '0.75'), A, spec)
        with self.assertRaises(ValueError):
            M.deck(template + '@EXTRA@\n', A, spec)

    def test_scenarios_are_ordered_and_windows_do_not_overlap(self):
        for cfg in (A, B):
            for name, seed in (('powerup', 0), ('slow-ramp', 0), ('brownout', 0), ('repower', 0), ('dipmap', 0), ('dipmap', 1), ('random', 17)):
                spec = M.scenario(name, cfg, seed)
                self.assertTrue(all(b > a for (a, _), (b, _) in zip(spec['pwl'], spec['pwl'][1:])), name)
                self.assertEqual(len(spec['windows']), len(spec['dips']))
                self.assertTrue(all(stop <= following for (_, stop), (following, _) in zip(spec['windows'], spec['windows'][1:])), name)
        with self.assertRaises(ValueError):
            M.scenario('nothing', A)
        classes = {M.classify_dip(A, depth, width) for _, depth, width in M.scenario('dipmap', A)['dips']}
        self.assertEqual(classes, {'reset', 'ignored'})


class Judgement(unittest.TestCase):
    def setUp(self):
        self.ramp = M.scenario('slow-ramp', A)
        self.good = record([(4.4e-3, 1, 1.61, 0.80), (7.1e-3, 0, 1.39, 0.70)], final=0.0)

    def label(self, spec, rec, cfg=A):
        with self.assertRaises(M.Mismatch) as caught:
            M.check_analog(cfg, spec, rec)
        return caught.exception.label

    def test_a_good_slow_ramp_reaches_its_goals(self):
        goals = M.check_analog(A, self.ramp, self.good)
        self.assertEqual(goals, {'cross/good-after-supply', 'analog/no-chatter', 'analog/rise-threshold',
                                 'analog/fall-threshold', 'analog/hysteresis-width'})

    def test_missing_and_non_finite_measurements_fail(self):
        for change in (lambda r: r['events'][0].pop('vdiv'), lambda r: r['events'][0].update(vdd=float('nan')),
                       lambda r: r.update(stop=float('inf')), lambda r: r.pop('final_det'),
                       lambda r: r['events'][1].update(value=2), lambda r: r.update(events=None)):
            rec = copy.deepcopy(self.good)
            change(rec)
            self.assertEqual(self.label(self.ramp, rec), 'ANALOG_MEASURE')
        brown = M.scenario('brownout', A)
        self.assertEqual(self.label(brown, record([(3e-5, 1, 1.8, 0.8)])), 'ANALOG_MEASURE')   # windows not measured

    def test_events_must_start_low_and_alternate(self):
        self.assertEqual(self.label(self.ramp, record([(1e-3, 0, 1.4, 0.7), (2e-3, 1, 1.6, 0.8)])), 'ANALOG_MEASURE')
        self.assertEqual(self.label(self.ramp, dict(self.good, initial_det=0.9)), 'ANALOG_MEASURE')

    def test_chatter_thresholds_and_hysteresis_each_have_their_own_label(self):
        four = record([(4.4e-3, 1, 1.61, 0.80), (4.5e-3, 0, 1.6, 0.8), (4.6e-3, 1, 1.61, 0.8), (7.1e-3, 0, 1.39, 0.7)], final=0.0)
        self.assertEqual(self.label(self.ramp, four), 'ANALOG_CHATTER')
        slack = M.TOL_VDD_V + self.ramp['ripple']
        at_edge = record([(4.4e-3, 1, 1.6 + slack - 1e-6, 0.80), (7.1e-3, 0, 1.4 - slack + 1e-6, 0.70)], final=0.0)
        self.assertIn('analog/rise-threshold', M.check_analog(A, self.ramp, at_edge))
        beyond = record([(4.4e-3, 1, 1.6 + slack + 1e-4, 0.80), (7.1e-3, 0, 1.39, 0.70)], final=0.0)
        self.assertEqual(self.label(self.ramp, beyond), 'ANALOG_THRESHOLD')
        node = record([(4.4e-3, 1, 1.61, 0.80 + M.TOL_DIV_V + 1e-4), (7.1e-3, 0, 1.39, 0.70)], final=0.0)
        self.assertEqual(self.label(self.ramp, node), 'ANALOG_THRESHOLD')
        narrow = record([(4.4e-3, 1, 1.61, 0.796), (7.1e-3, 0, 1.39, 0.7045)], final=0.0)   # each inside, width outside
        self.assertEqual(self.label(self.ramp, narrow), 'ANALOG_HYSTERESIS')

    def test_power_good_before_the_supply_is_in_range_is_caught(self):
        early = copy.deepcopy(self.good)
        early['events'][0]['vdd_max_before'] = 1.6 - M.TOL_VDD_V - self.ramp['ripple'] - 1e-4
        self.assertEqual(self.label(self.ramp, early), 'CROSS_EARLY')
        early['events'][0]['vdd_max_before'] = 1.6 - M.TOL_VDD_V - self.ramp['ripple'] + 1e-4
        M.check_analog(A, self.ramp, early)

    def test_step_delay_window(self):
        spec = M.scenario('powerup', A)
        low, high = M.step_delay(A)
        start = spec['pwl'][1][0]
        M.check_analog(A, spec, record([(start + low + 1e-9, 1, 1.8, 0.8)]))
        self.assertEqual(self.label(spec, record([(start + high + 1e-8, 1, 1.8, 0.8)])), 'ANALOG_DELAY')
        self.assertEqual(self.label(spec, record([(start + low - 1e-8, 1, 1.8, 0.8)])), 'ANALOG_DELAY')
        self.assertEqual(self.label(spec, record([], final=0.0)), 'ANALOG_DELAY')

    def brownout(self, cfg=A):
        spec = M.scenario('brownout', cfg)
        events, windows = [(3.3e-5, 1, 1.8, 0.8)], []
        for (at, depth, width), kind in zip(spec['dips'], ('ignored', 'ignored', 'reset', 'reset', 'reset')):
            if kind == 'reset':
                events += [(at + 8e-6, 0, depth, 0.7), (at + 8e-6 + max(width, 1.2e-5), 1, 1.8, 0.8)]
            windows.append(dict(det_min=0.0 if kind == 'reset' else 1.0, det_max=1.0, vdd_min=depth, vdiv_min=0.5))
        return spec, record(events, windows)

    def test_brownout_classes_and_pulse_width(self):
        spec, rec = self.brownout()
        goals = M.check_analog(A, spec, rec)
        self.assertTrue({'brownout/ignored-shallow', 'brownout/ignored-short', 'brownout/reset-shortest', 'brownout/reset-long',
                         'brownout/reset-in-cal', 'analog/min-pulse'} <= goals)
        short = copy.deepcopy(rec)
        short['events'][2]['t'] = short['events'][1]['t'] + M.minimum_pulse(A) - M.TOL_DELAY_S - 1e-8
        self.assertEqual(self.label(spec, short), 'ANALOG_PULSE')
        missed = copy.deepcopy(rec)                                  # the long dip no longer resets
        del missed['events'][3:5]
        missed['windows'][3]['det_min'] = 1.0
        self.assertEqual(self.label(spec, missed), 'ANALOG_BROWNOUT')
        twice = copy.deepcopy(rec)                                   # two falling events inside one dip
        at = spec['dips'][3][0]
        twice['events'][3:5] = [dict(twice['events'][3], t=at + 8e-6), dict(twice['events'][4], t=at + 2.2e-5),
                                dict(twice['events'][3], t=at + 2.4e-5), dict(twice['events'][4], t=at + 9e-5)]
        self.assertEqual(self.label(spec, twice), 'ANALOG_CHATTER')

    def test_repower_needs_every_power_cycle(self):
        spec = M.scenario('repower', A)
        events = []
        for index in range(4):
            events.append((1e-5 + index * 8e-4 + 3e-4, 1, 1.8, 0.8))
            if index < 3:
                events.append(((index + 1) * 8e-4 + 2e-5, 0, 1.4, 0.7))
        self.assertIn('repower/full-off', M.check_analog(A, spec, record(events)))
        self.assertEqual(self.label(spec, record(events[:5])), 'ANALOG_CHATTER')

    def test_solver_settings_tolerance(self):
        reference = record([(1e-3, 1, 1.6, 0.8), (2e-3, 0, 1.4, 0.7)])
        moved = copy.deepcopy(reference)
        moved['events'][1]['t'] += M.TOL_SETTINGS_S - 1e-9
        self.assertAlmostEqual(M.check_settings(reference, moved), M.TOL_SETTINGS_S - 1e-9)
        moved['events'][1]['t'] += 2e-9
        with self.assertRaises(M.Mismatch):
            M.check_settings(reference, moved)
        with self.assertRaises(M.Mismatch):
            M.check_settings(reference, record([(1e-3, 1, 1.6, 0.8)]))

    def test_measure_rejects_broken_solver_output(self):
        t, v = [0.0, 1e-6, 2e-6, 3e-6], [0.0, 0.2, 0.8, 1.0]
        good = SOLVE.measure(t, v, v, v, 1e-6, [(0.0, 3e-6)])
        self.assertEqual([e['value'] for e in good['events']], [1])
        self.assertAlmostEqual(good['events'][0]['t'], 1.5e-6)
        for times, values, windows in ((t, [0.0, float('nan'), 0.8, 1.0], []), ([0.0, 1e-6, 1e-6, 3e-6], v, []),
                                       (t[:3], v, []), (t, v, [(5e-6, 6e-6)])):
            with self.assertRaises(ValueError):
                SOLVE.measure(times, values, v, v, 1e-6, windows)


class Reference(unittest.TestCase):
    def test_events_are_moved_off_edges_and_compare_points(self):
        phase = 5000
        rec = dict(events=[dict(t=(phase + 3 * M.T_NS + 10) * 1e-9, value=1), dict(t=(phase + 9 * M.T_NS - 20) * 1e-9, value=0),
                           dict(t=(phase + 12 * M.T_NS + M.SAMPLE_NS - 5) * 1e-9, value=1), dict(t=(phase + 20 * M.T_NS + 700) * 1e-9, value=0)])
        events = M.to_events(rec, phase)
        self.assertEqual(events, [(phase + 3 * M.T_NS + M.GUARD_NS, 1), (phase + 9 * M.T_NS + M.GUARD_NS, 0),
                                  (phase + 12 * M.T_NS + M.SAMPLE_NS + M.GUARD_NS, 1), (phase + 20 * M.T_NS + 700, 0)])
        M.check_events(events, phase, 30)
        for bad in ([(phase + 100, 0)], [(phase + 100, 1), (phase + 90, 0)], [(phase + M.T_NS + 10, 1)],
                    [(phase + M.SAMPLE_NS + 10, 1)], [(phase - 100, 1)], [(phase + 31 * M.T_NS + 100, 1)]):
            with self.assertRaises(ValueError):
                M.check_events(bad, phase, 30)

    def test_release_clock_and_aborted_release(self):
        phase = 4000
        events = [(phase + 2 * M.T_NS + 700, 1), (phase + 3 * M.T_NS + 500, 0), (phase + 5 * M.T_NS + 100, 1)]
        found = M.releases(events, phase, 40, 2)
        self.assertEqual([r['rise'] for r in found], [None, 7])          # the first rise lasts one clock only
        self.assertEqual(M.releases(events, phase, 40, 3)[1]['rise'], 8)
        self.assertEqual(M.counts(events, phase, 40, A), dict(falls=1, releases=1))

    def test_closed_form_reference_equals_the_stepped_flip_flops(self):
        for cfg in (A, B):
            pulses = M.async_pulses(cfg)
            inputs = M.program(pulses['events'], pulses['phase'], pulses['cycles'], cfg, pulses['plans'])
            rows, scenes = M.expect(pulses['events'], pulses['phase'], pulses['cycles'], cfg, inputs)
            self.assertEqual(rows, simulate_flops(pulses['events'], pulses['phase'], pulses['cycles'], cfg, inputs))
            self.assertTrue(RUN.SCENES['async-pulses'] <= scenes)
            rng = random.Random(5)
            for _ in range(60):
                phase, cycles, t, events, value = M.T_NS + rng.randrange(M.T_NS), 90, 0, [], 1
                t = phase + rng.randrange(1, 4) * M.T_NS + 700
                while t < phase + (cycles - 2) * M.T_NS:
                    offset = (t - phase) % M.T_NS
                    if min(offset, M.T_NS - offset) >= M.GUARD_NS and abs(offset - M.SAMPLE_NS) >= M.GUARD_NS:
                        events.append((t, value))
                        value ^= 1
                    t += rng.choice((3, 40, 700, 3100, 9000, 23000, 61000))
                inputs = [[rng.randrange(16), int(rng.random() < 0.3), int(rng.random() < 0.1)] for _ in range(cycles)]
                rows, _ = M.expect(events, phase, cycles, cfg, inputs)
                self.assertEqual(rows, simulate_flops(events, phase, cycles, cfg, inputs))

    def test_plans_place_the_boundary_cases(self):
        phase, cycles = 4000, 80
        events = [(phase + 700, 1)]
        run = M.releases(events, phase, cycles, A['STAGES'])[0]['rise'] + 1
        load = run + A['WAIT'] - 1
        last = M.program(events, phase, cycles, A, [dict(cal=('delay', A['CAL_TIMEOUT']), strap=3)])
        rows, _ = M.expect(events, phase, cycles, A, last)
        self.assertEqual(rows[load + A['CAL_TIMEOUT']]['cal_start'], 1)
        self.assertEqual((rows[load + 1 + A['CAL_TIMEOUT']]['ready'], rows[load + 1 + A['CAL_TIMEOUT']]['init_fail']), (1, 0))
        late = M.program(events, phase, cycles, A, [dict(cal=('delay', A['CAL_TIMEOUT'] + 1), strap=3, done_again=True)])
        rows, _ = M.expect(events, phase, cycles, A, late)
        self.assertEqual((rows[-1]['ready'], rows[-1]['init_fail'], rows[-1]['cfg']), (0, 1, 3))
        before = M.program(events, phase, cycles, A, [dict(clear=('release', -1))])
        self.assertEqual(M.expect(events, phase, cycles, A, before)[0][-1]['por_flag'], 1)     # cleared while in reset: ignored
        at = M.program(events, phase, cycles, A, [dict(clear=('release', 0))])
        self.assertEqual(M.expect(events, phase, cycles, A, at)[0][run]['por_flag'], 0)

    def test_requirements_catalogue_matches_the_goals_the_runner_can_report(self):
        _, goals = RUN.E.C.catalog(HERE / 'requirements.json')
        self.assertEqual(len(goals), 34)
        self.assertEqual({label for _, label in RUN.MUTANTS.values()}, {'POR_RELEASE', 'POR_PARTIAL', 'POR_STATE', 'POR_ORDER', 'POR_UNKNOWN'})
        bench = (HERE / 'tb/por_tb.sv').read_text()
        import re
        shown = set(re.findall(r'COVER ([a-z/-]+)', bench))
        self.assertTrue(shown <= goals, shown - goals)
        for scenes in RUN.SCENES.values():
            self.assertTrue(scenes <= shown)


class RealTools(unittest.TestCase):
    """These use the pinned ngspice library and Icarus Verilog; without them the tests fail, not skip."""
    @classmethod
    def setUpClass(cls):
        cls.config = shutil.which('lsi-ngspice-config')
        cls.missing = [n for n in ('iverilog', 'vvp') if not shutil.which(n)]

    def setUp(self):
        self.assertIsNotNone(self.config, 'prepare ngspice and add its install/bin to PATH for the self-tests')
        self.assertEqual(self.missing, [])
        self.prefix = subprocess.run([self.config, '--prefix'], capture_output=True, text=True, check=True).stdout.strip()

    def solve(self, directory, text, request):
        directory = Path(directory)
        (directory / 'd.cir').write_text(text)
        (directory / 'r.json').write_text(json.dumps(request))
        return subprocess.run([sys.executable, str(HERE / 'solve.py'), self.prefix, str(directory / 'd.cir'), str(directory / 'r.json'),
                               str(directory / 'm.json'), str(directory / 'w.csv')], capture_output=True, text=True, timeout=120)

    def test_solver_failures_are_errors_and_leave_no_measurement(self):
        request = dict(stop=1e-4, step=1e-7, lookback=5e-5, windows=[])
        decks = {'no solution exists': 't\nV1 vdd 0 1\nR1 vdd vdiv 1k\nR2 vdiv 0 1k\nBx det 0 V = v(det) > 0.5 ? 0 : 1\n.save v(vdd) v(vdiv) v(det)\n.end\n',
                 'singular': 't\nV1 a 0 1\nV2 a 0 2\nR1 a vdiv 1k\nR2 vdiv det 1k\nR3 det vdd 1k\nR4 vdd 0 1k\n.save v(vdd) v(vdiv) v(det)\n.end\n',
                 'detector node missing': 't\nV1 vdd 0 1\nR1 vdd vdiv 1k\nR2 vdiv 0 1k\n.save v(vdd) v(vdiv)\n.end\n',
                 'syntax': 't\nV1 vdd 0 1\nR1 vdd vdiv\n.end\n'}
        for name, text in decks.items():
            with tempfile.TemporaryDirectory() as tmp:
                run = self.solve(tmp, text, request)
                self.assertEqual(run.returncode, 1, name)
                self.assertIn('SPICE_ERROR', run.stderr, name)
                self.assertNotIn('SPICE_PASS', run.stdout, name)
                self.assertFalse((Path(tmp) / 'm.json').exists(), name)
        spec = M.scenario('powerup', A)
        good = M.deck((HERE / 'por.cir.in').read_text(), A, spec)
        for name, bad in (('window without points', dict(M.request(A, spec), windows=[[1.0, 2.0]])), ('zero step', dict(M.request(A, spec), step=0)),
                          ('NaN stop', dict(M.request(A, spec), stop=float('nan'))), ('no lookback', {k: v for k, v in M.request(A, spec).items() if k != 'lookback'})):
            with tempfile.TemporaryDirectory() as tmp:
                run = self.solve(tmp, good, bad)
                self.assertEqual(run.returncode, 1, name)
                self.assertFalse((Path(tmp) / 'm.json').exists(), name)

    def test_a_solver_time_out_is_an_error_not_a_pass_or_a_detection(self):
        with tempfile.TemporaryDirectory() as tmp:
            args = SimpleNamespace(out=Path(tmp) / 'out', profile='smoke', seed=17, timeout=0.01, iverilog='iverilog', vvp='vvp')
            evidence = RUN.E.Evidence('timeout-probe', args, [HERE / 'run.py'], {}, ['only'])
            runner = RUN.Runner(evidence, Path(self.prefix))
            spec = M.scenario('slow-ramp', A)
            with self.assertRaisesRegex(ValueError, 'ngspice did not finish'):
                runner.solve('case', A, spec)
            ok, detail, rec, goals = runner.analog('fault', A, spec, 'no-hysteresis', 'ANALOG_CHATTER')
            self.assertEqual((ok, rec, goals), (False, None, set()))
            self.assertIn('did not finish', detail['error'])

    def test_smoke_passes_with_the_planned_checks_labels_and_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / 'out'
            run = subprocess.run([sys.executable, str(HERE / 'run.py'), '--out', str(out)], capture_output=True, text=True, timeout=300)
            self.assertEqual(run.returncode, 0, run.stdout[-3000:] + run.stderr[-2000:])
            summary = json.loads((out / 'summary.json').read_text())
            self.assertTrue(summary['success'] and summary['complete'])
            self.assertEqual(summary['planned'], 57)
            self.assertEqual((out / 'junit.xml').read_text().count('<testcase'), 57)
            details = {r['id']: r['detail'] for r in summary['results']}
            for config in M.CONFIGS:
                for fault, (_, label) in RUN.ANALOG_FAULTS.items():
                    self.assertEqual(details[f'{config}/detect-analog-{fault}']['label'], label)
                for mutation, (_, label) in RUN.MUTANTS.items():
                    self.assertEqual(details[f'{config}/detect-rtl-{mutation}']['message'], 'expected mutation detected by ' + label)
                self.assertEqual(details[f'{config}/coverage']['missing'], [])
                self.assertLessEqual(max(details[f'{config}/spice-settings']['max_shift_s']), M.TOL_SETTINGS_S)
                self.assertTrue((out / config / 'rtl-brownout' / 'wave.vcd').is_file())
                self.assertTrue((out / config / 'spice-brownout' / 'waveform.csv').is_file())
            again = subprocess.run([sys.executable, str(HERE / 'run.py'), '--out', str(out)], capture_output=True, text=True, timeout=60)
            self.assertNotEqual(again.returncode, 0)                 # an existing output directory is refused

    def test_missing_tools_cannot_pass(self):
        with tempfile.TemporaryDirectory() as tmp:
            for extra in (['--ngspice-config', 'no-such-config'], ['--iverilog', 'no-such-iverilog']):
                run = subprocess.run([sys.executable, str(HERE / 'run.py'), *extra, '--out', str(Path(tmp) / extra[1])],
                                     capture_output=True, text=True, timeout=300)
                self.assertEqual(run.returncode, 1, extra)

    def test_the_bench_fails_when_the_reference_expects_something_else(self):
        """Change one expected bit of a passing run and replay it: the comparison must object."""
        with tempfile.TemporaryDirectory() as tmp:
            pulses = M.async_pulses(A)
            inputs = M.program(pulses['events'], pulses['phase'], pulses['cycles'], A, pulses['plans'])
            rows, _ = M.expect(pulses['events'], pulses['phase'], pulses['cycles'], A, inputs)
            rows[40]['cfg'] ^= 1
            tmp = Path(tmp)
            (tmp / 'v.txt').write_text(M.vectors(inputs, rows))
            (tmp / 'e.txt').write_text(''.join(f'{t} {v}\n' for t, v in pulses['events']))
            build = subprocess.run(['iverilog', '-g2012', '-s', 'por_tb', '-o', str(tmp / 'b.vvp'), *map(str, RUN.SOURCES)], capture_output=True, text=True)
            self.assertEqual(build.returncode, 0, build.stderr)
            run = subprocess.run(['vvp', str(tmp / 'b.vvp'), '+VECTORS=' + str(tmp / 'v.txt'), '+EVENTS=' + str(tmp / 'e.txt'),
                                  '+WAVE=' + str(tmp / 'w.vcd'), f"+PHASE={pulses['phase']}"], capture_output=True, text=True, cwd=tmp)
            self.assertNotEqual(run.returncode, 0)
            self.assertIn('CHECK_FAIL POR_STATE', run.stdout)
            self.assertNotIn('RESULT PASS', run.stdout)


if __name__ == '__main__':
    unittest.main()

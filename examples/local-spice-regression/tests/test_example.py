"""Self-tests of the SPICE regression: the measurements, the statistics, the judge and the real runs."""
import copy
import importlib.util
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock
import xml.etree.ElementTree as ET

HERE = Path(__file__).resolve().parents[1]
ROOT = HERE.parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


RUN = load('spice_regression_run', HERE / 'run.py')
M = RUN.M
EXPECTED = json.loads((HERE / 'expected.json').read_text())
CONFIG = shutil.which('lsi-ngspice-config')


def record(values=None, tool=None, status='ok', points=100, name='inv'):
    return dict(id=name, status=status, detail='made up', values=values or {}, tool=tool or {}, points=points)


class FakeSolver:
    """Returns prepared records, so the judge can be tested at exact boundaries without ngspice."""
    def __init__(self, answer):
        self.answer, self.calls, self.e, self.args, self.prefix = answer, [], SimpleNamespace(out=None), None, None

    def run(self, name, jobs, timeout=None):
        self.calls.append((name, jobs))
        return self.answer(name, jobs)


class Measurements(unittest.TestCase):
    def test_crossings_interpolate_and_keep_direction(self):
        times = [0.0, 1.0, 2.0, 3.0, 4.0]
        values = [0.0, 1.0, 0.0, 1.0, 0.0]
        self.assertEqual(M.crossings(times, values, 0.25, True), [0.25, 2.25])
        self.assertEqual(M.crossings(times, values, 0.25, False), [1.75, 3.75])
        self.assertEqual(M.crossings(times, values, 2.0, True), [])
        # A sample exactly on the level counts once, for the segment that reaches it.
        self.assertEqual(M.crossings([0.0, 1.0, 2.0], [0.0, 0.5, 1.0], 0.5, True), [1.0])
        self.assertEqual(M.crossings([0.0, 1.0, 2.0], [1.0, 0.5, 0.0], 0.5, False), [1.0])

    def test_delay_takes_the_first_opposite_output_crossing_after_the_input(self):
        times = [0.0, 1.0, 2.0, 3.0, 4.0, 5.0]
        source = [0.0, 0.0, 1.0, 1.0, 1.0, 1.0]
        target = [1.0, 0.0, 1.0, 1.0, 0.0, 0.0]   # an early glitch before the input edge must not be used
        self.assertAlmostEqual(M.delay(times, source, target, 0.5, True), 2.0)
        for bad_source, bad_target in (([0.0] * 6, target), (source, [1.0] * 6)):
            with self.assertRaises(M.Mismatch) as raised:
                M.delay(times, bad_source, bad_target, 0.5, True)
            self.assertEqual(raised.exception.label, 'SPICE_MEASURE')

    def test_period_of_a_sine_and_too_few_cycles(self):
        times = [i * 1e-3 for i in range(12001)]
        values = [math.sin(2 * math.pi * t / 1.25) for t in times]
        self.assertAlmostEqual(M.period(times, values, 0.0), 1.25, places=6)
        with self.assertRaises(M.Mismatch) as raised:
            M.period(times[:9000], values[:9000], 0.0)     # 7.2 cycles: one crossing short
        self.assertEqual(raised.exception.label, 'SPICE_MEASURE')
        self.assertAlmostEqual(M.period(times[:11300], values[:11300], 0.0), 1.25, places=6)

    def test_a_ratio_that_is_not_defined_is_nan_and_nan_is_never_accepted(self):
        self.assertTrue(math.isnan(M.swing_ratio([0, 1], [0.0, 0.0], [0.0, 1.2])))
        self.assertAlmostEqual(M.swing_ratio([0, 1], [0.0, 1.0], [1.5, 0.0]), 1.5)
        for value in (math.nan, math.inf, -math.inf, None, 'x', 1):
            with self.assertRaises(M.Mismatch) as raised:
                M.finite('value', value)
            self.assertEqual(raised.exception.label, 'SPICE_NONFINITE')
        self.assertEqual(M.finite('value', 1.5), 1.5)

    def test_rc_reference_is_the_closed_form(self):
        tau = 1e-4
        reference = M.rc_reference(tau)
        self.assertAlmostEqual(1 - math.exp(-reference['t50'] / tau), 0.5)
        t10, t90 = -tau * math.log(0.9), -tau * math.log(0.1)
        self.assertAlmostEqual(reference['rise'], t90 - t10)
        times = [i * tau / 10 for i in range(60)]
        exact = [1 - math.exp(-t / tau) for t in times]
        self.assertLess(M.rc_error(times, exact, tau), 1e-15)
        self.assertAlmostEqual(M.rc_error(times, exact, 2 * tau), 0.25, places=2)   # twice the time constant

    def test_range_check_at_the_limit_and_one_step_beyond(self):
        M.in_range('L', 'x', 105.0, 100.0, 0.05)
        M.in_range('L', 'x', 95.0, 100.0, 0.05)
        for value in (105.0001, 94.9999, math.nan):
            with self.assertRaises(M.Mismatch):
                M.in_range('L', 'x', value, 100.0, 0.05)

    def test_hand_estimate_follows_the_square_law(self):
        typ = M.drive_estimate('tt', 1.2, M.LOAD)
        self.assertAlmostEqual(typ, 20e-15 * 0.6 / (0.5 * 220e-6 / 0.18 * 0.75 ** 2))
        self.assertLess(M.drive_estimate('ff', 1.32, M.LOAD), typ)
        self.assertGreater(M.drive_estimate('ss', 1.08, M.LOAD), typ)
        self.assertAlmostEqual(M.drive_estimate('tt', 1.2, 2 * M.LOAD), 2 * typ)


class Statistics(unittest.TestCase):
    def test_binomial_cdf_matches_the_direct_sum(self):
        for n, p in ((12, 0.3), (300, 0.9087), (40, 0.5)):
            for k in (0, 1, n // 2, n - 1):
                direct = sum(math.comb(n, i) * p ** i * (1 - p) ** (n - i) for i in range(k + 1))
                self.assertAlmostEqual(M.binomial_cdf(k, n, p), direct, places=10)
        self.assertEqual(M.binomial_cdf(-1, 10, 0.5), 0.0)
        self.assertEqual(M.binomial_cdf(10, 10, 0.5), 1.0)

    def test_acceptance_region_is_as_tight_as_alpha_allows(self):
        n, p, alpha = 300, 0.9, 0.001
        low, high = M.acceptance(n, p, p, alpha)
        self.assertGreater(M.binomial_cdf(low, n, p), alpha)           # low itself is accepted
        self.assertLessEqual(M.binomial_cdf(low - 1, n, p), alpha)     # one fewer is rejected
        self.assertGreater(1 - M.binomial_cdf(high - 1, n, p), alpha)
        self.assertLessEqual(1 - M.binomial_cdf(high, n, p), alpha)
        wider = M.acceptance(n, p - 0.01, p + 0.01, alpha)
        self.assertLessEqual(wider[0], low)
        self.assertGreaterEqual(wider[1], high)

    def test_recorded_region_follows_from_the_recorded_reference(self):
        mc = EXPECTED['monte_carlo']
        self.assertEqual(RUN.acceptance_region(mc, 300), tuple(mc['acceptance']['300']))
        self.assertEqual(RUN.acceptance_region(mc, 1000), tuple(mc['acceptance']['1000']))
        low, high = M.clopper_pearson(mc['reference']['passes'], mc['reference']['trials'], mc['reference_confidence'])
        self.assertLess(low, mc['reference']['passes'] / mc['reference']['trials'])
        self.assertLess(high - low, 0.015)   # the reference is much tighter than a 300-trial sample

    def test_clopper_pearson_solves_both_tail_equations(self):
        k, n, confidence = 274, 300, 0.99
        low, high = M.clopper_pearson(k, n, confidence)
        self.assertAlmostEqual(1 - M.binomial_cdf(k - 1, n, low), 0.005, places=6)
        self.assertAlmostEqual(M.binomial_cdf(k, n, high), 0.005, places=6)
        self.assertEqual(M.clopper_pearson(0, 50, 0.99)[0], 0.0)
        self.assertEqual(M.clopper_pearson(50, 50, 0.99)[1], 1.0)
        self.assertAlmostEqual(M.clopper_pearson(0, 50, 0.99)[1], 1 - 0.005 ** (1 / 50), places=6)

    def test_draws_depend_on_the_seed_the_stream_and_the_shift_only(self):
        self.assertEqual(M.draws(17, 50), M.draws(17, 50))
        self.assertEqual(M.draws(17, 50)[:20], M.draws(17, 20))
        self.assertNotEqual(M.draws(17, 50), M.draws(18, 50))
        self.assertNotEqual(M.draws(17, 50), M.draws(17, 50, stream='reference'))
        plain, shifted = M.draws(5, 4000), M.draws(5, 4000, mean_shift=0.02)
        mean = lambda rows, key: sum(r[key] for r in rows) / len(rows)
        self.assertAlmostEqual(mean(plain, 'n_vto'), 0.0, delta=0.001)
        self.assertAlmostEqual(mean(shifted, 'n_vto'), 0.02, delta=0.001)
        self.assertAlmostEqual(mean(plain, 'n_kp'), 1.0, delta=0.005)


class Decks(unittest.TestCase):
    def test_process_corners_move_threshold_and_gain_in_the_slow_direction(self):
        value = lambda line, key: float(line.split(key + '=')[1].split()[0])
        fast, typ, slow = (M.cards(p) for p in ('ff', 'tt', 'ss'))
        self.assertLess(value(fast[0], 'vto'), value(typ[0], 'vto'))
        self.assertLess(value(typ[0], 'vto'), value(slow[0], 'vto'))
        self.assertGreater(value(fast[1], 'vto'), value(typ[1], 'vto'))    # the p-channel threshold is negative
        self.assertGreater(value(fast[0], 'kp'), value(slow[0], 'kp'))
        shifted = M.cards('tt', dict(n_vto=0.01, p_vto=0.02, n_kp=1.1, p_kp=0.9))
        self.assertAlmostEqual(value(shifted[0], 'vto'), 0.46)
        self.assertAlmostEqual(value(shifted[1], 'vto'), -0.47)
        self.assertAlmostEqual(value(shifted[0], 'kp'), 242e-6)

    def test_decks_carry_the_condition_they_were_asked_for(self):
        deck = M.inverter_deck('ss', 125.0, 1.08)
        self.assertIn('temp=125', deck['deck'][3])
        self.assertIn('Vdd vdd 0 1.08', deck['deck'])
        self.assertTrue(any(line.startswith('Vin in 0 pulse(0 1.08') for line in deck['deck']))
        self.assertIn('Vin in 0 DC 0', M.inverter_deck('tt', 25.0, 1.2, hold_input=True)['deck'])
        ring = M.ring_deck('tt', 25.0, 1.2, weak_stage=2)
        loads = [line for line in ring['deck'] if line.startswith('C')]
        self.assertEqual(len(loads), M.STAGES)
        self.assertEqual(sum('4e-14' in line for line in loads), 1)
        self.assertEqual(M.rc_deck(1000.0, 1e-7)['stop'], 6e-4)

    def test_negative_jobs_differ_from_the_good_job_only_where_intended(self):
        good = RUN.inverter_job('j', 'tt', 25.0, 1.2)
        endless, broken = RUN.endless_job(), RUN.broken_netlist()
        self.assertEqual(endless['deck'], good['deck'])
        self.assertNotEqual(endless['tran'], good['tran'])
        self.assertEqual(sum(a != b for a, b in zip(broken['deck'], good['deck'])), 1)


class Judge(unittest.TestCase):
    def checks(self, answer):
        return RUN.Checks(FakeSolver(answer), copy.deepcopy(EXPECTED), 'smoke', 17)

    def inverter(self, **change):
        nominal = EXPECTED['inverter']['typ']
        values = dict(tphl=nominal['tphl'], tplh=nominal['tplh'], swing=1.07)
        values.update(change.get('values', {}))
        tool = dict(tphl=values['tphl'], tplh=values['tplh'])
        tool.update(change.get('tool', {}))
        return self.checks(lambda name, jobs: {'inv': record(values, tool, change.get('status', 'ok'))})

    def label(self, function):
        with self.assertRaises(M.Mismatch) as raised:
            function()
        return raised.exception.label

    def test_inverter_is_judged_by_each_rule_separately(self):
        nominal = EXPECTED['inverter']['typ']
        self.assertEqual(self.inverter().inverter('typ')['estimate_ratio'], 1.666)
        self.inverter(values=dict(tphl=nominal['tphl'] * 1.0199), tool=dict(tphl=nominal['tphl'] * 1.0199)).inverter('typ')
        cases = [
            (dict(values=dict(tphl=nominal['tphl'] * 1.0201), tool=dict(tphl=nominal['tphl'] * 1.0201)), 'INV_DELAY'),
            (dict(values=dict(tplh=nominal['tplh'] * 0.9799), tool=dict(tplh=nominal['tplh'] * 0.9799)), 'INV_DELAY'),
            (dict(tool=dict(tphl=nominal['tphl'] * 1.0011)), 'MEAS_METHOD'),
            (dict(values=dict(swing=0.9)), 'INV_SWING'),
            (dict(values=dict(swing=1.2)), 'INV_SWING'),
            (dict(values=dict(tphl=math.nan)), 'SPICE_NONFINITE'),
            (dict(status='SPICE_CONVERGENCE'), 'SPICE_CONVERGENCE'),
            (dict(status='SPICE_TIMEOUT'), 'SPICE_TIMEOUT'),
        ]
        for change, label in cases:
            self.assertEqual(self.label(lambda: self.inverter(**change).inverter('typ')), label, change)

    def test_a_delay_far_from_the_hand_estimate_is_caught_even_inside_a_wrong_range(self):
        checks = self.inverter(values=dict(tphl=5e-10), tool=dict(tphl=5e-10))
        checks.x['inverter']['typ']['tphl'] = 5e-10          # someone recorded a value ten times too large
        self.assertEqual(self.label(lambda: checks.inverter('typ')), 'INV_ESTIMATE')

    def test_rc_is_judged_against_the_formula_not_against_a_recorded_number(self):
        item = EXPECTED['rc'][0]
        reference = M.rc_reference(item['r'] * item['c'])
        def answer(values):
            return lambda name, jobs: {'rc': record(dict(error=1e-6, **values), dict(t50=values['t50'], rise=values['rise']),
                                                    name='rc')}
        self.checks(answer(reference)).rc(item)
        for values in (dict(reference, t50=reference['t50'] * 1.002), dict(reference, rise=reference['rise'] * 0.998)):
            self.assertEqual(self.label(lambda: self.checks(answer(values)).rc(item)), 'RC_TAU')
        late = lambda name, jobs: {'rc': record(dict(error=2e-4, **reference), reference, name='rc')}
        self.assertEqual(self.label(lambda: self.checks(late).rc(item)), 'RC_TAU')

    def monte_carlo(self, passes, failed=None):
        limit = EXPECTED['monte_carlo']['limit']
        def answer(name, jobs):
            out = {}
            for i, job in enumerate(jobs):
                delay = limit * (0.99 if i < passes else 1.01)
                out[job['id']] = record(dict(tphl=delay, tplh=delay), name=job['id'])
            if failed is not None:
                out[f't{failed}'] = record(status='SPICE_CONVERGENCE', name=f't{failed}')
            return out
        checks = self.checks(answer)
        with tempfile.TemporaryDirectory() as tmp:
            checks.s.e = SimpleNamespace(out=Path(tmp))
            (Path(tmp) / 'mc-seed17').mkdir()
            return checks.monte_carlo(17)

    def test_pass_count_at_both_ends_of_the_region_and_one_outside(self):
        low, high = EXPECTED['monte_carlo']['acceptance']['300']
        self.assertEqual(self.monte_carlo(low)['passes'], low)
        self.assertEqual(self.monte_carlo(high)['passes'], high)
        self.assertEqual(self.label(lambda: self.monte_carlo(low - 1)), 'MC_YIELD')
        self.assertEqual(self.label(lambda: self.monte_carlo(high + 1)), 'MC_YIELD')   # too good is also a finding

    def test_a_trial_that_did_not_finish_is_neither_a_pass_nor_a_fail(self):
        low, _ = EXPECTED['monte_carlo']['acceptance']['300']
        self.assertEqual(self.label(lambda: self.monte_carlo(low + 5, failed=3)), 'SPICE_CONVERGENCE')

    def test_a_trial_exactly_at_the_limit_passes(self):
        limit = EXPECTED['monte_carlo']['limit']
        answer = lambda name, jobs: {job['id']: record(dict(tphl=limit, tplh=limit), name=job['id']) for job in jobs}
        checks = self.checks(answer)
        with tempfile.TemporaryDirectory() as tmp:
            checks.s.e = SimpleNamespace(out=Path(tmp))
            (Path(tmp) / 'mc-seed17').mkdir()
            self.assertEqual(self.label(lambda: checks.monte_carlo(17)), 'MC_YIELD')   # 300 of 300 is above the region

    def test_corner_order_needs_all_three_quantities(self):
        checks = self.checks(None)
        checks.cache = {'inv-fast': dict(tphl=1.0, tplh=1.0), 'inv-typ': dict(tphl=2.0, tplh=2.0),
                        'inv-slow': dict(tphl=3.0, tplh=3.0), 'ring-fast': 1.0, 'ring-typ': 2.0, 'ring-slow': 3.0}
        checks.order()
        for key, value in (('inv-typ', dict(tphl=3.5, tplh=2.0)), ('inv-slow', dict(tphl=3.0, tplh=1.5)), ('ring-typ', 0.5)):
            broken = self.checks(None)
            broken.cache = dict(checks.cache, **{key: value})
            self.assertEqual(self.label(broken.order), 'CORNER_ORDER')


class Worker(unittest.TestCase):
    def solver(self, execution, write=None):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        solver = RUN.Solver(SimpleNamespace(out=Path(tmp.name)), SimpleNamespace(timeout=5), Path('/nowhere'))
        def fake(command, log, timeout, cwd):
            if write is not None:
                Path(command[-1]).write_text(json.dumps(write))
            return execution
        return solver, mock.patch.object(RUN.P, 'execute', fake)

    def test_a_worker_that_dies_or_times_out_marks_every_job(self):
        jobs = [dict(id='a', deck=[]), dict(id='b', deck=[])]
        for execution, label in ((dict(returncode=None, error='command timeout after 3s', seconds=3), 'SPICE_TIMEOUT'),
                                 (dict(returncode=1, error=None, seconds=0), 'SPICE_FATAL'),
                                 (dict(returncode=0, error=None, seconds=0), 'SPICE_FATAL')):   # exit 0, no result file
            solver, patch = self.solver(execution)
            with patch:
                self.assertEqual({r['status'] for r in solver.run('x', copy.deepcopy(jobs)).values()}, {label})

    def test_a_result_for_a_different_set_of_jobs_is_refused(self):
        solver, patch = self.solver(dict(returncode=0, error=None, seconds=0), write=[record(name='a')])
        with patch, self.assertRaises(ValueError):
            solver.run('x', [dict(id='a', deck=[]), dict(id='b', deck=[])])


class Plan(unittest.TestCase):
    def cases(self, profile):
        args = SimpleNamespace(profile=profile, seed=17, timeout=30)
        return RUN.plan(RUN.Checks(FakeSolver(None), EXPECTED, profile, 17), args)

    def test_every_goal_is_earned_and_every_negative_names_its_label(self):
        _, goals = RUN.E.C.catalog(HERE / 'requirements.json')
        for profile, count in (('smoke', 29), ('nightly', 31)):
            cases = self.cases(profile)
            self.assertEqual(len(cases), count)
            self.assertEqual(len({c[0] for c in cases}), count)
            self.assertEqual({g for c in cases for g in c[3]}, goals)
            for name, _, label, _ in cases:
                self.assertEqual(label is not None, name.startswith('detect-'), name)
        labels = sorted(c[2] for c in self.cases('smoke') if c[2])
        self.assertEqual(labels, ['INV_DELAY', 'INV_DELAY', 'INV_DELAY', 'MC_YIELD', 'MC_YIELD', 'RC_TAU', 'RING_FREQ',
                                  'SPICE_CONVERGENCE', 'SPICE_MEASURE', 'SPICE_NETLIST', 'SPICE_NONFINITE', 'SPICE_TIMEOUT'])


class RealRuns(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(CONFIG, 'prepare ngspice and add install/bin to PATH for all selftests')

    def run_example(self, *options, cwd=ROOT):
        return subprocess.run([sys.executable, str(HERE / 'run.py'), *options], cwd=cwd, capture_output=True,
                              text=True, timeout=180)

    def test_smoke_passes_with_a_relative_config_and_leaves_the_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / 'out'
            run = self.run_example('--ngspice-config', os.path.relpath(CONFIG, ROOT), '--out', str(out))
            self.assertEqual(run.returncode, 0, run.stdout[-3000:] + run.stderr[-2000:])
            summary = json.loads((out / 'summary.json').read_text())
            self.assertTrue(summary['success'] and summary['complete'])
            self.assertEqual(summary['planned'], 32)
            cases = list(ET.parse(out / 'junit.xml').getroot().iter('testcase'))
            self.assertEqual(len(cases), 32)
            self.assertFalse(list(ET.parse(out / 'junit.xml').getroot().iter('failure')))
            detail = {r['id']: r['detail'] for r in summary['results']}
            self.assertEqual(detail['detect-no-convergence']['actual'], 'SPICE_CONVERGENCE')
            self.assertEqual(detail['detect-endless-analysis']['actual'], 'SPICE_TIMEOUT')
            self.assertEqual(detail['diagnose-return-code']['code'], 0)
            self.assertEqual(detail['monte-carlo/seed17']['trials'], 300)
            self.assertEqual(detail['corners/grid']['corners'], 27)
            self.assertEqual(detail['corners/grid']['worst']['tplh']['corner'][:2], 'ss')
            for path in ('inv-typ/waveform.csv', 'ring-typ/waveform.csv', 'rc-1k-100n/waveform.csv',
                         'mc-seed17/draws.json', 'ngspice-source.json'):
                self.assertTrue((out / path).is_file(), path)
            self.assertEqual(len(json.loads((out / 'mc-seed17/draws.json').read_text())), 300)
            again = Path(tmp) / 'again'
            self.assertEqual(self.run_example('--out', str(again)).returncode, 0)
            second = {r['id']: r['detail'] for r in json.loads((again / 'summary.json').read_text())['results']}
            for name in ('monte-carlo/seed17', 'inverter/typ', 'ring/slow', 'corners/grid'):
                self.assertEqual(detail[name], second[name], name)     # the same seed gives the same numbers
            refused = self.run_example('--out', str(out))
            self.assertNotEqual(refused.returncode, 0)

    def test_another_seed_changes_only_the_monte_carlo_draws(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / 'out'
            self.assertEqual(self.run_example('--seed', '23', '--out', str(out)).returncode, 0)
            detail = {r['id']: r['detail'] for r in json.loads((out / 'summary.json').read_text())['results']}
            self.assertIn('monte-carlo/seed23', detail)
            self.assertEqual(detail['inverter/typ']['measured']['tphl'], float(f"{EXPECTED['inverter']['typ']['tphl']:.6g}"))
            self.assertNotEqual(json.loads((out / 'mc-seed23/draws.json').read_text()), M.draws(17, 300))

    def test_missing_tool_and_bad_arguments_cannot_pass(self):
        with tempfile.TemporaryDirectory() as tmp:
            missing = self.run_example('--ngspice-config', 'no-such-ngspice-config', '--out', str(Path(tmp) / 'a'))
            self.assertEqual(missing.returncode, 1)
            self.assertIn('RUNNER_ERROR', missing.stderr)
            self.assertNotEqual(self.run_example('--timeout', '0', '--out', str(Path(tmp) / 'b')).returncode, 0)
            self.assertNotEqual(self.run_example('--seed', '-1', '--out', str(Path(tmp) / 'c')).returncode, 0)

    def test_a_wrong_recorded_range_fails_the_run(self):
        """The ranges are not decoration: move one nominal by 3 % and the good circuit is rejected."""
        with tempfile.TemporaryDirectory() as tmp:
            wrong = copy.deepcopy(EXPECTED)
            wrong['inverter']['typ']['tphl'] *= 1.03
            path = Path(tmp) / 'expected.json'
            path.write_text(json.dumps(wrong))
            script = ("import importlib.util,sys\n"
                      f"spec=importlib.util.spec_from_file_location('r',{str(HERE / 'run.py')!r})\n"
                      "r=importlib.util.module_from_spec(spec);spec.loader.exec_module(r)\n"
                      f"r.EXPECTED=__import__('pathlib').Path({str(path)!r})\n"
                      f"sys.argv=['run.py','--out',{str(Path(tmp) / 'out')!r}]\nsys.exit(r.main())\n")
            run = subprocess.run([sys.executable, '-c', script], cwd=ROOT, capture_output=True, text=True, timeout=180)
            self.assertEqual(run.returncode, 1, run.stdout[-2000:])
            self.assertIn('CHECK_FAIL INV_DELAY inverter/typ', run.stdout)

    def test_worker_reports_each_kind_of_failure_and_keeps_going_after_a_bad_deck(self):
        prefix = subprocess.run([CONFIG, '--prefix'], capture_output=True, text=True, check=True).stdout.strip()
        good = RUN.inverter_job('good', 'tt', 25.0, 1.2)
        aborted = RUN.inverter_job('aborted', 'tt', 25.0, 1.2, settings=dict(reltol=1e-12, method='gear', step=5e-12),
                                   extra='itl4=2 abstol=1e-18 vntol=1e-12')
        bad = dict(RUN.broken_netlist(), id='bad')
        still = RUN.inverter_job('still', 'tt', 25.0, 1.2, hold_input=True)
        unknown = RUN.inverter_job('unknown', 'tt', 25.0, 1.2)
        unknown['vectors'] = ['time', 'v(in)', 'v(out)', 'v(no_such_node)']
        with tempfile.TemporaryDirectory() as tmp:
            jobs, result = Path(tmp) / 'jobs.json', Path(tmp) / 'results.json'
            jobs.write_text(json.dumps([bad, aborted, still, unknown, good]))
            run = subprocess.run([sys.executable, str(HERE / 'solve.py'), prefix, str(jobs), str(result)],
                                 capture_output=True, text=True, timeout=120, cwd=tmp)
            self.assertEqual(run.returncode, 0, run.stderr)
            status = {r['id']: r['status'] for r in json.loads(result.read_text())}
            self.assertEqual(status, dict(bad='SPICE_NETLIST', aborted='SPICE_CONVERGENCE', still='SPICE_MEASURE',
                                          unknown='SPICE_MEASURE', good='ok'))
            values = {r['id']: r for r in json.loads(result.read_text())}['good']
            self.assertAlmostEqual(values['values']['tphl'], EXPECTED['inverter']['typ']['tphl'], delta=1e-13)
            self.assertAlmostEqual(values['tool']['tphl'], values['values']['tphl'], delta=1e-14)


if __name__ == '__main__':
    unittest.main()

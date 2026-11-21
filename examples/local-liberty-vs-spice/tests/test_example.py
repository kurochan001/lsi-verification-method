"""Self-tests of the Liberty-versus-SPICE example: the formulas, the judgements and one real run."""
import copy
import importlib.util
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET

HERE = Path(__file__).resolve().parents[1]
ROOT = HERE.parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


RUN = load('liberty_vs_spice_run_test', HERE / 'run.py')
MODEL, CELLS = RUN.MODEL, RUN.CELLS
MEASURE = load('liberty_vs_spice_measure_test', HERE / 'measure.py')
TABLE = MODEL.load_table()


def label(action):
    try:
        action()
    except MODEL.Mismatch as exc:
        return exc.label
    return None


class FormulaTest(unittest.TestCase):
    def test_level_one_current_by_region_and_continuity(self):
        self.assertEqual(MODEL.drain_current('nmos', 0.45, 1.8), 0.0)
        self.assertEqual(MODEL.drain_current('pmos', 0.3, 1.8), 0.0)
        # 0.5 * 220u * (0.5/0.18) * 1.35^2 * (1 + 0.05*1.8), written out
        self.assertAlmostEqual(MODEL.drain_current('nmos', 1.8, 1.8), 6.0699375e-4, delta=1e-12)
        self.assertAlmostEqual(MODEL.drain_current('pmos', 1.8, 0.9), 110e-6 * (1 / 0.18) * 0.81 * 1.045, delta=1e-12)
        edge = 1.35   # triode and saturation meet at Vds = Vgs - Vt
        self.assertAlmostEqual(MODEL.drain_current('nmos', 1.8, edge - 1e-9), MODEL.drain_current('nmos', 1.8, edge + 1e-9), delta=1e-11)

    def test_both_copies_of_the_model_card_agree(self):
        for kind, card in (('nmos', CELLS.NMOS), ('pmos', CELLS.PMOS)):
            mine = MODEL.CARDS[kind]
            self.assertEqual((abs(card['vto']), card['kp'], card['lam']), (mine['vto'], mine['kp'], mine['lam']))
        self.assertEqual((CELLS.WN * 1e6, CELLS.WP * 1e6), (MODEL.CARDS['nmos']['width_um'], MODEL.CARDS['pmos']['width_um']))
        self.assertEqual((CELLS.VDD, round(CELLS.LENGTH * 1e6, 6)), (MODEL.VDD, MODEL.LENGTH_UM))
        # equal strength is what puts the inverter threshold at VDD/2
        self.assertAlmostEqual(CELLS.NMOS['kp'] * CELLS.WN, CELLS.PMOS['kp'] * CELLS.WP)

    def test_load_slope_and_stage_estimate_values(self):
        self.assertAlmostEqual(MODEL.load_slope('rise'), 0.40026, places=4)
        self.assertAlmostEqual(MODEL.load_slope('fall'), MODEL.load_slope('rise'), places=9)
        self.assertAlmostEqual(MODEL.stage_estimate(), 44.03, places=1)

    def test_interpolation_is_exact_at_entries_and_refuses_extrapolation(self):
        rows, columns, values = [10, 50], [1, 3], [[1.0, 3.0], [5.0, 7.0]]
        self.assertEqual(MODEL.interpolate(rows, columns, values, 10, 1), 1.0)
        self.assertEqual(MODEL.interpolate(rows, columns, values, 50, 3), 7.0)
        self.assertEqual(MODEL.interpolate(rows, columns, values, 30, 2), 4.0)
        for point in ((9.9, 2), (30, 3.1)):
            with self.assertRaises(ValueError):
                MODEL.interpolate(rows, columns, values, *point)


class StimulusTest(unittest.TestCase):
    def points(self, line):
        numbers = [float(x) for x in re.search(r'PWL\((.*)\)', line)[1].split()]
        return list(zip(numbers[::2], numbers[1::2]))

    def test_ramp_crosses_half_at_the_event_with_the_stated_transition(self):
        points = self.points(CELLS.ramp('x', 'x', 0.0, [1e-9], 60e-12))
        (t0, v0), (t1, v1) = points[1], points[2]
        self.assertEqual((v0, v1), (0.0, CELLS.VDD))
        self.assertAlmostEqual((t0 + t1) / 2, 1e-9, delta=1e-18)
        self.assertAlmostEqual(0.6 * (t1 - t0), 60e-12, delta=1e-18)   # 20 % to 80 % of a straight ramp

    def test_overlapping_events_are_refused(self):
        with self.assertRaises(ValueError):
            CELLS.ramp('x', 'x', 0.0, [1e-9, 1e-9 + 10e-12], 60e-12)

    def test_faults_change_only_what_they_name(self):
        base = CELLS.capture_deck(1, 2e-9, 5e-11, 5e-11, 2e-14)
        self.assertEqual(sum(line.startswith('Vdd') for line in base), 1)
        self.assertEqual(sum(line.startswith('Vdd') for line in CELLS.capture_deck(1, 2e-9, 5e-11, 5e-11, 2e-14, fault='double-supply')), 2)
        stuck = CELLS.capture_deck(1, 2e-9, 5e-11, 5e-11, 2e-14, fault='stuck-clock')
        self.assertEqual(len(self.points(next(l for l in stuck if l.startswith('Vclk')))), 1)
        for fault in ('weak-output', 'slow-master'):
            changed = [a for a, b in zip(base, CELLS.capture_deck(1, 2e-9, 5e-11, 5e-11, 2e-14, fault=fault)) if a != b]
            self.assertEqual(len(changed), 1, fault)
        with self.assertRaises(ValueError):
            CELLS.flop('unknown')

    def test_hold_stimulus_returns_data_after_the_clock(self):
        deck = CELLS.capture_deck(1, CELLS.CAPTURE - 1e-9, 1e-11, 1e-11, 2e-14, back_time=CELLS.CAPTURE + 5e-12)
        points = self.points(next(l for l in deck if l.startswith('Vd ')))
        self.assertEqual([v for _, v in points], [0.0, 0.0, CELLS.VDD, CELLS.VDD, 0.0])


class MeasureTest(unittest.TestCase):
    def test_crossing_interpolates_and_respects_direction_and_start(self):
        times, values = [0, 1, 2, 3, 4], [0.0, 1.0, 0.0, 1.0, 1.0]
        self.assertEqual(MEASURE.crossing(times, values, 0.5, 0, True), 0.5)
        self.assertEqual(MEASURE.crossing(times, values, 0.5, 0, False), 1.5)
        self.assertEqual(MEASURE.crossing(times, values, 0.5, 2, True), 2.5)
        self.assertIsNone(MEASURE.crossing(times, values, 0.5, 4, True))
        self.assertIsNone(MEASURE.crossing(times, values, 2.0, 0, True))

    def test_capture_verdict_needs_the_value_and_the_delay_limit(self):
        job = dict(new=1)
        good = dict(delay=100e-12, final_q=1.8)
        self.assertTrue(MEASURE.captured(good, job, 100e-12, 'degrade'))
        self.assertTrue(MEASURE.captured(dict(good, delay=110e-12), job, 100e-12, 'degrade'))      # exactly 10 %
        self.assertFalse(MEASURE.captured(dict(good, delay=110.1e-12), job, 100e-12, 'degrade'))   # just over
        self.assertTrue(MEASURE.captured(dict(good, delay=300e-12), job, 100e-12, 'captures'))
        self.assertFalse(MEASURE.captured(dict(good, final_q=0.0), job, 100e-12, 'captures'))
        self.assertFalse(MEASURE.captured(dict(good, delay=None), job, 100e-12, 'captures'))
        self.assertFalse(MEASURE.captured(dict(delay=50e-12, final_q=1.8), dict(new=0), 100e-12, 'degrade'))


class JudgementTest(unittest.TestCase):
    def test_table_validation(self):
        for change in (lambda t: t.update(schema_version=2), lambda t: t['cell_rise'].pop(),
                       lambda t: t['cell_rise'][0].pop(), lambda t: t['setup_rise'][0].__setitem__(0, float('nan')),
                       lambda t: t.update(load_ff=[10, 10, 100]), lambda t: t.pop('hold_fall'),
                       lambda t: t['cell_fall'][1].__setitem__(1, '1')):
            table = copy.deepcopy(TABLE)
            change(table)
            self.assertEqual(label(lambda: MODEL.validate_table(table)), 'TABLE_FORMAT')
        self.assertIs(MODEL.validate_table(copy.deepcopy(TABLE))['schema_version'], 1)

    def test_measurement_records_are_rejected_by_kind(self):
        good = dict(error=None, delay=1e-10)
        self.assertEqual(MODEL.need({'a': good}, 'a', 'delay'), good)
        cases = [({}, 'MEAS_MISSING'), ({'a': dict(error='ngspice analysis failed')}, 'SPICE_ERROR'),
                 ({'a': dict(error='Q does not switch after the clock edge')}, 'MEAS_MISSING'),
                 ({'a': dict(error=None)}, 'MEAS_MISSING'), ({'a': dict(error=None, delay=None)}, 'MEAS_MISSING'),
                 ({'a': dict(error=None, delay=float('nan'))}, 'MEAS_INVALID'),
                 ({'a': dict(error=None, delay=float('inf'))}, 'MEAS_INVALID'),
                 ({'a': dict(error=None, delay=True)}, 'MEAS_INVALID'), ({'a': dict(error=None, delay='1')}, 'MEAS_INVALID')]
        for results, expected in cases:
            self.assertEqual(label(lambda: MODEL.need(results, 'a', 'delay')), expected, results)

    def test_delay_tolerance_at_and_just_over_the_limit(self):
        measured = {name: copy.deepcopy(TABLE[name]) for name in MODEL.DELAY_TABLES}
        want = TABLE['cell_rise'][0][0]
        limit = MODEL.DELAY_ABS + MODEL.DELAY_REL * want
        measured['cell_rise'][0][0] = want + limit * 0.999
        self.assertAlmostEqual(MODEL.compare_delays(measured, TABLE), limit * 0.999)
        measured['cell_rise'][0][0] = want + limit * 1.001
        self.assertEqual(label(lambda: MODEL.compare_delays(measured, TABLE)), 'TABLE_DELAY')
        measured['cell_rise'][0][0] = want - limit * 1.001
        self.assertEqual(label(lambda: MODEL.compare_delays(measured, TABLE)), 'TABLE_DELAY')

    def test_constraint_tolerance_and_labels_by_kind(self):
        measured = {name: copy.deepcopy(TABLE[name]) for name in MODEL.CHECK_TABLES}
        measured['hold_fall'][1][1] += MODEL.CONSTRAINT_ABS + 0.01
        self.assertEqual(MODEL.compare_checks(measured, TABLE, 'setup'), 0.0)   # the setup tables are untouched
        self.assertEqual(label(lambda: MODEL.compare_checks(measured, TABLE, 'hold')), 'TABLE_HOLD')
        measured['hold_fall'][1][1] = TABLE['hold_fall'][1][1] + MODEL.CONSTRAINT_ABS - 0.01
        self.assertAlmostEqual(MODEL.compare_checks(measured, TABLE, 'hold'), MODEL.CONSTRAINT_ABS - 0.01)
        measured['setup_rise'][0][0] -= MODEL.CONSTRAINT_ABS + 0.01
        self.assertEqual(label(lambda: MODEL.compare_checks(measured, TABLE, 'setup')), 'TABLE_SETUP')

    def test_trends_reject_a_flat_or_reversed_table(self):
        self.assertTrue(MODEL.check_trends({n: TABLE[n] for n in MODEL.DELAY_TABLES}))
        flat = {n: copy.deepcopy(TABLE[n]) for n in MODEL.DELAY_TABLES}
        flat['cell_fall'][2] = [flat['cell_fall'][2][0]] * 3
        self.assertEqual(label(lambda: MODEL.check_trends(flat)), 'TREND_LOAD')
        slew = {n: copy.deepcopy(TABLE[n]) for n in MODEL.DELAY_TABLES}
        slew['cell_rise'][1], slew['cell_rise'][2] = slew['cell_rise'][2], slew['cell_rise'][1]
        self.assertEqual(label(lambda: MODEL.check_trends(slew)), 'TREND_SLEW')
        checks = {n: copy.deepcopy(TABLE[n]) for n in MODEL.CHECK_TABLES}
        self.assertTrue(MODEL.check_constraint_trends(checks))
        checks['setup_rise'] = checks['setup_rise'][::-1]
        self.assertEqual(label(lambda: MODEL.check_constraint_trends(checks)), 'TREND_SETUP')
        checks = {n: copy.deepcopy(TABLE[n]) for n in MODEL.CHECK_TABLES}
        checks['hold_fall'][0] = checks['hold_fall'][0][::-1]
        self.assertEqual(label(lambda: MODEL.check_constraint_trends(checks)), 'TREND_HOLD')

    def test_slope_and_estimate_reject_a_wrong_driver(self):
        good = {n: TABLE[n] for n in MODEL.DELAY_TABLES}
        self.assertEqual(set(MODEL.check_slope(good, TABLE)), {'rise', 'fall'})
        steep = {n: [[v + 0.4 * (c - 10) for v, c in zip(row, TABLE['load_ff'])] for row in TABLE[n]] for n in MODEL.DELAY_TABLES}
        self.assertEqual(label(lambda: MODEL.check_slope(steep, TABLE)), 'LOAD_SLOPE')   # a driver of half the width
        self.assertEqual(MODEL.check_estimate(good)['fastest'], 94.42)
        tiny = {n: [[v / 10 for v in row] for row in TABLE[n]] for n in MODEL.DELAY_TABLES}
        self.assertEqual(label(lambda: MODEL.check_estimate(tiny)), 'DELAY_ESTIMATE')

    def search(self, **change):
        probes = [dict(value=-300e-12, captured=False), dict(value=500e-12, captured=True),
                  dict(value=4.0e-12, captured=True), dict(value=3.2e-12, captured=False)]
        return dict(dict(value=4.0e-12, fails_at=3.2e-12, probes=probes), **change)

    def test_search_evidence_must_justify_the_boundary(self):
        self.assertEqual(MODEL.check_search(self.search()), 4)
        self.assertEqual(label(lambda: MODEL.check_search(self.search(fails_at=2.0e-12))), 'SEARCH_EVIDENCE')   # wider than 1 ps
        self.assertEqual(label(lambda: MODEL.check_search(self.search(value=3.6e-12))), 'SEARCH_EVIDENCE')      # never probed
        contradiction = self.search()
        contradiction['probes'].append(dict(value=100e-12, captured=False))
        self.assertEqual(label(lambda: MODEL.check_search(contradiction)), 'SEARCH_EVIDENCE')
        swapped = self.search(value=3.2e-12, fails_at=4.0e-12)
        self.assertEqual(label(lambda: MODEL.check_search(swapped)), 'SEARCH_EVIDENCE')

    def test_sweep_needs_a_single_boundary_at_the_table_value(self):
        rows = [dict(value=v * 1e-12, captured=v >= 20) for v in range(-40, 61, 20)]
        self.assertEqual(MODEL.check_sweep(dict(rows=rows), 10.0), dict(last_fail=0.0, first_pass=20.0))
        self.assertEqual(label(lambda: MODEL.check_sweep(dict(rows=rows), 30.0)), 'SWEEP_SHAPE')
        holes = copy.deepcopy(rows)
        holes[-1]['captured'] = False
        self.assertEqual(label(lambda: MODEL.check_sweep(dict(rows=holes), 10.0)), 'SWEEP_SHAPE')
        island = copy.deepcopy(rows)
        island[0]['captured'] = True
        self.assertEqual(label(lambda: MODEL.check_sweep(dict(rows=island), 10.0)), 'SWEEP_SHAPE')


class LibertyTest(unittest.TestCase):
    def test_checked_in_library_is_the_table(self):
        text = MODEL.LIBERTY.read_text()
        self.assertEqual(text, MODEL.liberty(TABLE))
        self.assertTrue(MODEL.round_trip(TABLE, text))
        flop = MODEL.read_flop(text)
        self.assertEqual(flop['delay']['cell_rise'][0][0], 0.10253)   # ns, from 102.53 ps
        self.assertEqual(flop['setup']['rise_constraint'][0][1], -0.025)

    def test_a_changed_value_or_shape_is_noticed(self):
        text = MODEL.LIBERTY.read_text()
        self.assertEqual(label(lambda: MODEL.round_trip(TABLE, text.replace('0.10253', '0.10353', 1))), 'LIBERTY_TABLE')
        shorter = copy.deepcopy(TABLE)
        shorter['cell_rise'] = shorter['cell_rise'][:2]
        self.assertEqual(label(lambda: MODEL.round_trip(shorter, text)), 'LIBERTY_TABLE')
        with self.assertRaises(ValueError):
            MODEL.read_flop(text.replace('cell(DFF)', 'cell(LATCH)'))

    def test_existing_teaching_libraries_are_constant_tables(self):
        for name, path in RUN.EXISTING.items():
            report = MODEL.compare_existing(TABLE, path.read_text())
            self.assertEqual(set(report), {'clk_to_q', 'setup', 'hold'}, name)
            self.assertTrue(all(v['existing_is_constant'] for v in report.values()), name)
        slow = MODEL.compare_existing(TABLE, RUN.EXISTING['local-sta/slow'].read_text())
        self.assertEqual(slow['clk_to_q']['existing_ps'], [200.0, 200.0])
        self.assertEqual(slow['hold']['measured_ps'], [-8.59, 20.31])


class PlanTest(unittest.TestCase):
    def test_job_identities_are_unique_and_cover_the_table(self):
        jobs = (RUN.device_jobs() + RUN.delay_jobs(TABLE) + RUN.check_jobs(TABLE) + [RUN.loose_job(TABLE)] +
                RUN.point_jobs(TABLE) + RUN.delay_jobs(TABLE, 'tight', settings=RUN.TIGHT, corners=True) +
                RUN.check_jobs(TABLE, 'tight', settings=RUN.TIGHT, first_only=True) + RUN.random_points(TABLE, 17) +
                RUN.sweep_jobs(TABLE))
        ids = [job['id'] for job in jobs]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual((len(RUN.delay_jobs(TABLE)), len(RUN.check_jobs(TABLE)), len(RUN.point_jobs(TABLE))), (18, 16, 12))
        self.assertTrue(all(job['kind'] in MEASURE.KINDS for job in jobs))

    def test_random_points_follow_the_seed_and_stay_inside_the_table(self):
        self.assertEqual(RUN.random_points(TABLE, 17), RUN.random_points(TABLE, 17))
        self.assertNotEqual(RUN.random_points(TABLE, 17), RUN.random_points(TABLE, 18))
        for point in RUN.random_points(TABLE, 5, 40):
            self.assertTrue(10 <= point['slew'] <= 100 and 10 <= point['load_ff'] <= 100)
        self.assertEqual({p['edge'] for p in RUN.random_points(TABLE, 17)}, {'rise', 'fall'})

    def test_points_sit_on_both_sides_of_the_table_values(self):
        jobs = {job['id']: job for job in RUN.point_jobs(TABLE)}
        setup = TABLE['setup_rise'][0][0] * 1e-12
        self.assertAlmostEqual(jobs['point/setup-rise/inside']['offset'], setup + 6e-12, delta=1e-18)
        self.assertAlmostEqual(jobs['point/setup-rise/outside']['offset'], setup - 6e-12, delta=1e-18)
        self.assertAlmostEqual(jobs['point/hold-fall/violation']['back'], TABLE['hold_fall'][0][0] * 1e-12 - 60e-12, delta=1e-18)
        self.assertGreater(6.0, MODEL.CONSTRAINT_ABS)   # the offsets are outside the comparison tolerance

    def test_every_goal_and_every_negative_label_is_planned(self):
        goals = RUN.E.C.catalog(HERE / 'requirements.json')[1]
        self.assertEqual(len(goals), 27)
        self.assertEqual(set(RUN.REJECT_GOAL.values()), {g for g in goals if g.startswith('reject/')})
        self.assertEqual(set(RUN.DETECT.values()), set(RUN.REJECT_GOAL))
        source = (HERE / 'run.py').read_text()
        self.assertEqual({g for g in goals if f"'{g}'" not in source}, set())

    def test_incomplete_result_files_are_refused(self):
        jobs = RUN.delay_jobs(TABLE)[:2]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'results.json'
            path.write_text(json.dumps(dict(results=[dict(id=jobs[0]['id'], error=None)])))
            self.assertEqual(label(lambda: RUN.read_results(path, jobs)), 'MEAS_MISSING')
            path.write_text(json.dumps(dict(results=[dict(id=j['id']) for j in jobs + jobs[:1]])))
            self.assertEqual(label(lambda: RUN.read_results(path, jobs)), 'MEAS_INVALID')


class RealRun(unittest.TestCase):
    """One smoke run with the pinned ngspice, shared by the tests below."""

    @classmethod
    def setUpClass(cls):
        cls.config = shutil.which('lsi-ngspice-config')
        if cls.config is None:
            raise AssertionError('prepare ngspice and add install/bin to PATH for all selftests')
        cls.tmp = tempfile.TemporaryDirectory()
        cls.out = Path(cls.tmp.name) / 'out'
        cls.run_ = subprocess.run([sys.executable, str(HERE / 'run.py'), '--ngspice-config',
                                   os.path.relpath(cls.config, ROOT), '--out', str(cls.out)],
                                  cwd=ROOT, capture_output=True, text=True, timeout=240)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_smoke_passes_with_the_planned_checks_and_evidence(self):
        self.assertEqual(self.run_.returncode, 0, self.run_.stdout[-3000:] + self.run_.stderr[-2000:])
        summary = json.loads((self.out / 'summary.json').read_text())
        self.assertTrue(summary['success'] and summary['complete'])
        self.assertEqual(summary['planned'], 31)
        cases = list(ET.parse(self.out / 'junit.xml').getroot().iter('testcase'))
        self.assertEqual(len(cases), 31)
        self.assertEqual(len(ET.parse(self.out / 'junit.xml').getroot().findall('.//failure')), 0)
        for name in ('manifest.json', 'ngspice-source.json', 'main/jobs.json', 'main/results.json',
                     'main/setup-rise-outside.csv', 'main/setup-fall-violation.csv', 'weak-output/results.json'):
            self.assertTrue((self.out / name).is_file(), name)
        manifest = json.loads((self.out / 'manifest.json').read_text())
        for source in ('cells.py', 'measure.py', 'model.py', 'characterized.json', 'ff_measured.lib'):
            self.assertIn('examples/local-liberty-vs-spice/' + source, manifest['source_sha256'])
        self.assertIn('examples/local-sta/design/slow.lib', manifest['source_sha256'])

    def test_every_negative_case_was_rejected_by_its_own_label(self):
        details = {r['id']: r['detail'] for r in json.loads((self.out / 'summary.json').read_text())['results']}
        for name, expected in RUN.DETECT.items():
            self.assertEqual((details[name]['expected'], details[name]['actual']), (expected, expected), name)
        self.assertEqual(details['coverage']['missing'], [])
        self.assertEqual(details['coverage']['unplanned'], [])

    def test_real_results_are_rejected_when_altered(self):
        jobs = RUN.delay_jobs(TABLE) + RUN.check_jobs(TABLE)
        results = RUN.read_results(self.out / 'main/results.json', jobs)
        delays, checks, worst = RUN.judge_grid(results, TABLE)
        self.assertLess(worst['delay'], 0.5)
        self.assertLess(max(worst['setup'], worst['hold']), 1.0)
        self.assertEqual(delays['cell_rise'][0], sorted(delays['cell_rise'][0]))
        for change, expected in ((lambda r: r.update(delay=r['delay'] * 1.08), 'TABLE_DELAY'),
                                 (lambda r: r.update(delay=float('nan')), 'MEAS_INVALID'),
                                 (lambda r: r.update(error='ngspice analysis failed: singular matrix'), 'SPICE_ERROR'),
                                 (lambda r: r.pop('transition'), 'MEAS_MISSING')):
            altered = copy.deepcopy(results)
            change(altered[jobs[4]['id']])
            self.assertEqual(label(lambda: RUN.judge_grid(altered, TABLE)), expected)
        altered = copy.deepcopy(results)
        search = altered[jobs[-1]['id']]
        search['value'] += 5e-12
        self.assertEqual(label(lambda: RUN.judge_grid(altered, TABLE)), 'TABLE_HOLD')
        self.assertEqual(label(lambda: MODEL.check_search(search)), 'SEARCH_EVIDENCE')

    def test_setup_violation_waveform_shows_q_keeping_the_old_value(self):
        def final(name):
            rows = (self.out / 'main' / name).read_text().splitlines()
            self.assertEqual(rows[0], 'time_s,clk_v,d_v,q_v')
            return float(rows[-1].split(',')[3])
        self.assertGreater(final('setup-rise-inside.csv'), 1.7)
        self.assertGreater(final('setup-rise-outside.csv'), 1.7)      # late, but it still switches
        self.assertLess(final('setup-rise-violation.csv'), 0.1)       # the old value stays
        self.assertGreater(final('setup-fall-violation.csv'), 1.7)

    def test_a_missing_tool_and_an_existing_output_are_failures(self):
        with tempfile.TemporaryDirectory() as tmp:
            broken = subprocess.run([sys.executable, str(HERE / 'run.py'), '--ngspice-config', 'no-such-ngspice-config',
                                     '--out', str(Path(tmp) / 'out')], cwd=ROOT, capture_output=True, text=True, timeout=60)
            self.assertEqual(broken.returncode, 1)
            self.assertIn('RUNNER_ERROR', broken.stderr)
        again = subprocess.run([sys.executable, str(HERE / 'run.py'), '--ngspice-config', self.config, '--out', str(self.out)],
                               cwd=ROOT, capture_output=True, text=True, timeout=60)
        self.assertNotEqual(again.returncode, 0)


if __name__ == '__main__':
    unittest.main()

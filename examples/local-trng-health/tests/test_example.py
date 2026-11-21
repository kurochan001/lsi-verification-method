from itertools import groupby, product
import math
from pathlib import Path
import random
import shutil
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
import xml.etree.ElementTree as ET
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'local-common'))
from local_test_support import load_example, read_json, run_example

P = load_example('local-trng-health')
GOALS = 27
FAST, STD = P.CONFIGS['fast'], P.CONFIGS['std']


def clocked(trial, parameters):
    """A second reference written as the clocked machine the README describes, cycle by cycle."""
    w, cr, ca, s = (parameters[k] for k in ('W', 'RCT_CUTOFF', 'APT_CUTOFF', 'STARTUP'))
    last = None
    run = pos = cnt = ref = seen = 0
    rct = apt = 0
    ready = False
    outputs = 0
    index = 0
    for valid, bit in trial:
        if not valid:
            continue
        index += 1
        run = run + 1 if bit == last else 1
        last = bit
        if pos == 0:
            ref, cnt = bit, 1
        elif bit == ref:
            cnt += 1
        pos = (pos + 1) % w
        if run >= cr and not rct:
            rct = index
        if cnt >= ca and not apt:
            apt = index
        failed = bool(rct or apt)
        if ready and not failed:
            outputs += 1
        seen += 1
        if seen == s and not failed:
            ready = True
    # ready names the sample after which it rises, whether or not the trial gets that far.
    startup_failed = bool((rct and rct <= s) or (apt and apt <= s))
    return dict(samples=index, ready=0 if startup_failed else s, rct=rct, apt=apt, outputs=outputs)


def simulate(rows, parameters, mutation=0):
    """Compile the real RTL and bench with the given rows and mutation."""
    for tool in ('iverilog', 'vvp'):
        if not shutil.which(tool):
            raise AssertionError(tool + ' is required')
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp)
        vectors = out / 'vectors.txt'
        vectors.write_text(''.join(' '.join(format(v, 'x') for v in r) + '\n' for r in rows))
        command = ['iverilog', '-g2012', '-s', P.TOP, '-o', str(out / 'sim.vvp'), f'-P{P.TOP}.MUTATION={mutation}']
        command += [f'-P{P.TOP}.{k}={v}' for k, v in parameters.items()] + [str(p) for p in P.SOURCES]
        subprocess.run(command, capture_output=True, text=True, timeout=60, check=True)
        return subprocess.run(['vvp', str(out / 'sim.vvp'), f'+VECTORS={vectors}', f'+WAVE={out / "wave.vcd"}'],
                              capture_output=True, text=True, timeout=60)


def trial_of(row):
    n, vmask, dmask = row[1], row[2], row[3]
    return [((vmask >> i) & 1, (dmask >> i) & 1) for i in range(n)]


class ProbabilityTests(unittest.TestCase):
    def test_cutoffs_are_the_smallest_counts_within_the_false_alarm_probability(self):
        for name, d in P.DESIGN.items():
            c = P.CONFIGS[name]
            self.assertLessEqual(2.0 ** -(c['RCT_CUTOFF'] - 1), 2.0 ** -d['rct_alpha'])
            self.assertGreater(2.0 ** -(c['RCT_CUTOFF'] - 2), 2.0 ** -d['rct_alpha'])
            self.assertLessEqual(P.apt_tail(c['W'], c['APT_CUTOFF']), 2.0 ** -d['apt_alpha'])
            self.assertGreater(P.apt_tail(c['W'], c['APT_CUTOFF'] - 1), 2.0 ** -d['apt_alpha'])
        self.assertEqual((FAST['RCT_CUTOFF'], FAST['APT_CUTOFF'], STD['RCT_CUTOFF'], STD['APT_CUTOFF']), (9, 40, 21, 590))

    def test_run_probability_matches_enumeration(self):
        for length, cutoff in product(range(2, 13), range(2, 7)):
            hits = 0
            for bits in product((0, 1), repeat=length):
                runs = [len(list(g)) for _, g in groupby(bits)]
                hits += max(runs) >= cutoff
            self.assertAlmostEqual(P.p_run(length, cutoff), hits / 2 ** length, places=12)

    def test_window_tail_matches_enumeration(self):
        for window in (6, 9, 12):
            for cutoff in range(2, window + 1):
                hits = sum(sum(b == bits[0] for b in bits) >= cutoff for bits in product((0, 1), repeat=window))
                self.assertAlmostEqual(P.apt_tail(window, cutoff), hits / 2 ** window, places=12)

    def test_acceptance_ranges_leave_at_most_the_tail_outside(self):
        for trials, q in ((200, 0.39), (600, 0.145), (25, 0.00097), (75, 1.4e-6)):
            low, high = P.acceptance(trials, q)
            pmf = [math.comb(trials, k) * q ** k * (1 - q) ** (trials - k) for k in range(trials + 1)]
            self.assertLessEqual(sum(pmf[:low]), P.TAIL)
            self.assertLessEqual(sum(pmf[high + 1:]), P.TAIL)
            self.assertGreater(sum(pmf[:low + 1]), P.TAIL)          # the range cannot be narrower
            self.assertGreater(sum(pmf[high:]), P.TAIL)

    def test_the_ranges_come_from_the_design_cutoffs(self):
        low = dict(FAST, RCT_CUTOFF=FAST['RCT_CUTOFF'] - 1)
        self.assertEqual(P.statistic_vectors('fast', 5, 50)[-1], P.statistic_vectors('fast', 5, 50, low)[-1])
        self.assertNotEqual(P.statistic_vectors('fast', 5, 50)[:-1], P.statistic_vectors('fast', 5, 50, low)[:-1])


class ModelTests(unittest.TestCase):
    def test_model_matches_the_clocked_reference(self):
        rng = random.Random(3)
        for parameters in (FAST, dict(W=8, RCT_CUTOFF=4, APT_CUTOFF=7, STARTUP=8), STD):
            for _ in range(300 if parameters['W'] < 100 else 20):
                bias = rng.choice((0.5, 0.5, 0.7, 0.9, 1.0))
                value = rng.randrange(2)
                length = rng.randrange(1, 4 * parameters['W'])
                trial = [(int(rng.random() < 0.9), value if rng.random() < bias else 1 - value) for _ in range(length)]
                self.assertEqual(P.evaluate(trial, parameters), clocked(trial, parameters))

    def test_every_boundary_trial_agrees_with_the_clocked_reference(self):
        for parameters in (FAST, STD):
            for r in P.boundary_vectors(parameters):
                e = clocked(trial_of(r), parameters)
                self.assertEqual(r[4:8], [e['ready'], e['rct'], e['apt'], e['outputs']])

    def test_idle_cycles_are_not_samples(self):
        trial = [(1, 1)] * 5 + [(0, 0)] * 3 + [(1, 1)] * 4
        e = P.evaluate(trial, FAST)
        self.assertEqual((e['samples'], e['rct']), (9, 9))
        self.assertEqual(P.evaluate([(1, 1)] * 5 + [(0, 1)] * 9 + [(1, 0)], FAST)['rct'], 0)


class PlanTests(unittest.TestCase):
    def cases(self, name, profile='smoke', seed=17, iterations=50):
        return P.make_cases(SimpleNamespace(profile=profile, seed=seed, iterations=iterations, demo_bug=0), P.CONFIGS[name])

    def test_plan_names_labels_and_seed(self):
        for name, last in (('fast', 'detect-mutation1-common-mode'), ('std', 'survive-mutation1-common-mode')):
            cases = self.cases(name)
            self.assertEqual([c['id'] for c in cases], ['boundaries', 'statistic-seed17', 'degrade-seed17',
                                                        *[f'detect-mutation{m}' for m in range(1, 9)], last])
            self.assertEqual([c['expected_failure'] for c in cases[3:11]], [P.LABELS[m] for m in range(1, 9)])
            self.assertEqual(len(self.cases(name, 'nightly')), len(cases) + 4)
            self.assertEqual(cases, self.cases(name))
            self.assertNotEqual(cases[1]['vectors'], self.cases(name, seed=18)[1]['vectors'])
            self.assertNotEqual(cases[2]['vectors'], self.cases(name, seed=18)[2]['vectors'])
        self.assertEqual(self.cases('fast')[-1]['expected_failure'], 'TRNG_RATE')
        self.assertEqual(self.cases('std')[-1]['category'], 'diagnostic')

    def test_every_rule_has_its_own_trial(self):
        for parameters in (FAST, STD):
            s, cr = parameters['STARTUP'], parameters['RCT_CUTOFF']
            rows = P.boundary_vectors(parameters)
            fails = [(r[5], r[6]) for r in rows]
            self.assertIn((s + cr, 0), fails)                      # the RCT at its cutoff after start-up
            self.assertIn((cr, 0), [(r[5], 0) for r in rows if r[4] == 0])
            self.assertIn((s, 0), fails)                           # on the last start-up sample
            self.assertIn((s + 1, 0), fails)                       # on the first sample after start-up
            self.assertIn((0, s + parameters['W']), fails)         # the APT on the last sample of a window
            self.assertTrue(any(0 < r[6] <= s and r[4] == 0 for r in rows))
            self.assertTrue(any(r[5] and r[6] for r in rows))
            self.assertTrue(any(r[8] & P.POWER_ON for r in rows))
            self.assertTrue(any((~r[2]) & ((1 << r[1]) - 1) for r in rows))   # idle cycles inside a trial
            self.assertLessEqual(max(r[1] for r in rows), P.MAXC)

    def test_degraded_sources_are_found_and_stronger_bias_is_found_sooner(self):
        for name in P.CONFIGS:
            for seed in (17, 18, 19):
                rows = P.degrade_vectors(name, seed)
                self.assertTrue(all(r[5] or r[6] for r in rows), (name, seed))
                self.assertTrue(all(r[4] for r in rows), (name, seed))          # the healthy part passes start-up
        # Median samples from the change to the alarm, over the model.
        w = FAST['W']
        medians = []
        for bias in (1.0, 0.9, 0.75):
            delays = []
            for s in range(60):
                rng = random.Random(f'median-{bias}-{s}')
                healthy = P.fair_bits(rng, FAST['STARTUP'] + w)
                bad = [1 if rng.random() < bias else 0 for _ in range(16 * w)]
                e = P.evaluate([(1, b) for b in healthy + bad], FAST)
                first = min(x for x in (e['rct'], e['apt']) if x)
                delays.append(first - len(healthy))
            medians.append(sorted(delays)[len(delays) // 2])
        self.assertEqual(medians, sorted(medians))
        self.assertLessEqual(medians[0], FAST['RCT_CUTOFF'])


class RtlTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(shutil.which('iverilog') and shutil.which('vvp'), 'Icarus Verilog is required')

    def test_all_configurations_mutants_and_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / 'out'
            result = run_example('local-trng-health', out)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            summary = read_json(out / 'summary.json')
            self.assertTrue(summary['success'] and summary['complete'], summary)
            self.assertEqual((summary['planned'], summary['results'], summary['functional_pass'],
                              summary['mutations_detected'], summary['diagnostics_pass']), (24, 24, 6, 17, 1))
            coverage = read_json(out / 'coverage.json')
            self.assertEqual(set(coverage), set(P.CONFIGS))
            self.assertTrue(all(c['success'] and c['hit'] == GOALS and not c['missing'] for c in coverage.values()))
            suite = ET.parse(out / 'junit.xml').getroot()
            self.assertEqual((suite.get('tests'), suite.get('failures'), suite.get('errors')), ('26', '0', '0'))
            for result in out.glob('*/result.json'):
                record = read_json(result)
                if record['category'] != 'functional':
                    self.assertEqual(record['credited_coverage'], [])
                self.assertIn('$enddefinitions', (result.parent / 'wave.vcd').read_text())
            self.assertIn('CHECK_FAIL TRNG_RATE', (out / 'fast-detect-mutation1-common-mode/simulation.log').read_text())
            self.assertEqual(read_json(out / 'std-survive-mutation1-common-mode/result.json')['status'], 'pass')

    def test_demo_faults_make_the_normal_regression_fail(self):
        with tempfile.TemporaryDirectory() as tmp:
            for fault in range(1, P.MUTANTS + 1):
                with self.subTest(fault=fault):
                    out = Path(tmp) / str(fault)
                    result = run_example('local-trng-health', out, '--configuration', 'fast', '--iterations', '40',
                                         '--demo-bug', str(fault))
                    self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                    record = read_json(out / 'fast-boundaries/result.json')
                    self.assertEqual((record['status'], record['message']), ('fail', 'checker failure: ' + P.LABELS[fault]))

    def test_the_reset_tail_scenarios_alone_find_a_restart_that_keeps_state(self):
        rows = P.boundary_vectors(FAST)
        for tag, mutation, label in ((P.AFTER_RCT_TAIL, 3, 'TRNG_RCT'), (P.AFTER_APT_TAIL, 4, 'TRNG_APT')):
            second = next(i for i, r in enumerate(rows) if r[8] & tag)
            pair = rows[second - 1:second + 1]      # the trial that leaves the state, then the tagged one
            self.assertIn('RESULT PASS checks=2', simulate(pair, FAST).stdout)
            result = simulate(pair, FAST, mutation)
            self.assertIn('CHECK_FAIL ' + label, result.stdout)
            self.assertIn('row=1 ', result.stdout + result.stderr)

    def test_the_checker_reports_each_label(self):
        rows = P.boundary_vectors(FAST)[:2]
        good = simulate(rows, FAST)
        self.assertIn('RESULT PASS checks=2', good.stdout, good.stdout + good.stderr)
        for column, label in ((4, 'TRNG_READY'), (5, 'TRNG_RCT'), (7, 'TRNG_OUTPUT')):
            changed = [list(r) for r in rows]
            changed[1][column] += 1
            result = simulate(changed, FAST)
            self.assertIn('CHECK_FAIL ' + label, result.stdout)
            self.assertNotIn('RESULT PASS', result.stdout)
        apt = [list(r) for r in rows]
        apt[1][6] = 1                                   # an APT failure that does not happen
        self.assertIn('CHECK_FAIL TRNG_APT', simulate(apt, FAST).stdout)
        trials = P.statistic_vectors('fast', 1, 3)[:-1]
        r, a = sum(t[5] != 0 for t in trials), sum(t[6] != 0 for t in trials)
        for judge, ok in (([2, r, r, a, a, 3, 0, 0, 0], True), ([2, r, r, a, a, 4, 0, 0, 0], False),
                          ([2, r + 1, 3, 0, 3, 3, 0, 0, 0], False), ([2, 0, 3, a + 1, 3, 3, 0, 0, 0], False),
                          ([2, 0, max(r - 1, 0), 0, 3, 3, 0, 0, 0], r == 0)):
            result = simulate(trials + [judge], FAST)
            self.assertEqual('CHECK_FAIL TRNG_RATE' in result.stdout, not ok, judge)


if __name__ == '__main__':
    unittest.main()

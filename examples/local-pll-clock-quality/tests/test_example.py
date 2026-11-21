import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'local-common'))
from system_test_support import SystemContract
from local_test_support import load_example, simulate_vectors

P = load_example('local-pll-clock-quality')
M = P.MODEL
P20, P34 = P.CONFIGS['p20ns'], P.CONFIGS['p34ns']
LOW, HIGH, LOCK, WINDOW = range(4)
WARMUP = 36


def measure(p, rows):
    """Recompute the five quantities from the pulse widths alone, as a second derivation."""
    body = [row for row in rows if row[WINDOW]]
    periods = [low + previous[HIGH] for previous, (low, *_ ) in zip(body, body[1:])]
    rises = [0]
    for period in periods:
        rises.append(rises[-1] + period)
    ties = [rise - index * p['PERIOD_PS'] for index, rise in enumerate(rises)]
    steps = [b - a for a, b in zip(periods, periods[1:])]
    return dict(high=min(row[HIGH] for row in body),
                low=min(row[LOW] for row in body[1:]),
                period=max(abs(period - p['PERIOD_PS']) for period in periods),
                tie=max(abs(tie) for tie in ties),
                step=max(abs(step) for step in steps))


def violations(p, rows):
    m = measure(p, rows)
    return {name for name, bad in (('high', m['high'] < p['MIN_PULSE_PS']), ('low', m['low'] < p['MIN_PULSE_PS']),
                                   ('period', m['period'] > p['PERIOD_TOL_PS']), ('tie', m['tie'] > p['TIE_LIMIT_PS']),
                                   ('step', m['step'] > p['STEP_LIMIT_PS'])) if bad}


def simulate(rows, parameters):
    """The bench writes clock_edges.csv into its working directory, so run it in a temporary one."""
    here = os.getcwd()
    with tempfile.TemporaryDirectory() as tmp:
        os.chdir(tmp)
        try:
            return simulate_vectors(P, rows, parameters)
        finally:
            os.chdir(here)


def label(result):
    lines = [line for line in result.stdout.splitlines() if line.startswith('CHECK_FAIL')]
    return lines[0].split()[1] if len(lines) == 1 and result.returncode else None


class ExampleTests(SystemContract, unittest.TestCase):
    EXAMPLE = 'local-pll-clock-quality'
    GOALS = 7

    def test_normal_stimulus_sits_exactly_on_every_inclusive_limit(self):
        for p in (P20, P34):
            for seed, intervals in ((17, 0), (17, 48), (42, 256)):
                rows = M.vectors(p, seed, intervals)
                self.assertEqual(violations(p, rows), set())
                m = measure(p, rows)
                self.assertEqual((m['high'], m['low'], m['period'], m['tie'], m['step']),
                                 (p['MIN_PULSE_PS'], p['MIN_PULSE_PS'], p['PERIOD_TOL_PS'],
                                  p['TIE_LIMIT_PS'], p['STEP_LIMIT_PS']))

    def test_each_fault_breaks_its_own_limit(self):
        # The period fault (+801 ps, then back to +400 ps) also makes the next difference 1202 ps;
        # the testbench checks the period first and reports PLL_PERIOD. The other four are isolated.
        expected = {1: {'high'}, 2: {'low'}, 3: {'period', 'step'}, 4: {'tie'}, 5: {'step'}}
        for p in (P20, P34):
            for fault, names in expected.items():
                self.assertEqual(violations(p, M.vectors(p, 17, 0, fault)), names, fault)
        self.assertEqual(len(P.FAULTS), len(expected))
        with self.assertRaises(ValueError):
            M.vectors(P20, 17, 0, 6)

    def test_warmup_is_outside_the_window_and_holds_a_short_unlocked_pulse(self):
        for p in (P20, P34):
            rows = M.vectors(p, 17, 0)
            self.assertEqual([row[WINDOW] for row in rows], [0] * WARMUP + [1] * (len(rows) - WARMUP))
            self.assertTrue(all(row[HIGH] < p['MIN_PULSE_PS'] and not row[LOCK] for row in rows[:4]))
            self.assertTrue(all(row[LOCK] for row in rows[4:]))
            self.assertEqual(M.vectors(p, 17, 5)[:WARMUP + 2], rows[:WARMUP + 2])
            self.assertNotEqual(M.vectors(p, 17, 5), M.vectors(p, 18, 5))

    def test_plan_names_labels_and_profiles(self):
        def plan(profile, bug=0):
            args = SimpleNamespace(profile=profile, seed=17, iterations=4, demo_bug=bug)
            return P.make_cases(args, P20)
        smoke, nightly = plan('smoke'), plan('nightly')
        self.assertEqual([c['id'] for c in smoke],
                         ['boundaries', 'random-seed17', 'detect-short-high', 'detect-short-low', 'detect-period',
                          'detect-phase-drift', 'detect-cycle-step'])
        self.assertEqual([c['id'] for c in nightly][1:4], ['random-seed17', 'random-seed18', 'random-seed19'])
        self.assertEqual([c['expected_failure'] for c in smoke[2:]],
                         ['PLL_SHORT_HIGH', 'PLL_SHORT_LOW', 'PLL_PERIOD', 'PLL_TIE', 'PLL_CYCLE_STEP'])
        # The faults are in the stimulus; the RTL mutation parameter stays 0 in every case.
        self.assertEqual({c['mutation'] for c in smoke + plan('smoke', 4)}, {0})
        self.assertEqual(plan('smoke', 4)[0]['vectors'], M.vectors(P20, 17, 0, 4))

    def test_checker_reports_each_stimulus_fault_on_the_real_rtl(self):
        self.assertEqual(simulate(M.vectors(P34, 17, 12), P34).returncode, 0)
        for fault, (_, failure) in enumerate(P.FAULTS, 1):
            self.assertEqual(label(simulate(M.vectors(P34, 17, 0, fault), P34)), failure)
        rows = M.vectors(P34, 17, 0)
        # Lock dropping inside the measurement window is not an accepted trace.
        self.assertNotEqual(simulate(rows[:-1] + [[rows[-1][LOW], rows[-1][HIGH], 0, 1]], P34).returncode, 0)


if __name__ == '__main__':
    unittest.main()

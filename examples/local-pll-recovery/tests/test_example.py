from pathlib import Path
from types import SimpleNamespace
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'local-common'))
from system_test_support import SystemContract
from local_test_support import load_example, simulate_vectors

P = load_example('local-pll-recovery')
M = P.MODEL
SLOW, FAST = P.CONFIGS['slow-pll'], P.CONFIGS['fast-pll']
RESET_N, LOCKED, RUNNING, DURATION, PERMIT, MISSING, FORBID, GOALS = range(8)
FIXED = 14


def label(result):
    lines = [line for line in result.stdout.splitlines() if line.startswith('CHECK_FAIL')]
    return lines[0].split()[1] if len(lines) == 1 and result.returncode else None


class ExampleTests(SystemContract, unittest.TestCase):
    EXAMPLE = 'local-pll-recovery'
    GOALS = 9

    def test_fixed_scenario_claims_every_goal_once_and_is_self_consistent(self):
        for p in (SLOW, FAST):
            rows = M.vectors(p, 17, 0)
            self.assertEqual(len(rows), FIXED)
            claimed = [bit for row in rows for bit in range(9) if row[GOALS] >> bit & 1]
            self.assertEqual(sorted(claimed), list(range(9)))
            for row in rows:
                # The clock may be permitted only with reset released, lock high and the clock running.
                if row[PERMIT]:
                    self.assertEqual((row[RESET_N], row[LOCKED], row[RUNNING], row[FORBID]), (1, 1, 1, 0), row)
                # A missing clock is reported only when the clock is stopped outside reset.
                self.assertEqual(row[MISSING], int(row[RESET_N] and not row[RUNNING]), row)
            # The chatter pulse stays below the qualification time; settling phases exceed it.
            self.assertEqual(rows[2][DURATION], p['LOCK_CYCLES'] - 2)
            self.assertGreater(rows[4][DURATION], p['TIMEOUT'] + p['LOCK_CYCLES'])
            self.assertGreater(rows[7][DURATION], p['TIMEOUT'])

    def test_random_phases_are_seeded_and_follow_the_fixed_part(self):
        base, more, other = M.vectors(SLOW, 17, 0), M.vectors(SLOW, 17, 5), M.vectors(SLOW, 18, 5)
        self.assertEqual(more[:FIXED], base)
        self.assertEqual(len(more), FIXED + 3 * 5)
        self.assertEqual(more, M.vectors(SLOW, 17, 5))
        self.assertNotEqual(more, other)
        for index in range(FIXED, len(more), 3):
            run, disturbance, recover = more[index:index + 3]
            self.assertEqual((run[LOCKED], run[RUNNING], run[PERMIT]), (1, 1, 1))
            self.assertIn((disturbance[LOCKED], disturbance[RUNNING], disturbance[MISSING]), ((0, 1, 0), (1, 0, 1)))
            self.assertEqual(disturbance[PERMIT], 0)
            self.assertEqual((recover[PERMIT], recover[MISSING]), (1, 0))

    def test_plan_names_labels_and_profiles(self):
        def plan(profile, bug=0):
            args = SimpleNamespace(profile=profile, seed=17, iterations=2, demo_bug=bug)
            return P.make_cases(args, SLOW)
        smoke, nightly = plan('smoke'), plan('nightly')
        self.assertEqual([c['id'] for c in smoke],
                         ['boundaries', 'random-seed17', 'mutation-1', 'mutation-2', 'mutation-3', 'mutation-4'])
        self.assertEqual([c['id'] for c in nightly][1:4], ['random-seed17', 'random-seed18', 'random-seed19'])
        self.assertEqual([(c['mutation'], c['expected_failure']) for c in smoke[2:]],
                         [(1, 'PLL_LOCK_QUALIFY'), (2, 'PLL_LOCK_LOSS'), (3, 'PLL_STOPPED_RESET'), (4, 'PLL_RESET_SYNC')])
        self.assertEqual([c['counts'] for c in smoke[:2]], [{'steps': FIXED}, {'steps': FIXED + 6}])
        self.assertEqual([c['mutation'] for c in plan('smoke', 2)[:2]], [2, 2])

    def test_checker_rejects_wrong_expectations_on_the_real_rtl(self):
        rows = M.vectors(FAST, 17, 0)
        self.assertEqual(simulate_vectors(P, rows, FAST).returncode, 0)
        wrong = [list(row) for row in rows]
        wrong[7][MISSING] = 0                      # claim the stopped clock is not reported
        self.assertEqual(label(simulate_vectors(P, wrong, FAST)), 'PLL_WATCHDOG')
        wrong = [list(row) for row in rows]
        wrong[1][LOCKED] = 1                       # lock is actually high where permission is forbidden
        self.assertEqual(label(simulate_vectors(P, wrong, FAST)), 'PLL_LOCK_QUALIFY')


if __name__ == '__main__':
    unittest.main()

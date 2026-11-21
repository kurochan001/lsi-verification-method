from pathlib import Path
from types import SimpleNamespace
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'local-common'))
from system_test_support import SystemContract
from local_test_support import load_example, simulate_vectors

P = load_example('local-pwm-adc')
M = P.MODEL
P16, P10 = P.CONFIGS['period16'], P.CONFIGS['period10']
(RESET_N, ENABLE, CFG_WRITE, CFG_DUTY, CFG_SAMPLE, VOLTAGE, READY, TRIGGER, PWM, DUTY, SAMPLE, CFG_ERROR,
 ADC_READY, ADC_BUSY, ADC_OVERRUN, ADC_VALID, ADC_CODE, GOALS) = range(18)


def rows_of(p, seed=17, iterations=0):
    return M.vectors(p, P.ADC_ORACLE, seed, iterations)


def label(result):
    lines = [line for line in result.stdout.splitlines() if line.startswith('CHECK_FAIL')]
    return lines[0].split()[1] if len(lines) == 1 and result.returncode else None


class ExampleTests(SystemContract, unittest.TestCase):
    EXAMPLE = 'local-pwm-adc'
    GOALS = 12

    def test_fixed_scenario_claims_every_goal(self):
        for p in (P16, P10):
            rows = rows_of(p)
            self.assertEqual({bit for row in rows for bit in range(12) if row[GOALS] >> bit & 1}, set(range(12)))

    def test_one_trigger_per_carrier_period_on_the_rising_slope(self):
        # Recount from the rows alone: between two triggers of an undisturbed run lie exactly 2*HALF steps.
        for p in (P16, P10):
            period = 2 * p['HALF_PERIOD']
            rows = rows_of(p, iterations=600)
            last = None
            seen = 0
            for index, row in enumerate(rows):
                if not (row[RESET_N] and row[ENABLE]) or row[CFG_WRITE]:
                    last = None                       # a reset, a stop or a write restarts the measurement
                    continue
                if row[TRIGGER]:
                    if last is not None and rows[last][SAMPLE] == row[SAMPLE] == rows[index - 1][SAMPLE]:
                        self.assertEqual(index - last, period, (index, last))
                        seen += 1
                    last = index
            self.assertGreater(seen, 3)
            for row in rows:
                if not (row[RESET_N] and row[ENABLE]):
                    self.assertEqual((row[TRIGGER], row[PWM]), (0, 0), row)

    def test_duty_extremes_and_rejected_settings(self):
        for p in (P16, P10):
            half = p['HALF_PERIOD']
            for row in rows_of(p, iterations=600):
                if row[RESET_N] and row[ENABLE]:
                    if row[DUTY] == 0:
                        self.assertEqual(row[PWM], 0, row)
                    if row[DUTY] == half:
                        self.assertEqual(row[PWM], 1, row)
                self.assertTrue(0 <= row[DUTY] <= half and 0 < row[SAMPLE] < half, row)   # the active pair stays legal
                if row[RESET_N] and row[CFG_WRITE]:
                    legal = 0 <= row[CFG_DUTY] <= half and 0 < row[CFG_SAMPLE] < half
                    self.assertEqual(row[CFG_ERROR], int(not legal), row)
                else:
                    self.assertEqual(row[CFG_ERROR], 0, row)

    def test_adc_columns_come_from_the_shared_adc_oracle(self):
        # Replay the trigger column into a fresh ADC oracle and compare its five outputs.
        for p in (P16, P10):
            adc = P.ADC_ORACLE(8, p['ACQUIRE'], p['CONVERT'], 1000)
            for row in rows_of(p, iterations=200):
                voltage = row[VOLTAGE] - (1 << 32) if row[VOLTAGE] >> 31 else row[VOLTAGE]
                outputs, _ = adc.step(row[RESET_N], row[TRIGGER], voltage, row[READY])
                self.assertEqual(row[ADC_READY:ADC_CODE + 1], outputs)

    def test_plan_names_labels_and_profiles(self):
        def plan(profile, bug=0):
            args = SimpleNamespace(profile=profile, seed=17, iterations=4, demo_bug=bug)
            return P.make_cases(args, P16)
        smoke, nightly = plan('smoke'), plan('nightly')
        self.assertEqual([c['id'] for c in smoke], ['boundaries', 'random-seed17'] + [f'mutation-{n}' for n in range(1, 6)])
        self.assertEqual([c['id'] for c in nightly][1:4], ['random-seed17', 'random-seed18', 'random-seed19'])
        self.assertEqual([(c['mutation'], c['expected_failure']) for c in smoke[2:]],
                         [(1, 'PWM_TRIGGER'), (2, 'PWM_CONFIG'), (3, 'PWM_TRIGGER'), (4, 'PWM_CONFIG'), (5, 'PWM_TRIGGER')])
        self.assertEqual(P.MUTANTS, 5)
        self.assertEqual([c['mutation'] for c in plan('smoke', 4)[:2]], [4, 4])

    def test_checker_rejects_wrong_expectations_on_the_real_rtl(self):
        rows = rows_of(P16)
        self.assertEqual(simulate_vectors(P, rows, P16).returncode, 0)
        trigger = next(index for index, row in enumerate(rows) if row[TRIGGER])
        high = next(index for index, row in enumerate(rows) if row[PWM])
        for index, column, expected in ((trigger, TRIGGER, 'PWM_TRIGGER'), (high, PWM, 'PWM_OUTPUT'), (high, DUTY, 'PWM_CONFIG')):
            wrong = [list(row) for row in rows]
            wrong[index][column] ^= 1
            self.assertEqual(label(simulate_vectors(P, wrong, P16)), expected)


if __name__ == '__main__':
    unittest.main()

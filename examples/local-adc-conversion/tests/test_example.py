from pathlib import Path
from types import SimpleNamespace
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'local-common'))
from system_test_support import SystemContract
from local_test_support import load_example, simulate_vectors

P = load_example('local-adc-conversion')
M = P.MODEL
WIDE, SHORT = P.CONFIGS['acq2-conv4'], P.CONFIGS['acq1-conv1']
READY, BUSY, OVERRUN, VALID, CODE = range(5)


def oracle(p):
    return M.AdcOracle(p['BITS'], p['ACQUIRE'], p['CONVERT'], p['LSB_UV'])


def convert(p, voltage):
    """Start at tick 0, present the voltage only at the capture tick and return the code."""
    adc = oracle(p)
    adc.step(1, 1, 0, 1)
    for tick in range(1, p['ACQUIRE'] + p['CONVERT'] + 1):
        outputs, _ = adc.step(1, 0, voltage if tick == p['ACQUIRE'] else 0, 1)
    return outputs


def label(result):
    lines = [line for line in result.stdout.splitlines() if line.startswith('CHECK_FAIL')]
    return lines[0].split()[1] if len(lines) == 1 and result.returncode else None


class ExampleTests(SystemContract, unittest.TestCase):
    EXAMPLE = 'local-adc-conversion'
    GOALS = 8

    def test_code_is_the_clamped_floor_of_voltage_over_lsb(self):
        # A second derivation: integer floor division, then clamp to the code range.
        for p in (WIDE, SHORT):
            lsb, top = p['LSB_UV'], (1 << p['BITS']) - 1
            for voltage in (-1000, -1, 0, 1, lsb - 1, lsb, lsb + 1, 7 * lsb - 1, 7 * lsb,
                            top * lsb - 1, top * lsb, (top + 1) * lsb, (top + 5) * lsb):
                outputs = convert(p, voltage)
                self.assertEqual(outputs[VALID], 1, voltage)
                self.assertEqual(outputs[CODE], max(0, min(top, voltage // lsb)), voltage)

    def test_result_appears_exactly_at_the_absolute_deadline(self):
        for p in (WIDE, SHORT):
            adc = oracle(p)
            self.assertEqual(adc.step(1, 1, 5 * p['LSB_UV'], 1)[0][READY], 1)
            valid = []
            for _ in range(p['ACQUIRE'] + p['CONVERT'] + 2):
                outputs, _ = adc.step(1, 0, 5 * p['LSB_UV'], 0)
                valid.append(outputs[VALID])
            # Valid first at tick ACQUIRE+CONVERT and held while the receiver is not ready.
            self.assertEqual(valid, [0] * (p['ACQUIRE'] + p['CONVERT'] - 1) + [1, 1, 1])

    def test_overrun_hold_and_reset_in_the_model(self):
        adc = oracle(WIDE)
        adc.step(1, 1, 0, 1)
        outputs, goals = adc.step(1, 1, 0, 1)                  # a second start while busy
        self.assertEqual((outputs[READY], outputs[BUSY], outputs[OVERRUN]), (0, 1, 1))
        self.assertTrue(goals & (1 << 5))
        outputs, goals = adc.step(0, 1, 0, 1)                  # reset cancels the conversion
        self.assertEqual(outputs, [0, 0, 0, 0, 0])
        self.assertTrue(goals & (1 << 7))
        for _ in range(WIDE['ACQUIRE'] + WIDE['CONVERT'] + 2):
            outputs, _ = adc.step(1, 0, 99000, 1)
            self.assertEqual(outputs[VALID], 0)                # the cancelled result never appears
        self.assertEqual(outputs[READY], 1)

    def test_plan_names_labels_and_profiles(self):
        def plan(profile, bug=0):
            args = SimpleNamespace(profile=profile, seed=17, iterations=4, demo_bug=bug)
            return P.make_cases(args, WIDE)
        smoke, nightly = plan('smoke'), plan('nightly')
        self.assertEqual([c['id'] for c in smoke],
                         ['boundaries', 'random-seed17', 'mutation-1', 'mutation-2', 'mutation-3', 'mutation-4'])
        self.assertEqual([c['id'] for c in nightly][1:4], ['random-seed17', 'random-seed18', 'random-seed19'])
        self.assertEqual([(c['mutation'], c['expected_failure']) for c in smoke[2:]],
                         [(1, 'ADC_CODE'), (2, 'ADC_CODE'), (3, 'ADC_VALID'), (4, 'ADC_BUSY')])
        self.assertEqual({c['category'] for c in smoke[:2]}, {'functional'})
        self.assertEqual([c['mutation'] for c in plan('smoke', 3)[:2]], [3, 3])
        fixed = smoke[0]['vectors']
        drain = WIDE['ACQUIRE'] + WIDE['CONVERT'] + 2                      # idle steps that end every case
        self.assertEqual(smoke[1]['vectors'][:len(fixed) - drain], fixed[:-drain])   # random steps follow the fixed part
        self.assertEqual({bit for row in fixed for bit in range(8) if row[9] >> bit & 1}, set(range(8)))

    def test_checker_rejects_a_wrong_expectation_on_the_real_rtl(self):
        rows = M.vectors(WIDE, 17, 0)
        self.assertEqual(simulate_vectors(P, rows, WIDE).returncode, 0)
        first_valid = next(index for index, row in enumerate(rows) if row[7])
        for column, expected in ((8, 'ADC_CODE'), (7, 'ADC_VALID'), (4, 'ADC_READY')):
            wrong = [list(row) for row in rows]
            wrong[first_valid][column] ^= 1
            self.assertEqual(label(simulate_vectors(P, wrong, WIDE)), expected)


if __name__ == '__main__':
    unittest.main()

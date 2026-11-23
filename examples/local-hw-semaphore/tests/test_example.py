from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'local-common'))
from local_test_support import load_example, simulate_vectors
from system_test_support import SystemContract

P = load_example('local-hw-semaphore')


class SemaphoreTests(SystemContract, unittest.TestCase):
    EXAMPLE = 'local-hw-semaphore'
    GOALS = 13

    def test_second_irq_can_open_a_new_window_on_the_same_edge(self):
        for parameters in P.CONFIGS.values():
            limit, win = parameters['KMAX'], parameters['WIN']
            p = P.Plan(win, limit)
            p.step(rst=0)
            for _ in range(limit - 1):
                p.step(events=1)
            p.step(events=3)
            self.assertEqual(p.rows[-1][-3:], [3, 0, 1])
            self.assertEqual(p.accepted, 1)
            for _ in range(win - 1):
                p.step()
            p.step(events=3)
            self.assertEqual(p.rows[-1][-3:], [0, 3, 0])
            p.step(events=2)
            self.assertEqual(p.rows[-1][-3:], [2, 0, 1])
            result = simulate_vectors(P, p.rows, parameters)
            self.assertEqual(result.returncode, 0, result.stdout)

    def test_rearm_has_priority_and_preserves_other_fence(self):
        p = P.Plan(8, 2)
        p.step(rst=0)
        for _ in range(256):
            p.step(inc=3)
        p.step(inc=3, rearm=2)
        self.assertEqual(p.counts, [255, 0])
        self.assertEqual(p.rows[-1][10], 1)
        p.step(claim=1, release=1)
        self.assertEqual(p.rows[-1][7:9], [0, 0])
        result = simulate_vectors(P, p.rows, {'WIN': 8, 'KMAX': 2})
        self.assertEqual(result.returncode, 0, result.stdout)

    def test_wrong_grant_is_detected_at_the_output(self):
        rows = P.vectors(17, 0, P.CONFIGS['w8k2'], boundary=True)
        result = simulate_vectors(P, rows, P.CONFIGS['w8k2'],
                                  {'hw_semaphore.sv': [('grant <= claim && !owned[slot];',
                                                       'grant <= claim;')]})
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('CHECK_FAIL SEM_STATE', result.stdout)

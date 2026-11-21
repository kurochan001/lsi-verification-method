from pathlib import Path
import re
import sys
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'local-common'))
from system_test_support import SystemContract
from local_test_support import load_example, simulate_vectors

P = load_example('local-otp-fuse')
M = P.MODEL


def label(result):
    return re.findall(r'^CHECK_FAIL (\w+)$', result.stdout, re.M)


class ExampleTests(SystemContract, unittest.TestCase):
    EXAMPLE = 'local-otp-fuse'
    GOALS = 19


class ModelTests(unittest.TestCase):
    def test_majority_any_and_disagreement(self):
        m = M.Model(16, 8, 3)
        m.fault(6, 2, 1, False)
        self.assertTrue(m.write(6, 0x0f))
        self.assertEqual(m.copies(6), [0x0f, 0x0f, 0x0d])
        self.assertEqual(m.read(6), 0x0f)
        self.assertEqual(m.rows[-1][4:6], [0x0f, 1 << 1 | 1 << 2])

    def test_a_locked_word_refuses_and_bits_are_never_cleared(self):
        m = M.Model(16, 8, 3)
        self.assertTrue(m.write(5, 0xa5))
        self.assertFalse(m.write(5, 0xff))
        self.assertEqual(m.rows[-1][5:7], [1 | 1 << 2, 1])
        self.assertEqual(m.copies(5), [0xa5] * 3)
        m.cut(9, 0xf0, 2 * 3 + 2)                    # two copies hold 0xf0
        self.assertFalse(m.write(9, 0x0f))           # read-back 0xff: refused, not locked
        self.assertEqual(m.copies(9), [0xff, 0xff, 0x0f])
        self.assertFalse(m.locked(9))

    def test_the_rows_programmed_before_a_loss_of_power_follow_the_timing(self):
        p = 3
        programmed = {}
        for edges in range(1, 4 * p + 7):
            m = M.Model(16, 8, p)
            m.cut(4, 0x3c, edges)
            programmed[edges] = ([int(m.cells[4][r] != 0) for r in range(4)])
        self.assertEqual(programmed[p], [0, 0, 0, 0])
        self.assertEqual(programmed[p + 1], [1, 0, 0, 0])
        self.assertEqual(programmed[2 * p + 1], [1, 1, 0, 0])
        self.assertEqual(programmed[3 * p + 1], [1, 1, 1, 0])
        self.assertEqual(programmed[4 * p + 3], [1, 1, 1, 0])
        self.assertEqual(programmed[4 * p + 4], [1, 1, 1, 1])

    def test_lifecycle_counts_any_copy_and_a_gap_is_restrictive(self):
        m = M.Model(16, 8, 3)
        self.assertEqual(m.lifecycle(), 0)
        m.cut(0, 0x01, 3 + 2)                        # one copy of word 0
        self.assertEqual(m.lifecycle(), 1)
        m2 = M.Model(16, 8, 3)
        m2.reset()
        m2.write(1, 0x01)                            # word 1 without word 0
        self.assertEqual(m2.lifecycle(), 3)
        m2.key_write(0x1)
        self.assertEqual(m2.rows[-1][5], 0)          # still TEST until the next reset loads it
        m2.reset()
        m2.key_write(0x1)
        self.assertEqual(m2.rows[-1][5], 1)

    def test_fixed_scenario_reaches_every_goal(self):
        for c in P.CONFIGS.values():
            rows, counts = M.boundary(*P.sizes(c))
            seen = {g for r in rows for g, f in M.FLAG.items() if r[-1] & f}
            self.assertEqual(seen, set(M.GOALS))
            self.assertEqual(len(M.GOALS), ExampleTests.GOALS)
            self.assertEqual(counts['steps'], len(rows))

    def test_random_rows_reproduce(self):
        self.assertEqual(M.random_rows(16, 8, 3, 5, 120), M.random_rows(16, 8, 3, 5, 120))
        self.assertNotEqual(M.random_rows(16, 8, 3, 5, 120), M.random_rows(16, 8, 3, 6, 120))


class CheckerTests(unittest.TestCase):
    """Each check fires on its own, and the timing of the specification holds edge by edge."""
    PARAMETERS = P.CONFIGS['prog3']

    def run_rows(self, edit=None, replacements=None, rows=None):
        rows = rows or [list(r) for r in M.boundary(*P.sizes(self.PARAMETERS))[0]]
        if edit:
            edit(rows)
        return simulate_vectors(P, rows, self.PARAMETERS, replacements)

    def first(self, rows, op, predicate=lambda r: True):
        return next(r for r in rows if r[0] == op and predicate(r))

    def test_unchanged_rows_pass(self):
        result = self.run_rows()
        self.assertEqual((result.returncode, label(result)), (0, []), result.stdout[-400:])

    def test_a_loss_of_power_at_every_edge_of_a_write_matches_the_model(self):
        p = self.PARAMETERS['PROG']
        m = M.Model(16, 8, p)
        m.reset()
        for edges in range(1, 4 * p + 7):
            word = 3 + edges % 13
            m.cut(word, 0x5a ^ edges, edges)
            m.read(word)
        result = self.run_rows(rows=m.finish()[0])
        self.assertEqual((result.returncode, label(result)), (0, []), result.stdout[-400:])

    def test_wrong_expectations_are_told_apart(self):
        def data(rows):
            self.first(rows, M.READ, lambda r: r[3])[3] ^= 1
        def err(rows):
            self.first(rows, M.WRITE)[5] ^= 1
        def flag(rows):
            self.first(rows, M.WRITE)[5] ^= 2
        def status(rows):
            self.first(rows, M.READ)[5] ^= 4
        def latency(rows):
            self.first(rows, M.READ)[6] += 1
        def state(rows):
            self.first(rows, M.RESET)[3] = 1
        def access(rows):
            self.first(rows, M.KEYWRITE)[5] = 1
        for edit, expected in ((data, 'OTP_DATA'), (err, 'OTP_ERR'), (flag, 'OTP_FLAG'), (status, 'OTP_STATUS'),
                               (latency, 'OTP_LATENCY'), (state, 'LC_STATE'), (access, 'LC_ACCESS')):
            with self.subTest(expected=expected):
                self.assertEqual(label(self.run_rows(edit)), [expected])

    def test_a_long_pulse_a_ready_while_busy_and_a_missing_response_are_reported(self):
        long_pulse = {'otp_ctrl.sv': [("localparam integer PULSE = MUTATION == 5 ? PROG - 1 : PROG;",
                                       "localparam integer PULSE = PROG + 1;")]}
        self.assertEqual(label(self.run_rows(replacements=long_pulse)), ['OTP_PULSE'])
        ready = {'otp_ctrl.sv': [('assign req_ready = state == S_IDLE;', "assign req_ready = 1'b1;")]}
        self.assertEqual(label(self.run_rows(replacements=ready)), ['OTP_READY'])
        silent = {'otp_ctrl.sv': [("resp_valid <= 1'b1; resp_err <= 1'b0;\n                            state <= S_RESP;",
                                   "resp_err <= 1'b0;\n                            state <= S_RESP;")]}
        self.assertEqual(label(self.run_rows(replacements=silent)), ['OTP_TIMEOUT'])


if __name__ == '__main__':
    unittest.main()

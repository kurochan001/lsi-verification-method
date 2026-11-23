from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'local-common'))
from local_test_support import load_example, simulate_vectors
from system_test_support import SystemContract

P = load_example('local-canfd')


class CanTests(SystemContract, unittest.TestCase):
    EXAMPLE = 'local-canfd'
    GOALS = 10

    def test_classic_crc_check_value(self):
        message = [b for octet in b'123456789' for b in P.bits(octet, 8)]
        self.assertEqual(P.checksum(message, 15, 0), 0x059e)

    def test_all_dlc_codes_on_real_rtl(self):
        rows = [[0, 0, 0, 0, 0]]
        for dlc, length in enumerate((0, 1, 2, 3, 4, 5, 6, 7, 8, 12, 16, 20, 24, 32, 48, 64)):
            data = bytes(range(length))
            rows.extend(P.frame(1, 1, 0x201, dlc, data))
            symbols = P.symbols(1, 1, 0x201, dlc, data)
            counts = [kind for _, kind, _ in symbols]
            self.assertEqual(counts.count(P.CRC), 17 if length <= 16 else 21)
            self.assertEqual(counts.count(P.FIXED), 6 if length <= 16 else 7)
        sim = simulate_vectors(P, rows)
        self.assertEqual(sim.returncode, 0, sim.stdout)

    def test_fixed_bit_must_complement_its_predecessor(self):
        rows = P.frame(1, 0, 0, 0, b'')
        index = next(i for i, row in enumerate(rows) if row[0] == 2 and row[2] == P.FIXED)
        rows[index][1] ^= 1
        sim = simulate_vectors(P, [[0]*5] + rows)
        self.assertNotEqual(sim.returncode, 0)
        self.assertIn('CHECK_FAIL CANFD_STUFF', sim.stdout)

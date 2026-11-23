from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'local-common'))
from local_test_support import load_example, simulate_vectors
from system_test_support import SystemContract

P = load_example('local-flash-ctrl')


class FlashTests(SystemContract, unittest.TestCase):
    EXAMPLE = 'local-flash-ctrl'
    GOALS = 14

    def test_authorization_and_serial_address_order(self):
        p = P.Plan()
        p.command(P.PROGRAM, 3, 0x21)
        self.assertEqual(p.rows[-1][5:8], [0, 0, True])
        p.command(P.WREN)
        p.command(P.PROGRAM, 3, 0x21)
        self.assertEqual(p.rows[-1][5:8], [3, 0xa00321, False])
        self.assertFalse(p.wel)
        p.command(P.READ, 3)
        self.assertEqual(p.rows[-1][6], 0x03030000)
        self.assertEqual(p.last, 0x21)

    def test_sector_preserves_neighbors_and_chip_erase_covers_last_byte(self):
        p = P.Plan()
        p.command(P.WREN)
        p.command(P.SECTOR, 7)
        self.assertEqual(p.mem[3:9], bytes([0xa3, 255, 255, 255, 255, 0xa8]))
        self.assertEqual(p.rows[-1][10], 6)
        p.command(P.WREN)
        p.command(P.ERASE)
        self.assertEqual(p.mem, bytes([255])*16)

    def test_failed_program_is_atomic_and_clear_recovers(self):
        p = P.Plan()
        p.command(P.WREN)
        p.command(P.PROGRAM, 15, 0x1f)
        self.assertTrue(p.fault)
        self.assertEqual(p.rows[-1][10:12], [7, True])
        self.assertEqual(p.byte(15), 0xaf)
        p.command(P.CLEAR)
        self.assertFalse(p.fault)
        p.command(P.READ, 15)
        self.assertEqual(p.rows[-1][7:9], [False, 0xaf])

    def test_invalid_address_does_not_alias_zero(self):
        p = P.Plan()
        p.command(P.WREN)
        p.command(P.PROGRAM, 16, 0)
        self.assertEqual(p.byte(0), 0xa0)
        p.xip(16)
        self.assertEqual(p.rows[-1][8], 0xff)

    def test_external_busy_reports_timeout_then_read_recovers(self):
        p = P.Plan()
        p.command(P.WREN)
        p.command(P.PROGRAM, 8, 0x80, stuck=True)
        self.assertEqual(p.rows[-1][10:], [7, True])
        p.command(P.READ, 8)
        self.assertEqual(p.rows[-1][7:9], [False, 0x80])
        self.assertFalse(p.wip)
        result = simulate_vectors(P, p.rows)
        self.assertEqual(result.returncode, 0, result.stdout)

    def test_bad_serial_readback_is_detected_independently_of_xip(self):
        p = P.Plan()
        p.command(P.READ, 9)
        result = simulate_vectors(P, p.rows, replacements={'flash_model.sv': [
            ('serial_data[7-bits[2:0]]', 'serial_data[bits[2:0]]')]})
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('CHECK_FAIL FLASH_DATA', result.stdout)


if __name__ == '__main__':
    unittest.main()

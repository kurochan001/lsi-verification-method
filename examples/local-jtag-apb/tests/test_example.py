from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'local-common'))
from local_test_support import load_example, simulate_vectors
from system_test_support import SystemContract

P = load_example('local-jtag-apb')


class BridgeTests(SystemContract, unittest.TestCase):
    EXAMPLE = 'local-jtag-apb'
    GOALS = 13

    def test_waits_and_sticky_error_clear_only_on_successful_high_read(self):
        p = P.Plan(2)
        p.tick(rst=0)
        p.tick()
        p.scan(3, 2, 1, instruction=True)
        p.transaction(5, data=0xb4, write=1)
        p.transaction(0x85, data=0x20, write=1)
        self.assertEqual((p.err, p.ram[5]), (1, 0xb4))
        p.transaction(1, extra=3)
        self.assertEqual(p.err, 1)
        self.assertEqual([r[7] for r in p.rows[-7:]], [2]*6+[0])
        p.transaction(5)
        self.assertEqual((p.err, p.last_read), (0, 0xb4))
        result = simulate_vectors(P, p.rows, {'WAIT': 2})
        self.assertEqual(result.returncode, 0, result.stdout)

    def test_reset_aborts_an_access_wait(self):
        p = P.Plan(2)
        p.tick(rst=0)
        p.tick()
        p.scan(3, 2, 1, instruction=True)
        p.scan(0x02a30006, 32, 0)
        p.tick()
        self.assertEqual(p.phase, 2)
        p.tick(rst=0)
        p.tick()
        p.scan(0, 32, P.IDCODE)
        self.assertFalse(any(p.ram))
        result = simulate_vectors(P, p.rows, {'WAIT': 2})
        self.assertEqual(result.returncode, 0, result.stdout)

    def test_serial_idcode_bit_error_is_visible(self):
        rows = P.vectors(17, 0, {'WAIT': 0}, boundary=True)
        result = simulate_vectors(P, rows, {'WAIT': 0},
                                  {'jtag_apb.sv': [("32'hB7071149", "32'hB7071148")]})
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('CHECK_FAIL JAPB_TAP', result.stdout)

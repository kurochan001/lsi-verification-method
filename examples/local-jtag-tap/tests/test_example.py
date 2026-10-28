from pathlib import Path
import sys, unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'local-common'))
from system_test_support import SystemContract
from local_test_support import load_example

P = load_example('local-jtag-tap')


class ExampleTests(SystemContract, unittest.TestCase):
    EXAMPLE = 'local-jtag-tap'
    GOALS = 12

    def test_idcode_capture_and_ir_update(self):
        p = P.Plan(0x12345678)
        p.reset()
        p.clock(0)
        p.go_shift_dr()
        self.assertEqual(p.id_shift, 0x12345678)
        p.reset()
        p.clock(0)
        p.load_ir([1, 1, 1, 1])
        self.assertEqual(p.ir, P.BYPASS)

    def test_extest_drives_boundary_register(self):
        p = P.Plan(0x12345678)
        p.fixed()
        self.assertIn(0xa5, [row[6] for row in p.rows])

    def test_tlr_resets_state_and_instruction(self):
        p = P.Plan(0xdeadbeef)
        p.reset()
        self.assertEqual(p.state, P.TLR)
        self.assertEqual(p.ir, P.IDCODE_IR)


if __name__ == '__main__':
    unittest.main()

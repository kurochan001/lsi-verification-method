from pathlib import Path
import sys, unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'local-common'))
from system_test_support import SystemContract
from local_test_support import load_example

P = load_example('local-lockstep-monitor')


class ExampleTests(SystemContract, unittest.TestCase):
    EXAMPLE = 'local-lockstep-monitor'
    GOALS = 12

    def test_fault_bit_is_detected_in_both_configurations(self):
        for bit in (0, 7):
            with self.subTest(bit=bit):
                p = P.Plan(bit)
                p.step(rst=0)
                p.step(op_valid=1, op=2, operand=0xaa)
                p.step(op_valid=1, op=0, operand=1, fault=1)
                p.step()
                self.assertEqual(p.rows[-1][7], 1)
                self.assertEqual(p.rows[-1][8], 1)
                self.assertEqual(p.rows[-1][9], 1)

    def test_recover_resynchronizes_and_illegal_stops(self):
        p = P.Plan(0)
        p.step(rst=0)
        p.step(op_valid=1, op=2, operand=0xaa)
        p.step(op_valid=1, op=0, operand=1, fault=1)
        p.step(recover=1)
        p.step(op_valid=1, op=0, operand=1)
        p.step()
        self.assertEqual(p.rows[-1][6], 0xab)
        p.step(op_valid=1, op=3)
        p.step()
        self.assertEqual(p.rows[-1][9], 2)
        self.assertEqual(p.rows[-1][7], 1)


if __name__ == '__main__':
    unittest.main()

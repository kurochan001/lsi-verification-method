from pathlib import Path
import sys, unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'local-common'))
from system_test_support import SystemContract
from local_test_support import load_example

P = load_example('local-address-map')


class ExampleTests(SystemContract, unittest.TestCase):
    EXAMPLE = 'local-address-map'
    GOALS = 13

    def test_alias_and_strict_decode_differ(self):
        alias = P.Plan(1)
        alias.write(0x000, 0x12345678)
        alias.read_step(0x400)
        self.assertEqual(alias.rows[-1][7], 0x12345678)
        strict = P.Plan(0)
        strict.write(0x000, 0x12345678)
        strict.read_step(0x400)
        self.assertEqual(strict.rows[-1][8], 1)

    def test_byte_strobes_preserve_other_lanes(self):
        p = P.Plan(1)
        p.write(0x000, 0x11223344)
        p.write(0x000, 0x000000aa, 0x1)
        p.read_step(0x000)
        self.assertEqual(p.rows[-1][7], 0x112233aa)

    def test_unmapped_write_has_no_side_effect(self):
        p = P.Plan(1)
        p.write(0x000, 0x01020304)
        p.write(0x300, 0xdeadbeef)
        p.read_step(0x000)
        self.assertEqual(p.rows[-1][7], 0x01020304)


if __name__ == '__main__':
    unittest.main()

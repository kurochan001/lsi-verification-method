from pathlib import Path
import sys, unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'local-common'))
from system_test_support import SystemContract
from local_test_support import load_example, simulate_vectors

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


    def test_gpio_pin_is_checked_without_software_readback(self):
        p=P.Plan(1);p.step(rst=0);p.write(0x200,5);p.idle()
        result=simulate_vectors(P,p.rows,replacements={'address_map.sv':[
            ('gpio_out <= pwdata[3:0];','gpio_out <= 0;')]})
        self.assertNotEqual(result.returncode,0,result.stdout)
        self.assertIn('CHECK_FAIL MAP_GPIO',result.stdout)

    def test_new_timer_and_gpio_events_win_over_w1c(self):
        for parameters in P.CONFIGS.values():
            p=P.Plan(parameters['ALIAS']);p.step(rst=0);p.write(0x108,2)
            p.write(0x100,3);p.idle();p.write(0x10c,1);p.read_step(0x10c)
            self.assertEqual(p.rows[-1][7],1)
            p.write(0x208,1);p.write(0x20c,1,gpio_in=1);p.read_step(0x20c,gpio_in=1)
            self.assertEqual(p.rows[-1][7],1)
            result=simulate_vectors(P,p.rows,parameters)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)


if __name__ == '__main__':
    unittest.main()

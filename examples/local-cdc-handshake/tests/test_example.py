from pathlib import Path
import sys, unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'local-common'))
from system_test_support import SystemContract
from local_test_support import load_example

P = load_example('local-cdc-handshake')


class ExampleTests(SystemContract, unittest.TestCase):
    EXAMPLE = 'local-cdc-handshake'
    GOALS = 14

    def test_data_and_pulse_reach_destination(self):
        p = P.Plan(2)
        p.set_profile(0)
        p.reset_ticks()
        p.send(0x00)
        p.send(0xff)
        data = [row[10] for row in p.rows if row[9] and row[5]]
        self.assertIn(0x00, data)
        self.assertIn(0xff, data)
        p.pulse()
        self.assertTrue(any(row[11] for row in p.rows))

    def test_clock_profiles_have_opposite_rates(self):
        def rises(profile):
            clocks = P.make_clocks(profile, 80)
            src = sum(1 for i, (sc, _) in enumerate(clocks) if sc and (i == 0 or not clocks[i - 1][0]))
            dst = sum(1 for i, (_, dc) in enumerate(clocks) if dc and (i == 0 or not clocks[i - 1][1]))
            return src, dst

        self.assertGreater(*rises(0))
        self.assertLess(*rises(1))

    def test_reset_deassert_is_delayed(self):
        p = P.Plan(3)
        p.set_profile(0)
        p.reset_ticks()
        after = [row for row in p.rows if row[2] and row[12] == 0]
        self.assertTrue(after)
        self.assertEqual(p.rows[-1][12], 1)


if __name__ == '__main__':
    unittest.main()

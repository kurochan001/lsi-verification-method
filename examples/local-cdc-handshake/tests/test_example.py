from pathlib import Path
import sys, unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'local-common'))
from system_test_support import SystemContract
from local_test_support import load_example, simulate_vectors

P = load_example('local-cdc-handshake')


class ExampleTests(SystemContract, unittest.TestCase):
    EXAMPLE = 'local-cdc-handshake'
    GOALS = 15

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


    def test_one_pulse_is_not_credited_as_back_to_back(self):
        for parameters in P.CONFIGS.values():
            p=P.Plan(parameters['SYNC_STAGES']);p.reset_ticks();p.pulse()
            for _ in range(120):p.step(dready=1)
            result=simulate_vectors(P,p.rows,parameters)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            self.assertEqual(result.stdout.count('COVER pulse/single'),1)
            self.assertNotIn('COVER pulse/back-to-back',result.stdout)

    def test_transport_queue_catches_an_error_shared_by_rtl_and_cycle_model(self):
        p=P.Plan(2);p.reset_ticks();p.send(0x55);p.send(0xaa)
        for _ in range(120):p.step(dready=1)
        rows=[list(row) for row in p.rows]
        for row in rows:
            if row[9]:row[10]^=1
        result=simulate_vectors(P,rows,{'SYNC_STAGES':2},replacements={'cdc_handshake.sv':[
            ("assign dst_data = MUTATION == 1 ? (data_reg ^ 8'h01) : data_reg;","assign dst_data = data_reg ^ 8'h01;")]})
        self.assertNotEqual(result.returncode,0,result.stdout)
        self.assertIn('CHECK_FAIL CDC_QUEUE',result.stdout)


if __name__ == '__main__':
    unittest.main()

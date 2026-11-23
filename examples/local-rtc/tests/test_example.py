from pathlib import Path
import sys, unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'local-common'))
from system_test_support import SystemContract
from local_test_support import load_example, simulate_vectors

P = load_example('local-rtc')


class ExampleTests(SystemContract, unittest.TestCase):
    EXAMPLE = 'local-rtc'
    GOALS = 14

    def test_seconds_advance_once_per_div_prescale_ticks(self):
        for parameters in P.CONFIGS.values():
            div = parameters['DIV']
            p = P.Plan(div)
            p.step(rst=0)
            p.set_ctrl(0x01)
            p.wait(4 * div + 3)
            self.assertEqual(p.rows[-1][5], 4)  # four prescale wraps, four seconds

    def test_alarm_matches_after_the_tick_and_w1c_arms_again(self):
        p = P.Plan(4)
        p.step(rst=0)
        p.write(1, 0x08)
        p.set_ctrl(0x01)
        p.until_sec(8)
        p.until_sub(p.div - 1)  # the next row is the matching tick
        p.step()  # the tick lands at the end of this row
        p.step()  # the pending flag shows on the row after
        self.assertEqual(p.rows[-1][7], 1)
        p.read(1)
        self.assertEqual(p.rows[-1][8] & 0x80, 0x80)  # the readback mirrors it
        p.write(1, 0x02)  # W1C clears it
        p.step()
        self.assertEqual(p.rows[-1][7], 0)
        p.jump(0x08)  # ignored: jump-set is off, so the counter keeps running
        self.assertNotEqual(p.rows[-1][5], 0x08)

    def test_jump_set_freezes_until_released(self):
        p = P.Plan(4)
        p.step(rst=0)
        p.set_ctrl(0x05)  # en + set
        p.jump(0xF0)
        p.wait(4 * p.div)
        self.assertEqual(p.rows[-1][5], 0xF0)  # seconds are frozen while set is 1
        p.set_ctrl(0x01)
        p.wait(p.div + 1)
        self.assertEqual(p.rows[-1][5], 0xF1)  # the first tick after release

    def test_slew_pauses_never_rewinds_and_maximum_adds_four(self):
        p = P.Plan(4)
        p.step(rst=0)
        p.set_ctrl(0x63)  # slew, ADJ=-2 -> clamped to zero
        p.wait(3 * p.div)
        self.assertEqual(p.rows[-1][5], 0)
        p.set_ctrl(0x33)  # ADJ=+3 -> the maximum rate of +4/s
        p.wait(p.div)
        self.assertEqual(p.rows[-1][5], 4)

    def test_alarm_match_wins_over_same_cycle_w1c(self):
        p = P.Plan(4)
        p.step(rst=0)
        p.write(1, 0x2A)
        p.set_ctrl(0x05)
        p.jump(0x2A)  # park on the alarm value
        p.until_sub(0)
        p.wait(p.div - 1)
        p.until_sub(p.div - 1)
        p.write(1, 0x02)  # the clear lands exactly on the matching tick
        self.assertEqual(p.rows[-1][7], 0)  # the flag was down while the row ran
        p.step()
        self.assertEqual(p.rows[-1][7], 1)  # but the new match won
    def test_capture_is_a_two_flop_snapshot(self):
        p = P.Plan(4)
        p.step(rst=0)
        p.set_ctrl(0x01)
        p.wait(4)
        p.step(cap=1)
        p.read(3)  # second synchronizer stage samples the pulse on this edge
        p.read(3)  # capture edge, before the nonblocking updates
        self.assertEqual(p.rows[-1][8:10], [0, 0])
        snapshot = p.rows[-1][5:7]
        p.read(3)
        self.assertEqual(p.rows[-1][8:10], snapshot)
        p.wait(5)
        p.read(3)
        self.assertEqual(p.rows[-1][8:10], snapshot)
        result = simulate_vectors(P, p.rows, parameters={'DIV': 4})
        self.assertEqual(result.returncode, 0, result.stdout)


    def test_post_increment_alarm_compare_is_caught(self):
        for parameters in P.CONFIGS.values():
            div = parameters['DIV']
            p = P.Plan(div)
            p.step(rst=0)
            p.write(1, 0x04)
            p.set_ctrl(0x01)
            p.wait(6 * div)
            result = simulate_vectors(P, p.rows, parameters=parameters, replacements={'rtc.sv': [
                ('((MUTATION == 2 ? sec[7:0] + inc[7:0] : sec[7:0]) == alarm)',
                 '(sec[7:0] + inc[7:0] == alarm)')]})
            self.assertNotEqual(result.returncode, 0, result.stdout)
            self.assertIn('CHECK_FAIL RTC_IRQ', result.stdout)


if __name__ == '__main__':
    unittest.main()

import copy
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'local-common'))
from system_test_support import SystemContract
from local_test_support import load_example

P = load_example('local-power-domains')
ICARUS = shutil.which('iverilog') and shutil.which('vvp')
# Written by hand from the RTL, not derived from the table: what must lose its value, per domain.
FORCED = {'pd_tb.dut.u_a.acc': 8, 'pd_tb.dut.u_a.scratch': 8, 'pd_tb.dut.u_a.fired': 1,
          'pd_tb.dut.u_b.mode': 4, 'pd_tb.dut.u_b.count': 8}
ISOLATED = {'a_sum': "8'd0", 'a_idle_n': "{1{1'b1}}", 'a_last': 'a_last_held', 'b_count': "8'd0", 'b_mode': 'b_mode_held'}


def simulate(model_text, rows, mutation=0, settle=2):
    """Compile the RTL and the bench with the given power model; return the simulation output."""
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp)
        (out / 'pd_power_model.sv').write_text(model_text)
        (out / 'vectors.txt').write_text(''.join(' '.join(format(v, 'x') for v in row) + '\n' for row in rows))
        subprocess.run(['iverilog', '-g2012', '-s', 'pd_tb', '-o', str(out / 'sim.vvp'), f'-Ppd_tb.MUTATION={mutation}',
                        f'-Ppd_tb.SETTLE={settle}', *map(str, P.SOURCES), str(out / 'pd_power_model.sv')],
                       capture_output=True, text=True, timeout=60, check=True)
        return subprocess.run(['vvp', str(out / 'sim.vvp'), f'+VECTORS={out / "vectors.txt"}', f'+WAVE={out / "wave.vcd"}'],
                              capture_output=True, text=True, timeout=60).stdout


class ExampleTests(SystemContract, unittest.TestCase):
    EXAMPLE = 'local-power-domains'
    GOALS = 23


class ModelTests(unittest.TestCase):
    def setUp(self):
        self.model = P.MODEL.PowerModel(P.intent())

    def test_b_follows_only_while_a_is_requested(self):
        m = self.model
        self.assertEqual(m.target(dict(a=0, b=1)), dict(a=0, b=0))
        self.assertEqual(m.power(dict(a=1, b=1)), ['a-up', 'b-up'])
        self.assertEqual(m.power(dict(a=0, b=1)), ['b-down', 'a-down'])
        self.assertEqual(m.power(dict(a=0, b=1)), [])

    def test_retained_values_return_and_the_others_restart_from_reset(self):
        m = self.model
        m.power(dict(a=1, b=1))
        for select, data in ((0, 0x35), (0, 0x21), (1, 0x8a), (1, 0x05)):
            self.assertTrue(m.operate(select, data))
        self.assertEqual(m.outputs(), dict(a_sum=0x56, a_idle_n=1, a_last=0x21, b_count=5, b_mode=0xa))
        m.power(dict(a=0, b=0))
        # off: 0, 1 and the last value, as the table says for each output
        self.assertEqual(m.outputs(), dict(a_sum=0, a_idle_n=1, a_last=0x21, b_count=0, b_mode=0xa))
        self.assertFalse(m.operate(0, 1))
        m.power(dict(a=1, b=1))
        self.assertEqual(m.outputs(), dict(a_sum=0x56, a_idle_n=1, a_last=0, b_count=0, b_mode=0xa))
        m.reset()
        m.power(dict(a=1, b=1))
        self.assertEqual(m.outputs(), dict(a_sum=0, a_idle_n=1, a_last=0, b_count=0, b_mode=0))

    def test_counter_of_b_adds_bit_0_of_the_sum_of_a(self):
        m = self.model
        m.power(dict(a=1, b=1))
        m.operate(0, 0x11)
        m.operate(1, 0x7f)
        self.assertEqual(m.outputs()['b_count'], 0x80)

    def test_fixed_scenario_gives_each_mutant_what_it_needs(self):
        plan = P.boundary_plan()
        kinds = [row[0] for row in plan.rows]
        self.assertEqual(set(kinds), set(range(6)))
        self.assertEqual(plan.counts, dict(ops_accepted=16, ops_refused=4, power_requests=18, resets=3))
        # mutant 3 needs a mode other than the reset value when B comes back
        back = next(row for previous, row in zip(plan.rows, plan.rows[1:]) if previous[10] == 0 and row[10] == 1 and row[0] == P.POWER)
        self.assertNotEqual(back[8], 0)
        with self.assertRaises(ValueError):  # an operand in the request cycle needs a domain that goes down
            P.Plan().power_with_operand(1, 0, 1)


class IntentTests(unittest.TestCase):
    def setUp(self):
        self.intent = P.intent()

    def broken(self, edit):
        table = copy.deepcopy(self.intent)
        edit(table)
        return table

    def test_table_is_valid_and_matches_the_registers_of_the_rtl(self):
        P.power_model_text()

    def test_state_that_powers_b_without_a_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'without the domains it requires'):
            P.GEN.validate(self.broken(lambda t: t['states'].update({'b-only': dict(a=0, b=1)})))

    def test_transition_must_switch_one_domain(self):
        with self.assertRaisesRegex(ValueError, 'exactly one domain'):
            P.GEN.validate(self.broken(lambda t: t['transitions'].update({'both-up': ['all-off', 'all-on']})))

    def test_crossing_without_isolation_needs_the_power_order(self):
        def edit(table):
            table['domains']['b']['requires'] = []
            table['states']['b-only'] = dict(a=0, b=1)
        with self.assertRaisesRegex(ValueError, 'needs isolation'):
            P.GEN.validate(self.broken(edit))

    def test_unknown_isolation_value_and_duplicate_name_are_rejected(self):
        with self.assertRaises(ValueError):
            P.GEN.validate(self.broken(lambda t: t['domains']['a']['outputs'][0].update(isolation='float')))
        with self.assertRaises(ValueError):
            P.GEN.validate(self.broken(lambda t: t['domains']['b']['registers'][0].update(name='acc')))

    def test_register_missing_from_the_table_is_found_by_the_audit(self):
        table = self.broken(lambda t: t['domains']['a']['registers'].pop(1))
        with self.assertRaisesRegex(ValueError, 'scratch'):
            P.power_model_text(table)
        with self.assertRaisesRegex(ValueError, 'ghost'):
            P.power_model_text(self.broken(lambda t: t['domains']['b']['registers'].append(
                dict(name='ghost', width=1, reset=0, retained=False))))


class GeneratorTests(unittest.TestCase):
    def setUp(self):
        self.text = P.power_model_text()

    def test_every_register_is_forced_to_x_and_released_once(self):
        forced = dict(re.findall(r"force (\S+) = (\d+)'bx;", self.text))
        self.assertEqual({name: int(width) for name, width in forced.items()}, FORCED)
        self.assertEqual(sorted(re.findall(r'release (\S+);', self.text)), sorted(FORCED))
        self.assertEqual(len(re.findall(r'\bforce\b', self.text)), len(FORCED))

    def test_every_isolated_output_is_compared_with_its_value(self):
        found = dict(re.findall(r'if \(pd_tb\.dut\.(\w+) !== (.+?)\) pd_tb\.fail\("PD_ISO"\);', self.text))
        self.assertEqual(found, ISOLATED)

    def test_states_transitions_and_checks_are_counted(self):
        count = lambda label: len(re.findall(f'fail\\("{label}"\\)', self.text))
        self.assertEqual((count('PD_STATE'), count('PD_TRANSITION')), (1, 1))
        self.assertEqual(sorted(re.findall(r"^\s+2'b(\d\d): ", self.text, re.M)), ['00', '10', '11'])
        self.assertEqual(sorted(re.findall(r"^\s+4'b(\d{4}): ", self.text, re.M)), ['0010', '1000', '1011', '1110'])
        self.assertEqual((count('PD_SEQ'), count('PD_RETAIN'), count('PD_INIT')), (8, 2, 3))
        self.assertEqual(count('PD_XLEAK'), 11)  # six control outputs and five isolated outputs

    def test_dropping_a_register_changes_the_text_and_is_seen_here(self):
        text = P.GEN.generate(P.intent(), drop_injection={'a.acc'})
        self.assertNotIn('force pd_tb.dut.u_a.acc', text)
        self.assertNotEqual(set(re.findall(r'force (\S+) =', text)), set(FORCED))


@unittest.skipUnless(ICARUS, 'Icarus required')
class SimulationTests(unittest.TestCase):
    ROWS = P.boundary_plan().rows

    def test_x_leak_is_found_only_because_the_registers_become_x(self):
        self.assertIn('CHECK_FAIL PD_XLEAK', simulate(P.power_model_text(), self.ROWS, mutation=1))
        # Without X in the accumulator the same mutant passes: the reset before power-off leaves 0,
        # which happens to be the isolation value. This is why the audit insists on every register.
        without = simulate(P.GEN.generate(P.intent(), drop_injection={'a.acc'}), self.ROWS, mutation=1)
        self.assertNotIn('CHECK_FAIL', without)
        self.assertIn('RESULT PASS checks=35', without)

    def test_wrong_expected_value_is_a_data_failure(self):
        rows = [list(row) for row in self.ROWS]
        rows[2][4] ^= 1
        output = simulate(P.power_model_text(), rows)
        self.assertEqual(re.findall(r'^CHECK_FAIL (\w+)$', output, re.M), ['PD_DATA'])

    def test_table_with_a_wrong_isolation_value_fails_the_correct_design(self):
        table = P.intent()
        table['domains']['a']['outputs'][0]['isolation'] = 'one'
        output = simulate(P.GEN.generate(table), self.ROWS)
        self.assertEqual(re.findall(r'^CHECK_FAIL (\w+)$', output, re.M), ['PD_ISO'])

    def test_settle_time_is_enforced(self):
        # The design waits 2 cycles; a checker that asks for 4 must object to the first power-up.
        text = P.power_model_text()
        self.assertEqual(text.count('< SETTLE)'), 4)
        output = simulate(text.replace('< SETTLE)', '< 4)'), self.ROWS, settle=2)
        self.assertEqual(re.findall(r'^CHECK_FAIL (\w+)$', output, re.M), ['PD_SEQ'])
        self.assertIn('RESULT PASS', simulate(text.replace('< SETTLE)', '< 4)'), self.ROWS, settle=4))


if __name__ == '__main__':
    unittest.main()

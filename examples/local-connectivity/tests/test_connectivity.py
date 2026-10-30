import copy
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'local-common'))
from local_test_support import load_example

P = load_example('local-connectivity')
G = P.G
YOSYS = shutil.which('yowasp-yosys') or shutil.which('yosys')


def edited(table, row_id, **fields):
    rows = copy.deepcopy(table)
    for row in rows:
        if row['id'] == row_id:
            row.update(fields)
    return rows


class PlanTest(unittest.TestCase):
    def test_plan_has_a_proof_a_cover_and_four_counterexamples(self):
        plan = P.plan(P.BOUND, 0)
        self.assertEqual([c['id'] for c in plan], ['connectivity-proof', 'scenario-cover'] +
                         [f'detect-mutation{m}' for m in range(1, 5)])
        self.assertEqual(plan[0]['depth'], P.PROOF_DEPTH)
        self.assertEqual([c['failure'] for c in plan[2:]], ['ap_irq1_timer', 'ap_uart_rx_idle', 'ap_pad3_gpio', 'ap_rst'])
        self.assertEqual(P.plan(P.BOUND, 3)[0]['parameters'], {'MUTATION': 3})

    def test_each_row_is_one_assertion_and_each_condition_one_cover(self):
        props = P.properties(P.CONFIGS['soc'], P.plan(P.BOUND, 0)[0])
        self.assertEqual(len(props['assert']), len(P.TABLE))
        self.assertTrue(set(P.FAILURES.values()) <= props['assert'])
        conditions = {r['when'] for r in P.TABLE if r['when']}
        self.assertEqual(len(props['cover']), len(conditions) + 1)
        self.assertEqual(props['assume'], set())

    def test_committed_checker_matches_the_files_it_was_generated_from(self):
        self.assertIsNone(G.stale())
        with tempfile.TemporaryDirectory() as tmp:
            changed = Path(tmp) / 'connectivity.csv'
            changed.write_text(G.TABLE.read_text().replace('IRQ1_TIMER,u_irq.src_i[1],u_timer.irq_o',
                                                           'IRQ1_TIMER,u_irq.src_i[1],u_uart.irq_o'))
            original, G.TABLE = G.TABLE, changed
            try:
                self.assertIn('run generate.py', G.stale())
            finally:
                G.TABLE = original

    def test_prepare_exposes_every_probe_and_sets_the_mutation(self):
        script = P.prepare(P.CONFIGS['soc'], P.plan(P.BOUND, 0)[3])
        self.assertIn('chparam -set MUTATION 2 soc_top', script)
        exposed = next(line for line in script.splitlines() if line.startswith('expose ')).split()[1:]
        self.assertEqual(exposed, ['w:' + p for p in G.probes(P.TABLE)])
        self.assertLess(script.index('flatten'), script.index('expose'))
        self.assertTrue(script.rstrip().endswith('read -formal -sv conn_check.sv'))


@unittest.skipUnless(YOSYS, 'Yosys required')
class TableTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.design = G.Design(*G.netlist(YOSYS))

    def rejects(self, table, message):
        with self.assertRaises(G.TableError) as caught:
            G.render(table, self.design)
        self.assertIn(message, str(caught.exception))

    def test_committed_checker_is_generated_from_the_table(self):
        self.assertEqual(G.render(P.TABLE, self.design), G.CHECKER.read_text())

    def test_missing_branch_of_a_condition_is_rejected(self):
        self.rejects([r for r in P.TABLE if r['id'] != 'UART_RX_IDLE'], 'u_uart.rx_i[0]')

    def test_overlapping_rows_are_rejected(self):
        self.rejects(edited(P.TABLE, 'PAD0_GPIO', when=''), 'pad_o[0]')

    def test_width_mismatch_is_rejected(self):
        self.rejects(edited(P.TABLE, 'IRQ_UNUSED', **{'from': "3'b000"}), 'IRQ_UNUSED')

    def test_unused_block_output_is_rejected(self):
        self.rejects(edited(P.TABLE, 'DMA_REQ0', **{'from': "1'b0"}), 'u_uart.dma_req_o')

    def test_unused_bit_of_a_bus_is_rejected(self):
        self.rejects(edited(P.TABLE, 'PAD3_GPIO', **{'from': "{u_gpio.gpio_oe_o[3],1'b0}"}), 'u_gpio.gpio_o[3]')

    def test_destination_used_as_a_source_is_rejected(self):
        self.rejects(edited(P.TABLE, 'GPIO_IN', **{'from': 'u_gpio.gpio_i'}), 'is not a block output or SoC input')

    def test_unknown_port_is_rejected(self):
        self.rejects(edited(P.TABLE, 'IRQ1_TIMER', **{'from': 'u_timer.irq'}), 'u_timer.irq')


if __name__ == '__main__':
    unittest.main()

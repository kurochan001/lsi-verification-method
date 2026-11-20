from pathlib import Path
import re
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'local-common'))
from system_test_support import SystemContract
from local_test_support import load_example, read_json, simulate_vectors

P = load_example('local-riscv-debug')
M, ISS = P.M, P.ISS
HERE = Path(__file__).resolve().parents[1]
PARAMETERS = P.CONFIGS['debug']
NOP = ('addi', 0, 0, 0)


def label(result):
    return re.findall(r'^CHECK_FAIL (\w+)$', result.stdout, re.M)


class ExampleTests(SystemContract, unittest.TestCase):
    EXAMPLE = 'local-riscv-debug'
    GOALS = 29

    @classmethod
    def setUpClass(cls):
        cls.rows, cls.facts = P.directed(1, 1, 0)  # every stop, one halt request of each kind, short loops

    def test_bit_layouts_are_the_ones_written_down_here(self):
        # Values worked out by hand from the field positions, not through the model's helpers.
        self.assertEqual(M.access(0x1005), 0x00221005)
        self.assertEqual(M.access(0x7b1, write=True), 0x002307b1)
        self.assertEqual(M.dmi(0x17, 0x00221005, 2), 0x17 << 34 | 0x00221005 << 2 | 2)
        self.assertEqual(M.dcsr_value(4, 1, 1), 0x40008107)
        self.assertEqual(M.dcsr_value(3, 0, 0), 0x400000c3)
        self.assertEqual(M.DTMCS, 1 << 12 | 7 << 4 | 1)
        with self.assertRaises(ValueError):
            M.dmi(128)

    def test_goal_names_agree_between_catalog_model_and_bench(self):
        catalog = [g for r in read_json(HERE / 'requirements.json')['requirements'] for g in r['goals']]
        self.assertEqual(sorted(catalog), sorted(M.GOALS + M.BENCH_GOALS))
        bench = (HERE / 'tb/debug_tb.sv').read_text()
        names = re.findall(r'goal_name = "([^"]+)"', bench)
        self.assertEqual(names, M.GOALS)
        self.assertEqual(re.findall(r'label_name = "([^"]+)"', bench), M.LABELS)
        for goal in M.BENCH_GOALS:
            self.assertIn(f'COVER {goal}', bench)

    def test_a_command_outlasts_two_scans_as_the_busy_test_needs(self):
        rtl = (HERE / 'rtl/debug_module.sv').read_text()
        self.assertEqual(int(re.search(r'CMD_CYCLES = (\d+)', rtl).group(1)), M.CMD_CYCLES)
        self.assertGreater(M.CMD_CYCLES, 2 * M.SCAN_CLOCKS)

    def test_fixed_scenario_plans_every_goal_and_counts_its_halts(self):
        rows, facts = P.directed()
        self.assertEqual(sorted(set(facts['goals'])), sorted(M.GOALS))
        self.assertEqual(facts['stops'], ['haltreq'] + ['ebreak'] * 5)
        # 6 stops, 4 + 2 steps at them; 6 + 20 plain requests; 4 requests with 1, 2, 3 and 4 steps
        self.assertEqual(facts['halts'], 6 + 6 + 26 + (4 + 1 + 2 + 3 + 4))
        self.assertEqual(P.counts(rows)['scans'], facts['scans'])
        self.assertLessEqual(len(facts['trace']), P.RETIRE_LIMIT)

    def test_stops_do_not_change_what_retires(self):
        """Resuming after the EBREAK retires what the same program retires with a NOP in its place."""
        import random
        stops = 0
        for seed in (1, 2, 3):
            rng = random.Random(seed)
            body = ISS.random_program(rng, 60, loops=True)
            places = sorted(rng.sample(range(13, len(body) - 1), 3), reverse=True)
            stopped, plain = list(body), list(body)
            for place in places:
                stopped.insert(place, ('ebreak',))
                plain.insert(place, NOP)
            data = ISS.random_data(rng)

            # the last EBREAK must end the program: stop there once more and clear ebreakm
            stopped = stopped[:-1] + ['end:', NOP, ('ebreak',), NOP, ('ebreak',)]
            plain = plain[:-1] + ['end:', NOP, NOP, NOP, ('ebreak',)]
            end = ISS.label_addresses(stopped)['end'] + 4

            def plan(debugger, cause, pc, regs, end=end):
                if cause == 'haltreq':
                    return [('ebreakm', 1)]
                return [('ebreakm', 0), ('dpc', None)] if pc == end else [('dpc', None)]
            debugger = M.Debugger(M.Script(), plan)
            with_stops = ISS.execute(ISS.assemble(stopped), data, traps=True, debug=debugger)
            without = ISS.execute(ISS.assemble(plain), data, traps=True)
            # the addresses that hold an EBREAK in one image and the NOP in the other
            skipped = {4 * i for i, (x, y) in enumerate(zip(ISS.assemble(stopped), ISS.assemble(plain))) if x != y}
            self.assertEqual(len(skipped), 4)
            stops += debugger.stops  # an EBREAK on a path not taken is never met
            key = lambda r: (r.pc, r.insn, r.rd, r.wdata, r.kind, r.addr, r.data)
            self.assertEqual([key(r) for r in with_stops], [key(r) for r in without if r.pc not in skipped])
        self.assertGreater(stops, 3 * 2 + 3)  # more than the first halt and the last EBREAK of each program

    def test_no_interrupt_is_taken_during_a_step_in_the_model(self):
        trace, labels = self.facts['trace'], self.facts['labels']
        traps = [i for i, r in enumerate(trace) if r.kind == 3 and r.addr == 0x8000000b]
        first = traps[0]
        # The line rises three instructions before the EBREAK; the two stepped instructions retire
        # and the interrupt is taken before the third.
        self.assertEqual([trace[first - 2].insn, trace[first - 1].insn], ISS.assemble([('csrrsi', 0, 'mstatus', 8), ('addi', 13, 0, 5)]))
        self.assertEqual(trace[first].insn, ISS.assemble([('addi', 14, 0, 6)])[0])

    def test_the_short_scenario_passes_and_the_checks_notice_changed_expectations(self):
        result = simulate_vectors(P, self.rows, PARAMETERS)
        self.assertEqual(result.returncode, 0, result.stdout[-600:])
        self.assertIn(f"COUNT halts={self.facts['halts']}", result.stdout)

        def changed(pick, column, value):
            rows = [list(r) for r in self.rows]
            index = next(i for i, r in enumerate(rows) if pick(r))
            rows[index][column] ^= value
            return label(simulate_vectors(P, rows, PARAMETERS))
        scan = lambda r, name, mode=0: r[0] == M.SCAN_DR and r[4] and r[5] == mode and r[7] == M.LABELS.index(name)
        self.assertEqual(changed(lambda r: scan(r, 'DBG_DPC'), 3, 4 << 2), ['DBG_DPC'])
        self.assertEqual(changed(lambda r: scan(r, 'DBG_DATA'), 3, 1 << 2), ['DBG_DATA'])
        self.assertEqual(changed(lambda r: scan(r, 'DBG_DTM'), 3, 1), ['DBG_DTM'])
        self.assertEqual(changed(lambda r: r[0] == M.POLL and r[7] == M.LABELS.index('DBG_CMDERR'), 3, 1 << 10), ['DBG_CMDERR'])
        self.assertEqual(changed(lambda r: r[0] == M.POLL and r[7] == M.LABELS.index('DBG_STATUS'), 3, 1 << 10 | 1 << 11), ['DBG_STATUS'])
        self.assertEqual(changed(lambda r: r[0] == M.FINAL and r[1] == 16, 2, 1), ['ISS_MEM'])

    def test_the_comparison_notices_each_piece_of_the_debug_logic_being_removed(self):
        edits = {
            'interrupt taken during a step': ('rv32i_core.sv', (" && !step_armed && !(mem_wfi", " && !(mem_wfi")),
            'the discarded access reaches the memory': ('rv32i_core.sv', ("!stopped && !dbg_enter &&", "!stopped &&")),
            'x0 is read from the register file': ('rv32i_core.sv', ("(dbg_regno[4:0] == 5'd0 ? 32'd0 : regs[dbg_regno[4:0]])", "regs[dbg_regno[4:0]]")),
            'dpc keeps its low bits': ('rv32i_core.sv', ("assign dbg_reg_rdata = dbg_gpr ?", "assign dbg_reg_rdata = dbg_regno == 16'h07b1 ? {dpc, 2'b11} : dbg_gpr ?")),
            'an EBREAK is reported as a step': ('rv32i_core.sv', ("step_pending ? 3'd4 : 3'd1;", "3'd4;")),
            'resume is never acknowledged': ('debug_module.sv', ("if (resuming && !halted) begin resumeack <= 1;", "if (resuming && !halted) begin")),
            'an error does not stay': ('debug_module.sv', ("accept && cmderr == 3'd0) begin\n                if (unsupported)", "accept) begin\n                if (unsupported)")),
            'a command runs although the hart runs': ('debug_module.sv', ("if (!halted) cmderr <= 3'd4;\n                    else begin", "begin")),
            'dtmcs reports another width': ('debug_dtm.sv', ("32'h00001071", "32'h00001061")),
            'a read request is taken for a write': ('debug_dtm.sv', ("dmi_op <= sr[1:0];", "dmi_op <= 2'd2;")),
        }
        expected = {'interrupt taken during a step': 'ISS_DATA', 'x0 is read from the register file': 'ISS_X', 'dpc keeps its low bits': 'DBG_DPC',
                    'an EBREAK is reported as a step': 'DBG_STATUS', 'resume is never acknowledged': 'DBG_STATUS',
                    'an error does not stay': None, 'a command runs although the hart runs': 'DBG_CMDERR',
                    'dtmcs reports another width': 'DBG_DTM', 'a read request is taken for a write': 'DBG_STATUS'}
        for name, (source, edit) in edits.items():
            with self.subTest(name):
                result = simulate_vectors(P, self.rows, PARAMETERS, {source: [edit]})
                self.assertNotEqual(result.returncode, 0, name)
                found = label(result)
                self.assertEqual(len(found), 1, result.stdout[-400:])
                if expected.get(name):
                    self.assertEqual(found, [expected[name]])


if __name__ == '__main__':
    unittest.main()

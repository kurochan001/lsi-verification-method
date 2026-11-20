from pathlib import Path
import random
import shutil
import sys
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'local-common'))
from system_test_support import SystemContract
from local_test_support import load_example, simulate_vectors

P = load_example('local-riscv-priv')
ISS = P.ISS
M, U = ISS.M, ISS.U
ICARUS = shutil.which('iverilog') and shutil.which('vvp')
PARAMETERS = P.CONFIGS['priv']
CORE = 'rv32i_core.sv'


def run(program, data=None):
    return ISS.execute(ISS.assemble(program), P.clean(data or ISS.directed_data()), traps=True, priv=True)


def traps(trace):
    return [(r.addr, r.data) for r in trace if r.kind == 3]


class ExampleTests(SystemContract, unittest.TestCase):
    EXAMPLE = 'local-riscv-priv'
    GOALS = 25

    def test_pmp_regions_follow_the_encodings_worked_out_by_hand(self):
        pmp = ISS.Protection()
        pmp.addr = [0x17, 0x27, 0x100, 0x3fff]
        pmp.cfg = [0x1b, 0x19, 0x00, 0x1c]
        # NAPOT: 0x17 = 0b10111 is base 0x10 words with three trailing ones, 64 bytes from 0x40.
        self.assertEqual([pmp.region(i) for i in range(4)], [(0x40, 0x80), (0x80, 0xc0), None, (0, 0x20000)])
        pmp.cfg[2] = 0x08 | 1   # top of range: from pmpaddr1 << 2 to pmpaddr2 << 2
        self.assertEqual(pmp.region(2), (0x9c, 0x400))
        pmp.cfg[2] = 0x10       # four bytes
        self.assertEqual(pmp.region(2), (0x400, 0x404))

    def test_lowest_entry_decides_and_must_cover_the_whole_access(self):
        pmp = ISS.Protection()
        pmp.addr, pmp.cfg = [0x17, 0x27, 0, 0x3fff], [0x1b, 0x19, 0, 0x1c]
        self.assertTrue(pmp.allows(0x40, 4, 0, U) and pmp.allows(0x7c, 4, 1, U))
        self.assertFalse(pmp.allows(0x40, 4, 2, U))                       # entry 0 has no X, although entry 3 has
        self.assertTrue(pmp.allows(0x80, 4, 0, U))
        self.assertFalse(pmp.allows(0x80, 4, 1, U))
        self.assertTrue(pmp.allows(0x100, 4, 2, U))
        self.assertFalse(pmp.allows(0x100, 4, 0, U))
        self.assertTrue(pmp.allows(0x100, 4, 0, M) and pmp.allows(0x80, 4, 1, M))  # nothing locked
        pmp.cfg = [0x10, 0, 0, 0x1f]                                      # four bytes at pmpaddr0, no permission
        pmp.addr[0] = 0x11                                                # 0x44..0x47
        self.assertFalse(pmp.allows(0x44, 4, 0, U))
        self.assertFalse(pmp.allows(0x46, 2, 0, U))
        self.assertTrue(pmp.allows(0x48, 4, 0, U))
        pmp.addr[0], pmp.cfg[0] = 0x11, 0x08 | 7                          # range 0..0x44, all permissions
        self.assertFalse(pmp.allows(0x42, 4, 0, U))                       # crosses the end of the range
        self.assertFalse(ISS.Protection().allows(0, 4, 0, U))             # no entry: user mode fails
        self.assertTrue(ISS.Protection().allows(0, 4, 0, M))

    def test_locked_entries_bind_machine_mode_and_keep_their_registers(self):
        pmp = ISS.Protection()
        pmp.write_addr(1, 0x30)
        self.assertFalse(pmp.write_cfg(0x00009000))                       # entry 1: locked, four bytes, no permission
        self.assertFalse(pmp.allows(0xc0, 4, 0, M))
        self.assertTrue(pmp.write_addr(1, 0x31))
        self.assertTrue(pmp.write_cfg(0))
        self.assertEqual((pmp.addr[1], pmp.read_cfg()), (0x30, 0x9000))
        self.assertFalse(pmp.write_cfg(0x9000))                           # the same value is not an ignored write
        top = ISS.Protection()
        top.write_cfg(0x8800)                                             # entry 1: locked, top of range
        self.assertTrue(top.write_addr(0, 5))                             # its bottom, pmpaddr0, is locked with it
        self.assertFalse(top.write_addr(2, 5))

    def test_write_without_read_is_stored_as_neither(self):
        pmp = ISS.Protection()
        pmp.write_cfg(0x1a | 0x60)                                        # W without R, and the two reserved bits
        self.assertEqual(pmp.read_cfg(), 0x18)

    def test_directed_program_reaches_every_goal_and_every_kind_of_trap(self):
        trace = run(P.directed_program())
        seen = 0
        for r in trace:
            seen |= r.more
        self.assertEqual(seen, (1 << len(ISS.PRIV_TAGS)) - 1)
        self.assertEqual({cause for cause, _ in traps(trace)},
                         {1, 2, 4, 5, 7, 8, 11, 0x80000003, 0x80000007, 0x8000000b})

    def test_user_mode_is_refused_what_the_specification_reserves(self):
        program = P.HANDLER + P.SETUP + P.to_user(1) + [
            ('csrrs', 3, 'mstatus', 0), ('mret',), ('lw', 3, P.EXECUTE_ONLY, 0), ('sw', 3, P.READ_ONLY, 0), ('ecall',),
            *P.TO_M, ('csrrs', 4, 'mstatus', 0), ('ebreak',)]
        trace = run(program)
        self.assertEqual(traps(trace), [(2, 0x300021f3), (2, ISS.MRET), (5, P.EXECUTE_ONLY), (7, P.READ_ONLY), (8, 0), (8, 0)])
        self.assertEqual(trace[-2].wdata & 0x1800, 0)                     # MRET left MPP = U
        handler_reads = [r.wdata for r in trace if r.insn >> 20 == 0x300 and r.rd == 19]
        self.assertTrue(all(value & 0x1800 == 0 for value in handler_reads))  # every trap came from user mode

    def test_interrupt_priority_and_vector(self):
        program = P.HANDLER + P.SETUP + [
            ('addi', 1, 0, ('abs', 'vtable')), ('ori', 1, 1, 1), ('csrrw', 0, 'mtvec', 1),
            ('csrrci', 0, 'mstatus', 8), *P.raise_lines(7), ('csrrsi', 0, 'mstatus', 8), ('addi', 3, 0, 1),
            *P.raise_lines(6), ('addi', 3, 0, 2), *P.raise_lines(2), ('ebreak',)]
        trace = run(program)
        labels = ISS.label_addresses(program)
        taken = [(r.addr & 0xf, trace[i + 1].pc - labels['vtable']) for i, r in enumerate(trace) if r.kind == 3]
        self.assertEqual(taken, [(11, 44), (3, 12), (7, 28)])

    def test_a_program_the_core_could_not_follow_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'never wake'):
            run(P.HANDLER + P.SETUP + [('wfi',), ('ebreak',)])
        with self.assertRaisesRegex(ValueError, 'armed timer'):
            run(P.HANDLER + P.SETUP + [('addi', 12, 0, 5), ('sw', 12, P.TIMER, 0), ('addi', 3, 0, 1), ('wfi',), ('ebreak',)])
        with self.assertRaisesRegex(ValueError, 'armed timer'):  # a line already pending would wake the core at once
            run(P.HANDLER + P.SETUP + [('csrrci', 0, 'mstatus', 8), *P.raise_lines(1), ('addi', 12, 0, 5),
                                       ('sw', 12, P.TIMER, 0), ('wfi',), ('ebreak',)])

    def test_random_programs_use_both_modes_and_all_three_lines(self):
        rng = random.Random(5)
        trace = run(P.random_program(rng, 600), ISS.random_data(rng))
        causes = {cause for cause, _ in traps(trace)}
        self.assertTrue({1, 5, 7, 8, 11, 0x80000003, 0x80000007, 0x8000000b} <= causes, causes)
        self.assertTrue(any(r.insn == ISS.WFI and r.kind == 0 for r in trace))

    def test_machine_mode_traps_are_unchanged_without_priv(self):
        # The traps example's CSR set: a PMP CSR is an illegal instruction there, WFI too.
        program = [('jal', 0, 'main'), 'handler:', ('csrrs', 21, 'mepc', 0), ('addi', 21, 21, 4), ('csrrw', 0, 'mepc', 21),
                   ('mret',), 'main:', ('addi', 1, 0, 4), ('csrrw', 0, 'mtvec', 1), ('csrrs', 3, 'pmpcfg0', 0), ('wfi',),
                   ('csrrs', 4, 'mstatus', 0), ('ebreak',)]
        trace = ISS.execute(ISS.assemble(program), [0] * ISS.DATA_WORDS, traps=True)
        self.assertEqual([cause for cause, _ in traps(trace)], [2, 2])
        self.assertEqual(trace[-2].wdata, 0x1880)                         # MPP reads as M, MPIE set by the MRETs

    @unittest.skipUnless(ICARUS, 'Icarus required')
    def test_the_comparison_notices_each_piece_of_the_core_being_removed(self):
        rows = P.boundary_vectors()
        edits = {
            'no refetch after a PMP write': ('if (pmp_flush) begin', "if (1'b0) begin"),
            'WFI does not wait': ('wire wfi_stall = PRIV != 0 &&', "wire wfi_stall = 1'b0 &&"),
            'interrupt taken on the waiting WFI': (' && !(mem_wfi && wfi_waited);', ';'),
            'MRET keeps MPRV': ('if (!st_mpp_m) st_mprv <= 0; end', 'end'),
            'user mode honours MIE': ('(st_mie || !priv_m || MUTATION == 14)', '(st_mie || MUTATION == 14)'),
            'TW ignored': ('(priv_m || !st_tw)', "1'b1"),
            'fetch not checked': ("wire if_fault = PRIV != 0 &&", "wire if_fault = 1'b0 &&"),
            'trap value of an access fault': ("mem_code != 4'd0 ? mem_tval : mem_result;", "mem_tval;"),
        }
        self.assertIn('RESULT PASS', simulate_vectors(P, rows, PARAMETERS).stdout)
        for name, edit in edits.items():
            with self.subTest(name):
                result = simulate_vectors(P, rows, PARAMETERS, {CORE: [edit]})
                self.assertIn('CHECK_FAIL ISS_', result.stdout, name)
                self.assertNotIn('RESULT PASS', result.stdout)

    @unittest.skipUnless(ICARUS, 'Icarus required')
    def test_default_configuration_ignores_the_added_instructions(self):
        # Without PRIV the core is the traps example's core: its own boundary vectors still pass.
        traps_example = load_example('local-riscv-traps')
        result = simulate_vectors(traps_example, traps_example.boundary_vectors(), traps_example.CONFIGS['traps'])
        self.assertIn('RESULT PASS', result.stdout)


if __name__ == '__main__':
    unittest.main()

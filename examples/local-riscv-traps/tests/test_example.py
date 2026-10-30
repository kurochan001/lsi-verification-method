from pathlib import Path
import random, sys, unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'local-common'))
from system_test_support import SystemContract
from local_test_support import load_example

P = load_example('local-riscv-traps')
ISS = P.ISS
MAIN = 4 * sum(not isinstance(x, str) for x in P.HANDLER + P.SETUP)  # first address after the setup


def run(program):  # the interrupt line starts low, as on the bench; a store to IRQ_ADDRESS raises it
    return ISS.execute(ISS.assemble(P.HANDLER + P.SETUP + program + [('ebreak',)]), [0] * ISS.DATA_WORDS, traps=True)


def traps(trace):
    return [(r.pc, r.addr, r.data) for r in trace if r.kind == 3]


class ExampleTests(SystemContract, unittest.TestCase):
    EXAMPLE = 'local-riscv-traps'
    GOALS = 10

    def test_iss_records_cause_epc_and_tval_of_each_exception(self):
        t = run([('ecall',), ('word', 0x02000033), ('lw', 5, 2, 10), ('sh', 4, 3, 10), ('addi', 6, 0, 1)])
        self.assertEqual(traps(t), [(MAIN, 11, 0), (MAIN + 4, 2, 0x02000033), (MAIN + 8, 4, ISS.BASE + 2),
                                    (MAIN + 12, 6, ISS.BASE + 3)])
        for i, r in enumerate(t):
            if r.kind == 3:
                self.assertEqual(t[i + 1].pc, 4)  # mtvec
                self.assertEqual(t[i + 2].wdata, r.pc)  # the handler reads mepc
        self.assertFalse(any(r.rd == 5 for r in t))  # the faulting load writes nothing
        self.assertEqual(t[-2].wdata, 1)

    def test_csr_fields_keep_only_what_the_core_implements(self):
        m = ISS.Machine()
        for address in (0x300, 0x304, 0x305, 0x340, 0x341, 0x344):
            m.write(address, 0xffffffff)
        self.assertEqual([m.read(a, 0) for a in (0x300, 0x304, 0x305, 0x340, 0x341, 0x344)],
                         [0x1888, 0x800, 0xfffffffc, 0xffffffff, 0xfffffffc, 0])
        self.assertEqual(m.read(0x344, 1), 0x800)
        self.assertEqual(m.enter(0x40, 11, 0), 0xfffffffc)
        self.assertEqual(m.read(0x300, 0), 0x1880)  # MIE moved to MPIE
        t = run([('csrrwi', 7, 'mscratch', 5), ('csrrs', 8, 'mscratch', 0), ('csrrci', 9, 'mscratch', 3),
                 ('csrrs', 11, 'mscratch', 0), ('csrrs', 12, 'mstatus', 0)])
        values = {r.rd: r.wdata for r in t if r.rd}
        self.assertEqual([values.get(r, 0) for r in (7, 8, 9, 11, 12)], [0, 5, 5, 4, 0x1808])  # MPP reads 3, MIE set by the setup

    def test_interrupt_is_taken_before_the_next_instruction(self):
        t = run([('addi', 11, 0, 1), ('sw', 11, P.IRQ_ADDRESS, 0), ('addi', 12, 0, 2), ('addi', 13, 0, 3)])
        self.assertEqual(traps(t), [(MAIN + 8, 0x8000000b, 0)])  # right after the store that raises the line
        self.assertEqual([r.pc for r in t if r.pc == MAIN + 8], [MAIN + 8, MAIN + 8])  # trapped, then executed
        t = run([('csrrci', 0, 'mstatus', 8), ('addi', 11, 0, 1), ('sw', 11, P.IRQ_ADDRESS, 0), ('addi', 12, 0, 2),
                 ('csrrsi', 0, 'mstatus', 8), ('addi', 13, 0, 3)])
        self.assertEqual(traps(t), [(MAIN + 20, 0x8000000b, 0)])  # held while MIE is 0, taken after CSRRSI

    def test_illegal_words_follow_the_decoder_table(self):
        for word in P.ILLEGAL:
            self.assertFalse(ISS.legal_rv32i(word), hex(word))
        words = ISS.assemble(P.directed_program())
        for item, word in zip((x for x in P.directed_program() if not isinstance(x, str)), words):
            if item[0] not in ('word', 'mret') and not item[0].startswith('csr'):
                self.assertTrue(ISS.legal_rv32i(word), item)

    def test_fixed_program_reaches_every_trap_and_interrupt_point(self):
        rows = P.boundary_vectors()
        tags = [r[8] for r in rows if r[0] == 3]
        for i, name in enumerate(P.TRAP_TAGS):
            self.assertTrue(any(t >> (20 + i) & 1 for t in tags), name)
        t = ISS.execute(ISS.assemble(P.directed_program()), ISS.directed_data(), traps=True)
        interrupted = [r.insn for r in t if r.kind == 3 and r.addr >> 31]
        self.assertEqual(interrupted, ISS.assemble([('addi', 12, 0, 2), ('addi', 15, 0, 5)]))
        self.assertEqual(len(traps(t)), 12)

    def test_random_events_never_read_an_unwritten_register_or_split_a_jump(self):
        for seed in (17, 18, 19):
            rng = random.Random(seed)
            program, data = P.random_program(rng, 300), ISS.random_data(rng)
            data[ISS.IRQ_WORD] = 0
            written = {0}
            for r in ISS.execute(ISS.assemble(program), data, traps=True):
                reads = {r.insn >> 15 & 31} if r.insn & 0x707f in {0x1073, 0x2073, 0x3073} else ISS.sources(r.insn)
                self.assertLessEqual(reads, written, hex(r.pc))
                written.add(r.rd)
            self.assertTrue({x[0] for x in program if isinstance(x, tuple)} >= {'ecall', 'word', 'csrrw', 'csrrs'})
            for i, item in enumerate(program):
                if isinstance(item, str) and item.startswith('B'):  # B label, AUIPC, at most one ADDI, JALR
                    end = next(j for j in range(i, len(program)) if isinstance(program[j], tuple) and program[j][0] == 'jalr')
                    self.assertEqual(program[i + 1][0], 'auipc')
                    self.assertIn([x[0] for x in program[i + 2:end]], ([], ['addi']))


if __name__ == '__main__':
    unittest.main()

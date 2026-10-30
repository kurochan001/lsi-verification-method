from pathlib import Path
import random, shutil, subprocess, sys, tempfile, unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'local-common'))
from system_test_support import SystemContract
from local_test_support import load_example

P = load_example('local-riscv-iss')
ISS = P.ISS
LLVM = Path('/opt/homebrew/opt/llvm/bin')
MC = shutil.which('llvm-mc') or (str(LLVM / 'llvm-mc') if (LLVM / 'llvm-mc').exists() else None)
OBJCOPY = shutil.which('llvm-objcopy') or (str(LLVM / 'llvm-objcopy') if (LLVM / 'llvm-objcopy').exists() else None)


def text(program):
    """The same program in assembler syntax, with JALR displacements written as numbers."""
    labels, lines = ISS.label_addresses(program), []
    for item in program:
        if isinstance(item, str):
            lines.append(item)
            continue
        name, *args = item
        fmt = ISS.OPS[name][0]
        if name in ('lw', 'sw', 'jalr'):
            imm = args[1]
            if isinstance(imm, tuple):
                imm = labels[imm[1]] - (labels[imm[2]] if imm[0] == 'off' else 0)
            lines.append(f'{name} x{args[0]}, {imm}(x{args[2]})')
        elif fmt == 'E':
            lines.append(name)
        elif fmt in 'UJ':
            lines.append(f'{name} x{args[0]}, {args[1]}')
        elif fmt == 'B':
            lines.append(f'{name} x{args[0]}, x{args[1]}, {args[2]}')
        else:
            lines.append(f"{name} x{args[0]}, x{args[1]}, {args[2] if fmt == 'I' else 'x' + str(args[2])}")
    return '\n'.join(lines) + '\n'


def llvm_words(program):
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        (tmp / 'p.s').write_text(text(program))
        subprocess.run([MC, '-triple=riscv32', '-mattr=-relax,-c', '-filetype=obj', '-o', str(tmp / 'p.o'), str(tmp / 'p.s')],
                       check=True, capture_output=True, timeout=60)
        subprocess.run([OBJCOPY, '-O', 'binary', '--only-section=.text', str(tmp / 'p.o'), str(tmp / 'p.bin')],
                       check=True, capture_output=True, timeout=60)
        data = (tmp / 'p.bin').read_bytes()
    return [int.from_bytes(data[i:i + 4], 'little') for i in range(0, len(data), 4)]


def registers(trace):
    regs = [0] * 32
    for r in trace:
        if r.rd:
            regs[r.rd] = r.wdata
    return regs


class ExampleTests(SystemContract, unittest.TestCase):
    EXAMPLE = 'local-riscv-iss'
    GOALS = 16

    @unittest.skipUnless(MC and OBJCOPY, 'llvm-mc and llvm-objcopy required')
    def test_assembler_matches_llvm_for_the_directed_and_random_programs(self):
        programs = [ISS.directed_program()] + [ISS.random_program(random.Random(s), 300) for s in (17, 18)]
        for program in programs:
            self.assertEqual(ISS.assemble(program), llvm_words(program))

    def test_iss_results_for_hand_computed_cases(self):
        trace = ISS.execute(ISS.assemble([
            ('lui', 1, 0x80000), ('srai', 2, 1, 31), ('srli', 3, 1, 31), ('sltiu', 4, 0, -1), ('slti', 5, 1, 0),
            ('addi', 6, 0, -2048), ('sub', 7, 0, 1), ('sll', 8, 3, 2), ('jal', 9, 'x'), ('addi', 10, 0, 1), 'x:',
            ('auipc', 11, 1), ('ebreak',)]), [0] * ISS.DATA_WORDS)
        regs = registers(trace)
        self.assertEqual(regs[1:10], [0x80000000, 0xffffffff, 1, 1, 1, 0xfffff800, 0x80000000, 0x80000000, 36])
        self.assertEqual((regs[10], regs[11]), (0, 40 + 0x1000))
        self.assertEqual(len(trace), 11)

    def test_writes_to_x0_are_dropped_and_jalr_clears_bit_zero(self):
        trace = ISS.execute(ISS.assemble([
            ('addi', 0, 0, 5), ('add', 1, 0, 0), 'h:', ('auipc', 2, 0), ('addi', 2, 2, 1),
            ('jalr', 3, ('off', 't', 'h'), 2), ('addi', 4, 0, 9), 't:', ('ebreak',)]), [0] * ISS.DATA_WORDS)
        self.assertEqual([(r.rd, r.wdata) for r in trace[:2]], [(0, 0), (1, 0)])
        self.assertEqual(trace[-1].pc, 24)
        self.assertNotIn(20, [r.pc for r in trace])

    def test_fixed_program_has_every_instruction_and_the_wait_forwarding_pattern(self):
        rows = P.boundary_vectors()
        retired = [r for r in rows if r[0] == 3]
        self.assertEqual({r[9] for r in retired}, set(range(len(ISS.NAMES))))
        bit = 1 << P.TAGS.index('mem/wait-forwarding')
        self.assertGreaterEqual(sum(bool(r[8] & bit) for r in retired), 2)

    def test_without_wait_states_mutation4_survives(self):
        if not (shutil.which('iverilog') and shutil.which('vvp')):
            self.skipTest('Icarus required')
        rows = P.vectors(ISS.directed_program(), ISS.directed_data(), lambda access, trace, i: 0)
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            (tmp / 'v.txt').write_text(''.join(' '.join(format(x, 'x') for x in r) + '\n' for r in rows))
            for mutation, verdict in ((4, 'RESULT PASS'), (2, 'CHECK_FAIL')):
                subprocess.run(['iverilog', '-g2012', '-s', 'core_tb', f'-Pcore_tb.MUTATION={mutation}', '-o',
                                str(tmp / 's.vvp'), *map(str, P.SOURCES)], check=True, capture_output=True, timeout=60)
                out = subprocess.run(['vvp', str(tmp / 's.vvp'), f"+VECTORS={tmp / 'v.txt'}", f"+WAVE={tmp / 'w.vcd'}"],
                                     capture_output=True, text=True, timeout=60).stdout
                self.assertIn(verdict, out)


if __name__ == '__main__':
    unittest.main()

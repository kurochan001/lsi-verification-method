import hashlib, importlib.util, json, random, re, shutil, subprocess, sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'local-common'))
from local_test_support import load_example

P = load_example('local-riscv-decoder')
G = P.G
HERE = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('rv32i_iss', HERE.parent / 'local-riscv-iss/iss.py')
ISS = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ISS)
LLVM = Path('/opt/homebrew/opt/llvm/bin')
MC = shutil.which('llvm-mc') or (str(LLVM / 'llvm-mc') if (LLVM / 'llvm-mc').exists() else None)
OBJCOPY = shutil.which('llvm-objcopy') or (str(LLVM / 'llvm-objcopy') if (LLVM / 'llvm-objcopy').exists() else None)
ICARUS = shutil.which('iverilog') and shutil.which('vvp')
COUNTEREXAMPLES = {1: 0x02405013, 2: 0x4135000f, 3: 0x20044033, 4: 0x80006063}


def sext(value, bits):
    return value - (1 << bits) if value >> (bits - 1) & 1 else value


IMMEDIATE = {  # written from the immediate figure of the base ISA, apart from the generator
    'I': lambda w: sext(w >> 20, 12),
    'S': lambda w: sext((w >> 25) << 5 | (w >> 7) & 31, 12),
    'B': lambda w: sext((w >> 31) << 12 | (w >> 7 & 1) << 11 | (w >> 25 & 63) << 5 | (w >> 8 & 15) << 1, 13),
    'U': lambda w: w & 0xfffff000,
    'J': lambda w: sext((w >> 31) << 20 | (w >> 12 & 255) << 12 | (w >> 20 & 1) << 11 | (w >> 21 & 1023) << 1, 21),
    'SHIFT': lambda w: w >> 20 & 31, 'R': lambda w: 0, 'NONE': lambda w: 0}


def expected(entries, word):
    found = G.decode(entries, word)
    if found is None:
        return '0'
    index, form, regs = found
    return f"1 {index} {IMMEDIATE[form](word) & 0xffffffff:08x} {''.join(str(int(r)) for r in regs)}"


def simulate(mutation, words):
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        (tmp / 'w.txt').write_text(''.join(f'{w:08x}\n' for w in words))
        subprocess.run(['iverilog', '-g2012', '-s', 'decoder_tb', f'-Pdecoder_tb.MUTATION={mutation}', '-o', str(tmp / 's.vvp'),
                        str(HERE / 'rtl/rv32i_decoder.sv'), str(HERE / 'tb/decoder_tb.sv')], check=True, capture_output=True, timeout=60)
        lines = subprocess.run(['vvp', str(tmp / 's.vvp'), f"+WORDS={tmp / 'w.txt'}"], capture_output=True, text=True,
                               timeout=300).stdout.splitlines()
    rows = [line.split() for line in lines]
    return ['0' if r[1] == '0' else f'1 {r[2]} {r[3]} {r[4]}' for r in rows if len(r) == 5 and len(r[0]) == 8]


def iss_words():
    words = ISS.assemble(ISS.directed_program())
    for seed in (17, 18, 19):
        words += ISS.assemble(ISS.random_program(random.Random(seed), 2000))
    return words


class PlanTest(unittest.TestCase):
    def test_plan_has_a_proof_a_cover_and_four_counterexamples(self):
        plan = P.plan(P.BOUND, 0)
        self.assertEqual([c['id'] for c in plan], ['decoder-proof', 'scenario-cover'] + [f'detect-mutation{m}' for m in range(1, 5)])
        self.assertEqual(plan[0]['depth'], 1)
        self.assertEqual([c['failure'] for c in plan[2:]], ['ap_legal', 'ap_legal', 'ap_legal', 'ap_imm'])
        self.assertEqual(P.plan(P.BOUND, 2)[0]['parameters'], {'MUTATION': 2})

    def test_properties_match_the_harness(self):
        labels = set(re.findall(r'\b((?:ap|cp)_\w+):', (HERE / 'decoder_formal.sv').read_text()))
        self.assertEqual(labels, P.ASSERTS | P.COVERS)
        self.assertTrue(P.prepare({}, P.plan(P.BOUND, 1)[2]).endswith('chparam -set MUTATION 1 decoder_formal\n'))


class TableTest(unittest.TestCase):
    def test_upstream_files_are_the_recorded_copies(self):
        record = json.loads((HERE / 'upstream.json').read_text())
        for name, item in record['files'].items():
            self.assertEqual(hashlib.sha256((HERE / name).read_bytes()).hexdigest(), item['sha256'], name)

    def test_table_has_the_forty_rv32i_instructions_in_the_decoder_order(self):
        names = [e['name'] for e in G.table()]
        self.assertEqual(len(names), 40)
        rtl = (HERE / 'rtl/rv32i_decoder.sv').read_text()
        numbered = dict((int(n), name.lower()) for name, n in re.findall(r'\b([A-Z]+) = (\d+)', rtl))
        self.assertEqual([numbered[i] for i in range(40)], names)

    def test_committed_specification_is_generated_from_the_table(self):
        self.assertEqual(G.SPEC.read_text(), G.render())

    def test_generator_rejects_overlaps_gaps_and_unknown_operands(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'rv_i'
            path.write_text('a rd rs1 imm12 14..12=0 6..2=0x04 1..0=3\nb rd rs1 imm12 14..12=0 6..2=0x04 1..0=3\n')
            with self.assertRaisesRegex(G.TableError, 'share encodings'):
                G.table([path])
        with self.assertRaisesRegex(G.TableError, 'cover the word'):
            G.parse_line('c rd rs1 14..12=0 6..2=0x04 1..0=3'.split())
        with self.assertRaisesRegex(G.TableError, 'unknown operand'):
            G.parse_line('d rd rs1 csr 14..12=1 6..2=0x1C 1..0=3'.split())

    @unittest.skipUnless(MC and OBJCOPY, 'llvm-mc and llvm-objcopy required')
    def test_llvm_encodings_decode_to_the_same_instructions(self):
        program = ['lui x1, 0x80000', 'auipc x2, 1', 'jal x1, 2048', 'jalr x2, -1(x3)', 'beq x1, x2, -4096',
                   'bne x1, x2, 2', 'blt x1, x2, 4094', 'bge x1, x2, 8', 'bltu x1, x2, 16', 'bgeu x1, x2, -2',
                   'lb x1, -2048(x2)', 'lh x1, 2047(x2)', 'lw x1, 0(x2)', 'lbu x1, 1(x2)', 'lhu x1, 2(x2)',
                   'sb x1, -1(x2)', 'sh x1, 2047(x2)', 'sw x1, -2048(x2)', 'addi x1, x2, -1', 'slti x1, x2, 5',
                   'sltiu x1, x2, -1', 'xori x1, x2, 0x555', 'ori x1, x2, 1', 'andi x1, x2, 0x7ff', 'add x1, x2, x3',
                   'sub x1, x2, x3', 'sll x1, x2, x3', 'slt x1, x2, x3', 'sltu x1, x2, x3', 'xor x1, x2, x3',
                   'srl x1, x2, x3', 'sra x1, x2, x3', 'or x1, x2, x3', 'and x1, x2, x3', 'fence rw, rw', 'ecall',
                   'ebreak', 'slli x1, x2, 31', 'srli x1, x2, 1', 'srai x1, x2, 31', 'fence.tso', 'pause']
        names = [line.split()[0] for line in program[:-2]] + ['fence', 'fence']
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            (tmp / 'p.s').write_text('\n'.join(program) + '\n')
            subprocess.run([MC, '-triple=riscv32', '-mattr=-relax,-c,+zihintpause', '-filetype=obj', '-o', str(tmp / 'p.o'),
                            str(tmp / 'p.s')], check=True, capture_output=True, timeout=60)
            subprocess.run([OBJCOPY, '-O', 'binary', '--only-section=.text', str(tmp / 'p.o'), str(tmp / 'p.bin')],
                           check=True, capture_output=True, timeout=60)
            data = (tmp / 'p.bin').read_bytes()
        words = [int.from_bytes(data[i:i + 4], 'little') for i in range(0, len(data), 4)]
        entries = G.table()
        self.assertEqual([entries[G.decode(entries, w)[0]]['name'] for w in words], names)


@unittest.skipUnless(ICARUS, 'Icarus required')
class SimulationTest(unittest.TestCase):
    def test_decoder_agrees_with_the_table_and_each_mutant_shows_on_its_counterexample(self):
        entries = G.table()
        rng = random.Random(5)
        words = [e['match'] | (rng.getrandbits(32) & ~e['mask']) for e in entries for _ in range(50)]
        words += [rng.getrandbits(32) for _ in range(20000)] + list(COUNTEREXAMPLES.values())
        want = [expected(entries, w) for w in words]
        self.assertEqual(simulate(0, words), want)
        for mutation, word in COUNTEREXAMPLES.items():
            with self.subTest(mutation=mutation):
                self.assertNotEqual(simulate(mutation, [word]), [expected(entries, word)])

    def test_instruction_streams_from_the_iss_example_hide_every_mutant(self):
        entries = G.table()
        words = iss_words()
        want = [expected(entries, w) for w in words]
        for mutation in range(5):
            with self.subTest(mutation=mutation):
                self.assertEqual(simulate(mutation, words), want)


if __name__ == '__main__':
    unittest.main()

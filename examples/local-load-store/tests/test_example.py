from pathlib import Path
import random, shutil, subprocess, sys, tempfile, unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'local-common'))
from system_test_support import SystemContract
from local_test_support import load_example

P = load_example('local-load-store')
ISS = P.ISS
LLVM = Path('/opt/homebrew/opt/llvm/bin')
MC = shutil.which('llvm-mc') or (str(LLVM / 'llvm-mc') if (LLVM / 'llvm-mc').exists() else None)
OBJCOPY = shutil.which('llvm-objcopy') or (str(LLVM / 'llvm-objcopy') if (LLVM / 'llvm-objcopy').exists() else None)


def run(program):
    return ISS.execute(ISS.assemble([('addi', 10, 0, ISS.BASE)] + program + [('ebreak',)]), [0] * ISS.DATA_WORDS)


class ExampleTests(SystemContract, unittest.TestCase):
    EXAMPLE = 'local-load-store'
    GOALS = 11

    def test_iss_extends_and_merges_sub_words_as_the_isa_defines(self):
        t = run([('lui', 1, 0xfedcc), ('addi', 1, 1, -0x568), ('sw', 1, 0, 10),       # 0xfedcba98
                 ('lb', 2, 0, 10), ('lbu', 3, 0, 10), ('lh', 4, 2, 10), ('lhu', 5, 2, 10), ('lb', 6, 3, 10),
                 ('addi', 7, 0, 0x55), ('sb', 7, 1, 10), ('sh', 7, 2, 10), ('lw', 8, 0, 10)])
        values = {r.rd: r.wdata for r in t if r.rd}
        self.assertEqual([values[r] for r in (2, 3, 4, 5, 6)], [0xffffff98, 0x98, 0xfffffedc, 0xfedc, 0xfffffffe])
        self.assertEqual(values[8], 0x00555598)
        self.assertEqual([r.data for r in t if r.kind == 2][1:], [0x55, 0x55])

    def test_iss_rejects_unaligned_accesses(self):
        for item in (('lh', 2, 1, 10), ('lw', 2, 2, 10), ('sh', 0, 3, 10), ('sw', 0, 6, 10)):
            with self.subTest(item=item), self.assertRaises(ValueError):
                run([item])
        run([('lb', 2, 3, 10), ('sb', 0, 1, 10), ('lhu', 2, 2, 10)])

    def test_generator_adds_sub_words_only_when_asked(self):
        plain = ISS.random_program(random.Random(17), 300)
        mixed = ISS.random_program(random.Random(17), 300, subword=True)
        names = lambda program: {x[0] for x in program if isinstance(x, tuple)}
        self.assertFalse(names(plain) & P.SUBWORD)
        self.assertEqual(names(mixed) & P.SUBWORD, P.SUBWORD)

    @unittest.skipUnless(MC and OBJCOPY, 'llvm-mc and llvm-objcopy required')
    def test_sub_word_encodings_match_llvm(self):
        program = [('lb', 1, -1, 2), ('lh', 3, 2046, 4), ('lbu', 5, 0, 6), ('lhu', 7, -2048, 8),
                   ('sb', 9, 1, 10), ('sh', 11, -2, 12)]
        text = ''.join(f'{n} x{a}, {i}(x{b})\n' for n, a, i, b in program)
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            (tmp / 'p.s').write_text(text)
            subprocess.run([MC, '-triple=riscv32', '-mattr=-relax,-c', '-filetype=obj', '-o', str(tmp / 'p.o'), str(tmp / 'p.s')],
                           check=True, capture_output=True, timeout=60)
            subprocess.run([OBJCOPY, '-O', 'binary', '--only-section=.text', str(tmp / 'p.o'), str(tmp / 'p.bin')],
                           check=True, capture_output=True, timeout=60)
            data = (tmp / 'p.bin').read_bytes()
        self.assertEqual(ISS.assemble(program), [int.from_bytes(data[i:i + 4], 'little') for i in range(0, len(data), 4)])

    def test_fixed_program_reaches_every_lane_and_sign(self):
        rows = P.boundary_vectors()
        tags = [r[8] for r in rows if r[0] == 3]
        for i, name in enumerate(P.LSU_TAGS):
            self.assertTrue(any(t >> (15 + i) & 1 for t in tags), name)
        self.assertEqual({r[9] for r in rows if r[0] == 3}, set(range(len(ISS.LOAD_STORE))))


if __name__ == '__main__':
    unittest.main()

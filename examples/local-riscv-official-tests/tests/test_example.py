"""Self-tests that need no downloaded sources: the linker, the setup script, the judgement and the bench."""
import hashlib
import io
import json
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tarfile
import tempfile
from types import SimpleNamespace
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'local-common'))
from local_test_support import EXAMPLES, load_example

P = load_example('local-riscv-official-tests')
SETUP = P.load('official_setup', P.HERE / 'setup_riscv_tests.py')
MC = P.tool('llvm-mc', 'llvm-mc')
CLANG = P.tool('clang', 'clang')
ICARUS = shutil.which('iverilog') and shutil.which('vvp')
# A program written for these tests, in the shape the test environment gives every test.
PROGRAM = '''
#include "riscv_test.h"
RVTEST_RV32U
RVTEST_CODE_BEGIN
  li TESTNUM, 2
  la x1, value
  lw x2, 0(x1)
  li x5, 0x1234
  bne x2, x5, fail
  li TESTNUM, 3
  sw x5, 4(x1)
  lw x4, 4(x1)
  bne x4, x5, fail
  j pass
fail: RVTEST_FAIL
pass: RVTEST_PASS
RVTEST_CODE_END
  .data
RVTEST_DATA_BEGIN
value: .word 0x1234, 0
RVTEST_DATA_END
'''


def assemble(text, directory, preprocess=False, name='t'):
    source = directory / f'{name}.s'
    if preprocess:
        (directory / f'{name}.S').write_text(text)
        done = subprocess.run([CLANG, '-E', '-P', '-x', 'assembler-with-cpp', f'-I{P.ENV}', '-o', str(source), str(directory / f'{name}.S')],
                              capture_output=True, text=True)
        assert done.returncode == 0, done.stderr
    else:
        source.write_text(text)
    done = subprocess.run([MC, '-triple=riscv32', '-mattr=-relax,-c', '-filetype=obj', '-o', str(directory / f'{name}.o'), str(source)],
                          capture_output=True, text=True)
    assert done.returncode == 0, done.stderr
    return (directory / f'{name}.o').read_bytes()


def archive(top, files):
    data = io.BytesIO()
    with tarfile.open(fileobj=data, mode='w:gz') as tar:
        for name, body in files.items():
            info = tarfile.TarInfo(f'{top}/{name}')
            info.size = len(body)
            tar.addfile(info, io.BytesIO(body))
    return data.getvalue()


def fake_pins(first, second):
    return dict(sources={'riscv-tests': dict(url='https://example.invalid/a.tar.gz', commit='a' * 40, directory='riscv-tests',
                                              sha256=hashlib.sha256(first).hexdigest()),
                         'riscv-test-env': dict(url='https://example.invalid/b.tar.gz', commit='b' * 40, directory='riscv-tests/env',
                                                sha256=hashlib.sha256(second).hexdigest())})


class LinkTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(MC and CLANG, 'llvm-mc and clang are required')
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_sections_are_placed_and_pc_relative_pairs_resolved(self):
        obj = assemble('.section .text.init\n_start: la x1, value\n lw x2, 0(x1)\n sw x2, value, x3\n ebreak\n'
                       '.section .tohost,"aw",@progbits\n.globl tohost\ntohost: .word 0, 0\n.data\nvalue: .word 7\n', self.dir)
        image, symbols, counts = P.LINK.link(obj)
        self.assertEqual((symbols['_start'], symbols['tohost'], symbols['value']), (0, 0x1000, 0x2000))
        self.assertEqual(counts, {'R_RISCV_PCREL_HI20': 2, 'R_RISCV_PCREL_LO12_I': 1, 'R_RISCV_PCREL_LO12_S': 1})
        words = P.LINK.words(image)
        # auipc x1, 2 ; addi x1, x1, 0 ; lw ; auipc x3, 2 ; sw x2, -12(x3)
        self.assertEqual(words[0], 0x00002097)
        self.assertEqual(words[1], 0x00008093)
        self.assertEqual(words[3], 0x00002197)
        self.assertEqual(words[4] & 0xfe000f80, ((-12 >> 5 & 0x7f) << 25 | (-12 & 31) << 7) & 0xffffffff)
        self.assertEqual(words[0x2000 >> 2], 7)
        self.assertEqual(len(image), 0x2004)

    def test_cross_section_jump_absolute_word_and_weak_symbol(self):
        obj = assemble('.section .text.init\n.weak handler\n_start: j far\n la x5, handler\n.text\nfar: ebreak\n'
                       '.data\npointer: .word far\n', self.dir)
        image, symbols, counts = P.LINK.link(obj)
        words = P.LINK.words(image)
        self.assertEqual(symbols['far'], 0x1000)
        self.assertEqual(words[0], 0x0000106f)                      # jal x0, +0x1000
        self.assertEqual(words[symbols['pointer'] >> 2], 0x1000)
        self.assertEqual(counts['R_RISCV_JAL'], 1)
        self.assertEqual(counts['R_RISCV_32'], 1)
        # the undefined weak symbol is address 0: auipc at 4 with distance -4
        self.assertEqual((words[1] >> 12, words[2] >> 20), (0, 0xffc))

    def test_what_the_linker_does_not_handle_is_an_error(self):
        cases = {
            'undefined symbol': '.section .text.init\n_start: la x1, nowhere\n',
            'section not handled': '.section .text.init\n_start: nop\n.section .rodata\n.word 1\n',
            'relocation types not handled': '.section .text.init\n_start: nop\n.data\nhere: .word here - _start\n',
            '.text.init must exist': '.text\n_start: nop\n',
        }
        for message, text in cases.items():
            with self.subTest(message=message), self.assertRaisesRegex(P.LINK.LinkError, message):
                P.LINK.link(assemble(text, self.dir))
        big = assemble('.section .text.init\n_start: nop\n.data\n.zero 70000\n', self.dir)
        with self.assertRaisesRegex(P.LINK.LinkError, 'exceeds the memory'):
            P.LINK.link(big)
        for junk in (b'', b'\x7fELF' + bytes(60), b'not an object'):
            with self.assertRaises((P.LINK.LinkError, struct.error)):
                P.LINK.link(junk)
        with self.assertRaisesRegex(P.LINK.LinkError, 'unknown fault'):
            P.LINK.link(big, fault='other')

    def test_injected_linker_fault_changes_only_the_low_parts(self):
        obj = assemble('.section .text.init\n_start: la x1, value\n ebreak\n.data\nvalue: .word 7\n', self.dir)
        good, bad = (P.LINK.words(P.LINK.link(obj, fault=f)[0]) for f in (None, 'lo12-off-by-four'))
        self.assertEqual([i for i, (a, b) in enumerate(zip(good, bad)) if a != b], [1])
        self.assertEqual((bad[1] >> 20) - (good[1] >> 20), 4)


class EnvironmentTests(unittest.TestCase):
    """The environment header of this example, with a program written here."""

    def setUp(self):
        self.assertTrue(MC and CLANG and ICARUS, 'llvm-mc, clang and Icarus Verilog are required')
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.args = SimpleNamespace(iverilog='iverilog', vvp='vvp', timeout=30)

    def tearDown(self):
        self.tmp.cleanup()

    def image(self, text=PROGRAM):
        image, symbols, _ = P.LINK.link(assemble(text, self.dir, preprocess=True))
        words = P.LINK.words(image)
        (self.dir / 'image.hex').write_text(''.join(f'{w:08x}\n' for w in words))
        return words, symbols

    def test_pass_and_fail_reach_tohost_on_the_iss_and_on_every_core_configuration(self):
        words, symbols = self.image()
        failing = list(words)
        failing[symbols['value'] >> 2] = 0x1235
        (self.dir / 'failing.hex').write_text(''.join(f'{w:08x}\n' for w in failing))
        for mode in ('traps', 'priv'):
            self.assertEqual((P.run_iss(words, symbols['tohost'], mode)['tohost'], P.run_iss(failing, symbols['tohost'], mode)['tohost']), (1, 5))
        for name, parameters in P.CONFIGS.items():
            with self.subTest(configuration=name):
                bench = P.compile_bench(self.args, self.dir, name, parameters)
                core = P.run_core(self.args, bench, self.dir / 'image.hex', symbols['tohost'], self.dir, name)
                self.assertEqual(P.judge(core, P.run_iss(words, symbols['tohost'], parameters['iss'])), 'pass')
                core = P.run_core(self.args, bench, self.dir / 'failing.hex', symbols['tohost'], self.dir, name + '-failing')
                self.assertEqual(P.judge(core, P.run_iss(failing, symbols['tohost'], parameters['iss'])), 'self-check:0x5')

    def test_unexpected_trap_endless_loop_and_missing_store_are_not_a_pass(self):
        bench = P.compile_bench(self.args, self.dir, 'traps', P.CONFIGS['traps'])
        cases = {
            # an illegal instruction: the handler marks tohost
            'self-check:0x402': PROGRAM.replace('la x1, value', '.word 0xffffffff\n  la x1, value'),
            # never ends
            'timeout': PROGRAM.replace('j pass', '1: j 1b'),
            # halts without the store to tohost
            'bench:OT_TOHOST_WRITES': PROGRAM.replace('j pass', 'ebreak'),
        }
        old, P.CYCLES = P.CYCLES, 3000
        try:
            for verdict, text in cases.items():
                with self.subTest(verdict=verdict):
                    words, symbols = self.image(text)
                    core = P.run_core(self.args, bench, self.dir / 'image.hex', symbols['tohost'], self.dir, 'case')
                    iss = dict(error=None, rows=[]) if verdict != 'self-check:0x402' else P.run_iss(words, symbols['tohost'], 'traps')
                    self.assertEqual(P.judge(core, iss), verdict)
        finally:
            P.CYCLES = old

    def test_a_trace_that_differs_from_the_iss_is_not_a_pass(self):
        words, symbols = self.image()
        bench = P.compile_bench(self.args, self.dir, 'traps', P.CONFIGS['traps'])
        core = P.run_core(self.args, bench, self.dir / 'image.hex', symbols['tohost'], self.dir, 'run')
        iss = P.run_iss(words, symbols['tohost'], 'traps')
        self.assertEqual(P.judge(core, iss), 'pass')
        self.assertEqual(P.judge(core, dict(iss, rows=iss['rows'][:-1])), 'trace')
        changed = list(iss['rows'])
        changed[5] = changed[5][:3] + (changed[5][3] ^ 1,) + changed[5][4:]
        self.assertEqual(P.judge(core, dict(iss, rows=changed)), 'trace')
        self.assertEqual(P.judge(core, dict(iss, error='stopped')), 'trace')
        self.assertEqual(P.judge(dict(core, status='error'), iss), 'error')

    def test_the_iss_wrapper_reports_what_it_cannot_run(self):
        # FENCE is one reason the upstream pass and fail macros are not used: the shared ISS rejects it.
        result = P.run_iss([0x0ff0000f, 0x00100073], 0x1000, 'traps')
        self.assertIsNone(result['tohost'])
        self.assertIn('unsupported instruction', result['error'])
        self.assertIn('did not reach EBREAK', P.run_iss([0x0000006f], 0x1000, 'traps')['error'])


class JudgementTests(unittest.TestCase):
    def test_mutation_classes(self):
        self.assertEqual(P.classify(dict(a='pass', b='pass')), 'invisible')
        self.assertEqual(P.classify(dict(a='pass', b='trace')), 'trace-only')
        for outcome in ('self-check:0x5', 'timeout', 'bench:OT_X'):
            self.assertEqual(P.classify(dict(a='trace', b=outcome)), 'self-check')
        self.assertEqual(P.classify(dict(a='self-check:0x5', b='error')), 'error')  # a tool error is never a detection

    def test_plan_counts_and_requirements(self):
        pins = json.loads(P.PINS.read_text())
        self.assertEqual((len(pins['tests']), sorted(pins['excluded'])), (40, ['fence_i', 'ma_data']))
        smoke, nightly = P.plan_ids(pins, 'smoke'), P.plan_ids(pins, 'nightly')
        self.assertEqual((len(smoke), len(nightly)), (208 + len(P.MUTATIONS['smoke']), 208 + 17))
        self.assertEqual(len(set(nightly)), len(nightly))
        self.assertEqual(sorted(pins['mutations']), sorted(str(m) for m in range(1, 18)))
        self.assertTrue(set(P.MUTATIONS['smoke']) <= set(P.MUTATIONS['nightly']))
        classes = {pins['mutations'][str(m)]['class'] for m in P.MUTATIONS['smoke']}
        self.assertEqual(classes, {'self-check', 'trace-only', 'invisible'} & classes)
        self.assertGreaterEqual(len(classes), 2)  # smoke shows a noticed and an unnoticed mutation
        catalog = json.loads(P.REQUIREMENTS.read_text())
        results = [dict(id=i, status='pass') for i in nightly if i != 'requirements']
        self.assertTrue(all(row['passed'] for row in P.requirement_results(catalog, results)))
        missing = [r for r in results if r['id'] != 'core-priv-add']
        failed = [row['id'] for row in P.requirement_results(catalog, missing) if not row['passed']]
        self.assertEqual(failed, ['OT-CORE'])

    def test_every_requirement_prefix_names_planned_checks(self):
        pins = json.loads(P.PINS.read_text())
        ids = P.plan_ids(pins, 'smoke')
        for item in json.loads(P.REQUIREMENTS.read_text())['requirements']:
            for prefix in item['checks']:
                self.assertTrue(any(i == prefix or i.startswith(prefix) for i in ids), prefix)


class SourceTests(unittest.TestCase):
    """The setup script and the checks of the prepared sources, with archives made here."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.first = archive('riscv-tests-aaaa', {'LICENSE': b'license', 'isa/rv32ui/add.S': b'add', 'isa/rv64ui/add.S': b'add64',
                                                  'isa/macros/scalar/test_macros.h': b'macros'})
        self.second = archive('riscv-test-env-bbbb', {'LICENSE': b'license', 'encoding.h': b'enc', 'p/riscv_test.h': b'env'})
        self.pins = fake_pins(self.first, self.second)
        self.pins.update(suite='isa/rv32ui', tests=['add'], excluded={})
        self.blobs = {'https://example.invalid/a.tar.gz': self.first, 'https://example.invalid/b.tar.gz': self.second}

    def tearDown(self):
        self.tmp.cleanup()

    def prepare(self, name='home'):
        return SETUP.prepare(self.dir / name, self.pins, self.blobs.__getitem__)

    def test_setup_extracts_both_archives_and_records_every_file(self):
        record = self.prepare()
        self.assertEqual(sorted(record['files']), ['riscv-tests/LICENSE', 'riscv-tests/env/LICENSE', 'riscv-tests/env/encoding.h',
                                                    'riscv-tests/env/p/riscv_test.h', 'riscv-tests/isa/macros/scalar/test_macros.h',
                                                    'riscv-tests/isa/rv32ui/add.S', 'riscv-tests/isa/rv64ui/add.S'])
        self.assertEqual((self.dir / 'home/riscv-tests/env/p/riscv_test.h').read_bytes(), b'env')
        with self.assertRaisesRegex(ValueError, 'output exists'):
            self.prepare()

    def test_setup_rejects_a_changed_download_and_unsafe_members(self):
        self.blobs['https://example.invalid/b.tar.gz'] = self.second + b'x'
        with self.assertRaisesRegex(ValueError, 'SHA256 mismatch'):
            self.prepare('changed')
        self.assertFalse((self.dir / 'changed').exists())  # nothing is extracted before both hashes agree
        data = io.BytesIO()
        with tarfile.open(fileobj=data, mode='w:gz') as tar:
            info = tarfile.TarInfo('top/../../escape')
            info.size = 1
            tar.addfile(info, io.BytesIO(b'x'))
        with self.assertRaisesRegex(ValueError, 'single top directory|unsafe'):
            SETUP.extract(data.getvalue(), self.dir / 'unsafe')

    def test_prepared_sources_are_checked_against_the_pins(self):
        self.prepare()
        home = self.dir / 'home'
        record = json.loads((home / P.RECORD).read_text())
        wanted = P.test_sources(self.pins, ['add']) + P.upstream_env(self.pins)
        self.pins['used_files_sha256'] = P.tree_sha256({name: record['files'][name] for name in wanted})
        self.assertEqual(sorted(P.verify_home(home, self.pins)), sorted(wanted))
        (home / 'riscv-tests/isa/rv64ui/add.S').write_bytes(b'edited')
        with self.assertRaisesRegex(ValueError, 'changed after it was prepared'):
            P.verify_home(home, self.pins)
        (home / 'riscv-tests/isa/rv64ui/add.S').write_bytes(b'add64')
        (home / 'riscv-tests/isa/rv32ui/extra.S').write_bytes(b'new')
        with self.assertRaisesRegex(ValueError, 'other tests than the pinned list'):
            P.verify_home(home, self.pins)
        (home / 'riscv-tests/isa/rv32ui/extra.S').unlink()
        with self.assertRaisesRegex(ValueError, 'differ from the pinned set'):
            P.verify_home(home, dict(self.pins, used_files_sha256='0' * 64))
        other = dict(self.pins, sources=dict(self.pins['sources']))
        other['sources']['riscv-tests'] = dict(other['sources']['riscv-tests'], commit='c' * 40)
        with self.assertRaisesRegex(ValueError, 'not the pinned riscv-tests'):
            P.verify_home(home, other)

    def test_real_pins_name_full_commits_and_archive_hashes(self):
        pins = json.loads(P.PINS.read_text())
        for source in pins['sources'].values():
            self.assertRegex(source['commit'], r'^[0-9a-f]{40}$')
            self.assertRegex(source['sha256'], r'^[0-9a-f]{64}$')
            self.assertTrue(source['url'].endswith(source['commit'] + '.tar.gz'))
            self.assertIn('LICENSE', source['license'])
        self.assertRegex(pins['used_files_sha256'], r'^[0-9a-f]{64}$')

    def test_runner_stops_without_the_sources_and_never_reports_a_pass(self):
        out = self.dir / 'out'
        done = subprocess.run([sys.executable, str(EXAMPLES / 'local-riscv-official-tests/run.py'), '--riscv-tests-home', str(self.dir / 'absent'),
                               '--out', str(out)], capture_output=True, text=True, timeout=60)
        self.assertEqual(done.returncode, 1)
        self.assertIn('setup_riscv_tests.py', done.stderr)
        self.assertNotIn('Regression: PASS', done.stdout)
        self.assertFalse((out / 'summary.json').exists())

    def test_runner_fails_every_planned_check_when_the_sources_are_not_the_pinned_ones(self):
        self.prepare()  # sources that carry a record, but not the pinned commits
        out = self.dir / 'out'
        done = subprocess.run([sys.executable, str(EXAMPLES / 'local-riscv-official-tests/run.py'), '--riscv-tests-home', str(self.dir / 'home'),
                               '--out', str(out)], capture_output=True, text=True, timeout=60)
        self.assertEqual(done.returncode, 1, done.stdout + done.stderr)
        summary = json.loads((out / 'summary.json').read_text())
        self.assertFalse(summary['success'])
        self.assertFalse(summary['complete'])
        self.assertEqual(next(r for r in summary['results'] if r['id'] == 'sources')['status'], 'fail')
        self.assertEqual(sum(r['status'] == 'pass' for r in summary['results'] if r['id'].startswith(('build-', 'core-', 'iss-'))), 0)


if __name__ == '__main__':
    unittest.main()

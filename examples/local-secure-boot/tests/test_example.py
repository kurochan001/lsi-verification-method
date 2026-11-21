import hashlib
import json
from pathlib import Path
import re
import shutil
import struct
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'local-common'))
from local_test_support import load_example, read_json, run_example, simulate_vectors
P = load_example('local-secure-boot')
M = P.MODEL
HERE = Path(__file__).resolve().parents[1]
DIRECTED = {'golden': 'pass', 'tamper-payload': 'digest', 'tamper-low-byte': 'digest', 'tamper-version': 'digest',
            'bad-magic': 'magic', 'length-zero': 'length', 'length-unaligned': 'length', 'length-max': 'pass',
            'length-over': 'length', 'version-equal': 'pass', 'version-below': 'rollback', 'irq-during-check': 'pass',
            'reset-during-check': 'pass', 'reset-during-image': 'pass', 'lifecycle-prod': 'pass', 'lifecycle-rma': 'pass',
            'irq-jumps-to-image': 'pass', 'rom-ignores-verdict': 'digest', 'unverified-tail': 'pass',
            'rom-jumps-to-header': 'pass'}


def args(**kw):
    from types import SimpleNamespace
    values = dict(seed=17, profile='smoke', iterations=P.ITERATIONS['smoke'], demo_bug=0)
    values.update(kw)
    return SimpleNamespace(**values)


class ModelTests(unittest.TestCase):
    def test_each_directed_scenario_breaks_the_rule_its_name_says(self):
        for max_len in (112, 80):
            found = {s.name: s.found() for s in M.directed(max_len)}
            self.assertEqual(found, DIRECTED)

    def test_the_digest_covers_the_header_and_the_payload_in_memory_order(self):
        s = M.directed(112)[0]
        data = b''.join(struct.pack('<I', w) for w in s.flash)[:4 + s.length]
        self.assertEqual(s.digest, hashlib.sha256(data).digest())
        self.assertEqual(len(data), 4 + 76)
        # The header is hashed, so changing its version alone is a digest failure, not a pass.
        tampered = [s for s in M.directed(112) if s.name == 'tamper-version'][0]
        version = M.parse(tampered.flash[0])[1]
        self.assertEqual(version, (M.MIN_VERSION + 2) ^ 1)
        self.assertGreaterEqual(version, M.MIN_VERSION)  # still new enough: only the digest rule is broken

    def test_the_low_byte_twin_shares_only_the_last_digest_byte(self):
        golden, twin = [s for s in M.directed(112) if s.name in ('golden', 'tamper-low-byte')]
        other = M.digest_of(twin.flash, twin.length)
        self.assertNotEqual(other, golden.digest)
        self.assertEqual(other[-1], golden.digest[-1])
        # The change is in the padding after EBREAK, so the code that runs is the same.
        self.assertEqual(twin.flash[1:1 + len(M.IMAGE)], golden.flash[1:1 + len(M.IMAGE)])

    def test_programs_and_their_stopping_points(self):
        self.assertEqual(len(M.IMAGE), 17)
        self.assertEqual(M.IMAGE[-1], M.EBREAK)
        self.assertEqual(M.IMAGE_HALT, 0x1044)
        for kind in ('good', 'jump', 'ignore', 'header'):
            words, labels = M.rom(kind)
            self.assertEqual(labels['handler'], 4)
            self.assertLess(len(words), 1024)
        words, _ = M.rom('good')
        self.assertEqual(words[M.rom_fail_halt() // 4], M.EBREAK)
        # The good handler returns with MRET; the faulty one never does, it leaves for the entry.
        self.assertIn(0x30200073, words)
        self.assertNotIn(0x30200073, M.rom('jump')[0])

    def test_outcomes_follow_the_firmware(self):
        out = {s.name: s.outcome() for s in M.directed(112)}
        self.assertEqual(out['golden']['ram']['mark'], M.SUCCESS)
        self.assertEqual(out['golden']['ram']['keysum'], M.KEY[0] ^ M.KEY[1] ^ M.KEY[2] ^ M.KEY[3])
        self.assertEqual(out['tamper-payload']['ram']['mark'], M.FAILURE)
        self.assertEqual(out['rom-ignores-verdict']['ram']['keysum'], 0)
        self.assertEqual(out['rom-ignores-verdict']['counts'], dict(starts=1, irqs=0, bus_errors=2))
        self.assertEqual(out['irq-during-check']['counts']['irqs'], 3)
        self.assertEqual(out['irq-jumps-to-image']['halt_pc'], M.ENTRY)
        self.assertEqual(out['rom-jumps-to-header']['halt_pc'], M.ENTRY - 4)
        self.assertEqual(out['unverified-tail']['halt_pc'], out['unverified-tail']['exec_hi'])
        self.assertEqual((out['lifecycle-prod']['debug'], out['lifecycle-rma']['debug'], out['golden']['debug']), (0, 0, 1))
        self.assertEqual(out['reset-during-image']['counts']['starts'], 2)
        for name in ('irq-jumps-to-image', 'rom-ignores-verdict'):
            self.assertEqual(out[name]['may_exec'], 0)

    def test_random_boots_are_reproducible_and_cover_every_verdict(self):
        self.assertEqual(M.random_scenario(5, 112).rows(), M.random_scenario(5, 112).rows())
        verdicts = set()
        for seed in range(300):
            s = M.random_scenario(seed, 80)
            verdicts.add(s.found())
            for ref, delay, kind in s.events:
                self.assertEqual((ref, kind), (M.AFTER_START, M.IRQ))
                self.assertLessEqual(delay, 150)  # well inside the shortest full check
            if s.events:
                self.assertIn(s.found(), ('pass', 'digest'))
        self.assertEqual(verdicts, {'pass', 'digest', 'rollback', 'length', 'magic'})

    def test_rows_carry_each_item_once(self):
        for s in M.directed(80):
            rows, _ = s.rows()
            kinds = [r[0] for r in rows]
            self.assertEqual((kinds.count(M.OTP), kinds.count(M.DIGEST), kinds.count(M.KEYWORD), kinds.count(M.RAM)), (1, 8, 4, 7))
            self.assertEqual(sorted(r[1] for r in rows if r[0] == M.EXPECT), sorted(M.EXPECT_IDS.values()))
            self.assertTrue(all(len(r) == 4 and all(0 <= v < 2 ** 32 for v in r) for r in rows))

    def test_the_plan_names_every_case_once_and_each_mutation_scenario_exists(self):
        cases = P.make_cases(args(), P.CONFIGS['max112-wait0'])
        self.assertEqual(len(cases), len(DIRECTED) + 2 + P.MUTANTS)
        self.assertEqual(len({c['id'] for c in cases}), len(cases))
        self.assertTrue({c['id'] for c in cases if c['category'] == 'functional'} >= set(DIRECTED))
        for mutation, (name, label) in P.DETECTS.items():
            self.assertIn(name, DIRECTED)
            self.assertRegex(label, r'^BOOT_[A-Z]+$')
        nightly = P.make_cases(args(profile='nightly', iterations=P.ITERATIONS['nightly']), P.CONFIGS['max80-wait2'])
        self.assertEqual(len(nightly), len(DIRECTED) + 12 + P.MUTANTS)

    def test_requirements_and_bench_name_the_same_goals(self):
        catalog = json.loads((HERE / 'requirements.json').read_text(encoding='utf-8'))
        goals = [g for r in catalog['requirements'] for g in r['goals']]
        self.assertEqual((len(catalog['requirements']), len(goals), len(set(goals))), (7, 26, 26))
        self.assertEqual(set(goals), set(re.findall(r'COVER (\S+?)"', (HERE / 'tb/secure_boot_tb.sv').read_text())))


class BenchTests(unittest.TestCase):
    """The bench's own judgements, on the correct RTL with rows changed by hand."""

    def setUp(self):
        self.assertTrue(shutil.which('iverilog') and shutil.which('vvp'), 'Icarus Verilog is required')
        self.golden, _ = M.directed(112)[0].rows()

    def run_rows(self, rows):
        return simulate_vectors(P, rows, P.CONFIGS['max112-wait0'])

    def change(self, kind, ident, value):
        rows = [list(r) for r in self.golden]
        hit = [r for r in rows if r[0] == kind and r[1] == ident]
        self.assertEqual(len(hit), 1)
        hit[0][2] = value
        return rows

    def test_the_golden_rows_pass(self):
        run = self.run_rows(self.golden)
        self.assertIn(f'RESULT PASS checks={len(self.golden)}', run.stdout)
        self.assertEqual(run.returncode, 0)

    def test_final_expectations_are_really_compared(self):
        for rows, label in ((self.change(M.RAM, 1, M.FAILURE), 'BOOT_RAM'),
                            (self.change(M.EXPECT, M.EXPECT_IDS['halt_pc'], 0x94), 'BOOT_HALT'),
                            (self.change(M.EXPECT, M.EXPECT_IDS['status'], 0x44), 'BOOT_VERDICT'),
                            (self.change(M.EXPECT, M.EXPECT_IDS['may_exec'], 0), 'BOOT_EXEC'),
                            (self.change(M.OTP, 3, 2), 'BOOT_DEBUG')):
            with self.subTest(label=label):
                run = self.run_rows(rows)
                self.assertNotEqual(run.returncode, 0)
                self.assertEqual(re.findall(r'^CHECK_FAIL (\S+)', run.stdout, re.M), [label])

    def test_a_timeout_has_its_own_label_and_bad_rows_are_refused(self):
        run = self.run_rows(self.change(M.EXPECT, M.EXPECT_IDS['max_cycles'], 40))
        self.assertEqual(re.findall(r'^CHECK_FAIL (\S+)', run.stdout, re.M), ['BOOT_TIMEOUT'])
        run = self.run_rows(self.golden + [[99, 0, 0, 0]])
        self.assertNotEqual(run.returncode, 0)
        self.assertNotIn('RESULT PASS', run.stdout)

    def test_a_wrong_otp_digest_is_a_digest_failure_not_a_pass(self):
        rows = self.change(M.DIGEST, 7, self.golden[[r[0] for r in self.golden].index(M.DIGEST) + 7][2] ^ 1)
        run = self.run_rows(rows)
        self.assertEqual(re.findall(r'^CHECK_FAIL (\S+)', run.stdout, re.M), ['BOOT_VERDICT'])


class RunTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(shutil.which('iverilog') and shutil.which('vvp'), 'Icarus Verilog is required')

    def test_smoke_of_one_configuration_with_every_mutation(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / 'out'
            result = run_example('local-secure-boot', out, '--configuration', 'max80-wait2')
            self.assertEqual(result.returncode, 0, result.stdout[-2000:] + result.stderr)
            summary = read_json(out / 'summary.json')
            planned = len(DIRECTED) + 2 + P.MUTANTS
            self.assertEqual((summary['success'], summary['planned'], summary['results']), (True, planned, planned))
            self.assertEqual((summary['functional_pass'], summary['mutations_detected']), (len(DIRECTED) + 2, P.MUTANTS))
            coverage = read_json(out / 'coverage.json')['max80-wait2']
            self.assertEqual((coverage['hit'], coverage['required']), (26, 26))
            # Every goal is reached by a fixed scenario, not only by a random boot.
            self.assertTrue(all(any('random' not in i for i in ids) for ids in coverage['hits'].values()))
            for mutation, (_, label) in P.DETECTS.items():
                log = (out / f'max80-wait2-detect-mutation{mutation}/simulation.log').read_text()
                self.assertEqual(re.findall(r'^CHECK_FAIL (\S+)', log, re.M), [label])
            cases = list(ET.parse(out / 'junit.xml').getroot().iter('testcase'))
            self.assertEqual(len(cases), planned + 1)
            self.assertFalse([c for c in cases if list(c)])

    def test_seed_changes_the_random_boots_only(self):
        a = P.make_cases(args(seed=3), P.CONFIGS['max112-wait0'])
        b = P.make_cases(args(seed=4), P.CONFIGS['max112-wait0'])
        fixed = lambda cases: [c['vectors'] for c in cases if not c['id'].startswith('random')]
        self.assertEqual(fixed(a), fixed(b))
        self.assertNotEqual([c['vectors'] for c in a if c['id'].startswith('random')],
                            [c['vectors'] for c in b if c['id'].startswith('random')])

    def test_a_demo_fault_makes_the_normal_regression_fail(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / 'out'
            result = run_example('local-secure-boot', out, '--configuration', 'max112-wait0', '--demo-bug', '3')
            self.assertEqual(result.returncode, 1, result.stdout[-2000:])
            self.assertEqual(read_json(out / 'max112-wait0-golden/result.json')['status'], 'fail')


if __name__ == '__main__':
    unittest.main()

import importlib.util
from pathlib import Path
import re
import sys
import tempfile
from types import SimpleNamespace
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'local-common'))
from local_test_support import load_example, read_json, run_example, simulate_vectors
HERE = Path(__file__).resolve().parents[1]
P = load_example('local-aes')
M = P.MODEL
spec = importlib.util.spec_from_file_location('local_aes_formal', HERE / 'formal.py')
F = importlib.util.module_from_spec(spec)
spec.loader.exec_module(F)
CONTROL = (0, 1, 2, 3, 6, 7, 8, 9)   # public inputs and the expected public outputs of a row


def rotl(v, n):
    return ((v << n) | (v >> (8 - n))) & 0xff


def sbox_by_power(a):
    """Third way to write the S-box, following the RTL's method (a^254 and rotations) in Python."""
    inv = pow_gf(a, 254)
    return inv ^ rotl(inv, 1) ^ rotl(inv, 2) ^ rotl(inv, 3) ^ rotl(inv, 4) ^ 0x63


def pow_gf(a, e):
    result = 1
    for _ in range(e):
        result = M.gf_mul(result, a)
    return result if a else 0


class ModelTests(unittest.TestCase):
    def test_published_fips197_examples(self):
        for vector in (M.FIPS_APPENDIX_B, M.FIPS_APPENDIX_C1):
            self.assertEqual(M.encrypt(vector['key'], vector['block']), vector['out'])
        keys = M.round_keys(M.FIPS_APPENDIX_B['key'])
        for index, value in M.FIPS_APPENDIX_A1_ROUND_KEYS.items():
            self.assertEqual(keys[index], value)
        for a, value in M.FIPS_SBOX_EXAMPLES.items():
            self.assertEqual(M.SBOX[a], value)

    def test_sbox_is_a_permutation_and_matches_a_third_method(self):
        self.assertEqual(sorted(M.SBOX), list(range(256)))
        self.assertEqual([sbox_by_power(a) for a in range(256)], M.SBOX)
        self.assertEqual(M.RCON, [0x01, 0x02, 0x04, 0x08, 0x10, 0x20, 0x40, 0x80, 0x1b, 0x36])

    def test_round_states_end_in_the_ciphertext(self):
        states = M.encrypt_rounds(M.FIPS_APPENDIX_C1['key'], M.FIPS_APPENDIX_C1['block'])
        self.assertEqual(len(states), 11)
        self.assertEqual(states[0], M.FIPS_APPENDIX_C1['key'] ^ M.FIPS_APPENDIX_C1['block'])
        self.assertEqual(states[-1], M.FIPS_APPENDIX_C1['out'])


class PlanTests(unittest.TestCase):
    def test_control_columns_do_not_depend_on_secrets(self):
        def schedule(key, block):
            p = P.Plan()
            p.cycle(rst=0)
            p.operation(key, block, hold=2, start_while_busy=True, change_inputs=True)
            p.cycle(start=1, key=key, block=block)
            p.cycle(cancel=1)
            p.operation(key ^ 5, block, hold=0)
            return p.rows
        first, second = schedule(0, 0), schedule(M.FIPS_APPENDIX_B['key'], M.FIPS_APPENDIX_B['block'])
        self.assertEqual([[r[i] for i in CONTROL] for r in first], [[r[i] for i in CONTROL] for r in second])
        self.assertNotEqual([r[10] for r in first], [r[10] for r in second])

    def test_latency_and_result_rows(self):
        p = P.Plan()
        p.cycle(rst=0)
        p.operation(M.FIPS_APPENDIX_C1['key'], M.FIPS_APPENDIX_C1['block'], hold=1)
        starts = [i for i, r in enumerate(p.rows) if r[1] and r[6]]
        first_valid = next(i for i, r in enumerate(p.rows) if r[8])
        self.assertEqual(first_valid - starts[0], P.LATENCY)
        self.assertEqual([r[9] for r in p.rows[starts[0] + 1:first_valid]], list(range(1, 11)))
        self.assertEqual(p.rows[first_valid][10], M.FIPS_APPENDIX_C1['out'])
        self.assertEqual(p.results, 1)

    def test_seed_reproduction_and_plan(self):
        args = SimpleNamespace(profile='smoke', seed=17, iterations=3, demo_bug=0)
        first = P.make_cases(args, {})
        self.assertEqual(first, P.make_cases(args, {}))
        self.assertEqual([c['id'] for c in first],
                         ['boundaries', 'random-seed17'] + [f'detect-mutation{m}' for m in range(1, 10)] +
                         ['random-misses-mutation1'])
        args.seed = 18
        self.assertNotEqual(first[1]['vectors'], P.make_cases(args, {})[1]['vectors'])
        self.assertEqual(first[0]['vectors'], P.make_cases(args, {})[0]['vectors'])
        # Random data never holds the all-zero block that the timing mutant needs.
        self.assertFalse(any(r[1] and r[6] and r[5] == 0 for r in first[1]['vectors']))
        self.assertTrue(any(r[1] and r[6] and r[5] == 0 for r in first[0]['vectors']))


class BenchTests(unittest.TestCase):
    def base(self):
        p = P.Plan()
        p.cycle(rst=0)
        p.operation(M.FIPS_APPENDIX_B['key'], M.FIPS_APPENDIX_B['block'], hold=1)
        p.cycle(start=1, key=M.FIPS_APPENDIX_C1['key'], block=M.FIPS_APPENDIX_C1['block'])
        p.cycle()
        p.cycle(cancel=1)   # cancel while busy, with a nonzero round key
        p.cycle()
        return p.rows

    def run_rows(self, rows):
        return simulate_vectors(P, rows, parameters={})

    def test_clean_rows_pass(self):
        r = self.run_rows(self.base())
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_the_bench_rejects_wrong_expectations_with_the_planned_label(self):
        rows = self.base()
        start = next(i for i, row in enumerate(rows) if row[1] and row[6])
        valid = next(i for i, row in enumerate(rows) if row[8])
        cases = {
            'AES_TIMING': (start + 3, 9, rows[start + 3][9] + 1),
            'AES_DATA': (valid, 10, rows[valid][10] ^ 1),
            'AES_FLOW': (0, 6, 1 - rows[0][6]),
        }
        for label, (index, column, value) in cases.items():
            with self.subTest(label=label):
                changed = [list(row) for row in rows]
                changed[index][column] = value
                r = self.run_rows(changed)
                self.assertNotEqual(r.returncode, 0)
                self.assertIn('CHECK_FAIL ' + label, r.stdout)

    def test_zeroization_and_gating_checks_read_the_real_registers(self):
        edits = {'aes128_core.sv': [("            if (MUTATION != 2) rkey <= 128'h0;", '')]}
        r = simulate_vectors(P, self.base(), parameters={}, replacements=edits)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn('CHECK_FAIL AES_ZERO', r.stdout)
        edits = {'aes128_core.sv': [("(out_valid || MUTATION == 4) ? state", "1'b1 ? state")]}
        r = simulate_vectors(P, self.base(), parameters={}, replacements=edits)
        self.assertIn('CHECK_FAIL AES_LEAK', r.stdout)


class RegressionTests(unittest.TestCase):
    def test_smoke_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / 'out'
            r = run_example('local-aes', out, '--iterations', '3')
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            summary = read_json(out / 'summary.json')
            self.assertEqual((summary['planned'], summary['mutations_detected'], summary['diagnostics_pass']), (12, 9, 1))
            coverage = read_json(out / 'coverage.json')['core']
            self.assertEqual((coverage['hit'], coverage['required']), (22, 22))
            self.assertEqual((out / 'junit.xml').read_text().count('<testcase'), 13)

    def test_every_demo_bug_fails_the_normal_regression(self):
        with tempfile.TemporaryDirectory() as tmp:
            for fault in range(1, P.MUTANTS + 1):
                with self.subTest(fault=fault):
                    out = Path(tmp) / str(fault)
                    r = run_example('local-aes', out, '--iterations', '1', '--demo-bug', str(fault))
                    self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
                    self.assertEqual(read_json(out / 'core-boundaries/result.json')['status'], 'fail')


class FormalPlanTests(unittest.TestCase):
    def test_plan_and_property_names_match_the_sources(self):
        plan = F.plan(F.BOUND, 0)
        self.assertEqual([c['id'] for c in plan],
                         ['constant-time-proof', 'scenario-cover', 'detect-mutation1', 'detect-mutation2',
                          'detect-mutation3', 'detect-mutation4', 'timing-proof-misses-mutation7'])
        self.assertEqual(set(F.FAILURES), {1, 2, 3, 4})   # the shared runner's --demo-bug takes 1..4
        text = (HERE / 'aes_ct_formal.sv').read_text() + (HERE / 'rtl/aes128_core.sv').read_text()
        named = set(re.findall(r'\b([a-z]{2}_[a-z_]+):\s*(?:assert|assume|cover)\b', text))
        self.assertEqual(named, F.ASSERTS | F.COVERS | {'as_initial_reset'})
        self.assertTrue(set(F.FAILURES.values()) <= F.ASSERTS)

    def test_the_proof_abstracts_the_data_path_only_under_formal(self):
        rtl = (HERE / 'rtl/aes128_core.sv').read_text()
        block = rtl[rtl.index('`ifdef FORMAL'):rtl.index('`endif')]
        self.assertIn('(* anyseq *) wire [127:0] f_round_out;', block)
        self.assertIn('wire [127:0] state_next = round_out;', rtl[rtl.index('`else'):])


if __name__ == '__main__':
    unittest.main()

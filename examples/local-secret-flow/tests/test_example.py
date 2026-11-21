import importlib.util
import json
from pathlib import Path
import random
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'local-common'))
from local_test_support import assert_evidence, load_example, read_json, run_example, simulate_vectors

EXAMPLE = 'local-secret-flow'
P = load_example(EXAMPLE)
M = P.MODEL
HERE = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('secret_flow_formal_plan', HERE / 'formal.py')
F = importlib.util.module_from_spec(spec)
spec.loader.exec_module(F)
FORMAL_TOOLS = ('yowasp-sby', 'yowasp-yosys', 'yowasp-yosys-smtbmc', 'yowasp-yosys-witness', 'z3')


def label(result):
    return re.findall(r'^CHECK_FAIL (\w+)$', result.stdout, re.M)


def ready(kw=8, lc=1):
    b = M.Block(kw)
    b.step(rst_n=0, lc=lc)
    return b


def flow_differences(kw, steps):
    """The checks of the testbench, applied to two model runs: what the policy calls public must agree."""
    a, b = M.Block(kw), M.Block(kw)
    found, allowed_seen, clean = [], set(), True
    for s in steps:
        row = {name: s.get(name, 1 if name == 'rst_n' else 0) for name in M.INPUTS}
        before = a.status()
        prod, scan = before >> 2 & 1, before >> 3 & 1
        allow = M.allowed(before, row)['read']
        if not row['rst_n'] or row['zeroize'] or (row['scan_en'] and not scan and prod):
            clean = True
        elif row['key_we'] and not row['scan_en']:
            clean = False
        common = {k: row[k] for k in M.INPUTS if k not in ('key0', 'key1')}
        oa, ob = a.step(key=row['key0'], **common), b.step(key=row['key1'], **common)
        prod = oa[M.STATUS] >> 2 & 1
        if oa[M.STATUS] != ob[M.STATUS]: found.append('status')
        if prod and oa[M.SO] != ob[M.SO]: found.append('scan')
        if not allow and oa[M.RD] != ob[M.RD]: found.append('dbg')
        if oa[M.ERR] != ob[M.ERR]: found.append('err')
        if not oa[M.STATUS] >> 1 & 1 and oa[M.CT] != ob[M.CT]: found.append('ct')
        if clean and (oa[M.CT], oa[M.RD], oa[M.SO]) != (ob[M.CT], ob[M.RD], ob[M.SO]): found.append('erased')
        if allow and oa[M.RD] != ob[M.RD]: allowed_seen.add('read-' + ('dev' if not prod else 'prod'))
        if not prod and oa[M.SO] != ob[M.SO]: allowed_seen.add('dev-scan')
        if oa[M.STATUS] >> 1 & 1 and oa[M.CT] != ob[M.CT]: allowed_seen.add('result')
    return found, allowed_seen


class ModelTests(unittest.TestCase):
    def test_the_first_cycle_must_be_a_reset_and_inputs_must_fit(self):
        with self.assertRaises(ValueError):
            M.Block(8).step(key_we=1, key=1)
        b = ready()
        with self.assertRaises(ValueError):
            b.step(key_we=1, key=256)
        with self.assertRaises(ValueError):
            M.Block(3)

    def test_key_loaded_comes_from_the_write_not_from_the_value(self):
        b = ready()
        self.assertEqual(b.step(start=1, din=3)[M.ERR], M.E_NOKEY << 8)
        out = b.step(key_we=1, key=0)
        self.assertEqual(out[M.STATUS] & 1, 1)
        self.assertEqual(b.step(start=1, din=0x96)[M.CT], 0x96)        # a zero key is a key

    def test_a_write_wins_over_a_start_and_clears_the_result(self):
        b = ready()
        b.step(key_we=1, key=0x0f), b.step(start=1, din=0xf0)
        out = b.step(key_we=1, key=0x33, start=1, din=1)
        self.assertEqual((out[M.STATUS] >> 1 & 1, out[M.CT], out[M.ERR]), (0, 0, 0))

    def test_production_key_read_is_zero_and_recorded_with_its_address_only(self):
        b = ready(lc=1)
        b.step(key_we=1, key=0xa5)
        out = b.step(dbg_req=1, dbg_addr=1)
        self.assertEqual((out[M.RD], out[M.ERR]), (0, M.E_DENIED << 8 | 1))
        self.assertEqual(b.step(dbg_req=1, dbg_addr=1, err_clr=1)[M.ERR], M.E_DENIED << 8 | 1)
        self.assertEqual(b.step(err_clr=1)[M.ERR], 0)
        d = ready(lc=0)
        d.step(key_we=1, key=0xa5)
        self.assertEqual(d.step(dbg_req=1, dbg_addr=1)[M.RD], 0xa5)

    def test_production_scan_entry_erases_drops_the_read_and_then_shifts_public_bits(self):
        b = ready(lc=1)
        b.step(key_we=1, key=0xa5), b.step(start=1, din=0x0f)
        out = b.step(scan_en=1, dbg_req=1, dbg_addr=2)
        self.assertEqual(out, [0b1100, 0, 0, 0, 0])
        bits = [1, 0, 1, 1]
        outs = [b.step(scan_en=1, scan_in=bits[i % 4]) for i in range(2 * 8 + 4)]
        self.assertEqual([o[M.SO] for o in outs[:16]], [0] * 16)
        self.assertEqual([o[M.SO] for o in outs[16:]], bits)            # 2*KW+1 shifts later
        self.assertEqual(b.step(start=1)[M.ERR], M.E_NOKEY << 8)         # erased: no key after scan

    def test_development_scan_shows_the_key_from_its_top_bit(self):
        b = ready(lc=0)
        b.step(key_we=1, key=0b10110010)
        self.assertEqual([b.step(scan_en=1)[M.SO] for _ in range(8)], [1, 0, 1, 1, 0, 0, 1, 0])
        self.assertEqual(b.status() & 1, 1)                               # development scan keeps the key valid

    def test_erase_wins_over_everything_on_its_edge(self):
        b = ready(lc=0)
        b.step(key_we=1, key=0x5a), b.step(start=1, din=1)
        out = b.step(zeroize=1, key_we=1, key=0x11, dbg_req=1, dbg_addr=1, scan_en=1)
        self.assertEqual(out, [0b1000, 0, 0, 0, 0])
        self.assertEqual((b.key, b.shadow, b.ct_q), (0, 0, 0))

    def test_the_policy_holds_for_the_model_and_its_allowed_differences_occur(self):
        for kw in (8, 16):
            found, seen = flow_differences(kw, M.boundaries(kw))
            self.assertEqual(found, [])
            self.assertEqual(seen, {'read-dev', 'read-prod', 'dev-scan', 'result'})
            for seed in range(5):
                self.assertEqual(flow_differences(kw, M.random_steps(kw, seed, 400))[0], [])

    def test_the_checker_would_see_a_model_that_leaks(self):
        steps = M.boundaries(8)
        original = M.Block.read
        try:
            M.Block.read = lambda self, addr: self.shadow if addr == 1 else original(self, addr)
            self.assertIn('dbg', flow_differences(8, steps)[0])
        finally:
            M.Block.read = original

    def test_equal_secrets_hide_every_flow(self):
        self.assertTrue(all(s.get('key0', 0) == s.get('key1', 0) for s in M.boundaries(8, equal=True)))
        rows, _ = M.vectors(8, M.boundaries(8, equal=True))
        self.assertTrue(all(r[13:18] == r[18:23] for r in rows))


class SimulationTests(unittest.TestCase):
    def run_rows(self, steps=None, replacements=None, parameters=None):
        rows, _ = M.vectors((parameters or {'KW': 8})['KW'], steps or M.boundaries(8))
        return simulate_vectors(P, rows, parameters, replacements)

    def test_the_fixed_scenario_passes_with_both_widths(self):
        for kw in (8, 16):
            rows, counts = M.vectors(kw, M.boundaries(kw))
            result = simulate_vectors(P, rows, {'KW': kw})
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn(f'RESULT PASS checks={len(rows)}', result.stdout)
            for name, value in counts.items():
                self.assertIn(f'COUNT {name}={value}', result.stdout)

    def test_a_read_on_the_production_entry_edge_must_be_dropped(self):
        edit = {'secret_block.sv': [('dbg_rdata <= dbg_req && !entry_erase ? read_value', 'dbg_rdata <= dbg_req ? read_value')]}
        self.assertEqual(label(self.run_rows(replacements=edit)), ['SF_FLOW_ERASED'])

    def test_an_error_record_without_reset_is_unknown_and_reported(self):
        edit = {'secret_block.sv': [('err_info <= {(KW + 2){1\'b0}};\n            scan_out <= 1\'b0;\n        end else if (zeroize)',
                                     'scan_out <= 1\'b0;\n        end else if (zeroize)')]}
        self.assertEqual(label(self.run_rows(replacements=edit)), ['SF_ERR'])

    def test_a_wrong_expected_value_is_not_hidden_by_the_flow_check(self):
        rows, _ = M.vectors(8, M.boundaries(8))
        rows[8][14] ^= 1                                    # copy a's result one bit off
        result = simulate_vectors(P, rows)
        self.assertEqual(label(result), ['SF_CT'])


class RunnerTests(unittest.TestCase):
    def test_real_rtl_all_configurations_and_mutants(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / 'out'
            result = run_example(EXAMPLE, out, '--iterations', '30')
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            assert_evidence(self, out, P.CONFIGS, 28, 8 * len(P.CONFIGS), mutants=6)
            for name in P.CONFIGS:
                for m, expected in P.LABELS.items():
                    self.assertIn(expected, read_json(out / f'{name}-detect-mutation{m}/result.json')['message'])
                hits = read_json(out / 'coverage.json')[name]['hits']
                self.assertTrue(all(f'{name}-boundaries' in ids for ids in hits.values()))

    def test_seed_changes_the_random_case_and_demo_faults_fail(self):
        a, b = M.random_steps(8, 17, 50), M.random_steps(8, 18, 50)
        self.assertNotEqual(a, b)
        self.assertEqual(a, M.random_steps(8, 17, 50))
        with tempfile.TemporaryDirectory() as tmp:
            for fault in range(1, P.MUTANTS + 1):
                with self.subTest(fault=fault):
                    out = Path(tmp) / str(fault)
                    result = run_example(EXAMPLE, out, '--configuration', 'kw8', '--iterations', '5', '--demo-bug', str(fault))
                    self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                    self.assertEqual(read_json(out / 'kw8-boundaries/result.json')['status'], 'fail')


class FormalPlanTests(unittest.TestCase):
    def test_plan_properties_and_wrapper_agree(self):
        plan = F.plan(F.BOUND, 0)
        self.assertEqual([c['id'] for c in plan], ['flow-proof', 'scenario-cover'] +
                         [f'detect-mutation{m}' for m in range(1, 6)] +
                         ['prod-ports-miss-mutation4', 'prod-internal-detect-mutation4'])
        self.assertEqual(F.plan(F.BOUND, 2)[0]['parameters'], dict(MUTATION=2, AUX=1, INTERNAL=1, PROD_ONLY=0))
        text = (HERE / 'secret_flow_formal.sv').read_text()
        labels = set(re.findall(r'\b((?:ap|ai|cp|as)_\w+):', text))
        self.assertEqual(labels, F.PORTS | F.INTERNAL | F.AUX | F.COVERS | {'as_initial_reset', 'as_prod'})
        for case in plan:
            p = F.properties({}, case)
            if case['category'] == 'mutation':
                self.assertIn(case['failure'], p['assert'])
                self.assertEqual(case['parameters']['AUX'], 0)        # the counterexample names only that check
        self.assertEqual(set(F.FAILURES), set(range(1, P.MUTANTS + 1)))
        self.assertEqual(F.CONFIGS, P.CONFIGS)

    def test_the_wrapper_differs_from_the_simulation_only_in_the_secret(self):
        text = (HERE / 'secret_flow_formal.sv').read_text()
        self.assertEqual(text.count('secret_block #('), 2)
        self.assertEqual(re.findall(r'\.key_wdata\((\w+)\)', text), ['key0', 'key1'])
        self.assertNotRegex(text, r'\.(?!key_wdata)\w+\(key[01]\)')

    def test_formal_finds_a_masking_leak_and_passes_the_left_over_copy_in_production(self):
        missing = [t for t in FORMAL_TOOLS if not shutil.which(t)]
        self.assertEqual(missing, [], 'formal tools are needed on PATH')
        with tempfile.TemporaryDirectory() as tmp:
            for task, outcome in (('detect-mutation2', 'detected'), ('prod-ports-miss-mutation4', 'pass')):
                out = Path(tmp) / task
                result = subprocess.run([sys.executable, str(HERE / 'formal.py'), '--configuration', 'kw8',
                                         '--task', task, '--out', str(out)], capture_output=True, text=True, timeout=300)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                summary = read_json(out / 'summary.json')
                self.assertEqual([r['outcome'] for r in summary['results']], [outcome])


if __name__ == '__main__':
    unittest.main()

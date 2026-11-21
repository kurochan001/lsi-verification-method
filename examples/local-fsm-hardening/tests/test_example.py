import importlib.util
from itertools import combinations
from pathlib import Path
import re, shutil, subprocess, sys, tempfile, unittest
from types import SimpleNamespace
import xml.etree.ElementTree as ET
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'local-common'))
from local_test_support import load_example, read_json, run_example, simulate_vectors

P = load_example('local-fsm-hardening')
M = P.M
HERE = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('fsm_hardening_formal_plan', HERE / 'formal.py')
F = importlib.util.module_from_spec(spec)
spec.loader.exec_module(F)
GOALS = 23
FORMAL_TOOLS = ('yowasp-sby', 'yowasp-yosys', 'yowasp-yosys-smtbmc', 'yowasp-yosys-witness', 'z3')


def classes(row):
    """The state of the lock without faults after the edge of a row."""
    grant, busy, lockout = row[6], row[7], row[8]
    return M.OPEN if grant else M.CHECK if busy else M.LOCKOUT if lockout else M.LOCKED


class ModelTests(unittest.TestCase):
    def test_lock_counts_failures_locks_out_exactly_at_the_limit_and_success_clears(self):
        lock = M.Lock(3)
        for _ in range(2):
            lock.step(start=1)
            self.assertEqual(lock.step(), [0, 0, 0, 0, lock.fails])
        self.assertEqual((lock.state, lock.fails), (M.LOCKED, 2))       # one short of the limit
        lock.step(start=1)
        self.assertEqual(lock.step(key_ok=1), [1, 0, 0, 0, 0])          # success on the last try clears
        lock.step(relock=1)
        for _ in range(3):
            lock.step(start=1)
            lock.step()
        self.assertEqual((lock.state, lock.fails), (M.LOCKOUT, 3))
        self.assertEqual(lock.step(start=1, key_ok=1, relock=1), [0, 0, 1, 0, 3])
        self.assertEqual(lock.step(rst_n=0), [0, 0, 0, 0, 0])
        self.assertEqual(lock.step(key_ok=1), [0, 0, 0, 0, 0])          # no key without start
        with self.assertRaises(ValueError):
            M.Lock(4)

    def test_hardened_codes_keep_three_bits_between_any_two_and_four_between_working_states(self):
        table = M.CODES['hardened']
        self.assertEqual(M.minimum_distance(table), 3)
        working = [table[s] for s in M.STATES]
        self.assertEqual({M.distance(a, b) for a, b in combinations(working, 2)}, {4})
        self.assertEqual({M.distance(table[M.ERROR], c) for c in working}, {3})
        self.assertFalse({0, 0b111111} & set(table.values()))
        self.assertEqual(M.minimum_distance(M.CODES['binary']), 1)

    def test_flip_tables_match_the_distance_argument(self):
        for bits in (1, 2):
            for state, counts in M.flip_table('hardened', bits).items():
                self.assertEqual(counts['invalid'], len(list(combinations(range(6), bits))), (bits, state))
        three = M.flip_table('hardened', 3)
        for state in M.STATES:   # three bits move a working state only into ERROR
            self.assertEqual((three[state]['error'], three[state]['privileged'], three[state]['silent']), (1, 0, 0), state)
        self.assertEqual((three[M.ERROR]['privileged'], three[M.ERROR]['silent']), (1, 3))
        binary = M.flip_table('binary', 1)
        self.assertEqual(binary[M.LOCKED]['privileged'], 1)            # 000 -> 010
        self.assertEqual(binary[M.LOCKOUT]['privileged'], 1)           # 011 -> 010
        self.assertEqual(sum(c['privileged'] for c in binary.values()), 2)
        self.assertEqual(sum(c['silent'] for c in binary.values()), 7)
        self.assertEqual(M.counter_flips(True, 1), dict(total=4, unnoticed=0))
        self.assertEqual(M.counter_flips(True, 2), dict(total=6, unnoticed=2))   # the same bit of both
        self.assertEqual(M.counter_flips(False, 1), dict(total=2, unnoticed=2))

    def test_code_tables_in_the_rtl_and_the_harness_are_the_specified_ones(self):
        rtl = (HERE / 'rtl/hardened_lock.sv').read_text()
        found = dict(re.findall(r"localparam \[5:0\] H_(\w+) = (?:MUTATION == 1 \? 6'b[01]+ : )?6'b([01]+);", rtl))
        self.assertEqual({k: int(v, 2) for k, v in found.items()},
                         {s: c for s, c in M.CODES['hardened'].items()})
        harness = (HERE / 'fsm_hardening_formal.sv').read_text()
        codes = [int(v, 2) for v in re.findall(r"code = 6'b([01]+);", harness)]
        self.assertEqual(codes, [M.CODES['hardened'][s] for s in M.STATES])
        self.assertIn(f"ERROR = 6'b{M.CODES['hardened'][M.ERROR]:06b}", harness)


class PlanTests(unittest.TestCase):
    def test_single_flips_cover_every_bit_in_every_state_and_in_error(self):
        for name, parameters in P.CONFIGS.items():
            rows = P.fault_rows(parameters['MAX_TRIES'])
            first = [(classes(r), r[4]) for r in rows if r[5] == P.FIRST]
            for state in M.STATES:
                masks = {mask for cls, mask in first if cls == state}
                self.assertEqual(masks, {1 << b for b in range(P.FW)}, (name, state))
            self.assertEqual({r[4] for r in rows if r[5] == P.AGAIN}, {1 << b for b in range(P.FW)}, name)
            self.assertEqual(len(first), len(P.contexts(parameters['MAX_TRIES'])) * 2 * P.FW, name)
            P.check_rows(rows)
            self.assertTrue(all(r[0] or not r[4] for r in rows))

    def test_a_flip_must_reach_the_edge_that_demands_error(self):
        p = P.Plan(3)
        p.reset()
        p.edge(fault=1)
        p.reset()
        with self.assertRaisesRegex(ValueError, 'closed by reset'):
            P.check_rows(p.rows)
        p = P.Plan(3)
        p.reset()
        p.edge(fault=1)
        with self.assertRaisesRegex(ValueError, 'ends on a flip'):
            P.check_rows(p.rows)
        with self.assertRaisesRegex(ValueError, 'reset wins'):
            P.Plan(3).edge(rst_n=0, fault=1)

    def test_double_counter_plan_reaches_the_limit_only_without_faults(self):
        for max_tries in (2, 3):
            rows = P.double_counter_rows(max_tries)
            flip = next(r for r in rows if r[5] == P.FIRST)
            self.assertEqual(bin(flip[4]).count('1'), 2)
            self.assertEqual((flip[4] >> 2) & 3, flip[4] & 3)           # the same bit of the counter and its copy
            self.assertIn(1, [r[8] for r in rows])                       # the lock without faults locks out
            self.assertNotIn(1, [r[6] for r in rows if r[5] != P.EXACT])  # and grants nothing after the flip

    def test_seed_reproduction_and_random_flips(self):
        args = SimpleNamespace(profile='smoke', seed=17, iterations=400, demo_bug=0)
        first = P.make_cases(args, P.CONFIGS['tries3'])
        self.assertEqual(first, P.make_cases(args, P.CONFIGS['tries3']))
        args.seed = 18
        self.assertNotEqual(first, P.make_cases(args, P.CONFIGS['tries3']))
        rows = P.random_rows(3, 17, 2000)
        self.assertGreater(P.counts(rows)['flips'], 20)
        self.assertGreater(P.counts(rows)['again'], 0)
        P.check_rows(rows)

    def test_case_ids_and_labels(self):
        args = SimpleNamespace(profile='nightly', seed=17, iterations=5, demo_bug=0)
        ids = [c['id'] for c in P.make_cases(args, P.CONFIGS['tries2'])]
        self.assertEqual(ids, ['scenarios', 'single-flips', 'random-seed17', 'random-seed18', 'random-seed19',
                               'double-state-flips', 'double-counter-flip'] + [f'detect-mutation{m}' for m in range(1, 9)])
        self.assertEqual(set(P.LABELS), set(range(1, P.MUTANTS + 1)))


class RtlTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(shutil.which('iverilog') and shutil.which('vvp'), 'Icarus required')

    def test_real_rtl_every_case_and_mutant(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / 'out'
            result = run_example('local-fsm-hardening', out)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            summary = read_json(out / 'summary.json')
            planned = 13 * len(P.CONFIGS)     # smoke: 3 normal cases, 2 diagnostics, 8 mutants
            self.assertEqual((summary['success'], summary['complete'], summary['planned']), (True, True, planned))
            self.assertEqual(summary['mutations_detected'], (P.MUTANTS + 1) * len(P.CONFIGS))
            self.assertEqual(summary['diagnostics_pass'], len(P.CONFIGS))
            coverage = read_json(out / 'coverage.json')
            self.assertEqual({k: (v['hit'], v['missing']) for k, v in coverage.items()}, {k: (GOALS, []) for k in P.CONFIGS})
            suite = ET.parse(out / 'junit.xml').getroot()
            self.assertEqual((suite.get('tests'), suite.get('failures'), suite.get('errors')), (str(planned + len(P.CONFIGS)), '0', '0'))
            for name in P.CONFIGS:
                for m in range(1, P.MUTANTS + 1):
                    record = read_json(out / f'{name}-detect-mutation{m}/result.json')
                    self.assertEqual(record['status'], 'detected', (name, m))
                    self.assertIn(P.LABELS[m], record['message'])
                self.assertIn('FSM_ESCALATE', read_json(out / f'{name}-double-counter-flip/result.json')['message'])

    def test_demo_fault_fails_the_normal_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / 'demo'
            result = run_example('local-fsm-hardening', out, '--configuration', 'tries2', '--iterations', '5', '--demo-bug', '1')
            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            self.assertEqual(read_json(out / 'tries2-single-flips/result.json')['status'], 'fail')
            self.assertEqual(read_json(out / 'tries2-scenarios/result.json')['status'], 'pass')   # codes are invisible without flips

    def test_checker_reports_unknown_outputs_and_rejects_a_second_flip_without_a_first(self):
        rows = P.scenario_rows(3)
        edits = {'hardened_lock.sv': [('assign fails = cnt_q;', "assign fails = rst_n ? cnt_q : 2'bxx;")]}
        self.assertIn('CHECK_FAIL FSM_UNKNOWN', simulate_vectors(P, rows, P.CONFIGS['tries3'], edits).stdout)
        bad = [[1, 0, 0, 0, 4, P.AGAIN, 0, 0, 0, 0, 0]]
        result = simulate_vectors(P, bad, P.CONFIGS['tries3'])
        self.assertIn('second flip without a first', result.stdout + result.stderr)
        self.assertNotIn('RESULT PASS', result.stdout)

    def test_an_undetected_flip_is_counted_not_hidden(self):
        """A lock that never raises alarm passes every exact row but not the flips."""
        edits = {'hardened_lock.sv': [('if (!valid) n_state = MUTATION == 4 ? C_LOCKED : C_ERROR;', 'if (!valid) n_state = state_q;'),
                                      ('else if (!cnt_ok) n_state = C_ERROR;', 'else if (!cnt_ok) n_state = state_q;')]}
        p = P.Plan(3)
        p.reset()
        p.edge(fault=1 << 4)
        p.edge()
        p.reset()
        output = simulate_vectors(P, p.rows, P.CONFIGS['tries3'], edits).stdout
        self.assertIn('FLIPS first=1 again=0 escalated=0 undetected=1 escaped=0', output)
        self.assertIn('CHECK_FAIL FSM_UNDETECTED', output)
        self.assertIn('RESULT PASS', simulate_vectors(P, p.rows, P.CONFIGS['tries3']).stdout)


class FormalPlanTests(unittest.TestCase):
    def test_plan_properties_and_failures(self):
        plan = F.plan(F.BOUND, 0)
        self.assertEqual([c['id'] for c in plan], ['single-flip-proof', 'scenario-cover', 'double-state-flip-proof',
                                                    'double-counter-flip-escalates', 'triple-state-flip-escalates',
                                                    'binary-code-escalates'] + [f'detect-mutation{m}' for m in range(1, 9)])
        by_id = {c['id']: c for c in plan}
        self.assertEqual(F.properties(F.CONFIGS['tries3'], by_id['single-flip-proof'])['assert'], F.ASSERTS | F.AIDS)
        self.assertEqual(F.properties(F.CONFIGS['tries3'], by_id['double-counter-flip-escalates'])['assert'],
                         {'ap_match', 'ap_no_escalation'})
        self.assertEqual(F.properties(F.CONFIGS['tries3'], by_id['binary-code-escalates'])['assert'], F.ASSERTS)
        self.assertEqual(F.plan(F.BOUND, 3)[0]['parameters']['MUTATION'], 3)
        self.assertTrue(set(F.FAILURES.values()) <= F.ASSERTS)
        for case in plan:
            if case['expect'] == 'FAIL':
                self.assertIn(case['failure'], F.properties(F.CONFIGS['tries3'], case)['assert'], case['id'])

    def test_property_names_match_the_sources(self):
        text = ''.join(p.read_text() for p in F.SOURCES)
        labels = set(re.findall(r'\b((?:ap|ai|cp|as)_\w+):', text))
        self.assertEqual(labels, F.ASSERTS | F.AIDS | F.COVERS | {'as_initial_reset', 'as_fault_shape'})

    def test_proof_and_binary_counterexample(self):
        self.assertEqual([t for t in FORMAL_TOOLS if not shutil.which(t)], [], 'formal tools required')
        with tempfile.TemporaryDirectory() as tmp:
            for task, outcome in (('single-flip-proof', 'pass'), ('binary-code-escalates', 'detected')):
                out = Path(tmp) / task
                result = subprocess.run([sys.executable, str(HERE / 'formal.py'), '--configuration', 'tries2', '--task', task,
                                         '--out', str(out)], capture_output=True, text=True, timeout=600)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertEqual(read_json(out / f'tries2-{task}/result.json')['outcome'], outcome)


if __name__ == '__main__':
    unittest.main()

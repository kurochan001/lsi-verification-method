import importlib.util
from pathlib import Path
import re, shutil, subprocess, sys, tempfile, unittest
from types import SimpleNamespace
import xml.etree.ElementTree as ET
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'local-common'))
from local_test_support import load_example, read_json, run_example, simulate_vectors

P = load_example('local-rate-limiter')
M = P.M
HERE = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('rate_limiter_formal_plan', HERE / 'formal.py')
F = importlib.util.module_from_spec(spec)
spec.loader.exec_module(F)
FORMAL = all(shutil.which(tool) for tool in ('yowasp-sby', 'yowasp-yosys', 'yowasp-yosys-smtbmc', 'z3'))
GOALS = 16


def over_granting_bucket(frac, rows):
    """The model with the order of mutant 3: saturate first, then add the refill."""
    cost, tokens, trace = 1 << frac, None, []
    for rst_n, req, depth, rate in rows:
        cap = depth * cost
        if not rst_n:
            tokens, grant = cap, 0
        else:
            avail = min(tokens, cap) + rate
            grant = int(bool(req) and avail >= cost)
            tokens = avail - (cost if grant else 0)
        trace.append((rst_n, grant, cap, rate))
    return trace


class ModelTests(unittest.TestCase):
    def test_bucket_fills_at_reset_saturates_and_spends_whole_tokens(self):
        b = M.Bucket(2)                                       # four units per token
        self.assertEqual(b.step(0, 0, 3, 0)[:2], (0, 12))    # reset fills to depth 3
        self.assertEqual([b.step(1, 1, 3, 0)[:2] for _ in range(4)], [(1, 8), (1, 4), (1, 0), (0, 0)])
        self.assertEqual(b.step(1, 1, 3, 3)[:2], (0, 3))     # one unit short of a token: refused
        self.assertEqual(b.step(1, 1, 3, 1)[:2], (1, 0))     # exactly one token: granted
        self.assertEqual(b.step(1, 0, 3, 7)[:2], (0, 7))
        self.assertEqual(b.step(1, 0, 3, 7)[:2], (0, 12))    # saturates at the depth
        self.assertEqual(b.step(1, 0, 1, 0)[:2], (0, 4))     # a smaller depth clamps at once
        self.assertEqual(b.step(1, 1, 0, 7)[:2], (0, 0))     # depth 0: never a token
        with self.assertRaises(ValueError):
            M.Bucket(2).step(1, 1, 3, 0)

    def test_window_bound_is_tight_and_the_textbook_bound_is_looser(self):
        rows = [(0, 0, 3, 0)] + [(1, 1, 3, 3)] * 12
        b = M.Bucket(2)
        trace = [(r[0], b.step(*r)[0], 3 * 4, r[3]) for r in rows]
        slack, where = M.window_slack(4, trace)
        self.assertEqual(slack, 0)
        start, end = where
        grants = sum(t[1] for t in trace[start:end + 1])
        self.assertEqual(grants, M.window_bound(4, [t[2] for t in trace], [t[3] for t in trace], start, end))
        # The loose bound adds the refill of the first cycle too: one rate more than can be delivered.
        self.assertGreaterEqual(M.loose_bound(4, 3, 3, end - start + 1), grants)

    def test_window_check_refutes_a_bucket_that_saturates_before_refilling(self):
        rows = [(0, 0, 3, 0)] + [(1, 1, 3, 3)] * 12
        slack, _ = M.window_slack(4, over_granting_bucket(2, rows))
        self.assertLess(slack, 0)
        # ...while the loose bound depth + rate * length still holds for that trace.
        trace = over_granting_bucket(2, rows)[1:]
        for length in range(1, len(trace) + 1):
            self.assertLessEqual(sum(t[1] for t in trace[:length]), M.loose_bound(4, 3, 3, length))


class PlanTests(unittest.TestCase):
    def test_fixed_plan_reaches_every_goal_in_both_configurations(self):
        for name, parameters in P.CONFIGS.items():
            rows = P.boundary_rows(parameters)
            tags = 0
            for row in rows:
                tags |= row[6]
            self.assertEqual([t for t in P.TAGS if not tags & P.BIT[t]], [], name)
            self.assertLess(len(rows), 400, name)

    def test_goals_of_the_catalog_and_of_the_bench_are_the_tags(self):
        catalog = read_json(HERE / 'requirements.json')
        self.assertEqual(sorted(g for r in catalog['requirements'] for g in r['goals']), sorted(P.TAGS))
        bench = (HERE / 'tb/token_bucket_tb.sv').read_text()
        self.assertEqual(re.findall(r'\d+: goal = "([^"]+)";', bench), P.TAGS)
        self.assertEqual(len(P.TAGS), GOALS)

    def test_random_rows_are_reproducible_and_stay_inside_the_window_bound(self):
        parameters = P.CONFIGS['f2d2r3']
        first = P.random_rows(parameters, 17, 200)
        self.assertEqual(first, P.random_rows(parameters, 17, 200))
        self.assertNotEqual(first, P.random_rows(parameters, 18, 200))
        trace = [(r[0], r[4], r[2] * 4, r[3]) for r in first]
        self.assertGreaterEqual(M.window_slack(4, trace)[0], 0)

    def test_cases_and_counts(self):
        args = SimpleNamespace(profile='nightly', seed=17, iterations=20, demo_bug=0)
        cases = P.make_cases(args, P.CONFIGS['f4d4r8'])
        self.assertEqual([c['id'] for c in cases], ['boundaries', 'random-seed17', 'random-seed18', 'random-seed19'] +
                         [f'detect-mutation{m}' for m in range(1, 6)])
        self.assertTrue(all(c['counts']['grants'] == sum(r[4] for r in c['vectors']) for c in cases))


class RtlTests(unittest.TestCase):
    def test_real_rtl_both_configurations_and_every_mutant(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / 'out'
            result = run_example('local-rate-limiter', out, '--iterations', '60')
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            summary = read_json(out / 'summary.json')
            self.assertEqual((summary['success'], summary['complete'], summary['planned']), (True, True, 14))
            self.assertEqual(summary['mutations_detected'], 10)
            coverage = read_json(out / 'coverage.json')
            self.assertEqual({k: (v['hit'], v['missing']) for k, v in coverage.items()}, {k: (GOALS, []) for k in P.CONFIGS})
            suite = ET.parse(out / 'junit.xml').getroot()
            self.assertEqual((suite.get('tests'), suite.get('failures'), suite.get('errors')), ('16', '0', '0'))
            for name in P.CONFIGS:
                for m in range(1, 6):
                    record = read_json(out / f'{name}-detect-mutation{m}/result.json')
                    self.assertEqual(record['status'], 'detected', (name, m))
                    self.assertIn(P.LABELS[m], record['message'])

    def test_demo_fault_fails_the_normal_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / 'demo'
            result = run_example('local-rate-limiter', out, '--configuration', 'f2d2r3', '--iterations', '5', '--demo-bug', '3')
            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            self.assertEqual(read_json(out / 'f2d2r3-boundaries/result.json')['status'], 'fail')

    def test_checker_reports_an_unknown_level_and_a_grant_without_request(self):
        rows = P.boundary_rows(P.CONFIGS['f2d2r3'])
        parameters = P.CONFIGS['f2d2r3']
        for edits, label in (([('else tokens <= next;', "else tokens <= req ? next : 'x;")], 'RL_UNKNOWN'),
                             ([('assign grant = req && enough;', 'assign grant = enough;')], 'RL_GRANT')):
            self.assertIn('CHECK_FAIL ' + label, simulate_vectors(P, rows, parameters, {'token_bucket.sv': edits}).stdout, label)
        self.assertIn('RESULT PASS checks=%d' % len(rows), simulate_vectors(P, rows, parameters).stdout)


class FormalPlanTests(unittest.TestCase):
    def test_plan_and_property_sets(self):
        plan = F.plan(F.BOUND, 0)
        self.assertEqual([c['id'] for c in plan], ['full-proof', 'window-proof', 'scenario-cover'] +
                         [f'detect-mutation{m}' for m in range(1, 6)] +
                         [f'window-refutes-mutation{m}' for m in F.WINDOW_REFUTES] +
                         [f'window-blind-mutation{m}' for m in F.WINDOW_BLIND])
        by = {c['id']: c for c in plan}
        self.assertEqual(F.properties({}, by['window-proof'])['assert'], {'ap_window', 'ai_slack'})
        self.assertEqual(F.properties({}, by['window-refutes-mutation1'])['assert'], {'ap_window'})
        self.assertEqual(F.properties({}, by['full-proof'])['cover'], F.COVERS)
        self.assertEqual(set(F.WINDOW_REFUTES) | set(F.WINDOW_BLIND), set(range(1, 6)))
        self.assertEqual((by['window-blind-mutation2']['mode'], by['window-blind-mutation2']['expect'], by['window-blind-mutation2']['category']),
                         ('prove', 'PASS', 'diagnostic'))
        self.assertEqual(F.properties({}, by['window-blind-mutation5'])['assert'], {'ap_window', 'ai_slack'})

    def test_property_names_match_the_harness(self):
        text = (HERE / 'rate_limiter_formal.sv').read_text()
        labels = set(re.findall(r'\b((?:ap|ai|cp|as)_\w+):', text))
        self.assertEqual(labels, F.WINDOW | F.LEMMA | F.STEPS | F.COVERS | {'as_initial_reset'})

    def test_window_proof_closes_and_the_window_bound_refutes_an_over_granting_mutant(self):
        self.assertTrue(FORMAL, 'the formal tools (yowasp-sby, yowasp-yosys, yowasp-yosys-smtbmc, z3) must be on PATH')
        with tempfile.TemporaryDirectory() as tmp:
            for task, outcome in (('window-proof', 'pass'), ('window-refutes-mutation3', 'detected')):
                out = Path(tmp) / task
                result = subprocess.run([sys.executable, str(HERE / 'formal.py'), '--configuration', 'f2d2r3', '--task', task,
                                         '--out', str(out)], capture_output=True, text=True, timeout=300)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertEqual(read_json(out / f'f2d2r3-{task}/result.json')['outcome'], outcome)


if __name__ == '__main__':
    unittest.main()

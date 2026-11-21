import importlib.util
from pathlib import Path
import re, shutil, subprocess, sys, tempfile, unittest
from types import SimpleNamespace
import xml.etree.ElementTree as ET
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'local-common'))
from local_test_support import load_example, read_json, run_example, simulate_vectors

P = load_example('local-long-counter')
HERE = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('long_counter_formal_plan', HERE / 'formal.py')
F = importlib.util.module_from_spec(spec)
spec.loader.exec_module(F)
ICARUS = shutil.which('iverilog') and shutil.which('vvp')
FORMAL = all(shutil.which(tool) for tool in ('yowasp-sby', 'yowasp-yosys', 'yowasp-yosys-smtbmc', 'z3'))
GOALS = 17
# Mutants that the fixed plan of each configuration detects.
SEEN = {'narrow8': {1, 2}, 'scaled8': {1, 2, 4, 6}, 'preload32': {1, 2, 3, 4, 5, 6}, 'force32': {1, 2, 3, 4, 6}}
EMULATE_5 = {'long_counter.sv': [('(load && MUTATION != 5)', '1\'b0')]}   # the test load leaves carry_q alone


def carries(rows, width):
    """Bit positions k whose carry (2**k - 1 to 2**k) the rows take by counting."""
    found, before = set(), 0
    for rst_n, enable, clear, op, value, limit, count, tick in rows:
        if rst_n and enable and not clear and op in (P.NONE, P.LOAD_IGNORED) and not tick:
            found |= {k for k in range(1, width) if before == (1 << k) - 1 and count == 1 << k}
        before = count
    return found


class PlanTests(unittest.TestCase):
    def test_model_counts_returns_to_zero_at_the_limit_and_goes_around_above_it(self):
        m = P.Model(4)
        self.assertEqual([m.step(enable=1, limit=2)[6:] for _ in range(4)], [[1, 0], [2, 0], [0, 1], [1, 0]])
        m.step(op=P.LOAD, value=14)
        self.assertEqual([m.step(enable=1, limit=2)[6:] for _ in range(5)], [[15, 0], [0, 0], [1, 0], [2, 0], [0, 1]])
        self.assertEqual(m.step(enable=1, limit=0)[6:], [0, 1])          # limit 0 ticks on every enabled cycle
        m.step(op=P.LOAD, value=2)
        self.assertEqual(m.step(limit=2)[6:], [2, 0])                    # paused on the limit
        self.assertEqual(m.step(enable=1, clear=1, limit=2)[6:], [0, 0])  # clear wins, without a tick
        m.step(op=P.LOAD, value=7)
        self.assertEqual(m.step(op=P.LOAD, value=9, enable=1, limit=7)[6:], [9, 0])  # load wins, without a tick
        self.assertEqual(m.step(op=P.LOAD_IGNORED, value=3)[6:], [9, 0])
        self.assertEqual(m.step(rst_n=0, enable=1)[6:], [0, 0])
        with self.assertRaises(ValueError):
            m.step(op=P.FORCE, value=1, enable=1)

    def test_every_plan_takes_every_carry_and_only_the_wide_ones_jump(self):
        for name, parameters in P.CONFIGS.items():
            width, method = parameters['WIDTH'], parameters['METHOD']
            rows = P.boundary_rows(width, method)
            self.assertEqual(carries(rows, width), set(range(1, width)), name)
            jumps = [r[3] for r in rows if r[3] in (P.LOAD, P.FORCE, P.FORCE_COUNT_ONLY)]
            if method == 0:
                self.assertEqual(jumps, [P.LOAD, P.LOAD])            # only the test of the load path itself
            else:
                self.assertEqual(jumps.count(P.JUMP[method]), len(jumps) - (2 if method == 2 else 0))
                self.assertGreater(len(jumps), width)
            self.assertLess(len(rows), 1000, name)                   # counting to bit 31 would take 2**31 rows
            self.assertEqual(P.counts(rows)['jumps'], len(jumps))

    def test_random_rows_shorten_the_test_only_by_the_method_of_the_configuration(self):
        for name, parameters in P.CONFIGS.items():
            rows = P.random_rows(parameters['WIDTH'], parameters['METHOD'], 17, 400)
            used = {r[3] for r in rows} - {P.NONE, P.LOAD_IGNORED}
            self.assertEqual(used, {P.JUMP[parameters['METHOD']]} if parameters['METHOD'] else set(), name)

    def test_seed_reproduction(self):
        args = SimpleNamespace(profile='smoke', seed=17, iterations=50, demo_bug=0)
        parameters = P.CONFIGS['preload32']
        first = P.make_cases(args, parameters)
        self.assertEqual(first, P.make_cases(args, parameters))
        args.seed = 18
        self.assertNotEqual(first, P.make_cases(args, parameters))

    def test_cases_follow_the_table_of_visible_mutants(self):
        args = SimpleNamespace(profile='nightly', seed=17, iterations=5, demo_bug=0)
        for name, parameters in P.CONFIGS.items():
            self.assertEqual(P.visible(parameters), SEEN[name])
            ids = [c['id'] for c in P.make_cases(args, parameters)]
            expected = ['boundaries', 'random-seed17', 'random-seed18', 'random-seed19'] + [
                ('detect' if m in SEEN[name] else 'survive') + f'-mutation{m}' for m in range(1, 7)]
            self.assertEqual(ids, expected + (['careless-force'] if name == 'force32' else []))


@unittest.skipUnless(ICARUS, 'Icarus required')
class RtlTests(unittest.TestCase):
    def test_real_rtl_all_configurations_mutants_and_survivors(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / 'out'
            result = run_example('local-long-counter', out, '--iterations', '30')
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            summary = read_json(out / 'summary.json')
            detected = sum(len(s) for s in SEEN.values())
            survived = 6 * len(SEEN) - detected
            self.assertEqual((summary['success'], summary['complete'], summary['planned']), (True, True, 8 * len(SEEN) + 1))
            self.assertEqual(summary['mutations_detected'], detected + 1)   # plus the false alarm of the careless force
            self.assertEqual(summary['diagnostics_pass'], survived)
            coverage = read_json(out / 'coverage.json')
            self.assertEqual({k: (v['hit'], v['missing']) for k, v in coverage.items()}, {k: (GOALS, []) for k in SEEN})
            suite = ET.parse(out / 'junit.xml').getroot()
            self.assertEqual((suite.get('tests'), suite.get('failures'), suite.get('errors')), (str(8 * len(SEEN) + 1 + len(SEEN)), '0', '0'))
            for name, seen in SEEN.items():
                for m in range(1, 7):
                    kind = 'detect' if m in seen else 'survive'
                    record = read_json(out / f'{name}-{kind}-mutation{m}/result.json')
                    self.assertEqual(record['status'], 'detected' if m in seen else 'pass', (name, m))
                    self.assertEqual(record['credited_coverage'], [])
                    if m not in seen:   # the survivor still shows every goal: coverage does not tell the plans apart
                        self.assertEqual(len(record['observed_coverage']), GOALS, (name, m))
            self.assertIn('CNT_COUNT', read_json(out / 'force32-careless-force/result.json')['message'])

    def test_demo_faults_fail_where_visible_and_pass_at_the_narrow_width(self):
        with tempfile.TemporaryDirectory() as tmp:
            for fault in range(1, 7):
                out = Path(tmp) / f'p{fault}'
                result = run_example('local-long-counter', out, '--configuration', 'preload32', '--iterations', '2', '--demo-bug', str(fault))
                self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                self.assertEqual(read_json(out / 'preload32-boundaries/result.json')['status'], 'fail')
            out = Path(tmp) / 'n3'
            result = run_example('local-long-counter', out, '--configuration', 'narrow8', '--iterations', '2', '--demo-bug', '3')
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(read_json(out / 'narrow8-boundaries/result.json')['status'], 'pass')

    def test_force_of_count_and_flag_passes_where_force_of_count_alone_fails(self):
        force32 = P.CONFIGS['force32']
        careless = P.careless_force_rows(32, 16)
        self.assertIn('CHECK_FAIL CNT_COUNT', simulate_vectors(P, careless, force32).stdout)
        careful = [[r[0], r[1], r[2], P.FORCE if r[3] == P.FORCE_COUNT_ONLY else r[3], *r[4:]] for r in careless]
        self.assertIn('RESULT PASS checks=5', simulate_vectors(P, careful, force32).stdout)

    def test_force_rows_are_rejected_outside_the_force_configuration(self):
        result = simulate_vectors(P, P.careless_force_rows(32, 16), P.CONFIGS['preload32'])
        self.assertIn('operation not available', result.stdout + result.stderr)
        self.assertNotIn('RESULT PASS', result.stdout)

    def test_stale_carry_flag_shows_only_when_the_load_lands_on_a_carry(self):
        preload32 = P.CONFIGS['preload32']

        def rows(value):
            p = P.Plan(32, 1)
            p.cycle(2, rst_n=0)
            p.cycle(op=P.LOAD, value=value)
            p.cycle(3, enable=1)
            return p.rows
        self.assertIn('RESULT PASS', simulate_vectors(P, rows(0xFFFE), preload32, EMULATE_5).stdout)
        self.assertIn('CHECK_FAIL CNT_COUNT', simulate_vectors(P, rows(0xFFFF), preload32, EMULATE_5).stdout)
        self.assertIn('RESULT PASS', simulate_vectors(P, rows(0xFFFF), preload32).stdout)

    def test_checker_reports_a_wrong_tick_a_wrong_load_and_an_unknown_count(self):
        rows = P.boundary_rows(32, 1)
        parameters = P.CONFIGS['preload32']
        for edits, label in (([('tick  <= rst_n &&', 'tick  <= 1\'b0 &&')], 'CNT_TICK'),
                             ([('else if (load) count_d = test_value;', 'else if (load) count_d = test_value ^ 32\'d4;')], 'CNT_LOAD'),
                             ([('count <= count_d;', 'count <= enable ? count_d : \'x;')], 'CNT_COUNT')):
            self.assertIn('CHECK_FAIL ' + label, simulate_vectors(P, rows, parameters, {'long_counter.sv': edits}).stdout, label)


class FormalPlanTests(unittest.TestCase):
    def test_plan_has_two_proofs_a_cover_task_one_task_per_mutant_and_the_bounded_miss(self):
        plan = F.plan(F.BOUND, 0)
        self.assertEqual([c['id'] for c in plan], ['counter-proof', 'functional-proof', 'scenario-cover'] +
                         [f'detect-mutation{m}' for m in range(1, 7)] + ['bounded-misses-mutation3'])
        self.assertEqual([c['depth'] for c in plan[:2]], [F.PROOF_DEPTH] * 2)
        self.assertEqual(plan[1]['parameters'], dict(MUTATION=0, FUNCTIONAL=1))
        self.assertEqual(plan[-1]['parameters'], dict(MUTATION=3, FUNCTIONAL=1))
        self.assertEqual((plan[-1]['mode'], plan[-1]['expect'], plan[-1]['category']), ('bmc', 'PASS', 'diagnostic'))
        self.assertEqual(F.properties(F.CONFIGS['w32'], plan[1])['assume'], {'as_initial_reset', 'as_functional'})
        self.assertEqual(F.properties(F.CONFIGS['w32'], plan[0])['assume'], {'as_initial_reset'})
        self.assertEqual(F.plan(F.BOUND, 2)[0]['parameters']['MUTATION'], 2)
        self.assertTrue(set(F.FAILURES.values()) <= F.ASSERTS)

    def test_property_names_match_the_sources(self):
        text = ''.join(p.read_text() for p in F.SOURCES)
        labels = set(re.findall(r'\b((?:ap|ai|cp|as)_\w+):', text))
        self.assertEqual(labels, F.ASSERTS | F.COVERS | {'as_initial_reset', 'as_functional'})
        # Both configurations have the second cut that mutant 3 changes.
        self.assertTrue(all(c['WIDTH'] > c['SPLIT'] + 8 for c in F.CONFIGS.values()))

    @unittest.skipUnless(FORMAL, 'formal tools required')
    def test_proof_completes_a_mutant_is_refuted_and_the_bounded_check_misses_it_without_the_test_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            for task, outcome in (('counter-proof', 'pass'), ('detect-mutation3', 'detected'), ('bounded-misses-mutation3', 'pass')):
                out = Path(tmp) / task
                result = subprocess.run([sys.executable, str(HERE / 'formal.py'), '--configuration', 'w32', '--task', task,
                                         '--out', str(out)], capture_output=True, text=True, timeout=300)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertEqual(read_json(out / f'w32-{task}/result.json')['outcome'], outcome)


if __name__ == '__main__':
    unittest.main()

from pathlib import Path
import json
import shutil
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'local-common'))
from local_test_support import load_example

R = load_example('local-sva-patterns')
M = R.M
HERE = R.HERE
EXPECTED = json.loads((HERE / 'expected.json').read_text())
TOOLS = ('verilator', 'yowasp-sby', 'yowasp-yosys', 'yowasp-yosys-smtbmc', 'yowasp-yosys-witness', 'z3')


def args(profile='smoke', seed=17):
    return SimpleNamespace(profile=profile, seed=seed)


class Plan(unittest.TestCase):
    def test_plan_is_fixed_and_nightly_adds_seeds_only(self):
        smoke, nightly = R.plan_ids(args()), R.plan_ids(args('nightly'))
        self.assertEqual((len(smoke), len(nightly)), (79, 95))
        self.assertEqual(len(set(nightly)), len(nightly))
        self.assertTrue(set(smoke) <= set(nightly))
        self.assertTrue(all('-seed' in name for name in set(nightly) - set(smoke)))

    def test_every_pattern_has_one_mutant_and_three_fixed_traces(self):
        self.assertEqual(sorted(R.MUTANTS.values()), sorted(M.PATTERNS))
        self.assertEqual(set(M.fixed_traces()), {(p, k) for p in M.PATTERNS for k in M.KINDS})
        self.assertEqual(set(R.PROVED) | {'nodup', 'order', 'cross'}, set(M.PATTERNS))

    def test_requirements_own_every_check_once(self):
        for profile in ('smoke', 'nightly'):
            ids = R.plan_ids(args(profile))
            evidence = SimpleNamespace(expected=ids, results=[dict(id=i, status='pass') for i in ids if i != 'requirements'],
                                       check=lambda name, ok, detail: (ok, detail))
            ok, detail = R.requirements(evidence)
            self.assertTrue(ok, detail)
            self.assertEqual((detail['requirements'], detail['goals']), (9, 78))

    def test_an_unmet_goal_and_an_unowned_check_are_reported(self):
        ids = R.plan_ids(args())
        results = [dict(id=i, status='fail' if i == 'sby-within-vacuous' else 'pass') for i in ids if i != 'requirements']
        check = lambda name, ok, detail: (ok, detail)
        ok, detail = R.requirements(SimpleNamespace(expected=ids, results=results, check=check))
        self.assertFalse(ok)
        self.assertEqual(detail['problems'], ['PAT-03: goal sby-within-vacuous not met'])
        ok, detail = R.requirements(SimpleNamespace(expected=ids + ['extra-check'], results=results, check=check))
        self.assertIn('checks without a requirement: extra-check', detail['problems'])


class Model(unittest.TestCase):
    def test_hand_table_and_model_agree_on_every_fixed_trace(self):
        for (pattern, kind), rows in M.fixed_traces().items():
            fails, hits = M.evaluate(pattern, rows)
            self.assertEqual((fails, len(hits)), (EXPECTED[pattern][kind]['fails'], EXPECTED[pattern][kind]['hits']), (pattern, kind))

    def test_each_kind_has_its_shape(self):
        for pattern in M.PATTERNS:
            entry = EXPECTED[pattern]
            self.assertTrue(entry['pass']['hits'] > 0 and not entry['pass']['fails'], pattern)
            self.assertTrue(entry['violation']['fails'], pattern)
            self.assertEqual(entry['vacuous'], dict(fails=[], hits=0), pattern)

    def test_boundaries_of_the_definitions(self):
        rows = M.blank(); M.put(rows, 2, v0=1, v1=1); M.put(rows, 5, v1=1)          # ack in the request cycle does not count
        self.assertEqual(M.evaluate('within', rows)[0], [])
        rows = M.blank(); M.put(rows, 2, v0=1, v1=1); M.put(rows, 6, v1=1)
        self.assertEqual(M.evaluate('within', rows)[0], [5])
        rows = M.blank(); M.put(rows, 2, v0=1, d0=1); M.put(rows, 3, v0=1, v1=1, d0=1, d1=1)  # start with its own completion
        self.assertEqual(M.evaluate('nodup', rows)[0], [3])
        rows = M.blank(); M.put(rows, 2, v0=1, d0=1); M.put(rows, 3, v1=1, d1=1); M.put(rows, 4, v0=1, d0=1)
        self.assertEqual(M.evaluate('nodup', rows)[0], [])
        rows = M.blank(True); M.put(rows, 4, v0=1); M.put(rows, 10, v1=1)             # the coinciding clk_b edge is not counted
        self.assertEqual(M.evaluate('cross', rows), ([], [6]))
        rows = M.blank(True); M.put(rows, 4, v0=1); M.put(rows, 12, v1=1)
        self.assertEqual(M.evaluate('cross', rows)[0], [10])

    def test_order_follows_one_item_at_a_time(self):
        rows = M.blank(); M.put(rows, 2, v0=1, d0=1); M.put(rows, 3, v0=1, d0=2); M.put(rows, 4, v1=1, d1=1); M.put(rows, 5, v1=1, d1=9)
        self.assertEqual(M.evaluate('order', rows), ([], [2]))                       # the second item was not followed
        rows = M.blank(); M.put(rows, 2, v0=1, d0=1); M.put(rows, 3, v1=1, d1=1); M.put(rows, 4, v0=1, d0=2); M.put(rows, 5, v1=1, d1=9)
        self.assertEqual(M.evaluate('order', rows), ([5], [2, 4]))

    def test_random_traces_without_faults_never_violate(self):
        for pattern in M.PATTERNS:
            for seed in range(200):
                fails, hits = M.evaluate(pattern, M.random_trace(pattern, seed, False))
                self.assertEqual(fails, [], (pattern, seed))
            self.assertTrue(any(M.evaluate(pattern, M.random_trace(pattern, seed, True))[0] for seed in range(20)), pattern)
            self.assertEqual(M.random_trace(pattern, 3, True), M.random_trace(pattern, 3, True))

    def test_trace_encoding_matches_the_harness_layout(self):
        row = dict(ea=1, eb=0, rst=1, v0=1, v1=0, d0=0xA, d1=0x5)
        self.assertEqual(M.encode([row]), '16a5\n')
        self.assertEqual(len(M.encode(M.blank()).splitlines()), M.LEN)
        self.assertIn(f'localparam LEN = {M.LEN};', (HERE / 'tb/trace_tb.sv').read_text())

    def test_queue_model_refuses_duplicates_and_keeps_order(self):
        q = M.Queue(lat=1)
        self.assertEqual(q.step(1, 2, 0x11, 0), (1, 0, 0, 0))
        self.assertEqual(q.step(1, 2, 0x22, 0), (0, 0, 2, 0x11))        # same identifier refused, delay running
        self.assertEqual(q.step(1, 3, 0x33, 0), (1, 1, 2, 0x11))
        self.assertEqual(q.step(0, 0, 0, 1), (1, 1, 2, 0x11))           # leaves; the next head starts its delay
        self.assertEqual(q.step(1, 2, 0x44, 1), (1, 0, 3, 0x33))        # identifier 2 is free again
        self.assertEqual(q.step(0, 0, 0, 1), (1, 1, 3, 0x33))
        q = M.Queue()
        for i in range(4):
            self.assertEqual(q.step(1, i, i, 0)[0], 1)
        self.assertEqual(q.step(1, 0, 9, 0)[0], 0)                      # full

    def test_queue_vectors_carry_stimulus_and_expectation(self):
        rows = M.queue_stimulus(None, 0)
        lines = M.queue_vectors(rows)
        self.assertEqual(len(lines), len(rows))
        self.assertTrue(all(len(line) == 7 and int(line, 16) < 1 << 25 for line in lines))
        self.assertEqual(M.queue_stimulus(5, 30), M.queue_stimulus(5, 30))
        self.assertEqual(len(M.queue_stimulus(5, 30)), 42)


class Binding(unittest.TestCase):
    def test_one_bind_file_feeds_both_tools(self):
        self.assertEqual(sorted(n for _, _, n in R.bindings(True)), sorted(f'u_{p}_aux' for p in M.PATTERNS))
        self.assertEqual(sorted(n for _, _, n in R.bindings(False)), sorted(f'u_{p}_sva' for p in R.ASSERTION_FORMS))
        self.assertEqual({m for m, _, _ in R.bindings(True)}, {'tagged_queue', 'event_cross'})

    def test_rewrite_adds_instances_to_a_copy_only(self):
        before = R.RTL['tagged_queue'].read_text()
        text, names = R.rewrite('tagged_queue', ['u_hold_aux'])
        self.assertEqual(names, ['u_hold_aux'])
        self.assertEqual(R.RTL['tagged_queue'].read_text(), before)
        self.assertIn('pat_hold_aux #(.W(DATA_W + 2)) u_hold_aux (', text)
        self.assertNotIn('bind ', text)
        self.assertNotIn('u_order_aux', text)
        self.assertNotIn('i_count', text)
        self.assertTrue(text.rstrip().endswith('endmodule'))
        self.assertEqual(text.replace(text[text.index('  // Instances rewritten'):text.rindex('endmodule')], ''), before)
        self.assertIn('i_pointer', R.rewrite('tagged_queue', ['u_hold_aux'], invariants=True)[0])
        self.assertEqual(len(R.rewrite('tagged_queue')[1]), 6)
        self.assertEqual(R.rewrite('event_cross')[1], ['u_cross_aux'])

    def test_rewrite_rejects_a_binding_that_does_not_exist(self):
        with self.assertRaises(ValueError):
            R.rewrite('tagged_queue', ['u_cross_aux'])
        with self.assertRaises(ValueError):
            R.rewrite('missing_module')

    def test_library_forms_exist_for_every_binding(self):
        library = ''.join(path.read_text() for path in R.LIBRARY)
        for _, body, _ in R.bindings(True) + R.bindings(False):
            self.assertIn('module ' + body.split()[0] + ' ', library)
        guarded = [path.name for path in R.LIBRARY if 'assert property' in path.read_text() and '`ifndef FORMAL' not in path.read_text()]
        self.assertEqual(guarded, [])                                    # Yosys must never see a concurrent assertion


class Parsing(unittest.TestCase):
    def test_reports_are_grouped_by_pattern_form_and_kind(self):
        log = ('PAT_HIT dut_tb.u_queue.u_hold_aux 30\nPAT_FAIL dut_tb.u_queue.u_hold_sva.ap 50\n'
               'PAT_FAIL dut_tb.u_queue.u_nodup_sva.g_id[3].ap 70\nPAT_FAIL dut_tb.u_queue.u_nodup_sva.g_id[1].ap 30\nnoise\n')
        self.assertEqual(R.reports(log), {('hold', 'aux', 'HIT'): [30], ('hold', 'sva', 'FAIL'): [50], ('nodup', 'sva', 'FAIL'): [30, 70]})
        self.assertEqual(R.reports('PAT_FAIL trace_tb.u.u_within_aux 105\n', R.trace_tick), {('within', 'aux', 'FAIL'): [5]})
        with self.assertRaises(ValueError):
            R.reports('PAT_FAIL trace_tb.u.other 105\n')
        with self.assertRaises(ValueError):
            R.reports('PAT_FAIL trace_tb.u.u_within_aux 110\n', R.trace_tick)

    def test_sby_logs_give_status_step_and_cover(self):
        fail = ('SBY [task] summary:   failed assertion trace_top.u.u_hold_aux.a_pattern at pat_report.svh:5.5-5.29 step 7\n'
                'SBY [task] DONE (FAIL, rc=2)\n')
        self.assertEqual(R.parse_sby(fail), dict(status='FAIL', failed='trace_top.u.u_hold_aux.a_pattern', step=7, reached={}, unreached=set(), induction=False))
        cover = ('engine_0: ##   0:00:00  Reached cover statement in step 5 at trace_top.u.u_hold_aux: c_antecedent\n'
                 'engine_0: ##   0:00:00  Unreached cover statement at trace_top.u.u_pipe_aux: c_antecedent\nDONE (FAIL, rc=2)\n')
        parsed = R.parse_sby(cover)
        self.assertEqual((parsed['reached'], parsed['unreached']), ({'trace_top.u.u_hold_aux': 5}, {'trace_top.u.u_pipe_aux'}))
        self.assertTrue(R.parse_sby('summary: successful proof by k-induction.\nDONE (PASS, rc=0)\n')['induction'])
        self.assertEqual(R.parse_sby('DONE (PASS, rc=0)\n', error='timeout')['status'], 'ERROR')
        self.assertEqual(R.parse_sby('no result')['status'], 'ERROR')
        self.assertEqual(R.parse_sby('DONE (PASS, rc=0)\nDONE (PASS, rc=0)\n')['status'], 'ERROR')

    def test_probe_table_never_excuses_a_form_the_library_uses(self):
        table = json.loads((HERE / 'probes/expected.json').read_text())
        self.assertEqual(set(table['acceptance']), set(R.ACCEPT_CASES))
        self.assertEqual(set(table['evaluation']), set(R.EVAL_CASES))
        for case, spec in table['evaluation'].items():
            self.assertNotEqual(spec.get('used_by_library', False), 'recorded' in spec, case)
            self.assertNotEqual(spec['correct'], spec.get('recorded'), case)
        source = (HERE / 'probes/eval.sv').read_text()
        for case in R.EVAL_CASES:
            self.assertIn(case, source)


class RealRun(unittest.TestCase):
    def test_smoke_passes_and_a_missing_tool_fails(self):
        self.assertEqual([name for name in TOOLS if not shutil.which(name)], [])
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / 'out'
            run = subprocess.run([sys.executable, str(HERE / 'run.py'), '--out', str(out)], capture_output=True, text=True)
            self.assertEqual(run.returncode, 0, run.stdout[-2000:] + run.stderr[-2000:])
            summary = json.loads((out / 'summary.json').read_text())
            self.assertTrue(summary['success'] and summary['complete'])
            self.assertEqual(summary['planned'], 79)
            details = {r['id']: r['detail'] for r in summary['results']}
            self.assertEqual(details['dut-mutant6']['model_comparison'], 'not noticed')
            self.assertEqual(details['formal-clean-hold']['method'], 'k-induction with internal invariants')
            self.assertTrue(details['formal-clean-order']['method'].startswith('bounded'))
            self.assertEqual((out / 'junit.xml').read_text().count('<testcase'), 79)
            broken = subprocess.run([sys.executable, str(HERE / 'run.py'), '--verilator', 'no-such-verilator', '--out', str(Path(tmp) / 'broken')],
                                    capture_output=True, text=True)
            self.assertEqual(broken.returncode, 1)
            failed = json.loads((Path(tmp) / 'broken/summary.json').read_text())
            self.assertFalse(failed['success'])
            self.assertEqual(sum(r['status'] == 'fail' for r in failed['results']), 79)


if __name__ == '__main__':
    unittest.main()

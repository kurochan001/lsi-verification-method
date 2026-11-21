import copy
import importlib.util
import json
from pathlib import Path
import random
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET

HERE = Path(__file__).resolve().parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


R = load('closure_trend_run', HERE / 'run.py')
T, C = R.T, R.C
HISTORY = T.load(R.DATA)
EXPECTED = json.loads((HERE / 'expected.json').read_text(encoding='utf-8'))


class TrendTest(unittest.TestCase):
    def test_the_fixed_history_is_valid_and_both_counts_agree(self):
        self.assertEqual(T.validate(HISTORY), EXPECTED['campaigns'])
        self.assertIsNone(R.first_difference(T.build(HISTORY), C.recount(R.DATA)))

    def test_the_numbers_counted_by_hand_are_reproduced(self):
        self.assertEqual(R.hand_counts(T.build(HISTORY), EXPECTED), {})

    def test_a_changed_hand_count_is_reported(self):
        expected = dict(EXPECTED, open=[0] * len(EXPECTED['open']))
        self.assertEqual(set(R.hand_counts(T.build(HISTORY), expected)), {'open'})

    def test_every_counting_error_is_found_at_the_planned_place(self):
        independent = C.recount(R.DATA)
        for mutation, (_, label) in R.MUTANTS.items():
            with self.subTest(mutation=mutation):
                self.assertEqual(R.first_difference(T.build(HISTORY, mutation=mutation), independent), label)

    def test_every_broken_input_is_refused_with_its_own_label(self):
        for name, edit in R.REJECTS.items():
            with self.subTest(name=name):
                broken = copy.deepcopy(HISTORY)
                edit(broken)
                with self.assertRaises(T.InputError) as caught:
                    T.build(broken)
                self.assertTrue(str(caught.exception).startswith(f'CT_INPUT {name}:'), str(caught.exception))

    def test_time_limits_and_jobs_that_never_started_are_not_verdicts(self):
        base = dict(id='x', success=False, started=True, message='checker failure')
        self.assertEqual(T.outcome(base), 'fail')
        self.assertEqual(C.verdict_of(base), 'fail')
        for change in (dict(message='job timeout after 1 s'), dict(message='command timeout after 60 s'), dict(started=False)):
            with self.subTest(change=change):
                self.assertEqual(T.outcome(dict(base, **change)), 'incomplete')
                self.assertEqual(C.verdict_of(dict(base, **change)), 'incomplete')
        self.assertEqual(T.outcome(dict(base, success=True, message='planned execution valid')), 'pass')

    def test_a_different_seed_is_a_different_plan(self):
        rows = {r['campaign']: r for r in T.build(HISTORY)['rows']}
        self.assertEqual((rows['c08']['commit'], rows['c09']['commit']), ('1a00007', '1a00007'))
        self.assertNotEqual(rows['c08']['seed'], rows['c09']['seed'])
        self.assertEqual(rows['c09']['flaky'], rows['c08']['flaky'])

    def test_markdown_reads_back_and_a_changed_cell_is_noticed(self):
        trend = T.build(HISTORY)
        text = T.render_markdown(trend)
        self.assertEqual(R.parse_markdown(text), trend['rows'])
        line = next(l for l in text.splitlines() if l.startswith('| c05 |'))
        changed = text.replace(line, line.replace('| 4 |', '| 5 |', 1))
        self.assertNotEqual(R.parse_markdown(changed), trend['rows'])

    def test_the_closure_check_lists_only_the_unmet_criteria(self):
        self.assertEqual(T.build(HISTORY)['summary']['verdict'], dict(ready=False, reasons=['open-defects']))
        relaxed = copy.deepcopy(HISTORY)
        relaxed['criteria']['max_open'] = 1
        for trend in (T.build(relaxed), R.recount_memory(relaxed)):
            self.assertEqual(trend['summary']['verdict'], dict(ready=True, reasons=[]))

    def test_generated_histories_agree_and_exercise_every_feature(self):
        rng = random.Random(5)
        seen = dict(flaky=0, reopened=0, denominator=0, incomplete=0, environment=0)
        for _ in range(150):
            history = R.random_history(rng)
            T.validate(history)
            trend = T.build(history)
            self.assertIsNone(R.first_difference(trend, R.recount_memory(history)))
            seen['flaky'] += bool(trend['summary']['flaky'])
            seen['reopened'] += any(r['reopened'] for r in trend['rows'])
            seen['denominator'] += bool(trend['summary']['denominator_changes'])
            seen['incomplete'] += any(r['incomplete'] for r in trend['rows'])
            seen['environment'] += trend['summary']['environment_issues'] > 0
        self.assertTrue(all(seen.values()), seen)

    def test_the_requirement_goals_are_planned_checks(self):
        catalog = json.loads((HERE / 'requirements.json').read_text(encoding='utf-8'))
        goals = {g for r in catalog['requirements'] for g in r['goals']}
        planned = {'inventory', 'trend-table', 'recount', 'markdown-roundtrip', 'hand-counts', 'requirements',
                   *[f'reject-{n}' for n in R.REJECTS], *[f'mutation{m}' for m in R.MUTANTS], 'random-01', 'random-02', 'random-03'}
        self.assertLessEqual(goals, planned)
        self.assertEqual(len({r['id'] for r in catalog['requirements']}), len(catalog['requirements']))


class RunnerTest(unittest.TestCase):
    def test_smoke_and_nightly_pass_with_their_planned_checks(self):
        with tempfile.TemporaryDirectory() as tmp:
            for profile, planned in (('smoke', 25), ('nightly', 34)):
                out = Path(tmp) / profile
                run = subprocess.run([sys.executable, str(HERE / 'run.py'), '--profile', profile, '--out', str(out)],
                                     capture_output=True, text=True)
                self.assertEqual(run.returncode, 0, run.stdout[-2000:] + run.stderr[-2000:])
                summary = json.loads((out / 'summary.json').read_text())
                self.assertTrue(summary['success'] and summary['complete'])
                self.assertEqual(summary['planned'], planned)
                self.assertEqual(len(list(ET.parse(out / 'junit.xml').getroot().iter('testcase'))), planned)
                self.assertTrue((out / 'trend.md').read_text(encoding='utf-8').startswith('# 収束の傾向'))
            again = subprocess.run([sys.executable, str(HERE / 'run.py'), '--out', str(Path(tmp) / 'smoke')],
                                   capture_output=True, text=True)
            self.assertEqual(again.returncode, 2)


if __name__ == '__main__':
    unittest.main()

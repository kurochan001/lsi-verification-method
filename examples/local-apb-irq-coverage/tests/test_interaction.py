"""Check the observed/checked distinction, timing correlation, selection and real RTL gates."""
import importlib.util
import json
import re
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET

HERE = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('test_apb_interaction', HERE / 'run.py')
R = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(R)
M = R.M


class InteractionModelTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='apb-cross-model-')
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name)

    def test_model_counts_and_per_bit_pending_zero_are_required(self):
        model = M.load_model(HERE / 'model.json')
        groups = M.required_groups(model, {'reset/recovery'})
        self.assertEqual({k: len(v) for k, v in groups.items()},
                         dict(pairwise=96, priority=32, temporal=48, legacy=1))
        self.assertIn('pairwise/bit3/pending0/event1', groups['pairwise'])
        self.assertIn('temporal/bit2/pending1/mask0/offset-1', groups['temporal'])
        self.assertEqual(len(R.full4_goals()), 64)
        # Independent port snapshot: bit2 is pending=1, mask=1, clear=1, event=0.
        snapshot = dict(cycle=7, rst=1, sel=1, enable=1, ready=1, error=0,
                        write=1, address=8, data=4, event=2, pre_config=5, pre_pending=6)
        actual = M.collect([snapshot])
        self.assertEqual({g for g in actual if g.startswith('pairwise/bit2/')}, {
            'pairwise/bit2/pending1/mask1', 'pairwise/bit2/pending1/clear1',
            'pairwise/bit2/pending1/event0', 'pairwise/bit2/mask1/clear1',
            'pairwise/bit2/mask1/event0', 'pairwise/bit2/clear1/event0'})
        self.assertIn('priority/bit2/mask1/clear1/event0', actual)
        self.assertFalse(any(g.startswith('priority/bit0/') for g in actual))

    def test_model_cannot_lower_strength_or_remove_bits(self):
        original = json.loads((HERE / 'model.json').read_text())
        for key, value in (('bits', [0]), ('pairwise_strength', 1), ('event_offsets', [0]),
                           ('revision', 0), ('extra_goals', {'unknown': []})):
            with self.subTest(key=key):
                path = self.path / 'model.json'
                path.write_text(json.dumps(dict(original, **{key: value})))
                with self.assertRaises(ValueError):
                    M.load_model(path)

    def test_candidate_plans_cover_model_for_all_waits(self):
        model = M.load_model(HERE / 'model.json')
        for wait in (0, 1, 3):
            cases = R.make_candidates(wait, 'smoke', 17, 20)
            self.assertEqual(len(cases), 114)
            self.assertEqual(len({c['id'] for c in cases}), len(cases))
            union = {g for c in cases for g in c['planned_goals']}
            groups = M.required_groups(model, set())
            self.assertTrue(set().union(*groups.values()) <= union)
            self.assertTrue(R.full4_goals() <= union)
            for case in cases:
                if case['origin'] == 'temporal':
                    bit, pending, mask, offset = map(int, re.fullmatch(
                        r'time-b(\d)-p(\d)-m(\d)-offset(-?\d)', case['id']).groups())
                    target = f'temporal/bit{bit}/pending{pending}/mask{mask}/offset{offset}'
                    self.assertIn(target, case['planned_goals'])

    def test_profiles_are_reproducible_and_preserve_original_vectors(self):
        for profile, expected in (('smoke', 114), ('nightly', 116)):
            cases = R.make_candidates(3, profile, 73, 30)
            self.assertEqual(cases, R.make_candidates(3, profile, 73, 30))
            self.assertEqual(len(cases), expected)
            self.assertEqual(cases[0]['vectors'], R.APB.boundary_vectors(3))
            randoms = [c for c in cases if c['id'].startswith('existing-random')]
            self.assertEqual(len(randoms), 1 if profile == 'smoke' else 3)
            for i, case in enumerate(randoms):
                self.assertEqual(case['vectors'], R.APB.random_vectors(3, 73+i, 30))

    def temporal_records(self):
        case = next(c for c in R.make_candidates(1, 'smoke', 17, 1)
                    if c['id'] == 'time-b0-p0-m1-offset0')
        rows = M.project_vectors(case['vectors'], 1)
        clear = next(i for i, r in enumerate(rows) if M.clear_transfer(r))
        return case, rows, clear

    def test_timing_requires_same_window_stable_mask_and_single_event(self):
        _, rows, center = self.temporal_records()
        goal = 'temporal/bit0/pending0/mask1/offset0'
        self.assertIn(goal, M.collect(rows))
        for change in ('reset', 'mask', 'second-event', 'second-clear'):
            with self.subTest(change=change):
                copied = [dict(r) for r in rows]
                after = copied[center+1]
                if change == 'reset':
                    after['rst'] = 0
                elif change == 'mask':
                    after['post_config'] ^= 1
                elif change == 'second-event':
                    after['event'] |= 1
                else:
                    after.update(sel=1, enable=1, ready=1, write=1, address=8, data=1)
                self.assertNotIn(goal, M.collect(copied))

    def test_no_cross_from_setup_stall_error_or_non_w1c_transfer(self):
        _, rows, center = self.temporal_records()
        observation = rows[center]
        self.assertTrue(any(g.startswith('pairwise/') for g in M.collect([observation])))
        for override in (dict(rst=0), dict(enable=0), dict(ready=0), dict(error=1),
                         dict(write=0), dict(address=0)):
            self.assertFalse(M.collect([dict(observation, **override)]))

    def trace(self, rows, missing_last_ok=False):
        lines = []
        for r in rows:
            lines.append('OBS ' + str(r['cycle']) + ' ' +
                         ' '.join(format(r[k], 'x') for k in M.FIELDS))
            if not (missing_last_ok and r is rows[-1]):
                lines.append('OK ' + str(r['cycle']))
        p = self.path / 'trace.txt'
        p.write_text('\n'.join(lines) + '\n')
        return p

    def test_failed_case_keeps_arrival_but_never_credits_a_pass(self):
        case, rows, center = self.temporal_records()
        prefix = rows[:center+1]
        path = self.trace(prefix, missing_last_ok=True)
        actual = M.read_trace(path, case['vectors'], complete=False)
        hits = sorted(M.collect(actual))
        self.assertTrue(hits)
        record = dict(case_id='failed', status='fail', observed_goals=hits, credited_goals=[],
                      observed_cycles=len(actual), seconds=0, cpu_seconds=0)
        goals = {'pairwise': {g for g in hits if g.startswith('pairwise/')}}
        result = R.metrics([dict(case, id='failed')], [record], goals)
        self.assertGreater(result['groups']['pairwise']['observed'], 0)
        self.assertEqual(result['groups']['pairwise']['passed'], 0)
        self.assertFalse(result['success'])
        with self.assertRaises(ValueError):
            M.read_trace(path, case['vectors'], complete=True)

    def test_trace_rejects_duplicate_verdict_x_changed_inputs_or_missing_tail(self):
        case, rows, _ = self.temporal_records()
        path = self.trace(rows)
        original = path.read_text()
        for bad in (original.replace('OK 1\n', 'OK 1\nOK 1\n', 1),
                    original.replace('OBS 1 0 ', 'OBS 1 x ', 1),
                    original.replace('OBS 1 0 ', 'OBS 1 1 ', 1),
                    '\n'.join(original.splitlines()[:-2]) + '\n'):
            path.write_text(bad)
            with self.assertRaises(ValueError):
                M.read_trace(path, case['vectors'], complete=True)

    def test_no_success_from_empty_missing_or_duplicate_executions(self):
        case = dict(id='one', checks=1, planned_goals=['pairwise/target'])
        required = dict(pairwise={'pairwise/target'})
        empty = R.metrics([case], [], required)
        self.assertEqual(empty['groups']['pairwise']['planned'], 1)
        self.assertEqual(empty['groups']['pairwise']['observed'], 0)
        self.assertFalse(empty['success'])
        result = dict(case_id='one', observed_goals=['pairwise/target'],
                      credited_goals=['pairwise/target'], status='pass', observed_cycles=1,
                      seconds=0, cpu_seconds=0)
        self.assertFalse(R.metrics([case], [result, result], required)['success'])
        self.assertFalse(R.metrics([case], [dict(result, status='error')], required)['success'])
        self.assertEqual(R.metrics([case], [dict(result, status='error')], required)
                         ['groups']['pairwise']['passed'], 0)
        self.assertEqual(R.metrics([case], [dict(result, probe='clear-priority')], required)
                         ['groups']['pairwise']['passed'], 0)


class InteractionRtlTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not shutil.which('iverilog') or not shutil.which('vvp'):
            raise RuntimeError('Icarus Verilog is required for these integration tests')

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='apb-cross-rtl-')
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.index = 0

    def invoke(self, *options):
        self.index += 1
        out = self.directory / f'results-{self.index}'
        process = subprocess.run([sys.executable, str(HERE / 'run.py'), '--transactions', '20',
                                  '--out', str(out), *options], capture_output=True, text=True, timeout=90)
        self.assertTrue((out / 'junit.xml').exists(), process.stdout + process.stderr)
        summary = json.loads((out / 'summary.json').read_text())
        return process, out, summary, ET.parse(out / 'junit.xml').getroot()

    def test_real_all_waits_preserve_goals_and_six_defects_in_fresh_runs(self):
        process, out, summary, junit = self.invoke()
        self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
        self.assertTrue(summary['success'])
        self.assertEqual(len(junit.findall('testcase')), 61)
        coverage = json.loads((out / 'coverage.json').read_text())
        runs = json.loads((out / 'executions.json').read_text())
        for wait in (0, 1, 3):
            report = coverage[str(wait)]
            self.assertEqual(report['existing']['groups']['legacy']['passed'], 44 if wait == 0 else 45)
            for strategy in ('full', 'selected'):
                metrics = report['measurements'][strategy]
                for group, count in (('pairwise', 96), ('priority', 32), ('temporal', 48),
                                     ('legacy', 44 if wait == 0 else 45)):
                    self.assertEqual(metrics['groups'][group]['planned'], count)
                    self.assertEqual(metrics['groups'][group]['observed'], count)
                    self.assertEqual(metrics['groups'][group]['passed'], count)
                self.assertTrue(all(p['detected'] for p in metrics['mutations'].values()))
            self.assertLess(report['measurements']['selected']['case_count'],
                            report['measurements']['full']['case_count'])
            selected = [r for r in runs if r['wait'] == wait and r['phase'] == 'selected/normal']
            self.assertTrue(selected)
            for r in selected:
                self.assertTrue((out / r['id'] / 'trace.txt').is_file())
                self.assertEqual(r['observed_cycles'], r['checks'])
                self.assertTrue(all('mutation-' not in g for g in r['credited_goals']))
        self.assertEqual(junit.attrib['failures'], '0')

    def test_omitting_additions_fails_despite_original_coverage_pass(self):
        process, out, summary, _ = self.invoke('--wait', '1', '--omit-additions')
        self.assertEqual(process.returncode, 1)
        self.assertFalse(summary['success'])
        selected = json.loads((out / 'coverage.json').read_text())['1']['measurements']['selected']
        self.assertEqual(selected['groups']['legacy']['passed'], 45)
        self.assertTrue(selected['groups']['temporal']['missing'])

    def test_normal_priority_bug_keeps_observation_but_fails_learning(self):
        process, out, summary, _ = self.invoke('--wait', '0', '--demo-bug', 'clear-priority')
        self.assertEqual(process.returncode, 1)
        self.assertFalse(summary['success'])
        report = json.loads((out / 'coverage.json').read_text())['0']
        self.assertFalse(report['learning']['success'])
        self.assertEqual(report['learning']['groups']['priority']['passed'], 0)
        runs = json.loads((out / 'executions.json').read_text())
        self.assertTrue(any(r['status'] == 'fail' and r['observed_goals'] for r in runs))
        self.assertFalse(any(r['credited_goals'] for r in runs))

    def test_missing_observation_file_cannot_use_cover_log_or_plan(self):
        tool = self.directory / 'strip-trace'
        tool.write_text(f'#!{sys.executable}\nimport subprocess,sys\n'
                        f'args=[{shutil.which("vvp")!r},*[a for a in sys.argv[1:] if not a.startswith("+TRACE=")]]\n'
                        'p=subprocess.run(args)\nsys.exit(p.returncode)\n')
        tool.chmod(0o755)
        process, out, summary, _ = self.invoke('--wait', '1', '--vvp', str(tool))
        self.assertEqual(process.returncode, 1)
        self.assertFalse(summary['success'])
        report = json.loads((out / 'coverage.json').read_text())['1']['learning']
        self.assertEqual(report['groups']['pairwise']['planned'], 96)
        self.assertEqual(report['groups']['pairwise']['observed'], 0)
        self.assertEqual(report['groups']['pairwise']['passed'], 0)

    def test_unreachable_model_goal_fails_without_lowering_catalogue(self):
        model = json.loads((HERE / 'model.json').read_text())
        model['extra_goals'] = {'pairwise': ['pairwise/required/never']}
        path = self.directory / 'model.json'
        path.write_text(json.dumps(model))
        process, out, summary, _ = self.invoke('--wait', '3', '--model', str(path))
        self.assertEqual(process.returncode, 1)
        self.assertFalse(summary['success'])
        report = json.loads((out / 'coverage.json').read_text())['3']['learning']
        self.assertIn('pairwise/required/never', report['groups']['pairwise']['missing'])

    def test_build_failure_is_not_a_detected_mutation(self):
        process, out, summary, _ = self.invoke('--wait', '0', '--iverilog', str(self.directory/'absent'))
        self.assertEqual(process.returncode, 1)
        self.assertFalse(summary['success'])
        runs = json.loads((out / 'executions.json').read_text())
        self.assertTrue(all(r['status'] == 'error' for r in runs))
        self.assertFalse(any(r['status'] == 'detected' for r in runs))

    def test_output_is_never_overwritten(self):
        out = self.directory / 'existing'
        out.mkdir()
        sentinel = out / 'keep'
        sentinel.write_text('old evidence')
        result = subprocess.run([sys.executable, str(HERE / 'run.py'), '--out', str(out)],
                                capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 2)
        self.assertEqual(sentinel.read_text(), 'old evidence')


if __name__ == '__main__':
    unittest.main()

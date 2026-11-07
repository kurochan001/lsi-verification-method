"""Keep the simulator bridge strict about parameters, provenance and failures."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

PATH = Path(__file__).resolve().parents[1] / 'run_kirimasim_examples.py'
SPEC = importlib.util.spec_from_file_location('kirimasim_examples', PATH)
K = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(K)
RESULTS_PATH = PATH.with_name('kirimasim_results.py')
RESULTS_SPEC = importlib.util.spec_from_file_location('kirimasim_results', RESULTS_PATH)
R = importlib.util.module_from_spec(RESULTS_SPEC)
RESULTS_SPEC.loader.exec_module(R)


class KirimasimExamplesTests(unittest.TestCase):
    def test_parameters_preserve_top_hierarchy_and_reject_ambiguous_flags(self):
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / 'tb.sv'
            source.write_text('module tb; parameter DEPTH=3; endmodule\n')
            argv = ['-g2012', '-s', 'tb', '-o', str(Path(temp) / 'sim.vvp'),
                    '-Ptb.DEPTH=1', str(source)]
            top, _, parameters, _ = K.parse_compile(argv)
            self.assertEqual(top, 'tb')
            self.assertIn('defparam tb.DEPTH = 1;', K.parameter_source(parameters))
            for extra in (['-Pother.DEPTH=2'], ['-Ptb.DEPTH=2'], ['-s', 'other'],
                          ['-DIGNORE_CHECKS'], ['-Ptb.X=1; $finish;'], [str(source)]):
                with self.subTest(extra=extra), self.assertRaises(ValueError):
                    K.parse_compile(argv + extra)
            with self.assertRaises(ValueError):
                K.parse_compile(argv[1:])

    def test_wall_time_limit_is_whole_seconds_and_never_shortened(self):
        for timeout, expected in ((60, '60'), (60.0, '60'), (0.5, '1'), (1.5, '2')):
            with self.subTest(timeout=timeout):
                command = K.source_command('engine', 'tb', [Path('tb.sv')], Path('p.sv'), timeout)
                self.assertIn('--max-wall-time=' + expected, command)

    def test_shim_runs_with_spaces_in_the_interpreter_path(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp) / 'a b'
            base.mkdir()
            python = base / 'python3'
            python.symlink_to(sys.executable)
            config = base / 'adapter.json'
            config.write_text(json.dumps(dict(version='engine-v1')))
            K.write_shim(base / 'vvp', 'run', str(python))
            result = subprocess.run([base / 'vvp', '-V'], capture_output=True, text=True, timeout=30,
                                    env=dict(os.environ, KIRIMASIM_ADAPTER_CONFIG=str(config)))
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('engine-v1', result.stdout)

    def test_source_snapshot_is_relative_to_the_resolved_root_and_covers_the_adapter(self):
        inputs = K.snapshot_inputs()
        self.assertIn(PATH, inputs)
        self.assertTrue(all(p.is_relative_to(K.ROOT) for p in inputs))

    def test_stale_source_or_binary_cannot_be_replayed(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            binary, source, recipe = [base / name for name in ('engine', 'tb.sv', 'sim.vvp')]
            binary.write_bytes(b'engine-v1')
            source.write_text('module tb; endmodule\n')
            config = dict(binary=str(binary), binary_sha256=K.digest(binary))
            data = dict(format='kirimasim-source-recipe-v1', binary_sha256=K.digest(binary),
                        source_sha256={str(source): K.digest(source)})
            recipe.write_text(json.dumps(data))
            self.assertEqual(K.verify_recipe(recipe, config), data)
            source.write_text('module changed; endmodule\n')
            with self.assertRaisesRegex(ValueError, 'source changed'):
                K.verify_recipe(recipe, config)
            binary.write_bytes(b'engine-v2')
            with self.assertRaisesRegex(ValueError, 'binary changed'):
                K.verify_recipe(recipe, config)

    def test_crash_timeout_and_unsupported_never_count_as_detection(self):
        lower = dict(phase='lower', returncode=0)
        run = dict(phase='run', returncode=1)  # Expected $fatal is checked by original runner.
        self.assertTrue(K.audit_events([lower, run])['success'])
        for bad in (dict(run, returncode=-11), dict(run, returncode=124),
                    dict(run, unsupported=['feature']), dict(run, error='host timeout'),
                    dict(lower, returncode=2)):
            with self.subTest(bad=bad):
                self.assertFalse(K.audit_events([lower, run, bad])['success'])
        self.assertFalse(K.audit_events([lower])['success'])
        self.assertFalse(K.audit_events([])['success'])

    def test_formal_and_other_engines_are_excluded_from_selection(self):
        registry = dict(examples=[dict(id='fifo', kind='simulation', tools=['iverilog', 'vvp']),
                                  dict(id='proof', kind='formal', tools=['sby']),
                                  dict(id='cpp', kind='simulation', tools=['verilator'])])
        self.assertEqual(K.selected_entries(registry, None), ['fifo'])
        with self.assertRaises(ValueError):
            K.selected_entries(registry, ['cpp'])

    def test_exit_codes_can_be_counted_for_the_simulations_alone(self):
        events = [dict(phase='lower', returncode=0), dict(phase='run', returncode=0),
                  dict(phase='run', returncode=1)]
        self.assertEqual(K.returncode_counts(events), {'0': 2, '1': 1})
        self.assertEqual(K.returncode_counts(events, 'run'), {'0': 1, '1': 1})


def native(lowering, simulations, abnormal=0):
    return dict(success=not abnormal, lowering=lowering, simulations=simulations, abnormal=abnormal)


def campaign(**changes):
    results = [dict(id='fifo-w0', example='fifo', success=True, native=native(2, 3), message='ok'),
               dict(id='fifo-w1', example='fifo', success=True, native=native(2, 4), message='ok'),
               dict(id='uart', example='uart', success=True, native=native(1, 1), message='ok')]
    return dict(success=True, complete=True, profile='smoke', seed=17, selected_examples=2,
                planned=3, passed=3, source_changes=[], native=native(5, 8),
                simulation_returncodes={'0': 6, '1': 2}, results=results) | changes


class KirimasimResultsTests(unittest.TestCase):
    COMMIT = 'a' * 40

    def test_table_counts_every_example_with_its_configurations(self):
        text = R.render(campaign(), self.COMMIT, 'base/')
        self.assertIn('**3／3 PASS**', text)
        self.assertIn(f'[`aaaaaaaaaaaa`](https://github.com/kurochan001/kirimasim/commit/{self.COMMIT})', text)
        self.assertIn('終了コード0が6回、1が2回', text)
        self.assertIn('| [fifo](base/fifo/README.md) | 2 | PASS | 4 | 7 | 0 |', text)
        self.assertIn('| [uart](base/uart/README.md) | 1 | PASS | 1 | 1 | 0 |', text)
        self.assertIn('| 合計 | 3 | 3／3 | 5 | 8 | 0 |', text)
        self.assertNotIn('不合格の構成', text)

    def test_failed_or_incomplete_campaign_is_never_shown_as_pass(self):
        rows = campaign()['results']
        broken = dict(rows[1], success=False, native=native(2, 4, 1), message='bad | value\nnext <x>')
        text = R.render(campaign(success=False, passed=2, results=[rows[0], broken, rows[2]]), self.COMMIT, 'x')
        self.assertIn('**2／3 FAIL**', text)
        self.assertIn('**FAIL**（1／2）', text)
        self.assertIn('| `fifo-w1` | bad \\| value next &lt;x>（異常終了1回） |', text)
        for label, changes, expected in (
                ('jobs missing', dict(complete=False, success=False, passed=2, results=rows[:2]), '**未完了**（結果は2件）'),
                ('complete flag alone', dict(complete=False), '**未完了**（結果は3件）'),
                ('inputs changed', dict(success=False, source_changes=['tools/x.py']), '| 実行中の入力変更 | tools/x.py |'),
                ('audit failed', dict(success=False), '**3／3 FAIL**')):
            with self.subTest(label):
                text = R.render(campaign(**changes), self.COMMIT, 'x')
                self.assertIn(expected, text)
                self.assertIn(' FAIL**', text)
                self.assertNotIn(' PASS**', text)

    def test_commit_must_be_full_and_bad_input_is_an_error(self):
        for commit in ('b279f56', 'main', self.COMMIT + '; x', ''):
            with self.subTest(commit), self.assertRaises(ValueError):
                R.render(campaign(), commit, 'x')
        with tempfile.TemporaryDirectory() as temp:
            summary = Path(temp) / 'summary.json'
            out = Path(temp) / 'results.md'
            command = [sys.executable, str(RESULTS_PATH), '--summary', str(summary),
                       '--commit', self.COMMIT, '--out', str(out)]
            for label, body in (('missing file', None), ('not JSON', '{'), ('missing key', '{}')):
                with self.subTest(label):
                    if body is not None:
                        summary.write_text(body)
                    done = subprocess.run(command, capture_output=True, text=True)
                    self.assertEqual(done.returncode, 2)
                    self.assertIn('KIRIMASIM_RESULTS_ERROR', done.stderr)
                    self.assertFalse(out.exists())
            summary.write_text(json.dumps(campaign()))
            done = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(done.returncode, 0, done.stderr)
            self.assertIn('**3／3 PASS**', out.read_text())

    def test_page_shows_the_recorded_run_and_is_reachable_from_the_readme(self):
        root = Path(__file__).resolve().parents[2]
        study = root / 'docs/case-study-kirimasim'
        record = json.loads((study / 'results-20261107.json').read_text())
        page = (study / 'results.md').read_text()
        commit = record['kirimasim']['source_commit']
        self.assertIn(f'(commit {commit[:12]})', record['kirimasim']['version'])
        self.assertIn(R.render(record, commit, '../../examples'), page)
        rows = record['results']
        self.assertTrue(record['success'] and record['complete'])
        self.assertEqual((len(rows), record['passed']), (record['planned'], record['planned']))
        self.assertEqual(len({row['example'] for row in rows}), record['selected_examples'])
        for key in ('lowering', 'simulations', 'abnormal'):
            self.assertEqual(sum(row['native'][key] for row in rows), record['native'][key])
        codes = record['simulation_returncodes']
        self.assertEqual(sum(codes.values()), record['native']['simulations'])
        # The table of versions states the same values as the record.
        row = next(line for line in page.splitlines() if line.startswith(f'| 2026-11-07 | [`{commit[:12]}`]'))
        self.assertIn(f"| {record['passed']}／{record['planned']} PASS | {record['native']['lowering']} | "
                      f"{record['native']['simulations']:,} | {codes['0']:,}／{codes['1']:,} | "
                      f"{record['native']['abnormal']} |", row)
        self.assertIn('(docs/case-study-kirimasim/results.md)', (root / 'README.md').read_text())


if __name__ == '__main__':
    unittest.main()

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


if __name__ == '__main__':
    unittest.main()

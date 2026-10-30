from pathlib import Path
import shutil, sys, tempfile, unittest
from types import SimpleNamespace
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'local-common'))
from system_test_support import SystemContract
from local_test_support import load_example, read_json, run_example

P = load_example('local-branch-predictor')
ISS = P.ISS
ICARUS = shutil.which('iverilog') and shutil.which('vvp')


def trace(program):
    return ISS.execute(ISS.assemble(program), [0] * ISS.DATA_WORDS)


class ExampleTests(SystemContract, unittest.TestCase):
    EXAMPLE = 'local-branch-predictor'
    GOALS = 10

    def test_counters_follow_the_direction_of_each_prediction(self):
        program = [('addi', 1, 0, 3), 'loop:', ('addi', 1, 1, -1), ('bne', 1, 0, 'loop'),
                   ('jal', 0, 'next'), 'next:', ('beq', 0, 0, 'skip'), ('addi', 2, 0, 1), 'skip:', ('ebreak',)]
        t = trace(program)
        # 3 BNE (taken, taken, not taken), 1 JAL, 1 forward BEQ taken.
        self.assertEqual(P.counters(t, 0), (5, 4))  # without prediction every taken one is a miss
        self.assertEqual(P.counters(t, 1), (5, 2))  # static: the loop exit and the forward BEQ

    def test_directed_program_covers_loop_exits_and_predictions_in_the_shadow_of_a_miss(self):
        rows = P.boundary_vectors(1)
        tags = [r[8] for r in rows if r[0] == 3]
        self.assertGreaterEqual(sum(bool(t & P.LOOP_EXIT) for t in tags), 3)
        self.assertEqual(sum(bool(t & P.SHADOW) for t in tags), 3)
        self.assertEqual(rows[-1][0], 4)

    def test_loops_keep_the_iss_example_programs_unchanged_and_always_end(self):
        import random
        for seed in (17, 18):
            self.assertEqual(ISS.random_program(random.Random(seed), 200), ISS.random_program(random.Random(seed), 200))
            program = ISS.random_program(random.Random(seed), 300, loops=True)
            self.assertTrue(any(isinstance(x, tuple) and x[0] == 'bne' and x[1] == 11 for x in program))
            self.assertEqual(trace(program)[-1].insn, ISS.EBREAK)

    def test_real_rtl_all_configurations_and_mutants(self):
        if not ICARUS:
            self.skipTest('Icarus required')
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / 'out'
            result = run_example(self.EXAMPLE, out, '--iterations', '60')
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            summary = read_json(out / 'summary.json')
            self.assertEqual((summary['planned'], summary['mutations_detected'], summary['diagnostics_pass']), (18, 6, 6))
            for name, item in read_json(out / 'coverage.json').items():
                self.assertEqual((item['hit'], item['missing']), (self.GOALS, []), name)

    def test_demo_faults_make_normal_regression_fail(self):
        if not ICARUS:
            self.skipTest('Icarus required')
        with tempfile.TemporaryDirectory() as tmp:
            for fault in range(1, 5):
                with self.subTest(fault=fault):
                    out = Path(tmp) / str(fault)
                    result = run_example(self.EXAMPLE, out, '--configuration', 'static', '--iterations', '60',
                                         '--demo-bug', str(fault))
                    self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                    self.assertEqual(read_json(out / 'static-boundaries/result.json')['status'], 'fail')


if __name__ == '__main__':
    unittest.main()

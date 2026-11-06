from pathlib import Path
import shutil, sys, tempfile, unittest
from types import SimpleNamespace
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'local-common'))
from system_test_support import SystemContract
from local_test_support import load_example, read_json, run_example, simulate_vectors

P = load_example('local-branch-predictor')
ISS = P.ISS
ICARUS = shutil.which('iverilog') and shutil.which('vvp')
# SHA-256 of the default generator's 200-instruction programs, as the ISS example runs them.
DEFAULT_PROGRAMS = {17: 'a0544a85fa78fad2b54c14e815b4270b1fa4638c11911b5978f4d1bdd445b235',
                    18: '537058d75cc6d10c6c0a3fa003418f1099106c1c5256a5bfeb466290c2332c31'}
TRAIN = "taken ? counter + (counter != 2'b11) : counter - (counter != 2'b00)"
READ = '(PREDICT == 1 ? if_backward : bht[pc[5:2]][1])'
# Wrong counters that only the flush count of the counter case can show.
COUNTER_MUTANTS = {'no saturation': [(TRAIN, "taken ? counter + 2'd1 : counter - 2'd1")],
                   'read index pc[3:0]': [(READ, '(PREDICT == 1 ? if_backward : bht[pc[3:0]][1])')],
                   'eight counters': [(READ, '(PREDICT == 1 ? if_backward : bht[{1\'b0, pc[4:2]}][1])'),
                                      ('counter = bht[ex_pc[5:2]]', "counter = bht[{1'b0, ex_pc[4:2]}]"),
                                      ('bht[ex_pc[5:2]] <=', "bht[{1'b0, ex_pc[4:2]}] <=")],
                   'index pc[6:3]': [(READ, '(PREDICT == 1 ? if_backward : bht[pc[6:3]][1])'),
                                     ('counter = bht[ex_pc[5:2]]', 'counter = bht[ex_pc[6:3]]'),
                                     ('bht[ex_pc[5:2]] <=', 'bht[ex_pc[6:3]] <=')],
                   'no training': [('bht[ex_pc[5:2]] <= ' + TRAIN + ';', ';')],
                   'reversed training': [('bht[ex_pc[5:2]] <= taken ?', 'bht[ex_pc[5:2]] <= !taken ?')],
                   'no prediction': [(READ, "(PREDICT == 1 ? if_backward : 1'b0)")]}


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

    def test_directed_program_covers_loop_exits_and_predictable_words_in_the_shadow_of_a_branch(self):
        rows = P.boundary_vectors(1)
        tags = [r[8] for r in rows if r[0] == 3]
        self.assertGreaterEqual(sum(bool(t & P.LOOP_EXIT) for t in tags), 3)
        self.assertEqual(sum(bool(t & P.SHADOW) for t in tags), 3)
        self.assertEqual(rows[-1][0], 4)

    def test_dynamic_count_follows_each_counter_and_refuses_timing_dependence(self):
        # BNE taken, taken, taken, not taken: counter 1 to 2 (miss), 3, 3, 2 (miss); JAL predicted; JALR flushes.
        t = trace([('addi', 1, 0, 4), 'loop:', ('addi', 2, 0, 1), ('addi', 1, 1, -1), ('bne', 1, 0, 'loop'),
                   ('jal', 0, 'next'), 'next:', 'here:', ('auipc', 5, 0), ('jalr', 0, ('off', 'end', 'here'), 5), 'end:', ('ebreak',)])
        self.assertEqual(P.dynamic_flushes(t), 3)
        with self.assertRaisesRegex(ValueError, 'too closely'):  # two instructions apart: IF reads before EX updates
            P.dynamic_flushes(trace([('addi', 1, 0, 3), 'loop:', ('addi', 1, 1, -1), ('bne', 1, 0, 'loop'), ('ebreak',)]))

    def test_counter_case_shows_each_wrong_predictor_through_the_flush_count(self):
        if not ICARUS:
            self.skipTest('Icarus required')
        rows, dynamic = P.counter_vectors(), P.CONFIGS['dynamic']
        result = simulate_vectors(P, rows, dynamic)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        for name, edits in COUNTER_MUTANTS.items():
            with self.subTest(name):
                result = simulate_vectors(P, rows, dynamic, {'rv32i_core.sv': edits})
                self.assertIn('CHECK_FAIL ISS_PERF', result.stdout)

    def test_loops_keep_the_iss_example_programs_unchanged_and_always_end(self):
        import hashlib, random
        for seed in (17, 18):
            words = ISS.assemble(ISS.random_program(random.Random(seed), 200))
            self.assertEqual(hashlib.sha256(' '.join(f'{w:08x}' for w in words).encode()).hexdigest(), DEFAULT_PROGRAMS[seed])
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
            self.assertEqual((summary['planned'], summary['mutations_detected'], summary['diagnostics_pass']), (19, 7, 5))
            for name, item in read_json(out / 'coverage.json').items():
                self.assertEqual((item['hit'], item['missing']), (self.GOALS, []), name)
            self.assertEqual([p.parent.name for p in out.glob('*-counters/result.json')], ['dynamic-counters'])

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

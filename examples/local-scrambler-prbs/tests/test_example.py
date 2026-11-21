import copy
import importlib.util
from pathlib import Path
import random
import re, shutil, subprocess, sys, tempfile, unittest
from types import SimpleNamespace
import xml.etree.ElementTree as ET
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'local-common'))
from local_test_support import load_example, read_json, run_example, simulate_vectors

P = load_example('local-scrambler-prbs')
M = P.MODEL
HERE = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('scrambler_prbs_formal_plan', HERE / 'formal.py')
F = importlib.util.module_from_spec(spec)
spec.loader.exec_module(F)
ICARUS = shutil.which('iverilog') and shutil.which('vvp')
FORMAL = all(shutil.which(tool) for tool in ('yowasp-sby', 'yowasp-yosys', 'yowasp-yosys-smtbmc', 'z3'))
GOALS = 29


def run_checker(n, tap, bits, **options):
    c = M.Checker(n, tap, **options)
    return c, [c.bit(b) for b in bits]


class ModelTests(unittest.TestCase):
    def test_periods_by_counting_and_by_the_order_of_x(self):
        self.assertEqual((M.period(7, 6), M.period(15, 14)), (127, 32767))
        self.assertEqual(7 * 31 * 151, 2 ** 15 - 1)
        self.assertTrue(M.maximal_length(7, 6, [127]))
        self.assertTrue(M.maximal_length(15, 14, [7, 31, 151]))
        # 2**31 - 1 is prime, so x**(2**31 - 1) == 1 with x != 1 gives the full period without counting.
        self.assertTrue(M.maximal_length(31, 28, [2 ** 31 - 1]))
        self.assertFalse(M.maximal_length(7, 5, [127]))                # x^7 + x^5 + 1 is not primitive
        self.assertEqual(M.x_power_mod(7, 7, 6), 0b1000001)            # x^7 = x^6 + 1

    def test_one_period_of_prbs7_is_balanced_and_has_the_runs_of_a_maximal_sequence(self):
        g = M.Generator(7, 6)
        bits = [g.bit() for _ in range(127)]
        self.assertEqual((sum(bits), 127 - sum(bits)), (64, 63))
        twice = ''.join(map(str, bits + bits))
        self.assertIn('1' * 7, twice)
        self.assertNotIn('1' * 8, twice)
        self.assertIn('0' * 6, twice)
        self.assertNotIn('0' * 7, twice)
        self.assertEqual([g.bit() for _ in range(127)], bits)

    def test_generator_seed_order_and_the_all_zero_state(self):
        g = M.Generator(7, 6)
        g.load(0b0000001)                       # only the newest bit is 1
        self.assertEqual(g.past, [0, 0, 0, 0, 0, 0, 1])
        self.assertEqual(g.peek(8), [0, 0, 0, 0, 0, 1, 1, 0])   # bit[n] = bit[n-7] ^ bit[n-6]: the 1 is 6 and then 7 bits back
        g.load(0)
        self.assertEqual((g.zero(), g.peek(40)), (1, [0] * 40))
        g.load(0b1000000)
        self.assertEqual(g.zero(), 0)
        self.assertEqual(g.bit(), 1)

    def test_checker_locks_after_fill_plus_lock_bits_and_flags_one_error_three_times(self):
        for n, tap in ((7, 6), (15, 14), (31, 28)):
            g = M.Generator(n, tap)
            bits = [g.bit() for _ in range(400)]
            c = M.Checker(n, tap, lock=32, loss=8)
            locked_at = None
            for i, b in enumerate(bits[:n + 40]):
                c.bit(b)
                if c.locked and locked_at is None:
                    locked_at = i
            self.assertEqual(locked_at, n + 32 - 1, n)
            wrong = list(bits)
            wrong[100] ^= 1
            c, flags = run_checker(n, tap, wrong)
            self.assertEqual([i - 100 for i, f in enumerate(flags) if f], [0, tap, n], n)
            self.assertEqual((c.locked, c.count), (1, 3))

    def test_checker_realigns_within_n_bits_after_a_slip_without_a_seed(self):
        for n, tap in ((7, 6), (15, 14), (31, 28)):
            g = M.Generator(n, tap)
            bits = [g.bit() for _ in range(400)]
            slipped = bits[:150] + bits[151:]
            c, flags = run_checker(n, tap, slipped)
            self.assertTrue(any(flags[150:150 + n]), n)
            self.assertFalse(any(flags[150 + n:]), n)
            self.assertEqual(c.locked, 1)

    def test_checker_loss_threshold_exactly_and_one_below(self):
        for name, parameters in P.CONFIGS.items():
            _, facts = P.fixed_session(parameters)
            self.assertEqual(facts['single'], 3, name)
            self.assertEqual((facts['below'], facts['below_peak'], facts['below_locked']), (P.LOSS - 1, P.LOSS - 1, 1), name)
            self.assertEqual((facts['at'], facts['at_locked']), (P.LOSS, (1, 0)), name)
            self.assertEqual((facts['count_before_extra'], facts['count']), (P.COUNT_MAX, P.COUNT_MAX), name)
            self.assertGreater(facts['slip_flags'], 0, name)
            self.assertEqual(facts['relock_bit'] % parameters['W'], 0, name)   # the lock arrives on the first bit of a word
        # A slip gives at most N flags; whether that costs the lock depends on the data around it.
        for n, tap in ((7, 6), (31, 28)):
            g = M.Generator(n, tap)
            bits = [g.bit() for _ in range(600)]
            worst = max(sum(run_checker(n, tap, bits[:at] + bits[at + 1:])[1]) for at in range(100, 400))
            self.assertLessEqual(worst, n)
            self.assertGreaterEqual(worst, P.LOSS if n == 31 else 1)

    def test_checker_never_locks_on_zeros_and_does_not_count_while_unlocked(self):
        c, flags = run_checker(7, 6, [0] * 200)
        self.assertEqual((c.locked, c.count, c.stuck(), any(flags)), (0, 0, 1, False))
        g = M.Generator(7, 6)
        bits = [g.bit() for _ in range(60)]
        bits[10] ^= 1                                   # an error before the lock
        c, flags = run_checker(7, 6, bits)
        self.assertEqual((sum(flags), c.count, c.locked), (3, 0, 1))
        c = M.Checker(7, 6, count_bits=2)
        g = M.Generator(7, 6)
        for i in range(400):
            c.bit(g.bit() ^ (i > 50 and i % 60 == 0))
        self.assertEqual(c.count, 3)                    # saturated

    def test_descrambler_recovers_after_n_bits_from_any_start_and_multiplies_one_error_by_three(self):
        rng = random.Random(5)
        n, tap = 58, 39
        s, d = M.Scrambler(n, tap), M.Descrambler(n, tap)
        for _ in range(77):
            s.bit(rng.getrandbits(1))                   # the receiver starts in the middle of the stream
        data = [rng.getrandbits(1) for _ in range(400)]
        sent = [s.bit(b) for b in data]
        out = [d.bit(b) for b in sent]
        self.assertNotEqual(out[:n], data[:n])
        self.assertEqual(out[n:], data[n:])
        sent[200] ^= 1
        d = M.Descrambler(n, tap)
        out = [d.bit(b) for b in sent]
        self.assertEqual([i - 200 for i in range(n, 400) if out[i] != data[i]], [0, tap, n])
        # A dropped bit: after n more bits the output is the data with the same bit dropped.
        sent[200] ^= 1
        d = M.Descrambler(n, tap)
        out = [d.bit(b) for b in sent[:250] + sent[251:]]
        self.assertEqual(out[250 + n:], data[251 + n:])
        self.assertNotEqual(out[250:250 + n], data[251:251 + n])

    def test_scrambler_scrambles_zero_data_after_reset_and_locks_up_when_the_data_follows_the_feedback(self):
        s = M.Scrambler(58, 39)
        self.assertTrue(any(s.bit(0) for _ in range(200)))
        s = M.Scrambler(58, 39)
        self.assertEqual([s.bit(s.feedback()) for _ in range(58)], [0] * 58)
        self.assertEqual([s.bit(0) for _ in range(300)], [0] * 300)
        self.assertEqual(s.bit(1), 1)
        self.assertTrue(any(s.bit(0) for _ in range(58)))

    def test_pack_puts_the_earliest_bit_at_bit_zero(self):
        self.assertEqual(M.pack([1, 0, 0, 1]), 0b1001)
        self.assertEqual(M.pack([1, 0, 0, 0, 0, 0, 0, 0]), 1)


class PlanTests(unittest.TestCase):
    def test_serial_and_parallel_plans_give_the_checker_the_same_bit_stream(self):
        """The fixed scenes of the checker are built on bits; only the cutting into words depends on W."""
        def bits(parameters):
            stream, _ = P.checker_stream(P.Session(parameters, random.Random(1)), 0)
            return stream.bits
        one, eight = bits(P.CONFIGS['p7-w1']), bits(P.CONFIGS['p7-w8'])
        self.assertEqual(one[:7 + P.LOCK + 8], eight[:7 + P.LOCK + 8])
        g = M.Generator(7, 6)
        self.assertEqual(one[:40], [g.bit() for _ in range(40)])
        self.assertEqual(len(eight) % 8, 0)

    def test_rows_have_the_columns_of_the_test_bench_and_counts_follow_them(self):
        for name, parameters in P.CONFIGS.items():
            rows = P.boundary_rows(parameters)
            self.assertEqual({len(r) for r in rows}, {23}, name)
            self.assertEqual([r[0] for r in rows[:2]], [0, 0])
            self.assertEqual(sum(not r[0] for r in rows), 3, name)        # the start and one reset in operation
            c = P.counts(rows)
            self.assertGreater(c['gen_words'] * parameters['W'], 2 * 127, name)   # more than two periods of PRBS7
            self.assertGreater(c['chk_flags'], P.COUNT_MAX, name)
            self.assertGreater(c['dsc_wrong'], 3, name)
            width = (1 << parameters['W']) - 1
            self.assertTrue(all(r[column] <= width for r in rows for column in (5, 9, 10, 16, 17, 20, 21, 22)), name)

    def test_seed_reproduction(self):
        args = SimpleNamespace(profile='smoke', seed=17, iterations=50, demo_bug=0)
        parameters = P.CONFIGS['p15-w8']
        first = P.make_cases(args, parameters)
        self.assertEqual(first, P.make_cases(args, parameters))
        args.seed = 18
        second = P.make_cases(args, parameters)
        self.assertNotEqual(first[1], second[1])
        self.assertEqual(first[0], second[0])                              # the fixed plan does not depend on the seed

    def test_parallel_only_mutants_are_survivors_at_one_bit_per_clock(self):
        args = SimpleNamespace(profile='nightly', seed=17, iterations=5, demo_bug=0)
        for name, parameters in P.CONFIGS.items():
            ids = [c['id'] for c in P.make_cases(args, parameters)]
            hidden = P.PARALLEL_ONLY if parameters['W'] == 1 else set()
            expected = ['boundaries', 'random-seed17', 'random-seed18', 'random-seed19'] + [
                ('survive' if m in hidden else 'detect') + f'-mutation{m}' for m in range(1, P.MUTANTS + 1)]
            self.assertEqual(ids, expected, name)
        self.assertEqual(set(P.LABELS), set(range(1, P.MUTANTS + 1)))

    def test_random_rows_use_idle_clocks_errors_slips_and_zero_runs(self):
        rows = P.random_rows(P.CONFIGS['p7-w8'], 17, 600)
        live = [r for r in rows if r[0]]
        self.assertTrue(any(not r[2] for r in live) and any(r[3] for r in live))
        self.assertTrue(any(not r[8] for r in live) and any(r[10] for r in live))
        self.assertTrue(any(r[13] for r in live))                          # stuck seen
        self.assertTrue(any(not r[15] for r in live) and any(not r[19] for r in live))
        self.assertTrue(any(r[21] != r[22] for r in live if r[19]))


@unittest.skipUnless(ICARUS, 'Icarus required')
class RtlTests(unittest.TestCase):
    def test_real_rtl_all_configurations_mutants_and_survivors(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / 'out'
            result = run_example('local-scrambler-prbs', out, '--iterations', '40')
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            summary = read_json(out / 'summary.json')
            configurations = len(P.CONFIGS)
            self.assertEqual((summary['success'], summary['complete'], summary['planned']), (True, True, 14 * configurations))
            self.assertEqual(summary['mutations_detected'], 12 * configurations - 2)
            self.assertEqual(summary['diagnostics_pass'], 2)
            coverage = read_json(out / 'coverage.json')
            self.assertEqual({k: (v['hit'], v['missing']) for k, v in coverage.items()}, {k: (GOALS, []) for k in P.CONFIGS})
            for name in P.CONFIGS:      # the fixed plan alone reaches every goal
                self.assertEqual(len(read_json(out / f'{name}-boundaries/result.json')['credited_coverage']), GOALS, name)
            suite = ET.parse(out / 'junit.xml').getroot()
            self.assertEqual((suite.get('tests'), suite.get('failures'), suite.get('errors')), (str(15 * configurations), '0', '0'))
            for mutation in P.PARALLEL_ONLY:
                self.assertEqual(read_json(out / f'p7-w1-survive-mutation{mutation}/result.json')['status'], 'pass')

    def test_demo_faults_make_the_normal_regression_fail(self):
        with tempfile.TemporaryDirectory() as tmp:
            for fault in range(1, P.MUTANTS + 1):
                out = Path(tmp) / str(fault)
                result = run_example('local-scrambler-prbs', out, '--configuration', 'p7-w8', '--iterations', '2', '--demo-bug', str(fault))
                self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                self.assertEqual(read_json(out / 'p7-w8-boundaries/result.json')['status'], 'fail')

    def test_checker_labels_for_errors_outside_the_planned_mutants_and_for_unknown_outputs(self):
        parameters = P.CONFIGS['p15-w8']
        rows = P.boundary_rows(parameters)
        for name, edits, label in (
                ('prbs_check.sv', [('assign err = valid ? flags : {W{1\'b0}};', 'assign err = flags;')], 'CHK_ERR'),
                ('prbs_check.sv', [('assign stuck = fill == FULL &&', 'assign stuck = ')], 'CHK_STUCK'),
                ('prbs_check.sv', [('if (g == GOOD) begin l = 1\'b1; b = 0; end', 'if (g == GOOD) begin l = 1\'b1; end')], 'CHK_LOCK'),
                ('prbs_check.sv', [('if (c != {CW{1\'b1}}) c = c + 1\'b1;', 'c = c + 1\'b1;')], 'CHK_COUNT'),
                ('ss_scrambler.sv', [('if (!rst_n) hist <= {N{1\'b1}};', 'if (!rst_n) hist <= {N{1\'b0}};')], 'SCR_DATA'),
                ('ss_scrambler.sv', [('else if (valid) hist <= hist_next;', 'else hist <= hist_next;')], 'SCR_DATA'),
                ('ss_descrambler.sv', [('assign dout = d;', 'assign dout = valid ? d : \'x;')], 'DSC_DATA'),
                ('prbs_gen.sv', [('else if (seed_load) hist <= seed;', 'else if (seed_load && !enable) hist <= seed;')], 'GEN_DATA'),
                ('prbs_gen.sv', [('assign data = x[N+W-1:N];', 'assign data = enable ? x[N+W-1:N] : \'x;')], 'GEN_DATA')):
            output = simulate_vectors(P, rows, parameters, {name: edits}).stdout
            self.assertIn('CHECK_FAIL ' + label, output, (name, edits))
            self.assertNotIn('RESULT PASS', output)
        self.assertIn(f'RESULT PASS checks={len(rows)}', simulate_vectors(P, rows, parameters).stdout)


class FormalPlanTests(unittest.TestCase):
    def test_plan_has_one_proof_per_module_a_cover_task_and_one_task_per_mutant(self):
        plan = F.plan(F.BOUND, 0)
        self.assertEqual([c['id'] for c in plan], ['gen-proof', 'scr-proof', 'dsc-proof', 'chk-proof', 'scenario-cover'] +
                         [f'detect-mutation{m}' for _, m, _ in F.MUTANTS])
        self.assertEqual([c['parameters']['TARGET'] for c in plan[:4]], [0, 1, 2, 3])
        self.assertTrue(all(c['depth'] == F.PROOF_DEPTH for c in plan[:4]))
        self.assertGreater(F.PROOF_DEPTH, max(c['W'] for c in F.CONFIGS.values()) + 1)   # a window always holds a word boundary
        self.assertTrue({f for _, _, f in F.MUTANTS} <= F.ASSERTS)
        self.assertTrue(P.PARALLEL_ONLY <= {m for _, m, _ in F.MUTANTS})                 # what the serial simulation cannot see
        self.assertEqual(F.plan(F.BOUND, 4)[0]['parameters']['MUTATION'], 4)
        self.assertEqual(F.properties(F.CONFIGS['n7-w8'], plan[0])['assume'], {'as_initial_reset'})

    def test_property_names_match_the_harness_and_the_state_ports_exist_only_for_the_proof(self):
        harness = (HERE / 'scrambler_prbs_formal.sv').read_text()
        self.assertEqual(set(re.findall(r'\b((?:ap|ai|cp|as)_\w+):', harness)), F.ASSERTS | F.COVERS | {'as_initial_reset'})
        for path in F.SOURCES[:4]:
            text = path.read_text()
            self.assertEqual(text.count('`ifdef FORMAL'), 2, path.name)
            outside = re.sub(r'`ifdef FORMAL.*?`endif', '', text, flags=re.S)
            self.assertNotIn('f_state', outside, path.name)

    @unittest.skipUnless(FORMAL, 'formal tools required')
    def test_a_proof_completes_and_the_parallel_only_mutant_is_refuted(self):
        with tempfile.TemporaryDirectory() as tmp:
            for task, outcome in (('gen-proof', 'pass'), ('detect-mutation4', 'detected')):
                out = Path(tmp) / task
                result = subprocess.run([sys.executable, str(HERE / 'formal.py'), '--configuration', 'n7-w8', '--task', task,
                                         '--out', str(out)], capture_output=True, text=True, timeout=600)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertEqual(read_json(out / f'n7-w8-{task}/result.json')['outcome'], outcome)


if __name__ == '__main__':
    unittest.main()

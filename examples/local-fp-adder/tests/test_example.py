from fractions import Fraction
import importlib.util
from pathlib import Path
import random, shutil, struct, subprocess, sys, tempfile, unittest
from types import SimpleNamespace
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'local-common'))
from local_test_support import load_example, read_json, run_example, simulate_vectors, assert_evidence

P = load_example('local-fp-adder')
M = P.M
HERE = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('fp_adder_formal_plan', HERE / 'formal.py')
F = importlib.util.module_from_spec(spec)
spec.loader.exec_module(F)
SMALL, SINGLE = P.CONFIGS['small'], P.CONFIGS['binary32']
ICARUS = shutil.which('iverilog') and shutil.which('vvp')
FORMAL = all(shutil.which(tool) for tool in ('yowasp-sby', 'yowasp-yosys', 'yowasp-yosys-smtbmc', 'z3'))


def bits(x):
    return struct.unpack('<I', struct.pack('<f', x))[0]


def number(code):
    return struct.unpack('<f', struct.pack('<I', code))[0]


class ModelTests(unittest.TestCase):
    def test_binary32_agrees_with_the_host_for_round_to_nearest_even(self):
        model, rng = P.adder(SINGLE), random.Random(5)
        compared = 0
        for _ in range(4000):
            a, b = rng.getrandbits(32), rng.getrandbits(32)
            if rng.random() < 0.5:
                b = (b & 0x807FFFFF) | ((a >> 23 & 0xFF) + rng.randint(-26, 26)) % 255 << 23
            if 'nan' in model.fmt.kind(a) or 'nan' in model.fmt.kind(b) or 'inf' in (model.fmt.kind(a), model.fmt.kind(b)):
                continue
            x, y = number(a), number(b)
            if Fraction(x) + Fraction(y) != Fraction(x + y):   # the double sum must be exact, or the host rounds twice
                continue
            try:
                host = bits(x + y)
            except OverflowError:
                host = model.fmt.infinity(int(x + y < 0))
            self.assertEqual(model.compute(0, M.RNE, a, b)[0], host, (hex(a), hex(b)))
            self.assertEqual(model.compute(1, M.RNE, a, b ^ 1 << 31)[0], host)
            compared += 1
        self.assertGreater(compared, 2000)

    def test_known_binary32_results_and_flags(self):
        model = P.adder(SINGLE)
        one, half_ulp, largest = bits(1.0), bits(2.0 ** -24), 0x7F7FFFFF
        self.assertEqual(model.compute(0, M.RNE, one, half_ulp)[:2], (one, M.NX))            # tie to even: down
        self.assertEqual(model.compute(0, M.RNE, one | 1, half_ulp)[:2], (one | 2, M.NX))    # tie to even: up
        self.assertEqual(model.compute(0, M.RMM, one, half_ulp)[:2], (one | 1, M.NX))
        self.assertEqual(model.compute(0, M.RUP, one, 1)[:2], (one | 1, M.NX))               # 1 + smallest subnormal
        self.assertEqual(model.compute(0, M.RDN, one, 1)[:2], (one, M.NX))
        self.assertEqual(model.compute(0, M.RNE, largest, largest)[:2], (0x7F800000, M.OF | M.NX))
        self.assertEqual(model.compute(0, M.RTZ, largest, largest)[:2], (largest, M.OF | M.NX))
        self.assertEqual(model.compute(0, M.RUP, largest | 1 << 31, largest | 1 << 31)[:2], (largest | 1 << 31, M.OF | M.NX))
        self.assertEqual(model.compute(1, M.RNE, one, one)[:2], (0, 0))
        self.assertEqual(model.compute(1, M.RDN, one, one)[:2], (1 << 31, 0))
        self.assertEqual(model.compute(0, M.RDN, 1 << 31, 1 << 31)[:2], (1 << 31, 0))
        self.assertEqual(model.compute(0, M.RUP, 0, 1 << 31)[:2], (0, 0))
        self.assertEqual(model.compute(1, M.RNE, 0x7F800000, 0x7F800000)[:2], (0x7FC00000, M.NV))
        self.assertEqual(model.compute(0, M.RNE, 0x7F800000, 0x7F800000)[:2], (0x7F800000, 0))
        self.assertEqual(model.compute(0, M.RNE, 0x7FC00123, one)[:2], (0x7FC00000, 0))      # quiet NaN: canonical, no flag
        self.assertEqual(model.compute(0, M.RNE, 0xFF800001, one)[:2], (0x7FC00000, M.NV))   # signaling NaN
        self.assertEqual(model.compute(0, M.RNE, 0x00000003, 0x00000004)[:2], (7, 0))        # subnormal sum, exact
        self.assertEqual(model.compute(0, M.RNE, 0x007FFFFF, 1)[:2], (0x00800000, 0))        # into the normal range, exact
        with self.assertRaises(ValueError):
            model.compute(0, 5, one, one)

    def test_small_format_properties(self):
        model = P.adder(SMALL)
        fmt, sign = model.fmt, 1 << 7
        finite = [c for c in range(256) if fmt.kind(c) in ('zero', 'subnormal', 'normal')]
        ordered = sorted(finite, key=lambda c: (fmt.value(c), -(c >> 7)))
        for mode in range(5):
            for a in range(256):
                for b in range(0, 256, 7):
                    self.assertEqual(model.compute(0, mode, a, b)[:2], model.compute(0, mode, b, a)[:2])   # commutative
                    self.assertEqual(model.compute(1, mode, a, b)[:2], model.compute(0, mode, a, b ^ sign)[:2])
            for a in finite:   # x - x is +0, or -0 when rounding down
                self.assertEqual(model.compute(1, mode, a, a)[:2], (sign if mode == M.RDN else 0, 0))
            for a in finite[::5]:   # the rounded sum never decreases when b grows
                previous = None
                for b in ordered:
                    code = model.compute(0, mode, a, b)[0]
                    value = (Fraction(-1) ** (code >> 7)) * Fraction(10 ** 9) if fmt.kind(code) == 'inf' else fmt.value(code)
                    if previous is not None:
                        self.assertGreaterEqual(value, previous)
                    previous = value

    def test_a_sum_never_underflows_but_the_rounding_itself_can(self):
        model = P.adder(SMALL)
        for mode in range(5):
            for a in range(256):
                for b in range(256):
                    self.assertEqual(model.compute(0, mode, a, b)[1] & (M.UF | M.DZ), 0)
        fmt = model.fmt
        tiny = Fraction(2) ** (fmt.emin - fmt.frac)                      # the smallest subnormal number
        self.assertEqual(M.round_to(tiny * Fraction(5, 2), fmt, M.RNE)[:2], (2, M.UF | M.NX))
        self.assertEqual(M.round_to(-tiny * Fraction(5, 2), fmt, M.RDN)[:2], (0x83, M.UF | M.NX))
        smallest_normal = Fraction(2) ** fmt.emin
        just_below = smallest_normal - tiny * Fraction(3, 8)
        # Rounded with a free exponent this is still below the normal range: tiny, and inexact.
        self.assertEqual(M.round_to(just_below, fmt, M.RNE)[:2], (fmt.pack(0, 1, 0), M.UF | M.NX))
        # Much closer to the smallest normal number: with a free exponent it rounds into the normal range, so it is not tiny.
        self.assertEqual(M.round_to(smallest_normal - tiny / 32, fmt, M.RNE)[:2], (fmt.pack(0, 1, 0), M.NX))

    def test_tags_name_what_the_rounding_did(self):
        model = P.adder(SINGLE)
        def tags(*call):
            word = model.compute(*call)[2]
            return {name for index, name in enumerate(M.TAGS) if word >> index & 1}
        one = bits(1.0)
        self.assertLessEqual({'round/tie', 'round/toward', 'mode/rne', 'operation/add'}, tags(0, M.RNE, one, bits(2.0 ** -24)))
        self.assertLessEqual({'round/tie', 'round/away', 'round/carry-into-exponent'}, tags(0, M.RNE, bits(2.0) - 1, bits(2.0 ** -24)))
        self.assertLessEqual({'align/far', 'round/away', 'mode/rup'}, tags(0, M.RUP, bits(2.0 ** 30), one))
        self.assertLessEqual({'align/cancellation', 'round/exact', 'operation/subtract'}, tags(1, M.RNE, one, one - 1))
        self.assertLessEqual({'result/subnormal', 'operand/subnormal'}, tags(0, M.RNE, 3, 4))
        self.assertIn('result/overflow-largest-finite', tags(0, M.RTZ, 0x7F7FFFFF, 0x7F7FFFFF))
        self.assertIn('result/invalid-infinities', tags(1, M.RNE, 0x7F800000, 0x7F800000))
        self.assertIn('result/negative-zero', tags(1, M.RDN, one, one))


class VectorTests(unittest.TestCase):
    def test_boundaries_reach_every_goal_in_both_formats(self):
        every = (1 << len(M.TAGS)) - 1
        for parameters in P.CONFIGS.values():
            word = 0
            for row in P.boundary_vectors(parameters):
                word |= row[6]
            self.assertEqual(word, every)

    def test_rows_pack_operands_and_results(self):
        model = P.adder(SMALL)
        row = P.row(model, 1, M.RUP, 0x38, [0x01, 0xB8, 0x7F])
        self.assertEqual(row[:4], [1, M.RUP, 0x38, 3])
        self.assertEqual([row[4] >> 8 * i & 0xFF for i in range(3)], [0x01, 0xB8, 0x7F])
        for index, b in enumerate([0x01, 0xB8, 0x7F]):
            code, flags, _ = model.compute(1, M.RUP, 0x38, b)
            self.assertEqual(row[5] >> 13 * index & 0x1FFF, code << 5 | flags)
        self.assertEqual(P.counts(SMALL, [row]), dict(additions=0, subtractions=3, invalid=0,
                         inexact=sum(model.compute(1, M.RUP, 0x38, b)[1] & 1 for b in (0x01, 0xB8, 0x7F))))
        with self.assertRaises(ValueError):
            P.row(P.adder(SINGLE), 0, 0, 0, list(range(200)))

    def test_exhaustive_plan_covers_every_pair_once_per_mode_and_operation(self):
        args = SimpleNamespace(profile='smoke', seed=17, iterations=2, demo_bug=0)
        cases = P.make_cases(args, SMALL)
        exhaustive = [c for c in cases if c['id'].startswith('exhaustive-')]
        self.assertEqual(len(exhaustive), 10)
        for case in exhaustive:
            self.assertEqual(sum(case['counts'][k] for k in ('additions', 'subtractions')), 65536)
            self.assertEqual(sorted(row[2] for row in case['vectors']), list(range(256)))
            self.assertTrue(all(row[3] == 256 for row in case['vectors']))
        self.assertFalse(any(c['id'].startswith('exhaustive-') for c in P.make_cases(args, SINGLE)))
        self.assertEqual(len({(c['vectors'][0][0], c['vectors'][0][1]) for c in exhaustive}), 10)

    def test_seed_reproduction(self):
        self.assertEqual(P.random_vectors(SINGLE, 3, 5), P.random_vectors(SINGLE, 3, 5))
        self.assertNotEqual(P.random_vectors(SINGLE, 3, 5), P.random_vectors(SINGLE, 4, 5))


@unittest.skipUnless(ICARUS, 'Icarus required')
class SimulationTests(unittest.TestCase):
    def test_real_rtl_all_configurations_and_mutants(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / 'out'
            result = run_example('local-fp-adder', out, '--iterations', '3')
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            summary = read_json(out / 'summary.json')
            self.assertTrue(summary['success'] and summary['complete'])
            self.assertEqual((summary['planned'], summary['functional_pass'], summary['mutations_detected']), (28, 14, 14))
            coverage = read_json(out / 'coverage.json')
            self.assertEqual({name: item['hit'] for name, item in coverage.items()}, dict(small=25, binary32=25))
            # The fixed vectors alone reach every goal.
            for name, item in coverage.items():
                self.assertTrue(all(f'{name}-boundaries' in cases for cases in item['hits'].values()))

    def test_demo_faults_make_normal_regression_fail(self):
        with tempfile.TemporaryDirectory() as tmp:
            for fault in range(1, P.MUTANTS + 1):
                out = Path(tmp) / str(fault)
                result = run_example('local-fp-adder', out, '--configuration', 'binary32', '--iterations', '2', '--demo-bug', str(fault))
                self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                self.assertEqual(read_json(out / 'binary32-boundaries/result.json')['status'], 'fail')

    def test_checker_reports_a_wrong_value_a_wrong_flag_and_an_unknown_bit(self):
        model = P.adder(SMALL)
        good = P.row(model, 0, M.RNE, 0x38, [0x38, 0x01])
        self.assertIn('RESULT PASS checks=1', simulate_vectors(P, [good], SMALL).stdout)
        value = list(good); value[5] ^= 1 << 5
        self.assertIn('CHECK_FAIL FP_VALUE', simulate_vectors(P, [value], SMALL).stdout)
        flag = list(good); flag[5] ^= 1 << 13
        self.assertIn('CHECK_FAIL FP_FLAGS', simulate_vectors(P, [flag], SMALL).stdout)
        unknown = {'fp_adder.sv': [('flags[0] = MUTATION == 7 ? guard : inexact;', 'flags[0] = 1\'bx;')]}
        self.assertIn('CHECK_FAIL FP_X', simulate_vectors(P, [good], SMALL, unknown).stdout)

    def test_losing_the_sticky_bit_also_gives_wrong_values(self):
        """Mutant 1 is reported through the inexact flag first; with the flag check removed the value check finds it."""
        edits = {'fp_adder.sv': [('&& MUTATION != 1', '&& 1\'b0')],
                 'fp_adder_tb.sv': [('if (flags !== want[4:0]) fail("FP_FLAGS");', '')]}
        for parameters in P.CONFIGS.values():
            self.assertIn('CHECK_FAIL FP_VALUE', simulate_vectors(P, P.boundary_vectors(parameters), parameters, edits).stdout)


class FormalPlanTests(unittest.TestCase):
    def test_plan_has_a_proof_a_cover_task_and_one_task_per_mutant(self):
        plan = F.plan(F.BOUND, 0)
        self.assertEqual([c['id'] for c in plan], ['adder-proof', 'scenario-cover'] + [f'detect-mutation{m}' for m in range(1, 8)])
        self.assertEqual(plan[0]['parameters'], dict(MUTATION=0, ONLY=0))
        self.assertEqual(F.properties(F.CONFIGS['e4f3'], plan[0])['assert'], {'ap_result', 'ap_flags'})
        for case in plan[2:]:
            # A mutant task keeps only the assertion it must fail, so the counterexample cannot be credited to the other one.
            self.assertEqual(F.properties(F.CONFIGS['e4f3'], case)['assert'], {case['failure']})
            self.assertEqual((case['mode'], case['expect']), ('bmc', 'FAIL'))
        self.assertEqual({F.FAILURES[m] for m in (1, 7)}, {'ap_flags'})
        self.assertEqual(F.plan(F.BOUND, 3)[0]['parameters']['MUTATION'], 3)

    @unittest.skipUnless(FORMAL, 'formal tools required')
    def test_a_mutant_is_refuted_and_the_scenarios_are_reached(self):
        with tempfile.TemporaryDirectory() as tmp:
            for task, outcome in (('detect-mutation2', 'detected'), ('scenario-cover', 'pass')):
                out = Path(tmp) / task
                result = subprocess.run([sys.executable, str(HERE / 'formal.py'), '--configuration', 'e4f3', '--task', task,
                                         '--out', str(out)], capture_output=True, text=True, timeout=300)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertEqual(read_json(out / f'e4f3-{task}/result.json')['outcome'], outcome)


if __name__ == '__main__':
    unittest.main()

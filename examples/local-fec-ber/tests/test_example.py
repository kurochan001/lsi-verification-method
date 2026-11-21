import importlib.util
import itertools
import json
import math
from pathlib import Path
import random
import shutil
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest

HERE = Path(__file__).resolve().parents[1]


def load(name):
    spec = importlib.util.spec_from_file_location('fec_' + name, HERE / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


R = load('run')
M = R.MODEL
ARGS = SimpleNamespace(profile='smoke', seed=17, iterations=6, demo_bug=0)


def run_example(out, *extra):
    return subprocess.run([sys.executable, str(HERE / 'run.py'), '--out', str(out), *extra],
                          capture_output=True, text=True, timeout=540)


def best_distance(received, length):
    """Exhaustive search: the smallest Hamming distance of any terminated code word of this length."""
    best = None
    for data in itertools.product((0, 1), repeat=length):
        sent = M.encode(list(data) + [0, 0])
        distance = sum(bin(a ^ b).count('1') for a, b in zip(sent, received))
        best = distance if best is None else min(best, distance)
    return best


class ModelTest(unittest.TestCase):
    def test_encoder_matches_a_hand_worked_sequence(self):
        # 1 0 1 1 with zero start: c0 = u^u1^u2, c1 = u^u2 -> 11 10 00 01, then the tail 0 0 -> 01 11
        self.assertEqual(M.encode([1, 0, 1, 1, 0, 0]), [3, 2, 0, 1, 1, 3])
        self.assertNotEqual(M.encode([1, 0, 1, 1], wrong_generator=True), M.encode([1, 0, 1, 1]))

    def test_decoder_returns_the_data_without_noise_at_every_depth(self):
        rng = random.Random(3)
        for depth in (2, 3, 9, 16, 24, 64):
            data = [rng.getrandbits(1) for _ in range(90)]
            self.assertEqual(M.run_frame(data, [], depth), data, depth)

    def test_decoder_output_is_a_closest_code_word(self):
        # The decision memory and traceback must find a code word no farther than the exhaustive search does.
        rng = random.Random(11)
        for _ in range(60):
            length = 7
            data = [rng.getrandbits(1) for _ in range(length)]
            noise = [rng.choice((0, 0, 0, 1, 2, 3)) for _ in range(length + 2)]
            received = [a ^ b for a, b in zip(M.encode(data + [0, 0]), noise)]
            decoded = M.run_frame(data, noise, 16)
            found = sum(bin(a ^ b).count('1') for a, b in zip(M.encode(decoded + [0, 0]), received))
            self.assertEqual(found, best_distance(received, length), (data, noise))

    def test_every_single_and_close_double_error_is_corrected(self):
        data = [1, 1, 0, 1, 0, 0, 1, 0, 1, 1, 1, 0]
        size = len(data) + 2
        for depth in (16, 24):
            for index in range(size):
                for value in (1, 2, 3):
                    self.assertEqual(M.run_frame(data, R.pattern(size, (index, value)), depth), data)
                for gap in range(1, 8):
                    if index + gap < size:
                        self.assertEqual(M.run_frame(data, R.pattern(size, (index, 1), (index + gap, 2)), depth), data)

    def test_metric_spread_fits_the_five_bit_registers(self):
        decoder = M.Viterbi(16)
        rng = random.Random(1)
        for _ in range(20000):
            decoder.step(rng.getrandbits(2))          # pure noise is the worst case for the spread
        self.assertLess(decoder.spread + 2, 32)
        self.assertLess(decoder.spread, 16)

    def test_the_two_defective_variants_differ_only_where_the_readme_says(self):
        data, noise = next(R.noisy_frames('noisy', 17, 16, 50, 1))
        self.assertEqual(M.run_frame(data, [], 16, decide=R.SHORT_DECISION), data)
        self.assertEqual(M.run_frame(data, [], 16, upper_wins=True), data)
        self.assertEqual(len(M.decode(M.frame_symbols(data, 16), 16, decide=6)), len(M.decode(M.frame_symbols(data, 16), 16)))


class StatisticsTest(unittest.TestCase):
    def test_binomial_interval_leaves_at_most_half_alpha_in_each_tail(self):
        for n, p, alpha in ((600, 0.1756, 0.001), (600, 0.0424, 0.001), (50, 0.5, 0.05)):
            lo, hi = M.binomial_interval(n, p, alpha)
            pmf = M.binomial_pmf(n, p)
            self.assertAlmostEqual(sum(pmf), 1.0, places=9)
            self.assertLessEqual(sum(pmf[:lo]), alpha / 2)
            self.assertLessEqual(sum(pmf[hi + 1:]), alpha / 2)
            self.assertGreater(sum(pmf[:lo + 1]), alpha / 2)      # one step tighter would exceed it
            self.assertGreater(sum(pmf[hi:]), alpha / 2)

    def test_normal_quantile_and_sum_interval(self):
        self.assertAlmostEqual(M.normal_quantile(0.975), 1.959964, places=5)
        self.assertAlmostEqual(M.normal_quantile(0.9995), 3.290527, places=5)
        lo, hi = M.sum_interval(600, 0.5, 2.0, 0.0, 0.001)
        self.assertEqual((lo, hi), (math.floor(300 - 3.290527 * math.sqrt(1200)), math.ceil(300 + 3.290527 * math.sqrt(1200))))
        skewed = M.sum_interval(600, 0.5, 2.0, 4.0, 0.001)             # a right-skewed count moves both ends up
        self.assertGreater(skewed[0], lo)
        self.assertGreater(skewed[1], hi)
        self.assertEqual(M.moments([0, 1, 0, 1]), (2.0, 1.0, 0.0))

    def test_reference_is_consistent_with_theory(self):
        for key, item in R.EXPECTED['reference'].items():
            probability = int(key.split('/p')[1]) / 1000
            histogram = item['histogram']
            self.assertEqual(sum(histogram), item['frames'])
            rate = sum(k * c for k, c in enumerate(histogram)) / (item['frames'] * R.FRAME_BITS)
            self.assertLess(rate, M.union_bound(probability), key)   # upper bound for unlimited depth
            self.assertLess(rate, probability, key)                  # the code must beat the bare channel
            self.assertGreater(rate, M.pairwise_error(5, probability) / 4, key)
            self.assertGreaterEqual(item['frames'], 100000)

    def test_a_fresh_sample_of_the_model_agrees_with_the_recorded_reference(self):
        item = R.EXPECTED['reference']['depth16/p50']
        fresh = M.measure('selftest', 3000, R.FRAME_BITS, 0.05, 16)
        lo, hi = M.binomial_interval(3000, sum(item['histogram'][1:]) / item['frames'], 1e-6)
        self.assertTrue(lo <= sum(e > 0 for e in fresh) <= hi)

    def test_judgment_rarely_rejects_a_correct_decoder_and_always_the_short_decision(self):
        (bit_low, bit_high), (frame_low, frame_high) = R.bounds(16, 50)
        rejected = 0
        for seed in range(100, 124):
            errors = [sum(a != b for a, b in zip(d, M.run_frame(d, n, 16)))
                      for d, n in R.noisy_frames('statistic', seed, 16, 50, R.EXPECTED['frames'])]
            rejected += not (bit_low <= sum(errors) <= bit_high and frame_low <= sum(e > 0 for e in errors) <= frame_high)
        self.assertLessEqual(rejected, 1)           # the design value is 0.002 per case
        for seed in range(100, 106):
            errors = [sum(a != b for a, b in zip(d, M.run_frame(d, n, 16, decide=R.SHORT_DECISION)))
                      for d, n in R.noisy_frames('statistic', seed, 16, 50, R.EXPECTED['frames'])]
            self.assertGreater(sum(e > 0 for e in errors), frame_high, seed)


class PlanTest(unittest.TestCase):
    def test_seed_reproduction(self):
        parameters = R.CONFIGS['depth16']
        first = R.make_cases(ARGS, parameters)
        self.assertEqual(first, R.make_cases(ARGS, parameters))
        other = R.make_cases(SimpleNamespace(profile='smoke', seed=18, iterations=6, demo_bug=0), parameters)
        self.assertNotEqual(first[2]['vectors'], other[2]['vectors'])
        self.assertEqual(first[0]['vectors'], other[0]['vectors'])     # the fixed scenario does not move

    def test_plan_names_labels_and_profiles(self):
        smoke = R.make_cases(ARGS, R.CONFIGS['depth24'])
        self.assertEqual([c['id'] for c in smoke], [
            'boundaries', 'correctable', 'noisy-seed17', 'statistic-p050',
            *[f'detect-mutation{m}' for m in range(1, 7)],
            'survive-correctable-mutation5', 'survive-statistic-mutation5',
            'survive-correctable-mutation6', 'shared-error-mutation6'])
        self.assertEqual([c['expected_failure'] for c in smoke[4:10]],
                         ['FEC_ENCODE', 'FEC_DECODE', 'FEC_DECODE', 'FEC_VALID', 'FEC_DECODE', 'FEC_FER'])
        nightly = R.make_cases(SimpleNamespace(profile='nightly', seed=17, iterations=6, demo_bug=0), R.CONFIGS['depth24'])
        self.assertEqual(len(nightly), len(smoke) + 3)
        self.assertIn('statistic-p030', [c['id'] for c in nightly])

    def test_fixed_scenarios_reach_every_goal_that_does_not_need_noise_or_statistics(self):
        catalog = json.loads((HERE / 'requirements.json').read_text())
        names = [g for r in catalog['requirements'] for g in r['goals']]
        self.assertEqual(len(names), 20)
        for depth in (16, 24):
            goals = {row[11] for row in R.boundary_rows(depth)}
            self.assertEqual(goals - {0}, set(range(R.ROUNDTRIP, R.FIRST_OUTPUT + 1)) | {R.TIE, R.LONG_STREAM, R.BEST_TIE}, depth)

    def test_the_pattern_beyond_the_capability_is_really_miscorrected(self):
        for depth in (16, 24):
            rows = R.boundary_rows(depth)
            marked = [i for i, row in enumerate(rows) if row[11] == R.BEYOND]
            self.assertEqual(len(marked), 1)
            self.assertGreaterEqual(R.counts(rows, depth)['frame_errors'], 1)

    def test_the_tie_frame_separates_the_two_tie_rules_in_the_fixed_scenario(self):
        for depth in (16, 24):
            self.assertNotEqual([row[5:7] for row in R.boundary_rows(depth)],
                                [row[5:7] for row in R.boundary_rows(depth, upper_wins=True)], depth)
            self.assertNotEqual([row[5:7] for row in R.boundary_rows(depth)],
                                [row[5:7] for row in R.boundary_rows(depth, highest_best=True)], depth)
            self.assertEqual(R.correctable_rows(depth), R.correctable_rows(depth, upper_wins=True), depth)
            self.assertEqual(R.correctable_rows(depth), R.correctable_rows(depth, decide=R.SHORT_DECISION), depth)

    def test_a_packed_frame_expands_to_the_cycles_of_the_unpacked_plan(self):
        data, noise = next(R.noisy_frames('noisy', 17, 16, 50, 1))
        for depth in (16, 24):
            plain, packed = R.Plan(depth), R.Plan(depth, pack=True)
            plain.frame(data, noise, goal=R.NOISY)
            packed.frame(data, noise, goal=R.NOISY)
            self.assertEqual(len(packed.rows), 3)
            self.assertEqual(packed.rows[2][0], 3)
            cycles = R.expand(packed.rows, depth)
            self.assertEqual(len(cycles), len(plain.rows))
            # The single-cycle goals (first output and the like) are the only difference.
            self.assertEqual([c[:11] + c[12:] for c in cycles], [c[:11] + c[12:] for c in plain.rows])
            dropped = {c[11] for c in plain.rows} - {c[11] for c in cycles}
            self.assertTrue(dropped and dropped <= {R.TRANSITIONS, R.SILENT, R.FIRST_OUTPUT}, dropped)
            self.assertEqual({c[11] for c in cycles}, {0, R.NOISY})
        with self.assertRaises(ValueError):
            packed.frame(data, noise, flush=False, reset=False)     # only whole frames after a reset can be packed
        with self.assertRaises(ValueError):
            R.Plan(16, pack=True).frame(data, noise, gaps={3})

    def test_counts_follow_the_rows(self):
        rows = R.noisy_rows(16, 17, 6)
        counted = R.counts(rows, 16)
        self.assertEqual((counted['bits'], counted['frames']), (6 * R.FRAME_BITS, 6))
        self.assertEqual(len(rows), 2 + 6)                      # two reset rows, then one row per frame
        expected = [sum(a != b for a, b in zip(d, M.run_frame(d, n, 16))) for d, n in R.noisy_frames('noisy', 17, 16, 50, 6)]
        self.assertEqual((counted['bit_errors'], counted['frame_errors']), (sum(expected), sum(e > 0 for e in expected)))

    def test_statistic_rows_end_with_the_bounds_and_never_compare_bits(self):
        rows = R.statistic_rows(16, 17, 50)
        (bit_low, bit_high), (frame_low, frame_high) = R.bounds(16, 50)
        self.assertEqual(rows[-1][0], 2)
        self.assertEqual(rows[-1][12:], [bit_low, bit_high, frame_low, frame_high])
        self.assertTrue(all(row[10] == 1 for row in rows if row[5]))
        self.assertEqual(R.counts(rows, 16)['frames'], R.EXPECTED['frames'])
        self.assertEqual(len(rows), 2 + R.EXPECTED['frames'] + 1)
        self.assertLess(bit_low, bit_high)
        self.assertLess(frame_low, frame_high)


class RtlTest(unittest.TestCase):
    """These run Icarus. A missing simulator is a failure, not a skip."""

    def setUp(self):
        self.assertTrue(shutil.which('iverilog') and shutil.which('vvp'), 'Icarus Verilog is required')

    def simulate(self, tmp, rows, depth=16, mutation=0):
        tmp = Path(tmp)
        vectors = tmp / 'vectors.txt'
        vectors.write_text(''.join(' '.join(format(v, 'x') for v in row) + '\n' for row in rows))
        build = subprocess.run(['iverilog', '-g2012', '-s', R.TOP, '-o', str(tmp / 'sim.vvp'), f'-P{R.TOP}.DEPTH={depth}',
                                f'-P{R.TOP}.MUTATION={mutation}', *[str(p) for p in R.SOURCES]], capture_output=True, text=True)
        self.assertEqual(build.returncode, 0, build.stderr)
        return subprocess.run(['vvp', str(tmp / 'sim.vvp'), f'+VECTORS={vectors}'], capture_output=True, text=True, cwd=tmp, timeout=120)

    def test_each_bound_of_the_judgment_row_fails_with_its_own_label(self):
        base = R.noisy_rows(16, 17, 12)
        counted = R.counts(base, 16)
        self.assertGreater(counted['bit_errors'], 0)
        rows = [row[:10] + [1] + row[11:] for row in base]          # count only
        for judge, label in (((0, 10 ** 6, 0, 10 ** 6), None),
                             ((counted['bit_errors'] + 1, 10 ** 6, 0, 10 ** 6), 'FEC_BER'),
                             ((0, counted['bit_errors'] - 1, 0, 10 ** 6), 'FEC_BER'),
                             ((0, 10 ** 6, counted['frame_errors'] + 1, 10 ** 6), 'FEC_FER'),
                             ((0, 10 ** 6, 0, counted['frame_errors'] - 1), 'FEC_FER'),
                             ((counted['bit_errors'], counted['bit_errors'], counted['frame_errors'], counted['frame_errors']), None)):
            with self.subTest(judge=judge), tempfile.TemporaryDirectory() as tmp:
                result = self.simulate(tmp, rows + [[2, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1, 0, *judge]])
                if label is None:
                    self.assertIn(f"RESULT PASS checks={len(rows) + 1}", result.stdout)
                    self.assertIn(f"COUNT bit_errors={counted['bit_errors']}", result.stdout)
                else:
                    self.assertIn('CHECK_FAIL ' + label, result.stdout)
                    self.assertNotIn('RESULT PASS', result.stdout)

    def test_smoke_of_one_configuration_and_its_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / 'out'
            result = run_example(out, '--configuration', 'depth16', '--iterations', '8')
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            summary = json.loads((out / 'summary.json').read_text())
            self.assertEqual((summary['planned'], summary['results'], summary['functional_pass'],
                              summary['mutations_detected'], summary['diagnostics_pass']), (14, 14, 4, 6, 4))
            coverage = json.loads((out / 'coverage.json').read_text())['depth16']
            self.assertEqual((coverage['hit'], coverage['required'], coverage['missing']), (20, 20, []))
            self.assertEqual(json.loads((out / 'depth16-detect-mutation6/result.json').read_text())['message'],
                             'expected mutation detected by FEC_FER')
            for name in ('manifest.json', 'junit.xml', 'tools.json', 'builds.json'):
                self.assertTrue((out / name).is_file(), name)
            manifest = json.loads((out / 'manifest.json').read_text())
            self.assertIn('examples/local-fec-ber/expected.json', manifest['source_sha256'])
            self.assertIn('examples/local-fec-ber/model.py', manifest['source_sha256'])

    def test_demo_bugs_fail_the_normal_cases_that_can_see_them(self):
        with tempfile.TemporaryDirectory() as tmp:
            for bug, failing, passing in ((2, 'boundaries', None), (6, 'statistic-p050', 'correctable')):
                with self.subTest(bug=bug):
                    out = Path(tmp) / str(bug)
                    result = run_example(out, '--configuration', 'depth16', '--iterations', '8', '--demo-bug', str(bug))
                    self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                    self.assertEqual(json.loads((out / f'depth16-{failing}/result.json').read_text())['status'], 'fail')
                    if passing:
                        self.assertEqual(json.loads((out / f'depth16-{passing}/result.json').read_text())['status'], 'pass')

    def test_existing_output_and_bad_arguments_are_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(run_example(Path(tmp)).returncode, 2)
            self.assertEqual(run_example(Path(tmp) / 'new', '--demo-bug', '7').returncode, 2)


if __name__ == '__main__':
    unittest.main()

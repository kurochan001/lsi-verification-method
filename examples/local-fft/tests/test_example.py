import math
from pathlib import Path
import random
import re
import shutil
import sys
import tempfile
from types import SimpleNamespace
import unittest
import xml.etree.ElementTree as ET
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'local-common'))
from local_test_support import load_example, read_json, run_example, simulate_vectors

P = load_example('local-fft')
M = P.M
HERE = Path(__file__).resolve().parents[1]
ICARUS = shutil.which('iverilog') and shutil.which('vvp')
GOALS = 19
SMALL, LARGE, RAW = (P.CONFIGS[name] for name in ('n16-scaled', 'n64-scaled', 'n16-unscaled'))


def shape(parameters):
    return parameters['LOGN'], parameters['WIDTH'], parameters['SCALE']


def args(profile='smoke', seed=17, iterations=3, demo_bug=0):
    return SimpleNamespace(profile=profile, seed=seed, iterations=iterations, demo_bug=demo_bug)


def in_place(samples, logn, width, scale):
    """The transform the way the RTL is built: bit-reversed load, then stage by stage in place."""
    size = 1 << logn
    low, high = M.limits(width)
    memory = [None] * size
    for number, sample in enumerate(samples):
        memory[M.bit_reverse(number, logn)] = sample
    overflow = False

    def finish(value):
        nonlocal overflow
        value = (value + 1) >> 1 if scale else value
        overflow |= not low <= value <= high
        return min(high, max(low, value))

    for stage in range(logn):
        for pair in range(size // 2):
            offset = pair & ((1 << stage) - 1)
            a = ((pair >> stage) << (stage + 1)) | offset
            b = a | (1 << stage)
            angle = offset << (5 - stage)
            (ar, ai), (br, bi) = memory[a], memory[b]
            tr = (M.COS[angle] * br + M.SIN[angle] * bi + M.ROUND) >> M.FRACTION
            ti = (M.COS[angle] * bi - M.SIN[angle] * br + M.ROUND) >> M.FRACTION
            memory[a] = (finish(ar + tr), finish(ai + ti))
            memory[b] = (finish(ar - tr), finish(ai - ti))
    return memory, overflow


def random_frame(rng, parameters, span=None):
    span = span if span is not None else P.tone_amplitude(parameters)
    return [(rng.randint(-span, span), rng.randint(-span, span)) for _ in range(1 << parameters['LOGN'])]


class ModelTests(unittest.TestCase):
    def test_constants_in_the_rtl_are_the_ones_the_model_computes(self):
        rtl = (HERE / 'rtl/fft.sv').read_text()

        def table(name):
            found = {}
            for k, text in re.findall(rf"5'd(\d+): {name}_q14 = ([^;]+);", rtl):
                literal = text.split(':')[-1].strip()                 # the correct value follows a mutation switch
                found[int(k)] = int(literal.replace("16'sd", ''))
            return [found[k] for k in range(32)]
        self.assertEqual(table('cos'), M.COS)
        self.assertEqual(table('sin'), M.SIN)
        self.assertIn(f"(MUTATION == 4) ? 16'sd{M.COS[8] + 1}", rtl)
        self.assertEqual((M.COS[0], M.SIN[0], M.COS[16], M.SIN[16]), (1 << 14, 0, 0, 1 << 14))   # 1 and -j are exact

    def test_the_recursion_is_the_in_place_transform_with_bit_reversal(self):
        self.assertEqual([M.bit_reverse(v, 4) for v in (0, 1, 2, 3, 8, 15)], [0, 8, 4, 12, 1, 15])
        rng = random.Random(5)
        for parameters in (SMALL, LARGE, RAW):
            logn, width, scale = shape(parameters)
            top = P.top(parameters)
            for span in (P.tone_amplitude(parameters), top, 3):
                frame = random_frame(rng, parameters, span)
                self.assertEqual(M.fft(frame, logn, width, scale), in_place(frame, logn, width, scale))
        with self.assertRaises(ValueError):
            M.fft([(0, 0)] * 15, 4, 16, 1)
        with self.assertRaises(ValueError):
            M.fft([(32768, 0)] + [(0, 0)] * 15, 4, 16, 1)

    def test_known_transforms(self):
        size = 16
        # An impulse has a flat spectrum, a constant has one bin, and both are exact.
        self.assertEqual(M.fft([(1600, 0)] + [(0, 0)] * 15, 4, 16, 1), ([(100, 0)] * size, False))
        self.assertEqual(M.fft([(100, -7)] + [(0, 0)] * 15, 4, 16, 0), ([(100, -7)] * size, False))
        self.assertEqual(M.fft([(32767, -32768)] * size, 4, 16, 1), ([(32767, -32768)] + [(0, 0)] * 15, False))
        self.assertEqual(M.fft([(5, 0)] * size, 4, 16, 0)[0][0], (80, 0))
        # Sample 1 of an impulse turns the phase by one step per bin.
        out, _ = M.fft([(0, 0), (16000, 0)] + [(0, 0)] * 14, 4, 16, 0)
        self.assertEqual((out[0], out[4], out[8], out[12]), ((16000, 0), (0, -16000), (-16000, 0), (0, 16000)))
        self.assertEqual(M.reference([(0, 0), (16000, 0)] + [(0, 0)] * 14, 0)[4], (0, -16000))
        # A tone lands in its bin; the integer result is close to, but not always, the rounded transform.
        tone = P.tone(64, 5, 20000, 0.3)
        got, overflow = M.fft(tone, 6, 16, 1)
        ref = M.reference(tone, 1)
        self.assertFalse(overflow)
        self.assertEqual(max(range(64), key=lambda k: got[k][0] ** 2 + got[k][1] ** 2), 5)
        self.assertNotEqual(got, ref)
        self.assertLessEqual(M.errors(tone, 6, 16, 1), M.tolerance(tone, 6, 1))

    def test_the_derived_bound_covers_random_and_structured_frames_and_is_not_vacuous(self):
        rng = random.Random(11)
        for parameters, worst_allowed in ((SMALL, 6), (LARGE, 9), (RAW, 4)):
            logn, width, scale = shape(parameters)
            size, worst = 1 << logn, 0
            frames = [random_frame(rng, parameters) for _ in range(200)]
            frames += [P.tone(size, k, P.tone_amplitude(parameters), 0.2 * k) for k in range(size)]
            for frame in frames:
                error = M.errors(frame, logn, width, scale)
                self.assertLessEqual(error, M.tolerance(frame, logn, scale))
                worst = max(worst, error)
            largest = M.tolerance(P.tone(size, 1, P.tone_amplitude(parameters)), logn, scale)
            self.assertEqual(largest, worst_allowed)
            self.assertGreaterEqual(worst, 1)                       # the integer transform does differ
            self.assertLess(largest, 8 * max(worst, 1))             # and the bound is within one order of it
        # The bound grows with the stages, and with the amplitude through the twiddle error.
        self.assertLess(M.error_bound([(100, 0)] * 16, 4, 1), M.error_bound([(100, 0)] * 64, 6, 1))
        self.assertLess(M.error_bound([(100, 0)] * 64, 6, 1), M.error_bound([(30000, 0)] * 64, 6, 1))
        self.assertEqual(M.error_bound([(100, 0)] * 4, 2, 0), 0.0)  # two stages without scaling are exact
        self.assertEqual(M.tolerance([(100, 0)] * 4, 2, 0), 1)

    def test_parseval_window_holds_for_the_model_and_rejects_a_wrong_spectrum(self):
        rng = random.Random(3)
        for parameters in (SMALL, LARGE, RAW):
            logn, width, scale = shape(parameters)
            for _ in range(50):
                frame = random_frame(rng, parameters)
                out, overflow = M.fft(frame, logn, width, scale)
                self.assertFalse(overflow)
                low, high = M.energy_window(frame, logn, scale)
                energy = sum(re * re + im * im for re, im in out)
                self.assertTrue(low <= energy <= high, (low, energy, high))
                self.assertFalse(low <= sum(4 * (re * re + im * im) for re, im in out) <= high)      # twice the amplitude
                self.assertFalse(low <= energy - max(re * re + im * im for re, im in out) <= high)   # the largest bin missing
        self.assertEqual(M.energy_window([(0, 0)] * 16, 4, 1)[0], 0)

    def test_overflow_edges_are_exact(self):
        for parameters in (SMALL, LARGE, RAW):
            logn, width, scale = shape(parameters)
            size = 1 << logn
            edge = P.overflow_edge(parameters, lambda a: P.square_tone(size, 1, a))
            self.assertFalse(M.fft(P.square_tone(size, 1, edge - 1), logn, width, scale)[1])
            out, overflow = M.fft(P.square_tone(size, 1, edge), logn, width, scale)
            self.assertTrue(overflow)
            self.assertIn(P.top(parameters), [v for sample in out for v in sample])
            deeper = min(P.top(parameters), edge + edge // 8)     # halves round up, so the negative edge lies a little further
            negative, _ = M.fft([(-v, -w) for v, w in P.square_tone(size, 1, deeper)], logn, width, scale)
            self.assertIn(-P.top(parameters) - 1, [v for sample in negative for v in sample])
        constant = P.overflow_edge(RAW, lambda a: [(a, 0)] * 16)
        self.assertEqual(constant, 2048)                             # 16 * 2048 is one more than fits
        self.assertEqual(M.fft([(2047, 0)] * 16, 4, 16, 0), ([(32752, 0)] + [(0, 0)] * 15, False))
        self.assertEqual(M.fft([(2048, 0)] * 16, 4, 16, 0), ([(32767, 0)] + [(0, 0)] * 15, True))
        with self.assertRaises(ValueError):
            P.overflow_edge(SMALL, lambda a: [(a, 0)] * 16)          # a scaled constant never saturates
        with self.assertRaises(ValueError):
            M.errors([(2048, 0)] * 16, 4, 16, 0)

    def test_the_tie_frame_tells_rounding_half_up_from_half_down_and_from_truncation(self):
        for parameters in (SMALL, LARGE, RAW):
            logn, width, scale = shape(parameters)
            frame = P.tie_frame(parameters)
            self.assertEqual(sum(sample != (0, 0) for sample in frame), 1)
            up = M.fft(frame, logn, width, scale)
            self.assertFalse(up[1])
            self.assertNotEqual(up, M.fft(frame, logn, width, scale, M.ROUND - 1))
            self.assertNotEqual(up, M.fft(frame, logn, width, scale, 0))


class PlanTests(unittest.TestCase):
    def test_one_frame_takes_load_run_and_send_clocks_and_ignores_offers_while_busy(self):
        for parameters in (SMALL, LARGE, RAW):
            logn, width, scale = shape(parameters)
            size = 1 << logn
            frame = P.tone(size, 3, P.tone_amplitude(parameters), 0.5)
            quiet, noisy = P.Plan(parameters), P.Plan(parameters)
            quiet.frame(frame)
            noisy.frame(frame, gaps=(0, 5), busy=True)
            self.assertEqual(P.clocks(quiet.rows), size + logn * size // 2 + size)
            self.assertEqual(P.clocks(noisy.rows), P.clocks(quiet.rows) + 2)
            sent = [r for r in quiet.rows if r[5]]
            self.assertEqual(sum(r[15] for r in sent), size)
            self.assertEqual([r[6] for r in sent][-1], 1)
            self.assertEqual(sum(r[6] * r[15] for r in sent), 1)
            out, _ = M.fft(frame, logn, width, scale)
            expanded = [(r[8], r[9]) for r in sent for _ in range(r[15])]
            self.assertEqual(expanded, [(re & P.MASK, im & P.MASK) for re, im in out])
            self.assertEqual([r[5:15] for r in sent], [r[5:15] for r in noisy.rows if r[5]])
            self.assertEqual({r[4] for r in noisy.rows if r[1] and r[2] == 0x7abc}, {0})   # offered while not ready
            self.assertTrue(quiet.idle() and noisy.idle())

    def test_reset_drops_the_frame_in_every_phase(self):
        size = 16
        frame = P.tone(size, 2, 1000)
        for clocks_before_reset in (5, size + 3, size + 32 + 4):          # loading, running, sending
            p = P.Plan(SMALL)
            p.frame(frame, wait=False) if clocks_before_reset >= size else [p.cycle(valid=1, re=1, im=1) for _ in range(5)]
            while P.clocks(p.rows) < clocks_before_reset:
                p.cycle()
            p.cycle(rst=0)
            self.assertTrue(p.idle())
            before = len(p.rows)
            p.frame(frame)
            self.assertEqual(P.counts(p.rows[before:])['frames'], 1)
        c = P.counts(P.boundary_vectors(SMALL))
        self.assertGreater(c['accepted'], c['outputs'])                    # samples of dropped frames
        self.assertLess(c['frames'] * size, c['outputs'])                  # and bins of a frame cut while sending

    def test_identical_clocks_share_one_row_and_counts_weigh_them(self):
        p = P.Plan(SMALL)
        p.frame([(7, 7)] * 16)
        loaded = [r for r in p.rows if r[1]]
        self.assertEqual((len(loaded), loaded[0][15]), (1, 16))            # sixteen equal samples: one row
        self.assertEqual(P.counts(p.rows), dict(accepted=16, frames=1, outputs=16, overflow_frames=0, inexact=0))
        self.assertLess(len(p.rows), 10)
        self.assertEqual(P.clocks(p.rows), 16 + 32 + 16)

    def test_fixed_rows_hold_each_edge_and_one_past_it(self):
        for parameters in (SMALL, LARGE, RAW):
            rows = P.boundary_vectors(parameters)
            c = P.counts(rows)
            self.assertGreaterEqual(c['overflow_frames'], 3)
            self.assertGreater(c['inexact'], 0)
            size = 1 << parameters['LOGN']
            edge = P.overflow_edge(parameters, lambda a: P.square_tone(size, 1, a))
            loaded = {r[2] for r in rows if r[1] and r[4]}
            self.assertLessEqual({edge - 1, edge}, loaded)
            self.assertLessEqual({P.top(parameters), (-P.top(parameters) - 1) & P.MASK}, loaded)
        raw = {r[2] for r in P.boundary_vectors(RAW) if r[1] and r[4]}
        self.assertLessEqual({2047, 2048}, raw)
        self.assertEqual(P.core_frames(SMALL).rows, P.boundary_vectors(SMALL)[:len(P.core_frames(SMALL).rows)][:-1] + [P.core_frames(SMALL).rows[-1]])

    def test_plan_names_seeds_and_expected_failures(self):
        smoke, nightly = P.make_cases(args(), SMALL), P.make_cases(args('nightly'), SMALL)
        names = ['boundaries', 'random-seed17', 'limit-observed', 'limit-one-less',
                 *[f'detect-mutation{m}' for m in range(1, P.MUTANTS + 1)]]
        self.assertEqual([c['id'] for c in smoke], names)
        self.assertEqual([c['id'] for c in nightly], names[:2] + ['random-seed18', 'random-seed19'] + names[2:])
        self.assertEqual({c['id']: (c['category'], c['expected_failure']) for c in smoke if c['expected_failure']},
                         {'limit-one-less': ('diagnostic', 'FFT_TOLERANCE'),
                          **{f'detect-mutation{m}': ('mutation', P.LABELS[m]) for m in range(1, P.MUTANTS + 1)}})
        self.assertEqual(smoke, P.make_cases(args(), SMALL))
        other = P.make_cases(args(seed=18), SMALL)
        self.assertNotEqual(smoke[1]['vectors'], other[1]['vectors'])
        self.assertEqual(smoke[0]['vectors'], other[0]['vectors'])
        self.assertEqual(len({tuple(map(tuple, c['vectors'])) for c in smoke[4:]}), 1)   # every mutant sees the short scenario
        self.assertLess(len(smoke[4]['vectors']), len(smoke[0]['vectors']))

    def test_the_two_tightened_cases_differ_by_exactly_one_unit(self):
        for parameters in (SMALL, LARGE, RAW):
            cases = {c['id']: c for c in P.make_cases(args(), parameters)}
            limit = P.observed_limit(parameters)
            for name, value in (('limit-observed', limit), ('limit-one-less', limit - 1)):
                self.assertEqual({r[12] for r in cases[name]['vectors'] if r[5]}, {value}, name)
            self.assertGreater(limit, 0)
            self.assertLess(limit, M.tolerance(P.probe_frames(parameters)[0], parameters['LOGN'], parameters['SCALE']))
            self.assertEqual(len(P.probe_frames(parameters)), P.PROBE_FRAMES)


class RtlTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(ICARUS, 'Icarus is required for these tests')

    def rows(self, edit=None, parameters=SMALL):
        p = P.Plan(parameters)
        p.cycle(rst=0)
        p.frame(P.tone(16, 3, 9000, 0.4), gaps=(2,), busy=True)
        p.frame([(900, -40)] + [(0, 0)] * 15)
        p.cycle()
        rows = [list(r) for r in p.rows]
        if edit:
            edit(rows, [i for i, r in enumerate(rows) if r[5]])
        return rows

    def run_rows(self, edit=None, replacements=None):
        return simulate_vectors(P, self.rows(edit), SMALL, replacements).stdout

    def test_each_check_of_the_testbench_fails_alone(self):
        self.assertIn(f'RESULT PASS checks={len(self.rows())}', self.run_rows())

        def exact_only(rows, sent):          # one unit off, still inside the tolerance
            rows[sent[3]][8] = (rows[sent[3]][8] + 1) & P.MASK
        self.assertIn('CHECK_FAIL FFT_DATA', self.run_rows(exact_only))

        def far(rows, sent):                 # the reference moved away: tolerance fails before the exact check
            rows[sent[3]][11] = (rows[sent[3]][11] + 40) & P.MASK
        self.assertIn('CHECK_FAIL FFT_TOLERANCE', self.run_rows(far))

        def not_ready(rows, sent):
            rows[sent[0] - 1][4] = 1
        self.assertIn('CHECK_FAIL FFT_READY', self.run_rows(not_ready))

        def early(rows, sent):
            rows[sent[0] - 1][5] = 1
        self.assertIn('CHECK_FAIL FFT_VALID', self.run_rows(early))

        def missing(rows, sent):
            rows[sent[2]][5] = 0
        self.assertIn('CHECK_FAIL FFT_VALID', self.run_rows(missing))

        def last(rows, sent):
            rows[sent[4]][6] = 1
        self.assertIn('CHECK_FAIL FFT_LAST', self.run_rows(last))

        def flag(rows, sent):
            rows[sent[1]][7] = 1
        self.assertIn('CHECK_FAIL FFT_OVERFLOW', self.run_rows(flag))

        def energy_low(rows, sent):          # the window moved above the sum
            final = [i for i in sent if rows[i][6]][0]
            rows[final][13] = rows[final][14] + 1
            rows[final][14] = rows[final][13] + 10
        self.assertIn('CHECK_FAIL FFT_ENERGY', self.run_rows(energy_low))

        def energy_high(rows, sent):
            final = [i for i in sent if rows[i][6]][0]
            rows[final][14] = rows[final][13] - 1
        self.assertIn('CHECK_FAIL FFT_ENERGY', self.run_rows(energy_high))

    def test_a_saturating_frame_skips_the_tolerance_but_not_the_exact_check(self):
        p = P.Plan(RAW)
        p.cycle(rst=0)
        p.frame([(2048, 0)] * 16)
        p.cycle()
        rows = [list(r) for r in p.rows]
        self.assertEqual({r[12] for r in rows if r[5]}, {P.SKIP})
        self.assertIn(f'RESULT PASS checks={len(rows)}', simulate_vectors(P, rows, RAW).stdout)
        first = [i for i, r in enumerate(rows) if r[5]][0]
        rows[first][8] -= 1
        self.assertIn('CHECK_FAIL FFT_DATA', simulate_vectors(P, rows, RAW).stdout)

    def test_an_unknown_output_is_not_a_pass(self):
        unknown = {'fft.sv': [("assign out_im = out_valid ? mem_im[index] : '0;", "assign out_im = 'x;")]}
        self.assertIn('CHECK_FAIL FFT_UNKNOWN', self.run_rows(replacements=unknown))

    def test_real_rtl_all_configurations_mutants_and_the_tightened_limit(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / 'out'
            result = run_example('local-fft', out, '--iterations', '2')
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            summary = read_json(out / 'summary.json')
            planned = 3 * (4 + P.MUTANTS)
            self.assertEqual((summary['success'], summary['complete'], summary['planned'], summary['results']), (True, True, planned, planned))
            self.assertEqual((summary['functional_pass'], summary['mutations_detected'], summary['diagnostics_pass']),
                             (9, 3 * (P.MUTANTS + 1), 0))
            coverage = read_json(out / 'coverage.json')
            self.assertEqual({k: (v['hit'], v['missing']) for k, v in coverage.items()}, {k: (GOALS, []) for k in P.CONFIGS})
            suite = ET.parse(out / 'junit.xml').getroot()
            self.assertEqual((suite.get('tests'), suite.get('failures'), suite.get('errors')), (str(planned + 3), '0', '0'))
            for name in P.CONFIGS:
                # The fixed scenario alone reaches every goal; the random case is not needed for coverage.
                self.assertEqual(len(read_json(out / f'{name}-boundaries/result.json')['credited_coverage']), GOALS, name)
                for m, label in P.LABELS.items():
                    record = read_json(out / f'{name}-detect-mutation{m}/result.json')
                    self.assertEqual((record['status'], record['credited_coverage']), ('detected', []), (name, m))
                    self.assertIn(label, record['message'])
                tight = read_json(out / f'{name}-limit-one-less/result.json')
                self.assertEqual((tight['status'], tight['category']), ('detected', 'diagnostic'))
                self.assertIn('$enddefinitions', (out / f'{name}-boundaries/wave.vcd').read_text())
            manifest = read_json(out / 'manifest.json')
            self.assertEqual((manifest['seed'], manifest['profile']), (17, 'smoke'))
            self.assertEqual(len(manifest['cases']), planned)

    def test_demo_faults_make_the_normal_regression_fail(self):
        with tempfile.TemporaryDirectory() as tmp:
            for fault in range(1, P.MUTANTS + 1):
                out = Path(tmp) / str(fault)
                result = run_example('local-fft', out, '--configuration', 'n16-scaled', '--iterations', '1', '--demo-bug', str(fault))
                self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                record = read_json(out / 'n16-scaled-boundaries/result.json')
                self.assertEqual(record['status'], 'fail')
                self.assertIn(P.LABELS[fault], record['message'])
                self.assertEqual(read_json(out / 'n16-scaled-limit-one-less/result.json')['status'], 'detected')   # always the correct circuit


if __name__ == '__main__':
    unittest.main()

from pathlib import Path
import random, re, sys, tempfile, unittest
from types import SimpleNamespace
import xml.etree.ElementTree as ET
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'local-common'))
from local_test_support import load_example, read_json, run_example, simulate_vectors

P = load_example('local-image-scaler')
M = P.M
HERE = Path(__file__).resolve().parents[1]
STREAM = ['stream/in-gap', 'stream/in-wait', 'stream/out-stall']   # observed by the bench itself
GOALS = len(P.TAGS) + len(STREAM)


def accumulators(size_in, size_out, bits=None):
    """The comparison of the design, in Python: exact unless the width is cut (bits)."""
    mask = (1 << bits) - 1 if bits else -1
    a, b, p, out = size_in & mask, (2 * size_out) & mask, 0, []
    for _ in range(size_out):
        steps = 0
        while not a < b:
            p, b, steps = p + 1, (b + 2 * size_out) & mask, steps + 1
            if steps > 10000:
                return None
        out.append(p)
        a = (a + 2 * size_in) & mask
    return out


class ModelTests(unittest.TestCase):
    def test_centre_aligned_nearest_neighbour(self):
        self.assertEqual([M.source_index(x, 4, 3) for x in range(3)], [0, 2, 3])        # 3/4
        self.assertEqual([M.source_index(x, 3, 5) for x in range(5)], [0, 0, 1, 2, 2])  # 5/3
        self.assertEqual([M.source_index(x, 5, 5) for x in range(5)], list(range(5)))
        self.assertEqual(M.resize([[1, 2], [3, 4]], 2, 2, 1, 1), [[4]])                  # centre of a 2x2 frame
        self.assertTrue(M.tie(1, 4, 3))                    # 3/2 * 4/3 = 2: on the boundary of columns 1 and 2
        self.assertFalse(any(M.tie(x, 3, 5) for x in range(5)))   # an odd source never ties
        self.assertEqual(M.period(4, 3), 3)
        with self.assertRaises(ValueError):
            M.resize([[1, 2]], 3, 1, 1, 1)

    def test_the_accumulator_comparison_equals_the_rational_model_for_every_size(self):
        for size_in in range(1, 25):
            for size_out in range(1, 25):
                self.assertEqual(accumulators(size_in, size_out),
                                 [M.source_index(x, size_in, size_out) for x in range(size_out)], (size_in, size_out))

    def test_a_rounded_fixed_point_step_drifts_where_the_exact_phase_does_not(self):
        # 5/3 with an eight-bit fractional step: the rounding error adds up along a line.
        drift = M.first_drift(5, 3, 8, 256)
        self.assertIsNotNone(drift)
        self.assertGreater(drift, 24)                      # beyond every frame of this example
        self.assertIsNone(M.first_drift(4, 2, 8, 256))     # an exact power-of-two step never drifts

    def test_one_bit_narrower_accumulators_fail_only_at_the_largest_widths(self):
        for max_w, narrow in ((12, 8), (24, 10)):
            bad = {(i, o) for i in range(1, max_w + 1) for o in range(1, max_w + 1)
                   if accumulators(i, o, narrow) != [M.source_index(x, i, o) for x in range(o)]}
            self.assertTrue(bad, max_w)
            self.assertTrue(all(i >= max_w - 2 and o >= max_w - 2 for i, o in bad), (max_w, bad))


class PlanTests(unittest.TestCase):
    def test_fixed_plan_tags_every_goal_in_both_configurations(self):
        for name, parameters in P.CONFIGS.items():
            plan = P.boundary_rows(parameters)
            tags = 0
            for row in plan.rows:
                tags |= row[6]
            self.assertEqual([t for t in P.TAGS if not tags & P.BIT[t]], [], name)
            self.assertTrue(any(r[0] == P.PIXEL and r[2] for r in plan.rows))       # input gaps
            self.assertTrue(any(r[0] == P.EXPECT and r[3] for r in plan.rows))      # output stalls

    def test_each_refused_size_breaks_exactly_one_rule(self):
        for parameters in P.CONFIGS.values():
            mw, mh = parameters['MAX_W'], parameters['MAX_H']
            refused = [r for r in P.boundary_rows(parameters).rows if r[0] == P.CONFIG and r[5] & P.ERROR]
            self.assertEqual(len(refused), 8)
            for row in refused:
                limits = (mw, mh, mw, mh)
                broken = [i for i, (v, top) in enumerate(zip(row[1:5], limits)) if not 1 <= v <= top]
                self.assertEqual(len(broken), 1, row)

    def test_catalog_and_bench_name_the_same_goals(self):
        catalog = read_json(HERE / 'requirements.json')
        self.assertEqual(sorted(g for r in catalog['requirements'] for g in r['goals']), sorted(P.TAGS + STREAM))
        bench = (HERE / 'tb/image_scaler_tb.sv').read_text()
        self.assertEqual(re.findall(r'\d+: goal = "([^"]+)";', bench), P.TAGS)

    def test_random_frames_are_reproducible(self):
        parameters = P.CONFIGS['max12']
        self.assertEqual(P.random_rows(parameters, 17, 3).rows, P.random_rows(parameters, 17, 3).rows)
        self.assertNotEqual(P.random_rows(parameters, 17, 3).rows, P.random_rows(parameters, 18, 3).rows)
        args = SimpleNamespace(profile='nightly', seed=17, iterations=2, demo_bug=0)
        ids = [c['id'] for c in P.make_cases(args, parameters)]
        self.assertEqual(ids, ['boundaries', 'random-seed17', 'random-seed18', 'random-seed19'] +
                         [f'detect-mutation{m}' for m in range(1, 10)])


class RtlTests(unittest.TestCase):
    def test_real_rtl_both_configurations_and_every_mutant(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / 'out'
            result = run_example('local-image-scaler', out, '--iterations', '2')
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            summary = read_json(out / 'summary.json')
            self.assertEqual((summary['success'], summary['complete'], summary['planned']), (True, True, 22))
            self.assertEqual(summary['mutations_detected'], 18)
            coverage = read_json(out / 'coverage.json')
            self.assertEqual({k: (v['hit'], v['missing']) for k, v in coverage.items()}, {k: (GOALS, []) for k in P.CONFIGS})
            suite = ET.parse(out / 'junit.xml').getroot()
            self.assertEqual((suite.get('tests'), suite.get('failures'), suite.get('errors')), ('24', '0', '0'))
            for name in P.CONFIGS:
                for m in range(1, 10):
                    self.assertIn(P.LABELS[m], read_json(out / f'{name}-detect-mutation{m}/result.json')['message'])

    def test_demo_fault_fails_the_normal_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / 'demo'
            result = run_example('local-image-scaler', out, '--configuration', 'max12', '--iterations', '1', '--demo-bug', '2')
            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            self.assertEqual(read_json(out / 'max12-boundaries/result.json')['status'], 'fail')

    def test_bench_reports_extra_output_unknown_data_and_a_stuck_scaler_with_their_own_labels(self):
        parameters = P.CONFIGS['max12']
        plan = P.Plan(parameters, random.Random(3))
        plan.frame(4, 4, 3, 3)
        plan.frame(3, 3, 5, 5)
        rows = plan.rows
        self.assertIn('RESULT PASS checks=%d' % len(rows), simulate_vectors(P, rows, parameters).stdout)
        single = P.Plan(parameters, random.Random(4))
        single.frame(2, 2, 1, 1)
        narrow = P.Plan(parameters, random.Random(5))
        narrow.frame(1, 2, 3, 1)
        narrow.frame(2, 2, 2, 2)
        for plan_rows, edits, label in (
                (single.rows, [('state <= DECIDE;\n                            end', 'state <= EMIT;\n                            end')], 'SCALE_EXTRA'),
                (rows, [('out_pixel <= line_mem[p[AW-1:0]];', "out_pixel <= ox == 8'd1 ? 'x : line_mem[p[AW-1:0]];")], 'SCALE_DATA'),
                (rows, [('if (col_here) begin', "if (1'b0) begin")], 'SCALE_TIMEOUT'),
                # a one-pixel-wide row that waits for a second pixel swallows the next frame
                (narrow.rows, [("state <= cfg_in_w == 8'd1 ? DECIDE : FILL;", 'state <= FILL;')], 'SCALE_FRAME')):
            log = simulate_vectors(P, plan_rows, parameters, {'image_scaler.sv': edits}).stdout
            self.assertIn('CHECK_FAIL ' + label, log, label)
        self.assertNotIn('SCALE_TIMEOUT', P.LABELS.values())     # a hang never counts as a detected mutant


if __name__ == '__main__':
    unittest.main()

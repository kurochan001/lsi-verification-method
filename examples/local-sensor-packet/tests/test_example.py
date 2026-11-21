from itertools import combinations
from pathlib import Path
import random
import re
import sys
from types import SimpleNamespace
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'local-common'))
from local_test_support import load_example, read_json, simulate_vectors
from system_test_support import SystemContract

P = load_example('local-sensor-packet')
M = P.M
HERE = Path(__file__).resolve().parents[1]
RTL = (HERE / 'rtl/sensor_packet_rx.sv').read_text()
BENCH = (HERE / 'tb/sensor_packet_tb.sv').read_text()
DERIVED = ['pipeline/frame', 'lanes/queue-full']        # printed by the bench from what the circuit did


def shape(name):
    c = P.CONFIGS[name]
    return c['LANES'], c['MAX_LINE'], c['PIPE_W'], c['PIPE_H']


def pixels_out(outputs):
    return [o['pix_data'] for o in outputs if o['pix_valid']]


class Contract(SystemContract, unittest.TestCase):
    EXAMPLE = 'local-sensor-packet'
    GOALS = len(P.GOALS) + len(DERIVED)


class CodeTests(unittest.TestCase):
    def test_crc_matches_the_published_check_value(self):
        # CRC-16/MCRF4XX: reflected 0x1021, start 0xffff, no final inversion.
        self.assertEqual(M.crc16(b'123456789'), 0x6f91)
        self.assertEqual(M.crc16([]), 0xffff)

    def test_crc_table_agrees_with_a_bit_serial_division(self):
        rng = random.Random(1)
        for _ in range(50):
            data = [rng.randrange(256) for _ in range(rng.randrange(1, 12))]
            value = 0xffff
            for byte in data:
                for bit in range(8):
                    feedback = (value ^ byte >> bit) & 1
                    value = value >> 1 ^ (0x8408 if feedback else 0)
            self.assertEqual(M.crc16(data), value)

    def test_header_code_is_linear_and_has_distance_four(self):
        rng = random.Random(2)
        for _ in range(200):
            a, b = rng.randrange(1 << 24), rng.randrange(1 << 24)
            self.assertEqual(M.ecc_encode(a ^ b), M.ecc_encode(a) ^ M.ecc_encode(b))
        # A linear code has minimum distance four when no word of data weight 1..3 has total weight below four.
        for weight in (1, 2, 3):
            for bits in combinations(range(24), weight):
                value = sum(1 << b for b in bits)
                self.assertGreaterEqual(weight + bin(M.ecc_encode(value)).count('1'), 4, bits)

    def test_every_single_flip_is_repaired_and_every_double_flip_refused(self):
        rng = random.Random(3)
        for value in (0, 0xffffff, 0x2a0003, *[rng.randrange(1 << 24) for _ in range(4)]):
            word = [value & 0xff, value >> 8 & 0xff, value >> 16, M.ecc_encode(value)]
            self.assertEqual(M.header_decode(*word), (value, False))
            for bit in range(30):
                self.assertEqual(M.header_decode(*P.flip(word, [bit])), (value, True), bit)
            for pair in combinations(range(30), 2):
                self.assertIsNone(M.header_decode(*P.flip(word, pair)), pair)
            for bit in (30, 31):
                self.assertIsNone(M.header_decode(*P.flip(word, [bit])))

    def test_rtl_masks_and_positions_are_the_positional_definition(self):
        masks = [int(v, 16) for v in re.findall(r"MASK\d = 24'h([0-9a-f]{6})", RTL)]
        self.assertEqual(masks, [sum(1 << k for k, p in enumerate(M.POSITIONS) if p >> j & 1) for j in range(5)])
        table = re.search(r'POS = \{(.*?)\};', RTL, re.S).group(1)
        self.assertEqual([int(v) for v in re.findall(r"5'd(\d+)", table)], M.POSITIONS[::-1])
        self.assertEqual(len(M.POSITIONS), 24)

    def test_packet_layout(self):
        self.assertEqual(M.short_packet(M.T_LS, 0x0102)[:3], [M.T_LS, 0x02, 0x01])
        packet = M.long_packet(M.T_ROW, [7, 8, 9])
        self.assertEqual(packet[:3] + packet[4:7], [M.T_ROW, 3, 0, 7, 8, 9])
        self.assertEqual(packet[7] | packet[8] << 8, M.crc16([7, 8, 9]))
        self.assertEqual(len(M.frame_packets(1, [[1], [2]])), 8)


class ReceiverTests(unittest.TestCase):
    def test_a_clean_frame_survives_every_tolerated_skew_on_every_lane(self):
        for name in P.CONFIGS:
            lanes, max_line, _, _ = shape(name)
            limit = P.skew_limit(lanes, max_line)
            lines = [[(17 * y + 5 * x + 1) & 0xff for x in range(max_line)] for y in range(3)]
            for lane in range(lanes):
                for late in range(limit):
                    s = P.Stim(lanes, max_line)
                    s.reset()
                    s.burst(P.flat(M.frame_packets(9, lines)), skew=[late if i == lane else 0 for i in range(lanes)])
                    s.sync()
                    self.assertEqual(pixels_out(s.outputs), sum(lines, []), (name, lane, late))
                    self.assertEqual(sum(o['frame_clean'] for o in s.outputs), 1)
                    self.assertFalse(any(o['err'] for o in s.outputs))

    def test_the_skew_limit_fills_a_queue_and_one_more_row_overflows(self):
        for name in P.CONFIGS:
            lanes, max_line, _, _ = shape(name)
            limit = P.skew_limit(lanes, max_line)
            stream = P.flat(P.small_frame(0, (max_line,) * 3))
            for late, overflow in ((limit - 1, False), (limit, True)):
                s = P.Stim(lanes, max_line)
                s.reset()
                s.burst(stream, skew=[late] + [0] * (lanes - 1))
                receiver, deepest, errors = M.Receiver(lanes, max_line), 0, 0
                for row in s.rows:
                    errors |= receiver.edge(row['rst_n'], row['active'], row['valid'], row['data'])['err']
                    deepest = max(deepest, *(len(q) for q in receiver.queue))
                self.assertEqual(bool(errors & M.ERR_LANE), overflow, (name, late))
                self.assertEqual(deepest, M.DEPTH)

    def test_what_follows_a_header_that_cannot_be_used_is_discarded(self):
        s = P.Stim(2, 8)
        s.reset()
        s.burst(P.flat([P.flip(M.short_packet(M.T_FS, 1), (0, 1)), M.short_packet(M.T_FS, 2)]))
        s.burst(M.short_packet(M.T_FS, 3))
        s.sync()
        self.assertEqual([o['evt_num'] for o in s.outputs if o['frame_start']], [3])
        self.assertEqual(sum(bin(o['err']).count('1') for o in s.outputs), 1)


class PlanTests(unittest.TestCase):
    def test_goal_names_agree_between_plan_bench_and_requirements(self):
        table = dict((int(i), name) for i, name in re.findall(r'(\d+): goal = "([^"]+)"', BENCH))
        self.assertEqual([table[i] for i in range(len(P.GOALS))], P.GOALS)
        self.assertEqual(len(table), len(P.GOALS))
        self.assertIn(f'k <= {len(P.GOALS) - 1};', BENCH)
        listed = [g for r in read_json(HERE / 'requirements.json')['requirements'] for g in r['goals']]
        self.assertEqual(sorted(listed), sorted(P.GOALS + DERIVED))

    def test_every_goal_is_tagged_once_by_the_fixed_scenes(self):
        for name in P.CONFIGS:
            stim = P.boundary_stim(*shape(name))
            tags = [row['tags'] for row in stim.rows]
            for index, goal in enumerate(P.GOALS):
                self.assertEqual(sum(tag >> index & 1 for tag in tags), 1, (name, goal))

    def test_a_scene_that_does_not_show_its_effect_is_refused(self):
        s = P.Stim(2, 8)
        s.reset()
        with self.assertRaisesRegex(ValueError, 'does not show its effect'):
            s.scene('row/crc-error', lambda: s.burst(P.flat(P.small_frame(1))), lambda out: out['err'] & M.ERR_CRC)
        with self.assertRaisesRegex(ValueError, 'does not show its effect'):   # an error the scene does not allow
            s.scene('seq/frame-clean', lambda: s.burst(M.short_packet(M.T_FE, 1)), lambda out: True)

    def test_plan_ids_labels_and_counts(self):
        args = SimpleNamespace(profile='nightly', seed=5, iterations=3, demo_bug=0)
        for name, parameters in P.CONFIGS.items():
            cases = P.make_cases(args, parameters)
            self.assertEqual([c['id'] for c in cases], ['boundaries', 'random-seed5', 'random-seed6', 'random-seed7'] +
                             [f'detect-mutation{m}' for m in range(1, P.MUTANTS + 1)])
            self.assertEqual([c['expected_failure'] for c in cases[4:]],
                             [P.label(m, parameters['LANES']) for m in range(1, P.MUTANTS + 1)])
            fixed = cases[0]['counts']
            self.assertEqual(fixed['pipe_pixels'], 2 * parameters['PIPE_W'] * parameters['PIPE_H'])
            self.assertGreater(min(fixed['errors'], fixed['fixes'], fixed['rows_ok'], fixed['frames_clean']), 20)
            self.assertEqual(cases[1]['counts']['pipe_pixels'], 0)
            self.assertTrue(all(len(row) == 3 for row in fixed and cases[0]['vectors']))

    def test_random_cases_reach_errors_and_clean_frames(self):
        for name in P.CONFIGS:
            lanes, max_line, _, _ = shape(name)
            stim = P.random_stim(11, 60, lanes, max_line)
            c = P.counts(stim)
            self.assertGreater(c['frames_clean'], 5)
            self.assertGreater(c['errors'], 5)


class CheckerTests(unittest.TestCase):
    """The bench must report a wrong expectation, and an unknown output, under the right label."""

    def vectors(self, name='lanes2'):
        lanes, max_line, _, _ = shape(name)
        s = P.Stim(lanes, max_line)
        s.reset()
        s.burst(P.flat([M.short_packet(0x1f, 1)] + P.small_frame(3) + [M.short_packet(M.T_FE, 9)]))
        return s.vectors()

    def run_rows(self, rows, **options):
        return simulate_vectors(P, rows, parameters=P.CONFIGS['lanes2'], **options)

    def test_clean_vectors_pass(self):
        result = self.run_rows(self.vectors())
        self.assertIn('RESULT PASS', result.stdout)
        self.assertNotIn('CHECK_FAIL', result.stdout)

    def test_each_wrong_expectation_has_its_label(self):
        rows = self.vectors()
        find = lambda bit: next(i for i, row in enumerate(rows) if row[1] >> bit & 1)   # noqa: E731
        for label, index, change in (('SP_PIXEL', find(0), 1 << 16), ('SP_PIXEL', find(1), 1 << 1),
                                     ('SP_ROW', find(3), 1 << 4), ('SP_FRAME', find(5), 1 << 24),
                                     ('SP_FRAME', find(6), 1 << 7), ('SP_ERROR', find(9), 1 << 9),
                                     ('SP_ERROR', find(12), 1 << 12)):
            changed = [list(row) for row in rows]
            changed[index][1] ^= change
            result = self.run_rows(changed)
            self.assertIn('CHECK_FAIL ' + label, result.stdout, (label, index))
            self.assertNotIn('RESULT PASS', result.stdout)

    def test_unknown_outputs_fail(self):
        for old, new, label in (("pix_data <= n_pix ? popped : 8'd0;", "pix_data <= n_pix ? 8'bx : 8'd0;", 'SP_PIXEL'),
                                ('err <= e;', "err <= 6'bx;", 'SP_ERROR')):
            result = self.run_rows(self.vectors(), replacements={'sensor_packet_rx.sv': [(old, new)]})
            self.assertIn('CHECK_FAIL ' + label, result.stdout)

    def test_a_frame_the_pipeline_cannot_take_is_reported(self):
        lanes, max_line, width, height = shape('lanes2')
        s = P.Stim(lanes, max_line)
        s.pipe = 1
        s.reset()
        # Rows one pixel too wide: the frame is complete in the middle of the last row, and the
        # pipeline is padding when the next pixel arrives.
        s.burst(P.flat(M.frame_packets(1, [[1] * (width + 1)] * height)))
        result = self.run_rows(s.vectors())
        self.assertIn('CHECK_FAIL SP_PIPE', result.stdout)


if __name__ == '__main__':
    unittest.main()

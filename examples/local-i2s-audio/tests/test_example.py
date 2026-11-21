from pathlib import Path
import random
import shutil
import sys
import tempfile
from types import SimpleNamespace
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'local-common'))
from local_test_support import assert_evidence, load_example, read_json, run_example, simulate_vectors

P = load_example('local-i2s-audio')
SHAPES = {name: (c['WORD'], c['SLOT']) for name, c in P.CONFIGS.items()}
GOALS = 17
# Row columns.
RST, VALID, LEFT, RIGHT, SEL, E_SCK, E_WS, E_SD, READY, SCK, WS, SD, UNDER, FRAMES, RX_L, RX_R, ERRORS = range(17)


def decode(samples, word):
    """A third way to read I2S: delay ws by one sample, then cut the data wherever it changes."""
    delayed = [None] + [ws for ws, _ in samples[:-1]]
    words, run, channel = [], [], None
    for (_, sd), ws in zip(samples, delayed):
        if ws != channel:
            if channel is not None and run:
                words.append((channel, P.bits_word(run, word)))
            run, channel = [], ws
        run.append(sd)
    return words


def tx_samples(rows):
    """(ws, sd) on the rising edges of the transmitter's sck, read from the expected pins."""
    return [(now[WS], now[SD]) for before, now in zip(rows, rows[1:]) if now[RST] and now[SCK] and not before[SCK]]


def deliveries(rows):
    out, last = [], 0
    for r in rows:
        if not r[RST]:
            last = 0
        elif r[FRAMES] != last:
            out.append((r[RX_L], r[RX_R]))
            last = r[FRAMES]
    return out


class ModelTests(unittest.TestCase):
    def test_a_word_goes_out_msb_first_and_comes_back(self):
        self.assertEqual(P.word_bits(0x8001, 16, 16), [1] + [0] * 14 + [1])
        self.assertEqual(P.word_bits(0x800001, 24, 32), [1] + [0] * 22 + [1] + [0] * 8)
        for word, slot in SHAPES.values():
            for value in (0, 1, 1 << (word - 1), (1 << word) - 1, 0x5a5a & ((1 << word) - 1)):
                self.assertEqual(P.bits_word(P.word_bits(value, word, slot), word), value)
        self.assertEqual(P.bits_word([1, 0, 1], 16), 0xa000)                 # missing bits read as zero
        self.assertEqual(P.bits_word([0] * 16 + [1, 1], 16), 0)              # bits past the word are dropped

    def test_ws_changes_one_bit_period_before_the_most_significant_bit(self):
        for word, slot in SHAPES.values():
            plan = P.Plan(word, slot)
            plan.reset()
            plan.send(1 << (word - 1), 1 << (word - 1))
            plan.frames(2)
            rows = [r for r in plan.rows if r[RST]]
            ws_low = next(i for i, r in enumerate(rows) if r[WS] == 0)
            first_bit = next(i for i, r in enumerate(rows) if r[SD] == 1)
            self.assertEqual(first_bit - ws_low, 2)                          # one sck period is two clocks
            ws_high = next(i for i, r in enumerate(rows) if i > ws_low and r[WS] == 1)
            second_bit = next(i for i, r in enumerate(rows) if i > first_bit + 2 and r[SD] == 1)
            self.assertEqual(second_bit - ws_high, 2)
            self.assertEqual(ws_high - ws_low, 2 * slot)

    def test_pins_only_change_with_the_falling_edge_of_sck(self):
        for word, slot in SHAPES.values():
            rows = [r for r in P.boundary_vectors(word, slot)]
            for before, now in zip(rows, rows[1:]):
                if before[RST] and now[RST]:
                    self.assertNotEqual(before[SCK], now[SCK])               # the clock never stops
                    if (before[WS], before[SD]) != (now[WS], now[SD]):
                        self.assertEqual((before[SCK], now[SCK]), (1, 0))

    def test_the_transmitted_stream_decodes_to_the_pairs_in_order(self):
        rng = random.Random(3)
        for word, slot in SHAPES.values():
            pairs = [(rng.randrange(1 << word), rng.randrange(1 << word)) for _ in range(6)]
            plan = P.Plan(word, slot)
            plan.reset()
            for pair in pairs:
                plan.send(*pair)
            plan.frames(3)
            words = decode(tx_samples(plan.rows), word)
            lefts = [v for c, v in words if c == 0]
            rights = [v for c, v in words if c == 1]
            sent = [p for p in zip(lefts, rights[1:]) if p != (0, 0)]        # the idle slot before the first frame is a right slot
            self.assertEqual(sent, pairs)
            self.assertEqual([p for p in deliveries(plan.rows) if p != (0, 0)], pairs)   # loopback through the receiver model

    def test_an_empty_frame_is_zero_and_reported_once(self):
        word, slot = SHAPES['w16-s16']
        plan = P.Plan(word, slot)
        plan.reset()
        plan.frames(3)
        rows = [r for r in plan.rows if r[RST]]
        self.assertEqual(sum(r[UNDER] for r in rows), 3)
        self.assertTrue(all(r[SD] == 0 and r[READY] == 1 for r in rows))
        under = [i for i, r in enumerate(rows) if r[UNDER]]
        self.assertEqual([b - a for a, b in zip(under, under[1:])], [4 * slot, 4 * slot])

    def test_a_waiting_pair_blocks_the_next_one_until_its_frame_starts(self):
        word, slot = SHAPES['w16-s16']
        plan = P.Plan(word, slot)
        plan.reset()
        plan.send(1, 2)
        plan.send(3, 4)
        plan.send(5, 6)
        rows = [r for r in plan.rows if r[RST]]
        self.assertEqual(sum(r[VALID] and r[READY] for r in rows), 3)
        self.assertGreater(sum(r[VALID] and not r[READY] for r in rows), 4 * slot)

    def receive(self, slots, word, slot, idle_ws, shape=None):
        plan = P.Plan(word, slot)
        plan.reset(external=1)
        plan.stream(slots, idle_ws=idle_ws, shape=shape)
        return plan

    def test_receiver_keeps_the_word_whatever_the_slot_length(self):
        for word, slot in SHAPES.values():
            ones, top = (1 << word) - 1, 1 << (word - 1)
            for length, errors, want in ((None, 0, ones), (slot - 1, 1, ones if slot > word else ones - 1),
                                         (slot + 1, 1, ones), (word - 3, 1, ones - 7), (1, 1, top),
                                         (slot + P.counter_period(slot), 1, ones)):
                plan = self.receive([P.ext_slot(0, ones, word, slot, length), P.ext_slot(1, 1, word, slot)], word, slot, 1)
                last = plan.rows[-1]
                self.assertEqual((last[FRAMES], last[RX_L], last[RX_R], last[ERRORS]), (1, want, 1, errors), (word, slot, length))

    def test_receiver_needs_a_left_word_before_a_right_word(self):
        word, slot = SHAPES['w16-s16']
        plan = self.receive([P.ext_slot(1, 7, word, slot), P.ext_slot(0, 8, word, slot), P.ext_slot(1, 9, word, slot)], word, slot, 0)
        self.assertEqual(deliveries(plan.rows), [(8, 9)])
        alone = self.receive([P.ext_slot(1, 7, word, slot), P.ext_slot(0, 8, word, slot)], word, slot, 0)
        self.assertEqual(deliveries(alone.rows), [])                          # a right word and a left word, in that order, are no pair
        late = self.receive([P.ext_slot(1, 7, word, slot), P.ext_slot(0, 8, word, slot), P.ext_slot(1, 9, word, slot)], word, slot, 1)
        self.assertEqual(deliveries(late.rows), [(8, 9)])                     # no change of ws announced the first slot; it is skipped

    def test_the_shape_of_the_clock_does_not_change_what_is_received(self):
        rng = random.Random(11)
        for word, slot in SHAPES.values():
            slots = [P.ext_slot(i % 2, rng.randrange(1 << word), word, slot, None if i % 3 else slot + i - 4) for i in range(8)]
            plain = self.receive(slots, word, slot, 1)
            uneven = self.receive(slots, word, slot, 1, shape=lambda n: (1 + n % 3, 1 + (n * 5) % 4))
            self.assertEqual(deliveries(plain.rows), deliveries(uneven.rows))
            self.assertEqual(plain.rows[-1][ERRORS], uneven.rows[-1][ERRORS])
            self.assertGreater(len(uneven.rows), len(plain.rows))


class PlanTests(unittest.TestCase):
    def cases(self, name, profile='smoke', seed=17, iterations=5):
        args = SimpleNamespace(profile=profile, seed=seed, iterations=iterations, demo_bug=0)
        return P.make_cases(args, P.CONFIGS[name])

    def test_plan_names_labels_and_seed(self):
        for name in P.CONFIGS:
            cases = self.cases(name)
            self.assertEqual([c['id'] for c in cases], ['boundaries', 'random-seed17', *[f'detect-mutation{m}' for m in range(1, 8)]])
            self.assertEqual([c['expected_failure'] for c in cases[2:]], [P.LABELS[m] for m in range(1, 8)])
            self.assertEqual(len(self.cases(name, 'nightly')), len(cases) + 2)
            self.assertEqual(cases, self.cases(name))
            self.assertNotEqual(cases[1]['vectors'], self.cases(name, seed=18)[1]['vectors'])

    def test_fixed_scenario_has_every_rule_on_its_own_rows(self):
        for word, slot in SHAPES.values():
            rows = P.boundary_vectors(word, slot)
            live = [r for r in rows if r[RST]]
            self.assertTrue(any(r[VALID] and r[READY] for r in live))
            self.assertTrue(any(r[VALID] and not r[READY] for r in live))     # offered while one is waiting
            self.assertTrue(any(not r[VALID] and r[READY] for r in live))     # ready, nothing offered
            self.assertTrue(any(r[UNDER] for r in live))
            self.assertTrue(any(r[SEL] for r in live) and any(not r[SEL] for r in live))
            self.assertEqual(P.counts(rows)['errors'], 6)                     # short by one, long by one, short word, one bit, long, wrapped
            lengths = {len(P.ext_slot(0, 0, word, slot, n)[1]) for n in (slot - 1, slot + 1)}
            self.assertEqual(lengths, {slot - 1, slot + 1})                   # exactly one either side of a good slot

    def test_the_selector_only_moves_in_reset_and_data_is_still_when_the_clock_rises(self):
        for word, slot in SHAPES.values():
            for rows in (P.boundary_vectors(word, slot), P.random_vectors(5, 40, word, slot), P.random_vectors(6, 40, word, slot)):
                for before, now in zip(rows, rows[1:]):
                    if before[SEL] != now[SEL]:
                        self.assertEqual((before[RST], now[RST]), (0, 0))
                    if now[SEL] and now[E_SCK] and not before[E_SCK]:
                        self.assertEqual((before[E_WS], before[E_SD]), (now[E_WS], now[E_SD]))

    def test_random_plans_use_both_sources_and_bad_slot_lengths(self):
        for word, slot in SHAPES.values():
            seen = dict(ext=0, loop=0, errors=0)
            for seed in range(17, 23):
                rows = P.random_vectors(seed, 24, word, slot)
                seen['ext'] += any(r[SEL] and r[RST] for r in rows)
                seen['loop'] += any(not r[SEL] and r[RST] and r[VALID] for r in rows)
                seen['errors'] += P.counts(rows)['errors']
            self.assertTrue(all(seen.values()), seen)


class RtlTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(shutil.which('iverilog') and shutil.which('vvp'), 'Icarus Verilog is required')

    def test_all_configurations_mutants_and_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / 'out'
            result = run_example('local-i2s-audio', out, '--iterations', '4')
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            assert_evidence(self, out, P.CONFIGS, GOALS, 9 * len(P.CONFIGS), mutants=7)
            for name in P.CONFIGS:
                hits = read_json(out / 'coverage.json')[name]['hits']
                self.assertTrue(all(f'{name}-boundaries' in cases for cases in hits.values()), hits)

    def test_seed_reproduces_the_vectors(self):
        with tempfile.TemporaryDirectory() as tmp:
            texts = []
            for run in ('a', 'b', 'c'):
                out = Path(tmp) / run
                seed = '23' if run != 'c' else '24'
                result = run_example('local-i2s-audio', out, '--configuration', 'w16-s16', '--iterations', '6', '--seed', seed)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                texts.append((out / f'w16-s16-random-seed{seed}/vectors.txt').read_text())
            self.assertEqual(texts[0], texts[1])
            self.assertNotEqual(texts[0], texts[2])

    def test_demo_faults_make_the_normal_regression_fail(self):
        with tempfile.TemporaryDirectory() as tmp:
            for fault in range(1, P.MUTANTS + 1):
                with self.subTest(fault=fault):
                    out = Path(tmp) / str(fault)
                    result = run_example('local-i2s-audio', out, '--configuration', 'w24-s32', '--iterations', '2', '--demo-bug', str(fault))
                    self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                    record = read_json(out / 'w24-s32-boundaries/result.json')
                    self.assertEqual((record['status'], record['message']), ('fail', 'checker failure: ' + P.LABELS[fault]))

    def test_the_checker_reports_each_wrong_column_and_an_unknown_output(self):
        word, slot = SHAPES['w16-s16']
        rows = P.boundary_vectors(word, slot)[:6 * 4 * slot]
        good = simulate_vectors(P, rows, P.CONFIGS['w16-s16'])
        self.assertIn(f'RESULT PASS checks={len(rows)}', good.stdout, good.stdout + good.stderr)
        first = next(i for i, r in enumerate(rows) if r[FRAMES])
        for column, label in ((READY, 'I2S_TX_FLOW'), (UNDER, 'I2S_TX_FLOW'), (SCK, 'I2S_TX_SCK'), (WS, 'I2S_TX_WS'), (SD, 'I2S_TX_SD'),
                              (FRAMES, 'I2S_RX_VALID'), (RX_L, 'I2S_RX_DATA'), (RX_R, 'I2S_RX_DATA'), (ERRORS, 'I2S_RX_ERROR')):
            changed = [list(r) for r in rows]
            changed[first][column] ^= 1
            result = simulate_vectors(P, changed, P.CONFIGS['w16-s16'])
            self.assertNotEqual(result.returncode, 0, label)
            self.assertIn('CHECK_FAIL ' + label, result.stdout, label)
            self.assertNotIn('RESULT PASS', result.stdout)
        unknown = simulate_vectors(P, rows, P.CONFIGS['w16-s16'], {'i2s_rx.sv': [('left <= left_hold;', "left <= {WORD{1'bx}};")]})
        self.assertIn('CHECK_FAIL I2S_RX_DATA', unknown.stdout)

    def test_a_wrapping_length_counter_is_caught_by_the_fixed_scenario(self):
        """Found by putting small errors into a copy of the RTL: kept as a test of the scenario."""
        for name, (word, slot) in SHAPES.items():
            result = simulate_vectors(P, P.boundary_vectors(word, slot), P.CONFIGS[name],
                                      {'i2s_rx.sv': [("if (count != TOP) count <= count + 1'b1;", "count <= count + 1'b1;")]})
            self.assertIn('CHECK_FAIL I2S_RX_ERROR', result.stdout, name)


if __name__ == '__main__':
    unittest.main()

#!/usr/bin/env python3
"""Convolutional code with a Viterbi decoder: bit-exact checks, and an error rate judged against an interval."""
import importlib.util
import json
from pathlib import Path
import random
import sys

HERE = Path(__file__).resolve().parent
NAME = 'local-fec-ber'
TOP = 'fec_ber_tb'
CONFIGS = {'depth16': dict(DEPTH=16), 'depth24': dict(DEPTH=24)}
ITERATIONS = {'smoke': 40, 'nightly': 120}      # frames of the noisy bit-exact case, per seed
SOURCES = [HERE / 'rtl/conv_encoder.sv', HERE / 'rtl/viterbi_decoder.sv', HERE / 'tb/fec_ber_tb.sv']
EXTRA_INPUTS = [HERE / 'model.py', HERE / 'expected.json']
MUTANTS = 6
LABELS = {1: 'FEC_ENCODE', 2: 'FEC_DECODE', 3: 'FEC_DECODE', 4: 'FEC_VALID', 5: 'FEC_DECODE', 6: 'FEC_FER'}
SHORT_DECISION = 6                               # the decision depth of mutant 6
FRAME_BITS = 64
POINTS = {'smoke': (50,), 'nightly': (50, 30)}   # channel error probability in units of 1/1000

spec = importlib.util.spec_from_file_location('fec_ber_model', HERE / 'model.py')
MODEL = importlib.util.module_from_spec(spec)
spec.loader.exec_module(MODEL)
EXPECTED = json.loads((HERE / 'expected.json').read_text())

(ROUNDTRIP, GAPS, CONTINUOUS, TRANSITIONS, SINGLE_C0, SINGLE_C1, DOUBLE_SAME, DOUBLE_ADJACENT, DOUBLE_APART,
 BEYOND, RESET_MID, RESTART, SILENT, FIRST_OUTPUT, NOISY, STAT_BER, STAT_FER, TIE, LONG_STREAM, BEST_TIE) = range(1, 21)


def add_arguments(parser):
    # A statistical case simulates about 50000 cycles; the shared default of 10 s is too tight on a busy machine.
    parser.set_defaults(timeout=30.0)


def bounds(depth, permille):
    """Allowed bit errors and frame errors of one statistical case, from the recorded reference."""
    reference = EXPECTED['reference'][f'depth{depth}/p{permille}']
    frames, alpha = EXPECTED['frames'], EXPECTED['alpha']
    histogram = reference['histogram']
    failed = sum(histogram[1:]) / sum(histogram)
    return (MODEL.sum_interval(frames, *MODEL.moments(histogram), alpha),
            MODEL.binomial_interval(frames, failed, alpha))


# One frame per depth on which two states are equally good when a bit leaves, and the choice
# between them changes that bit. Found by search with model.Viterbi(highest_best=True).
BEST_STATE_TIE = {
    16: ([0, 1, 0, 1, 1, 1, 1, 1, 1, 0, 0, 0, 0, 1, 0, 1, 0, 0, 0, 1, 0, 0, 1, 1, 1, 0, 0, 0, 0, 1, 1, 0, 1, 0, 1, 1, 0, 0, 1, 0],
         ((6, 1), (9, 3), (12, 2), (18, 2))),
    24: ([1, 1, 0, 0, 1, 1, 1, 0, 0, 0, 1, 0, 1, 1, 1, 1, 1, 1, 0, 1, 0, 1, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 0, 1, 1, 1, 1, 1, 0, 1],
         ((11, 2), (14, 3), (19, 2), (23, 2), (28, 2), (30, 2))),
}


class Plan:
    """Builds the rows, with the encoder state and a decoder model that predicts each output."""

    def __init__(self, depth, pack=False, **decoder_options):
        self.depth, self.pack = depth, pack
        self.decoder = MODEL.Viterbi(depth, **decoder_options)
        self.rows = []
        self.state = 0
        self.pending = []          # accepted bits whose output has not appeared: [bit, data, last, goal]
        self.pairs = set()         # (encoder state, bit) pairs seen since the plan began
        self.outputs = 0
        self.cycle(op=1)
        self.cycle(op=1)

    def cycle(self, op=0, valid=0, bit=0, noise=0, mode=0, goal=0, data=0, last=0, last_goal=0, judge=(0, 0, 0, 0)):
        clean, exp_valid, exp_bit, is_data, ref, is_last = 0, 0, 0, 0, 0, 0
        if op == 1:
            self.decoder.reset()
            self.state, self.pending, self.outputs = 0, [], 0
        elif valid:
            clean = MODEL.symbol(self.state, bit)
            if len(self.pairs) < 8:
                self.pairs.add((self.state, bit))
                if len(self.pairs) == 8 and not goal:
                    goal = TRANSITIONS
            self.state = (bit << 1) | (self.state >> 1)
            self.pending.append([bit, data, last, last_goal])
            decoded = self.decoder.step(clean ^ noise)
            if decoded is None:
                if not goal and len(self.pending) == self.depth - 1:
                    goal = SILENT                 # the last symbol before the first output
            else:
                ref, is_data, is_last, frame_goal = self.pending.pop(0)
                exp_valid, exp_bit = 1, decoded
                self.outputs += 1
                if self.outputs == 1 and not goal:
                    goal = FIRST_OUTPUT
                if is_last and frame_goal:
                    goal = frame_goal
        self.rows.append([op, valid, bit, noise, clean, exp_valid, exp_bit, is_data, ref, is_last, mode, goal, *judge])

    def frame(self, data, noise=(), gaps=(), mode=0, goal=0, flush=True, reset=True):
        """One terminated frame. noise[i] hits symbol i of data and tail; gaps are idle cycles before a symbol.

        A packing plan writes the frame as one row (see pack_frame), which the bench expands again."""
        start = len(self.rows)
        packable = self.pack and flush and reset and not gaps and self.decoder.steps == 0
        if self.pack and not packable:
            raise ValueError('a packing plan holds only whole frames after a reset')
        self._frame(data, noise, gaps, mode, goal, flush, reset)
        if packable:
            cycles = self.rows[start:]
            del self.rows[start:]
            self.rows.append(pack_frame(cycles, len(data), self.depth))

    def _frame(self, data, noise, gaps, mode, goal, flush, reset):
        bits = list(data) + [0, 0]
        for index, bit in enumerate(bits):
            if index in gaps:
                self.cycle(mode=mode)
            self.cycle(valid=1, bit=bit, noise=noise[index] if index < len(noise) else 0, mode=mode,
                       data=int(index < len(data)), last=int(index == len(data) - 1), last_goal=goal)
        if flush:
            for _ in range(MODEL.flush_length(self.depth)):
                self.cycle(valid=1, mode=mode)
        if reset:
            self.cycle(op=1)


def pack_frame(cycles, length, depth):
    """One row for a frame of length data bits that starts right after a reset.

    Columns: 3, length, data, noise c0, noise c1, symbol c0, symbol c1, expected bits, 0, 0, mode, goal.
    Bit i of a mask is symbol i; bit i of the expected bits is output i. Goals that the plan gives
    to single cycles (first output and the like) are dropped; the fixed scenario, which is never
    packed, earns them."""
    symbols, outputs = cycles[:-1], [c for c in cycles if c[5]]
    goals = {c[11] for c in cycles if c[9]}
    row = [3, length,
           sum(c[2] << i for i, c in enumerate(symbols[:length])),
           sum((c[3] >> 1) << i for i, c in enumerate(symbols)), sum((c[3] & 1) << i for i, c in enumerate(symbols)),
           sum((c[4] >> 1) << i for i, c in enumerate(symbols)), sum((c[4] & 1) << i for i, c in enumerate(symbols)),
           sum(c[6] << i for i, c in enumerate(outputs)), 0, 0, symbols[0][10], goals.pop(), 0, 0, 0, 0]
    cleaned = [c[:11] + [c[11] if c[9] else 0] + c[12:] for c in cycles]
    if expand_frame(row, depth) != cleaned:
        raise ValueError('frame does not have the packable form')
    return row


def expand_frame(row, depth):
    """The cycles the bench makes of a packed row: the symbols of the frame, then one reset cycle."""
    _, length, data, n0, n1, s0, s1, expected, _, _, mode, goal = row[:12]
    cycles = []
    for k in range(length + 2 + depth - 1):
        j = k - (depth - 1)
        is_data = int(0 <= j < length)
        last = int(j == length - 1)
        cycles.append([0, 1, (data >> k) & 1 if k < length else 0, (((n0 >> k) & 1) << 1) | ((n1 >> k) & 1),
                       (((s0 >> k) & 1) << 1) | ((s1 >> k) & 1), int(j >= 0), (expected >> j) & 1 if j >= 0 else 0,
                       is_data, (data >> j) & 1 if is_data else 0, last, mode, goal if last else 0, 0, 0, 0, 0])
    cycles.append([1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0])
    return cycles


def expand(rows, depth):
    """Every row as clock cycles, the way the bench runs them."""
    cycles = []
    for row in rows:
        cycles += expand_frame(row, depth) if row[0] == 3 else [row]
    return cycles


def pattern(length, *errors):
    noise = [0] * length
    for index, value in errors:
        noise[index] |= value
    return noise


def boundary_rows(depth, **decoder_options):
    """Fixed scenario: clean frames, idle cycles, frames without a gap between them, reset, latency
    and one pattern beyond the correcting capability."""
    p = Plan(depth, **decoder_options)
    rng = random.Random(f'fec-ber/boundaries/{depth}')
    data = [1, 0, 1, 1, 0, 0, 1, 0, 0, 0, 1, 1, 1, 0, 1, 0] + [rng.getrandbits(1) for _ in range(depth + 8)]
    size = len(data) + 2
    p.frame(data, goal=ROUNDTRIP)
    p.frame(data, gaps={0, 1, 5, 6, 7, len(data), len(data) + 1}, goal=GAPS)
    p.frame(data[:20], flush=False, reset=False, goal=CONTINUOUS)        # the next frame follows at once
    p.frame(data[5:30], goal=CONTINUOUS)
    p.frame(data, pattern(size, (3, 2)), goal=SINGLE_C0)
    p.frame(data, pattern(size, (3, 1)), goal=SINGLE_C1)
    p.frame(data, pattern(size, (9, 3)), goal=DOUBLE_SAME)
    p.frame(data, pattern(size, (9, 2), (10, 1)), goal=DOUBLE_ADJACENT)
    p.frame(data, pattern(size, (9, 1), (14, 2)), goal=DOUBLE_APART)
    p.frame(data, pattern(size, (9, 3), (10, 2)), goal=BEYOND)           # three errors in two symbols
    # Three errors that leave two paths at the same distance: the tie rule decides, and here it decides right.
    p.frame(data, pattern(size, (4, 3), (5, 1)), goal=TIE)
    tie_data, tie_errors = BEST_STATE_TIE[depth]
    p.frame(tie_data, pattern(len(tie_data) + 2, *tie_errors), goal=BEST_TIE)
    # Forty frames without a reset, one error in each: the path metrics must stay relative, not grow.
    for index in range(40):
        short = data[index % 7:index % 7 + 12]
        p.frame(short, pattern(14, (3 + index % 5, 1 + index % 2)), flush=index == 39, reset=index == 39,
                goal=LONG_STREAM if index == 39 else 0)
    for bit in data[:depth + 3]:                                         # reset while outputs are flowing
        p.cycle(valid=1, bit=bit, data=1)
    p.cycle(op=1, goal=RESET_MID)
    p.cycle()
    p.frame(data, goal=RESTART)
    p.cycle()
    p.cycle()
    return p.rows


def correctable_rows(depth, **decoder_options):
    """Every single error and every pair of errors up to 7 symbols apart, in a short frame."""
    p = Plan(depth, pack=True, **decoder_options)
    rng = random.Random(f'fec-ber/correctable/{depth}')
    data = [rng.getrandbits(1) for _ in range(12)]
    size = len(data) + 2
    p.frame(data, goal=ROUNDTRIP)
    for index in range(size):
        p.frame(data, pattern(size, (index, 2)), goal=SINGLE_C0)
        p.frame(data, pattern(size, (index, 1)), goal=SINGLE_C1)
        p.frame(data, pattern(size, (index, 3)), goal=DOUBLE_SAME)
        for gap in range(1, 8):
            if index + gap < size:
                for first in (1, 2):
                    for second in (1, 2):
                        p.frame(data, pattern(size, (index, first), (index + gap, second)),
                                goal=DOUBLE_ADJACENT if gap == 1 else DOUBLE_APART)
    return p.rows


def noisy_frames(tag, seed, depth, permille, frames):
    """Independent frames of random data with the error patterns of the channel."""
    rng = random.Random(f'fec-ber/{tag}/{seed}/{depth}/{permille}')
    for _ in range(frames):
        data = [rng.getrandbits(1) for _ in range(FRAME_BITS)]
        yield data, MODEL.channel(rng, FRAME_BITS + 2, permille / 1000)


def noisy_rows(depth, seed, frames, permille=50, **decoder_options):
    """Noisy frames compared bit for bit with the model."""
    p = Plan(depth, pack=True, **decoder_options)
    for data, noise in noisy_frames('noisy', seed, depth, permille, frames):
        clean = MODEL.run_frame(data, noise, depth, **decoder_options) == data and any(noise)
        p.frame(data, noise, goal=NOISY if clean else 0)
    return p.rows


def statistic_rows(depth, seed, permille, **decoder_options):
    """Frames whose errors are only counted, then one row that judges both counts."""
    p = Plan(depth, pack=True, **decoder_options)
    for data, noise in noisy_frames('statistic', seed, depth, permille, EXPECTED['frames']):
        p.frame(data, noise, mode=1)
    (bit_low, bit_high), (frame_low, frame_high) = bounds(depth, permille)
    p.cycle(op=2, mode=1, judge=(bit_low, bit_high, frame_low, frame_high))
    return p.rows


def counts(rows, depth):
    rows = expand(rows, depth)
    data = [r for r in rows if r[5] and r[7]]
    frames, failed, wrong = 0, 0, 0
    for row in rows:
        if row[0] == 1:
            wrong = 0
        if row[5] and row[7]:
            wrong += row[6] != row[8]
            if row[9]:
                frames += 1
                failed += wrong > 0
                wrong = 0
    return dict(bits=len(data), bit_errors=sum(r[6] != r[8] for r in data), frames=frames, frame_errors=failed)


def make_cases(args, parameters):
    depth, bug = parameters['DEPTH'], args.demo_bug
    base, correctable = boundary_rows(depth), correctable_rows(depth)
    noisy = noisy_rows(depth, args.seed, args.iterations)
    points = POINTS[args.profile]
    statistic = {permille: statistic_rows(depth, args.seed, permille) for permille in points}

    def case(name, rows, mutation=bug, category='functional', expected=None):
        return dict(id=name, vectors=rows, mutation=mutation, category=category, expected_failure=expected)

    cases = [case('boundaries', base), case('correctable', correctable)]
    for seed in range(args.seed, args.seed + (3 if args.profile == 'nightly' else 1)):
        cases.append(case(f'noisy-seed{seed}', noisy if seed == args.seed else noisy_rows(depth, seed, args.iterations)))
    cases += [case(f'statistic-p{permille:03d}', rows) for permille, rows in statistic.items()]
    first = statistic[points[0]]
    plans = {1: base, 2: base, 3: base, 4: base, 5: base, 6: first}
    for mutation in range(1, MUTANTS + 1):
        cases.append(case(f'detect-mutation{mutation}', plans[mutation], mutation, 'mutation', LABELS[mutation]))
    # What each kind of check cannot see. The expected outputs come from a model with the same defect
    # only where the name says so; elsewhere the mutant passes the unchanged plan.
    cases += [
        case('survive-correctable-mutation5', correctable, 5, 'diagnostic'),
        case('survive-statistic-mutation5', statistic_rows(depth, args.seed, points[0], upper_wins=True), 5, 'diagnostic'),
        case('survive-correctable-mutation6', correctable, 6, 'diagnostic'),
        case('shared-error-mutation6', noisy_rows(depth, args.seed, args.iterations, decide=SHORT_DECISION), 6, 'diagnostic'),
    ]
    for item in cases:
        item['counts'] = counts(item['vectors'], depth)
    return cases


if __name__ == '__main__':
    spec = importlib.util.spec_from_file_location('local_runner', HERE.parent / 'local-common/runner.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    sys.exit(module.main(sys.modules[__name__]))

#!/usr/bin/env python3
"""CIC decimator: register width, wrapping integrators, decimation phase and an exact integer model."""
import importlib.util
from pathlib import Path
import random
import sys

HERE = Path(__file__).resolve().parent
NAME = 'local-cic-decimator'
TOP = 'cic_tb'
IN_W = 8
CONFIGS = {'n3-r4-m1': dict(STAGES=3, RATE=4, DELAY=1), 'n2-r5-m2': dict(STAGES=2, RATE=5, DELAY=2)}
ITERATIONS = {'smoke': 40, 'nightly': 300}
SOURCES = [HERE / 'rtl/cic_decimator.sv', HERE / 'tb/cic_tb.sv']
MUTANTS = 7
LABELS = {1: 'CIC_DATA', 2: 'CIC_DATA', 3: 'CIC_DATA', 4: 'CIC_VALID', 5: 'CIC_VALID', 6: 'CIC_DATA', 7: 'CIC_DATA'}
LOW, HIGH = -(1 << (IN_W - 1)), (1 << (IN_W - 1)) - 1
IDLE_DATA = 0x5a                       # driven while in_valid is 0; must never reach the filter


def gain(stages, rate, delay):
    return (rate * delay) ** stages


def output_width(stages, rate, delay):
    """Smallest two's-complement width that holds LOW * gain, the largest magnitude of the sum."""
    return IN_W + (gain(stages, rate, delay) - 1).bit_length()


def fitting_amplitudes(stages, rate, delay):
    """Largest constant inputs whose output still fits in one bit less than the output width."""
    half = 1 << (output_width(stages, rate, delay) - 2)
    g = gain(stages, rate, delay)
    return -(half // g), (half - 1) // g


class Model:
    """Exact reference written as moving sums: no integrators, no combs and no word length.

    The filter is STAGES moving sums of RATE*DELAY input samples in a row; every RATE-th
    accepted sample after a restart gives one output. Python integers do not overflow, so the
    model also proves that each expected value fits in the output width.
    """

    def __init__(self, stages, rate, delay):
        self.stages, self.rate, self.span = stages, rate, rate * delay
        self.width = output_width(stages, rate, delay)
        self.restart()
        self.output = None

    def restart(self):
        self.levels = [[] for _ in range(self.stages + 1)]      # level 0 is the accepted input

    def accept(self, sample):
        self.levels[0].append(sample)
        for level in range(1, self.stages + 1):
            self.levels[level].append(sum(self.levels[level - 1][-self.span:]))
        if len(self.levels[0]) % self.rate:
            return None
        value = self.levels[-1][-1]
        if not -(1 << (self.width - 1)) <= value < 1 << (self.width - 1):
            raise ValueError('output width too small for the exact sum')
        return value

    def step(self, rst_n=1, in_valid=0, sync=0, data=0):
        """One clock: returns the row [inputs..., out_valid, out_data] seen before the edge."""
        if not rst_n:
            self.restart()
            self.output = None
        shown = self.output
        row = [rst_n, in_valid, sync, data & ((1 << IN_W) - 1), int(shown is not None),
               (shown or 0) & ((1 << self.width) - 1)]
        self.output = None
        if rst_n:
            if sync:
                self.restart()
            elif in_valid:
                self.output = self.accept(data)
        return row


class Plan:
    def __init__(self, stages, rate, delay):
        self.model = Model(stages, rate, delay)
        self.rows = []

    def cycle(self, **inputs):
        self.rows.append(self.model.step(**inputs))

    def reset(self):
        self.cycle(rst_n=0)

    def idle(self, cycles=1):
        for _ in range(cycles):
            self.cycle(data=IDLE_DATA)

    def sync(self, with_sample=False):
        self.cycle(sync=1, in_valid=int(with_sample), data=HIGH if with_sample else IDLE_DATA)

    def samples(self, values, gaps=()):
        """Back-to-back samples; gaps maps a sample index to idle cycles inserted before it."""
        gaps = dict(gaps)
        for index, value in enumerate(values):
            self.idle(gaps.get(index, 0))
            self.cycle(in_valid=1, data=value)

    def flush(self):
        self.idle(2)


def lengths(stages, rate, delay):
    """Samples for the sums to fill, and for a full-scale constant to wrap the first integrator."""
    fill = stages * rate * delay + 2 * rate
    wrap = ((1 << (output_width(stages, rate, delay) - 1)) // HIGH + 2 * rate) // rate * rate + rate
    return fill, wrap


def crossing(amplitude, stages, rate, delay):
    """A constant whose running sum first leaves the range of one bit less on a sample that
    completes a decimation period, so that a narrower first integrator shows in that output."""
    half = 1 << (output_width(stages, rate, delay) - 2)
    count = ((half - 1) // amplitude if amplitude > 0 else half // -amplitude) + 1
    return [0] * (-count % rate) + [amplitude] * (count + stages * rate * delay)


def boundary_vectors(stages, rate, delay):
    """Every goal and every rule on purpose: full scale, the half-range edges, phase, sync, reset."""
    p = Plan(stages, rate, delay)
    fill, wrap = lengths(stages, rate, delay)
    span = rate * delay
    low_fit, high_fit = fitting_amplitudes(stages, rate, delay)
    p.reset()
    p.idle(3)                                       # ready for input, none offered
    p.samples([LOW] * wrap)                         # full-scale negative constant: the smallest output
    p.sync()
    p.samples([HIGH] * wrap)                        # full-scale positive constant: the largest output
    p.sync()
    p.samples([HIGH, LOW] * (fill // 2 + rate))     # full scale, alternating every sample
    p.sync()
    p.samples(([HIGH] * span + [LOW] * span) * (stages + 2))    # full scale, alternating every span
    p.sync()
    p.samples([high_fit + 1] * fill)                # one step past what one bit less would hold
    p.sync()
    p.samples([low_fit - 1] * fill)
    p.sync()
    p.samples([high_fit] * fill)                    # exactly what one bit less would hold
    p.sync()
    p.samples([low_fit] * fill)
    p.sync()
    p.samples(crossing(HIGH, stages, rate, delay))  # the first integrator passes half range on an output sample
    p.sync()
    p.samples(crossing(LOW, stages, rate, delay))
    p.sync()
    p.samples([0] * (2 * rate))                     # zero in, zero out
    p.samples([3, -7, 11, -2, 5, 1, -9, 4] * (fill // 8 + 2), gaps={1: 2, rate: 1, rate + 2: 3, 3 * rate - 1: 1})
    p.samples([17] * (rate - 2))                    # leave the decimation period part way through
    p.sync(with_sample=True)                        # restart; the offered sample is discarded
    p.samples([21, -13, 8, 30, -1] * (fill // 5 + 2))
    p.samples([9] * (rate - 1))
    p.reset()                                       # reset part way through a period, with history
    p.idle(1)
    p.samples([-40, 55, -3, 12] * (fill // 4 + 2))
    p.flush()
    return p.rows


def small_signal_vectors(stages, rate, delay):
    """As hard as it gets without leaving the range of a register one bit narrower."""
    p = Plan(stages, rate, delay)
    fill, wrap = lengths(stages, rate, delay)
    span = rate * delay
    low_fit, high_fit = fitting_amplitudes(stages, rate, delay)
    p.reset()
    p.samples([high_fit] * (2 * wrap))              # long enough to wrap the first integrator
    p.sync()
    p.samples([low_fit] * (2 * wrap))
    p.sync()
    p.samples(([high_fit] * span + [low_fit] * span) * (stages + 2), gaps={2: 1, span + 1: 2})
    p.sync(with_sample=True)
    p.samples([high_fit, low_fit] * (fill // 2 + rate))
    p.sync()
    p.samples(crossing(high_fit, stages, rate, delay))
    p.sync()
    p.samples(crossing(low_fit, stages, rate, delay))
    p.flush()
    return p.rows


def random_vectors(seed, iterations, stages, rate, delay):
    rng = random.Random(seed)
    p = Plan(stages, rate, delay)
    p.reset()
    for _ in range(iterations):
        kind = rng.randrange(20)
        if kind == 0:
            p.reset()
        elif kind == 1:
            p.sync(with_sample=bool(rng.randrange(2)))
        elif kind < 5:
            p.idle(rng.randrange(1, 4))
        else:
            style = rng.randrange(4)
            count = rng.randrange(1, 3 * rate + 1)
            if style == 0:
                values = [rng.choice((LOW, HIGH))] * count
            elif style == 1:
                values = [rng.choice((LOW, HIGH)) for _ in range(count)]
            else:
                values = [rng.randrange(LOW, HIGH + 1) for _ in range(count)]
            p.samples(values, gaps={rng.randrange(count): rng.randrange(3)} if rng.randrange(3) == 0 else ())
    p.flush()
    return p.rows


def counts(rows):
    return dict(accepted=sum(bool(r[0] and r[1] and not r[2]) for r in rows), outputs=sum(r[4] for r in rows))


def make_cases(args, parameters):
    shape = (parameters['STAGES'], parameters['RATE'], parameters['DELAY'])
    baseline, small = boundary_vectors(*shape), small_signal_vectors(*shape)
    cases = [dict(id='boundaries', vectors=baseline, mutation=args.demo_bug, category='functional', expected_failure=None),
             dict(id='small-signal', vectors=small, mutation=args.demo_bug, category='functional', expected_failure=None)]
    for seed in range(args.seed, args.seed + (3 if args.profile == 'nightly' else 1)):
        cases.append(dict(id=f'random-seed{seed}', vectors=random_vectors(seed, args.iterations, *shape),
                          mutation=args.demo_bug, category='functional', expected_failure=None))
    for mutation in range(1, MUTANTS + 1):
        cases.append(dict(id=f'detect-mutation{mutation}', vectors=baseline, mutation=mutation,
                          category='mutation', expected_failure=LABELS[mutation]))
    # One bit less in every register is invisible until the output leaves the narrower range,
    # while one bit less in the first integrator alone already fails on a small signal.
    cases.append(dict(id='survive-mutation1-small-signal', vectors=small, mutation=1,
                      category='diagnostic', expected_failure=None))
    cases.append(dict(id='detect-mutation7-small-signal', vectors=small, mutation=7,
                      category='mutation', expected_failure='CIC_DATA'))
    for case in cases:
        case['counts'] = counts(case['vectors'])
    return cases


if __name__ == '__main__':
    spec = importlib.util.spec_from_file_location('local_runner', HERE.parent / 'local-common/runner.py')
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)
    sys.exit(runner.main(sys.modules[__name__]))

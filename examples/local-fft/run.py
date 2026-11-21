#!/usr/bin/env python3
"""Sequential fixed-point FFT: bit-exact against an integer model, and within a derived error bound of the transform."""
import importlib.util
import math
from pathlib import Path
import random
import sys

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('fft_model', HERE / 'model.py')
M = importlib.util.module_from_spec(spec)
spec.loader.exec_module(M)

NAME = 'local-fft'
TOP = 'fft_tb'
CONFIGS = {'n16-scaled': dict(LOGN=4, WIDTH=16, SCALE=1), 'n64-scaled': dict(LOGN=6, WIDTH=16, SCALE=1),
           'n16-unscaled': dict(LOGN=4, WIDTH=16, SCALE=0)}
ITERATIONS = {'smoke': 6, 'nightly': 24}       # random frames per case
SOURCES = [HERE / 'rtl/fft.sv', HERE / 'tb/fft_tb.sv']
EXTRA_INPUTS = [HERE / 'model.py']
MUTANTS = 10
# The check of the short fixed scenario that sees each mutant first.
LABELS = {1: 'FFT_TOLERANCE', 2: 'FFT_TOLERANCE', 3: 'FFT_DATA', 4: 'FFT_DATA', 5: 'FFT_DATA', 6: 'FFT_OVERFLOW',
          7: 'FFT_TOLERANCE', 8: 'FFT_LAST', 9: 'FFT_READY', 10: 'FFT_TOLERANCE'}
SKIP = 0xffffffff          # tolerance field of a frame that saturates
MASK = (1 << 32) - 1
PROBE_FRAMES = 6           # the frames that the two tightened cases use


class Plan:
    """Rows for the testbench: a cycle model of the control, and the integer transform for the data."""

    def __init__(self, parameters, tighten=None):
        self.logn, self.width, self.scale = parameters['LOGN'], parameters['WIDTH'], parameters['SCALE']
        self.n = 1 << self.logn
        self.tighten = tighten
        self.state, self.buffer, self.timer, self.position, self.result = 'load', [], 0, 0, None
        self.rows = []

    def idle(self):
        return self.state == 'load' and not self.buffer

    def cycle(self, rst=1, valid=0, re=0, im=0):
        row = [rst, valid, re & MASK, im & MASK, int(self.state == 'load'), 0, 0, 0, 0, 0, 0, 0, 0, 0, 0]
        if self.state == 'send':
            out, overflow, ref, tol, window = self.result
            k = self.position
            last = k == self.n - 1
            row[5:] = [1, int(last), int(overflow), out[k][0] & MASK, out[k][1] & MASK, ref[k][0] & MASK,
                       ref[k][1] & MASK, tol, window[0] if last else 0, window[1] if last else 0]
        if self.rows and self.rows[-1][:15] == row:
            self.rows[-1][15] += 1        # the same clock again: one row with a repeat count
        else:
            self.rows.append(row + [1])
        if not rst:
            self.state, self.buffer = 'load', []
        elif self.state == 'load':
            if valid:
                self.buffer.append((re, im))
                if len(self.buffer) == self.n:
                    self.result = self.transform(self.buffer)
                    self.state, self.timer = 'run', self.logn * self.n // 2
        elif self.state == 'run':
            self.timer -= 1
            if not self.timer:
                self.state, self.position = 'send', 0
        else:
            self.position += 1
            if self.position == self.n:
                self.state, self.buffer = 'load', []

    def transform(self, samples):
        out, overflow = M.fft(samples, self.logn, self.width, self.scale)
        ref = M.reference(samples, self.scale)
        if overflow:
            return out, overflow, ref, SKIP, (0, 0)
        tol = M.tolerance(samples, self.logn, self.scale) if self.tighten is None else self.tighten
        return out, overflow, ref, tol, M.energy_window(samples, self.logn, self.scale)

    def frame(self, samples, gaps=(), busy=False, wait=True):
        """Load one frame. gaps: sample numbers before which the source pauses for one clock.
        busy: keep offering a sample while the transform runs and the bins go out."""
        assert len(samples) == self.n and self.idle()
        for number, (re, im) in enumerate(samples):
            if number in gaps:
                self.cycle(valid=0, re=0x1357, im=-0x2468)     # offered without valid: ignored
            self.cycle(valid=1, re=re, im=im)
        while wait and self.state != 'load':
            self.cycle(valid=int(busy), re=0x7abc if busy else 0, im=-0x1234 if busy else 0)


def top(parameters):
    return (1 << (parameters['WIDTH'] - 1)) - 1


def tone(size, k, amplitude, phase=0.0):
    return [(round(amplitude * math.cos(2 * math.pi * k * n / size + phase)),
             round(amplitude * math.sin(2 * math.pi * k * n / size + phase))) for n in range(size)]


def square_tone(size, k, amplitude):
    """Each component at +-amplitude with the sign of a tone in bin k: the largest possible real part of that bin."""
    def sign(value):
        return amplitude if value >= 0 else -amplitude
    return [(sign(math.cos(2 * math.pi * k * n / size + 0.01)), sign(math.sin(2 * math.pi * k * n / size + 0.01)))
            for n in range(size)]


def overflow_edge(parameters, build):
    """Smallest amplitude at which build(amplitude) saturates. The one below it is the largest that fits."""
    logn, width, scale = parameters['LOGN'], parameters['WIDTH'], parameters['SCALE']
    low, high = 1, top(parameters)
    if not M.fft(build(high), logn, width, scale)[1]:
        raise ValueError('the pattern never saturates')
    while low < high:                        # an estimate; the scan below makes it exact
        middle = (low + high) // 2
        if M.fft(build(middle), logn, width, scale)[1]:
            high = middle
        else:
            low = middle + 1
    edge = max(1, low - 64)
    while not M.fft(build(edge), logn, width, scale)[1]:
        edge += 1
    return edge


def tone_amplitude(parameters):
    """A tone that cannot saturate: scaled transforms keep it, unscaled ones grow it N times."""
    return top(parameters) * 3 // 4 if parameters['SCALE'] else top(parameters) // (1 << parameters['LOGN']) * 3 // 4


def tie_frame(parameters):
    """An impulse whose product with a twiddle factor lies exactly between two integers:
    rounding half up and rounding half down give different transforms."""
    logn, width, scale = parameters['LOGN'], parameters['WIDTH'], parameters['SCALE']
    size = 1 << logn
    values = [sign << k for k in range(width - 1, 1, -1) for sign in (-1, 1) if -(1 << (width - 1)) <= sign << k < 1 << (width - 1)]
    for position in range(1, size):
        for value in values:
            frame = [(0, 0)] * position + [(value, 0)] + [(0, 0)] * (size - 1 - position)
            up, half_down = M.fft(frame, logn, width, scale), M.fft(frame, logn, width, scale, M.ROUND - 1)
            if up != half_down and not up[1]:
                return frame
    raise ValueError('no impulse reaches a rounding tie')


def core_frames(parameters):
    """The short fixed scenario: every mutant is seen here. Returns a Plan."""
    size, peak = 1 << parameters['LOGN'], top(parameters)
    small = tone_amplitude(parameters)
    p = Plan(parameters)
    p.cycle(rst=0)
    p.cycle()
    p.frame([(small, 0)] + [(0, 0)] * (size - 1))                       # impulse at sample 0: a flat spectrum
    p.frame([(0, 0), (0, small)] + [(0, 0)] * (size - 2))               # impulse at sample 1: bit reversal matters
    p.frame(tone(size, 1, small), busy=True)                            # a sample is offered all the time while busy
    p.frame(tone(size, size // 2 - 1, small, 0.3), gaps=(1, size // 2))
    p.frame(tie_frame(parameters))                                      # a product exactly between two integers
    edge = overflow_edge(parameters, lambda a: square_tone(size, 1, a))
    p.frame(square_tone(size, 1, edge - 1))                             # the largest amplitude that fits
    p.frame(square_tone(size, 1, edge))                                 # one more saturates
    p.frame([(-v, -w) for v, w in square_tone(size, 1, min(peak, edge + edge // 8))])
    p.frame([(3, -2)] * size)                                           # the flag of the frame before is gone
    # Reset in the middle of loading: the next frame starts from sample 0 again.
    for re, im in tone(size, 2, small)[:size // 2 + 1]:
        p.cycle(valid=1, re=re, im=im)
    p.cycle(rst=0, valid=1, re=1, im=1)
    p.frame(tone(size, 2, small))
    return p


def boundary_vectors(parameters):
    size, peak, low = 1 << parameters['LOGN'], top(parameters), -top(parameters) - 1
    small = tone_amplitude(parameters)
    p = core_frames(parameters)
    p.frame([(0, 0)] * size)
    p.frame([(0, 0)] * (size - 1) + [(-small, small)])                  # impulse at the last sample
    p.frame([(peak, peak)] * size)                                      # constant at full scale
    p.frame([(low, low)] * size)                                        # constant at the most negative value
    p.frame([(peak, 0) if n % 2 == 0 else (low, 0) for n in range(size)])   # the fastest alternation
    p.frame([(low, peak)] * (size // 2) + [(peak, low)] * (size // 2))
    for k in range(size):                                               # one tone per bin, back to back
        p.frame(tone(size, k, small, 0.1 * k))
    p.frame([(round(small * math.cos(2 * math.pi * 3 * n / size)), 0) for n in range(size)])   # a real cosine: two bins
    if not parameters['SCALE']:
        # Unscaled: a constant grows N times. The largest constant that fits, and one more.
        edge = overflow_edge(parameters, lambda a: [(a, 0)] * size)
        p.frame([(edge - 1, 0)] * size)
        p.frame([(edge, 0)] * size)
        p.frame([(0, -edge)] * size)
        p.frame([(1, 1)] * size)
        # The same edge in bin N/2, which is the lower output of its butterfly, in each component.
        p.frame([(edge - 1, 0) if n % 2 == 0 else (1 - edge, 0) for n in range(size)])
        p.frame([(edge, 0) if n % 2 == 0 else (-edge, 0) for n in range(size)])
        p.frame([(0, edge) if n % 2 == 0 else (0, -edge) for n in range(size)])
        p.frame([(0, -2) if n % 2 == 0 else (0, 2) for n in range(size)])
    # Reset while the transform runs, and while the bins go out; a frame follows each.
    p.frame(tone(size, 5 % size, small), wait=False)
    for _ in range(3):
        p.cycle()
    p.cycle(rst=0)
    p.frame(tone(size, 6 % size, small, 1.0))
    p.frame([(peak, peak)] * size if not parameters['SCALE'] else square_tone(size, 1, peak), wait=False)
    while p.state != 'send':
        p.cycle()
    for _ in range(size // 2):
        p.cycle()
    p.cycle(rst=0)                                                      # the overflow flag is dropped as well
    p.frame(tone(size, 7 % size, small, 2.0), busy=True)
    p.cycle()
    p.cycle()
    return p.rows


def probe_frames(parameters):
    """Frames without saturation for the two tightened cases."""
    size, small = 1 << parameters['LOGN'], tone_amplitude(parameters)
    rng = random.Random(20261121)
    frames = [tone(size, k, small, 0.37 * k) for k in (1, size // 4 + 1, size - 1)]
    span = small * 2 // 3
    while len(frames) < PROBE_FRAMES:
        frames.append([(rng.randint(-span, span), rng.randint(-span, span)) for _ in range(size)])
    return frames


def observed_limit(parameters):
    """Largest component error of the integer model over the probe frames (a measurement, not a bound)."""
    return max(M.errors(f, parameters['LOGN'], parameters['WIDTH'], parameters['SCALE']) for f in probe_frames(parameters))


def probe_vectors(parameters, tighten):
    p = Plan(parameters, tighten)
    p.cycle(rst=0)
    for frame in probe_frames(parameters):
        p.frame(frame)
    p.cycle()
    return p.rows


def random_vectors(seed, iterations, parameters):
    size, peak = 1 << parameters['LOGN'], top(parameters)
    rng = random.Random(seed)
    p = Plan(parameters)
    p.cycle(rst=0)
    for _ in range(iterations):
        kind = rng.random()
        span = peak if kind < 0.35 else tone_amplitude(parameters) if kind < 0.8 else 3
        samples = [(rng.randint(-span - (span == peak), span), rng.randint(-span - (span == peak), span))
                   if rng.random() < 0.9 else (0, 0) for _ in range(size)]
        gaps = tuple(rng.sample(range(size), rng.choice((0, 0, 1, 3))))
        if rng.random() < 0.2:                                          # reset at a random point of the frame
            p.frame(samples, gaps=gaps, wait=False)
            for _ in range(rng.randrange(0, p.logn * size // 2 + size)):
                p.cycle(valid=rng.randrange(2), re=rng.randint(-peak, peak), im=rng.randint(-peak, peak))
            p.cycle(rst=0)
        else:
            p.frame(samples, gaps=gaps, busy=rng.random() < 0.5)
        for _ in range(rng.choice((0, 0, 1, 4))):
            p.cycle()
    p.cycle()
    return p.rows


def counts(rows):
    sent = [r for r in rows if r[5]]
    last = [r for r in sent if r[6]]
    return dict(accepted=sum(r[15] for r in rows if r[0] and r[1] and r[4]), frames=sum(r[15] for r in last),
                outputs=sum(r[15] for r in sent), overflow_frames=sum(r[7] * r[15] for r in last),
                inexact=sum(r[15] for r in sent if r[12] != SKIP and r[8:10] != r[10:12]))


def clocks(rows):
    return sum(r[15] for r in rows)


def make_cases(args, parameters):
    core = core_frames(parameters)
    core.cycle()
    short = core.rows

    def case(name, vectors, category='functional', mutation=args.demo_bug, expected=None):
        return dict(id=name, vectors=vectors, mutation=mutation, category=category, expected_failure=expected,
                    counts=counts(vectors))

    cases = [case('boundaries', boundary_vectors(parameters))]
    for seed in range(args.seed, args.seed + (3 if args.profile == 'nightly' else 1)):
        cases.append(case(f'random-seed{seed}', random_vectors(seed, args.iterations, parameters)))
    limit = observed_limit(parameters)
    # The largest error that the probe frames produce passes, and one unit less fails:
    # the tolerance check of the testbench is live at exactly that unit.
    cases.append(case('limit-observed', probe_vectors(parameters, limit)))
    cases.append(case('limit-one-less', probe_vectors(parameters, limit - 1), category='diagnostic', mutation=0,
                      expected='FFT_TOLERANCE'))
    for m in range(1, MUTANTS + 1):
        cases.append(case(f'detect-mutation{m}', short, category='mutation', mutation=m, expected=LABELS[m]))
    return cases


if __name__ == '__main__':
    spec = importlib.util.spec_from_file_location('local_runner', HERE.parent / 'local-common/runner.py')
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)
    sys.exit(runner.main(sys.modules[__name__]))

#!/usr/bin/env python3
"""Per-channel INT32 to INT8 requantization: two rounding rules, clamp order, parameter capture and elastic flow."""
import importlib.util
from pathlib import Path
import random
import sys

HERE = Path(__file__).resolve().parent
NAME = 'local-requantize'
TOP = 'requantize_tb'
CONFIGS = {'ch2-full': {'CH': 2, 'ACT_MIN': -128, 'ACT_MAX': 127},
           'ch4-narrow': {'CH': 4, 'ACT_MIN': -20, 'ACT_MAX': 100}}
ITERATIONS = {'smoke': 200, 'nightly': 2000}
SOURCES = [HERE / 'rtl/requantize.sv', HERE / 'tb/requantize_tb.sv']
HALF = 1 << 30            # multiplier 0.5 in Q31
MAX_MULT = (1 << 31) - 1  # largest multiplier, just below 1.0
INT32 = (-(1 << 31), (1 << 31) - 1)


def round_half_up(num, den):
    """num/den to the nearest integer, ties toward +infinity (den > 0)."""
    return (2 * num + den) // (2 * den)


def round_half_away(num, den):
    """num/den to the nearest integer, ties away from zero (den > 0)."""
    return (1 if num >= 0 else -1) * ((2 * abs(num) + den) // (2 * den))


def requantize(x, m, s, zp, lo, hi):
    """Reference written from the rounding rules, not from the RTL's nudge and mask steps."""
    t = round_half_up(x * m, 1 << 31)
    u = round_half_away(t, 1 << s) + zp
    return max(lo, min(hi, u)), int(not lo <= u <= hi)


def solve(t, m):
    """An int32 x whose first rounding gives t; m >= 2^30 reaches every t in range."""
    start = (t << 31) // m
    for x in range(start - 2, start + 3):
        if INT32[0] <= x <= INT32[1] and round_half_up(x * m, 1 << 31) == t:
            return x
    raise ValueError(f'no int32 input reaches {t} with multiplier {m}')


class Model:
    """Three-slot elastic pipeline; the result is computed with the parameters at acceptance."""

    def __init__(self, ch, lo, hi):
        self.ch, self.lo, self.hi = ch, lo, hi
        self.reset()

    def reset(self):
        self.params = [(0, 0, 0)] * self.ch
        self.stages = [None, None, None]

    def step(self, rst, cfg, value, ready):
        if not rst:
            self.reset()
            return [0, 0, 0, 0]
        s0, s1, s2 = self.stages
        ready2 = s2 is None or ready
        ready1 = s1 is None or ready2
        ready0 = s0 is None or ready1
        outputs = [int(ready0), int(s2 is not None), *((0, 0) if s2 is None else (s2[0] & 0xff, s2[1]))]
        result = None
        if value is not None and ready0:
            result = requantize(value[1], *self.params[value[0]], self.lo, self.hi)
        self.stages = [result if ready0 else s0, s0 if ready1 else s1, s1 if ready2 else s2]
        if cfg is not None:
            self.params[cfg[0]] = tuple(cfg[1:])
        return outputs


class Plan:
    def __init__(self, ch, lo, hi):
        self.ch = ch
        self.model = Model(ch, lo, hi)
        self.rows = []

    def cycle(self, rst=1, cfg=None, value=None, ready=1):
        outputs = self.model.step(rst, cfg, value, ready)
        c = (self.ch - 1, 0x2aaaaaaa, 0x15, -0x5b) if cfg is None else cfg  # unused payloads carry junk
        x = (self.ch - 1, 0x5a5a5a5a) if value is None else value
        row = [rst, int(cfg is not None), c[0], c[1], c[2], c[3] & 0xff,
               int(value is not None), x[0], x[1] & 0xffffffff, ready, *outputs]
        self.rows.append(row)
        return row

    def send(self, ch, x, cfg=None):
        while not self.cycle(cfg=cfg, value=(ch, x))[10]:
            cfg = None

    def configure(self, ch, m, s, zp):
        self.cycle(cfg=(ch, m, s, zp))

    def stream(self, values, readies):
        """Offer each value until accepted, using the given out_ready pattern, then ready=1."""
        values = list(values)
        for ready in readies:
            if not values:
                return
            if self.cycle(value=values[0], ready=ready)[10]:
                values.pop(0)
        for value in values:
            self.send(*value)

    def drain(self):
        while any(stage is not None for stage in self.model.stages):
            self.cycle()


def boundary_vectors(ch, lo, hi):
    p = Plan(ch, lo, hi)
    p.cycle(rst=0)
    p.send(0, 12345)                       # parameters cleared by reset
    p.configure(0, HALF, 0, 0)             # t = x/2: odd x are ties of the first rounding
    for x in (3, -3, 1, -1, 5, -5):
        p.send(0, x)
    p.configure(1, HALF, 1, 0)
    p.send(1, 5)                           # two roundings give 2; one rounding of 5/4 gives 1
    for s in range(1, 32):                 # every shift: ties of the second rounding and neighbours
        c = s % ch
        m = MAX_MULT if s % 2 or s >= 29 else HALF
        p.configure(c, m, s, 0)
        k = 1 if s < 31 else 0
        for sign in (1, -1):
            for d in (-1, 0, 1):
                p.send(c, solve(sign * (k * (1 << s) + (1 << (s - 1))) + d, m))
    p.configure(0, HALF, 0, -128)          # activation limits and one step beyond them
    for u in (lo - 1, lo, hi, hi + 1):
        p.send(0, 2 * (u + 128))
    p.configure(0, MAX_MULT, 0, -128)      # magnitudes that only fit before narrowing
    p.send(0, INT32[1])
    p.send(0, INT32[0])
    p.configure(1, HALF, 0, 127)
    p.send(1, 0)
    p.configure(0, HALF, 2, 10)
    p.send(0, 400, cfg=(0, HALF, 1, -10))  # same edge: the old parameters apply
    p.send(0, 200)
    p.configure(0, HALF, 3, 5)             # written while the previous value is in flight
    p.drain()
    for i in range(8):                     # back-to-back over the channels
        p.send(i % ch, 40 * i - 150)
    p.send(0, 7)
    p.cycle()
    p.cycle()
    p.stream([(0, 2 * i + 1) for i in range(6)], [0, 0, 0, 0, 0, 1, 0, 1])
    for i in range(3):
        p.send(0, 100 + i)
    p.cycle(rst=0)                         # reset with values in flight
    p.send(1, 999)
    p.drain()
    return p.rows


def random_params(rng):
    roll = rng.randrange(8)
    m = (HALF, MAX_MULT)[roll] if roll < 2 else rng.randrange(0, HALF) if roll == 2 else rng.randrange(HALF, MAX_MULT)
    return m, rng.randrange(32), rng.randrange(-128, 128)


def random_value(rng, model):
    c = rng.randrange(model.ch)
    m, s, zp = model.params[c]
    if m == 0 or rng.randrange(8) == 0:
        return c, rng.randrange(INT32[0], INT32[1] + 1)
    t = rng.randrange(model.lo - zp - 40, model.hi - zp + 40) * (1 << s) + rng.randrange(-(1 << s), 1 << s)
    return c, max(INT32[0], min(INT32[1], (t << 31) // m + rng.randrange(-2, 3)))


def random_vectors(seed, iterations, ch, lo, hi):
    rng = random.Random(seed)
    p = Plan(ch, lo, hi)
    p.cycle(rst=0)
    accepted, pending = 0, None
    while accepted < iterations:
        roll = rng.randrange(200)
        if roll == 0:
            p.cycle(rst=0)
            pending = None
        if roll == 0 or not accepted and pending is None:
            for c in range(ch):
                p.configure(c, *random_params(rng))
        cfg = (rng.randrange(ch), *random_params(rng)) if roll < 16 else None
        if pending is None and rng.randrange(4):
            pending = random_value(rng, p.model)
        row = p.cycle(cfg=cfg, value=pending, ready=int(rng.randrange(3) != 0))
        if pending is not None and row[10]:
            accepted += 1
            pending = None
    p.drain()
    return p.rows


def counts(rows):
    return dict(accepted=sum(bool(r[0] and r[6] and r[10]) for r in rows),
                completed=sum(bool(r[0] and r[11] and r[9]) for r in rows),
                writes=sum(bool(r[0] and r[1]) for r in rows))


def make_cases(args, parameters):
    shape = parameters['CH'], parameters['ACT_MIN'], parameters['ACT_MAX']
    base = boundary_vectors(*shape)
    cases = [dict(id='boundaries', vectors=base, mutation=args.demo_bug, category='functional',
                  expected_failure=None)]
    for seed in range(args.seed, args.seed + (3 if args.profile == 'nightly' else 1)):
        cases.append(dict(id=f'random-seed{seed}', vectors=random_vectors(seed, args.iterations, *shape),
                          mutation=args.demo_bug, category='functional', expected_failure=None))
    for mutation in range(1, 5):
        cases.append(dict(id=f'detect-mutation{mutation}', vectors=base, mutation=mutation,
                          category='mutation', expected_failure='REQ_DATA'))
    for case in cases:
        case['counts'] = counts(case['vectors'])
    return cases


if __name__ == '__main__':
    spec = importlib.util.spec_from_file_location('local_runner', HERE.parent / 'local-common/runner.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    sys.exit(module.main(sys.modules[__name__]))

#!/usr/bin/env python3
"""Piecewise-linear sigmoid and tanh judged by an error bound over every input."""
import importlib.util
import math
from pathlib import Path
import random
import sys

HERE = Path(__file__).resolve().parent
NAME = 'local-activation'
TOP = 'activation_tb'
CONFIGS = {'sigmoid': {'FUNC': 0}, 'tanh': {'FUNC': 1}}
ITERATIONS = {'smoke': 300, 'nightly': 3000}
SOURCES = [HERE / 'rtl/pwl_activation.sv', HERE / 'tb/activation_tb.sv']
TOLERANCE = 1.25  # required bound: |y - 1024*f(x)| <= 1.25 output LSB
LOOSE = 2.5       # a looser bound used only by the diagnostics
INPUTS = range(-2048, 2048)


def ideal(func, x):
    """Exact function value in output LSB (scale 1024), from the floating-point library."""
    if func == 0:
        return 1024 / (1 + math.exp(-x / 256))
    return 1024 * math.tanh(x / 512)


class Model:
    """One output register; the expected value is the ideal function, not the RTL table."""

    def __init__(self, func, tolerance):
        self.func = func
        self.tolerance = round(tolerance * 256)
        self.reset()

    def reset(self):
        self.slot = None

    def step(self, rst, x, ready):
        if not rst:
            self.reset()
            return [0, 0, 0, 0]
        in_ready = int(self.slot is None or bool(ready))
        outputs = [in_ready, int(self.slot is not None),
                   0 if self.slot is None else round(ideal(self.func, self.slot) * 256) & 0xffffffff,
                   self.tolerance]
        if in_ready:
            self.slot = x
        return outputs


class Plan:
    def __init__(self, func, tolerance=TOLERANCE):
        self.model = Model(func, tolerance)
        self.rows = []

    def cycle(self, rst=1, x=None, ready=1):
        outputs = self.model.step(rst, x, ready)
        row = [rst, int(x is not None), (0x5a5 if x is None else x) & 0xfff, ready, *outputs]
        self.rows.append(row)
        return row

    def send(self, x, ready=1):
        while not self.cycle(x=x, ready=ready)[4]:
            pass

    def drain(self):
        while self.model.slot is not None:
            self.cycle()


def boundary_vectors(func, tolerance=TOLERANCE):
    p = Plan(func, tolerance)
    p.cycle(rst=0)
    for x in INPUTS:          # every input, back to back
        p.send(x)
    p.drain()
    p.send(-1)
    for _ in range(3):        # output held while the next input waits
        p.cycle(x=1, ready=0)
    p.send(1)
    p.cycle(rst=0)            # reset with a result waiting
    p.send(0)
    p.drain()
    return p.rows


def random_vectors(seed, iterations, func):
    rng = random.Random(seed)
    p = Plan(func)
    p.cycle(rst=0)
    accepted, pending = 0, None
    while accepted < iterations:
        if rng.randrange(150) == 0:
            p.cycle(rst=0)
            pending = None
        if pending is None and rng.randrange(4):
            pending = rng.choice(INPUTS)
        row = p.cycle(x=pending, ready=int(rng.randrange(3) != 0))
        if pending is not None and row[4]:
            accepted += 1
            pending = None
    p.drain()
    return p.rows


def counts(rows):
    return dict(accepted=sum(bool(r[0] and r[1] and r[4]) for r in rows),
                completed=sum(bool(r[0] and r[5] and r[3]) for r in rows))


def make_cases(args, parameters):
    func = parameters['FUNC']
    base = boundary_vectors(func)
    cases = [dict(id='boundaries', vectors=base, mutation=args.demo_bug, category='functional',
                  expected_failure=None)]
    for seed in range(args.seed, args.seed + (3 if args.profile == 'nightly' else 1)):
        cases.append(dict(id=f'random-seed{seed}', vectors=random_vectors(seed, args.iterations, func),
                          mutation=args.demo_bug, category='functional', expected_failure=None))
    for mutation in range(1, 5):
        cases.append(dict(id=f'detect-mutation{mutation}', vectors=base, mutation=mutation,
                          category='mutation', expected_failure='ACT_TOLERANCE'))
    loose = boundary_vectors(func, LOOSE)
    for mutation in (1, 2):   # the looser bound lets these small errors through
        cases.append(dict(id=f'loose-bound-mutation{mutation}', vectors=loose, mutation=mutation,
                          category='diagnostic', expected_failure=None))
    for case in cases:
        case['counts'] = counts(case['vectors'])
    return cases


if __name__ == '__main__':
    spec = importlib.util.spec_from_file_location('local_runner', HERE.parent / 'local-common/runner.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    sys.exit(module.main(sys.modules[__name__]))

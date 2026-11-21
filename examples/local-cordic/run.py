#!/usr/bin/env python3
"""Pipelined CORDIC: bit-exact against an integer model, and within a derived error bound of the mathematical result."""
import importlib.util
import math
from pathlib import Path
import random
import sys

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('cordic_model', HERE / 'model.py')
M = importlib.util.module_from_spec(spec)
spec.loader.exec_module(M)

NAME = 'local-cordic'
TOP = 'cordic_tb'
CONFIGS = {'w16-i16-g4': dict(WIDTH=16, ITER=16, GUARD=4), 'w12-i12-g2': dict(WIDTH=12, ITER=12, GUARD=2)}
ITERATIONS = {'smoke': 200, 'nightly': 2000}
SOURCES = [HERE / 'rtl/cordic.sv', HERE / 'tb/cordic_tb.sv']
EXTRA_INPUTS = [HERE / 'model.py']
MUTANTS = 6
# The check of the fixed scenario that sees each mutant first.
LABELS = {1: 'CORDIC_DATA', 2: 'CORDIC_TOLERANCE', 3: 'CORDIC_DATA', 4: 'CORDIC_DATA',
          5: 'CORDIC_TOLERANCE', 6: 'CORDIC_VALID'}
# Angle step of the two sweeps, (rotation, vectoring). Nightly turns by every 16-bit angle.
# The common runner copies every row into manifest.json, so the vectoring sweep stays coarser.
SWEEP_STEP = {'smoke': (16, 16), 'nightly': (1, 4)}
PROBE_STEP = 16                           # the set that the two tightened cases use
MASK = (1 << 20) - 1


def add_arguments(parser):
    # One case of the nightly sweep simulates 65,536 operations; ten seconds are not enough on a busy machine.
    parser.set_defaults(timeout=60.0)


class Plan:
    """Rows for the testbench: the pipeline as a queue of expected results."""

    def __init__(self, parameters, tighten=None):
        self.w, self.n, self.g = parameters['WIDTH'], parameters['ITER'], parameters['GUARD']
        self.tighten = tighten
        self.queue = [None] * (self.n + 2)
        self.rows = [[1, i, M.residual_bound(i, self.n, self.g)] + [0] * 14 for i in range(self.n + 1)]

    def cycle(self, rst=1, valid=0, mode=0, x=0, y=0, z=0):
        out = self.queue.pop(0)
        if rst and valid:
            exp, ref = M.cordic(mode, x, y, z, self.w, self.n, self.g), M.reference(mode, x, y, z)
            tol = list(M.tolerance(mode, x, y, self.w, self.n, self.g))
            if self.tighten is not None:
                tol[0] = tol[1] = self.tighten
            self.queue.append((exp, ref, tol))
        else:
            self.queue.append(None)
        if not rst:
            self.queue = [None] * len(self.queue)
        exp, ref, tol = out or ((0, 0, 0), (0, 0, 0), (0, 0, 0))
        self.rows.append([0, rst, valid, mode, x & MASK, y & MASK, z, int(out is not None),
                          *(e & MASK for e in exp[:2]), exp[2], *(r & MASK for r in ref[:2]), ref[2], *tol])

    def op(self, mode, x, y, z=0, gap=0):
        self.cycle(valid=1, mode=mode, x=x, y=y, z=z)
        for _ in range(gap):
            self.cycle(x=0x55, y=-0x2b, z=0x1234)       # values that are offered without valid are ignored

    def drain(self):
        for _ in range(len(self.queue) + 1):
            self.cycle()


def boundary_vectors(parameters):
    w = parameters['WIDTH']
    top, low = (1 << (w - 1)) - 1, -(1 << (w - 1))
    p = Plan(parameters)
    p.cycle(rst=0)
    p.cycle()
    # Rotation: the four quadrants, exactly on and one unit inside each fold boundary, and the extremes of x and y.
    for z in (0x0000, 0x0001, 0x2000, 0x3fff, 0x4000, 0x4001, 0x6000, 0x7fff, 0x8000, 0x8001, 0xa000,
              0xbfff, 0xc000, 0xc001, 0xe000, 0xffff):
        p.op(0, top, 0, z)
    for x, y, z in ((top, top, 0x2000), (low, low, 0x2000), (low, top, 0xe000), (top, low, 0x6000), (0, 0, 0x1234),
                    (1, 0, 0x4000), (0, -1, 0x8000), (top // 3, -(top // 5), 0x1555)):
        p.op(0, x, y, z, gap=1)
    # Vectoring: axes, quadrants, the zero vector, vectors too short to have a direction, and the extremes.
    for x, y in ((top, 0), (low, 0), (0, top), (0, low), (0, 0), (1, 1), (-1, 1), (-1, -1), (1, -1), (2, -1),
                 (top, top), (low, top), (low, low), (top, low), (top, 1), (top, -1), (-top, 1), (low, -1),
                 (top // 2, top // 3), (-(top // 7), top // 2), (-(top // 3), -(top // 11)), (top // 9, -(top // 2))):
        p.op(1, x, y, z=0xabcd)                         # z_in is ignored in vectoring
    # Interleaved modes back to back, then a reset that drops everything in the pipeline.
    for k in range(6):
        p.op(k & 1, top // (k + 1), -(top // (k + 2)), z=0x1000 * k)
    p.op(0, top, 0, 0x2000)
    p.op(1, top, top)
    p.cycle(rst=0)
    p.drain()                                           # nothing may come out after the reset
    p.op(0, top, 0, 0x4000)
    p.drain()
    return p.rows


def sweep_vectors(parameters, mode, step, offset=0, tighten=None):
    w = parameters['WIDTH']
    radius = (1 << (w - 1)) - 1
    p = Plan(parameters, tighten)
    p.cycle(rst=0)
    for z in range(offset % step, M.TURN, step):
        if mode:
            a = 2 * math.pi * z / M.TURN
            p.op(1, round(radius * math.cos(a)), round(radius * math.sin(a)))
        else:
            p.op(0, radius, 0, z)
    p.drain()
    return p.rows


def random_vectors(seed, iterations, parameters):
    w = parameters['WIDTH']
    rng = random.Random(seed)
    p = Plan(parameters)
    p.cycle(rst=0)
    for k in range(iterations):
        small = rng.random() < 0.15
        span = 4 if small else 1 << (w - 1)
        p.op(rng.randrange(2), rng.randrange(-span, span), rng.randrange(-span, span), rng.randrange(M.TURN),
             gap=rng.choice((0, 0, 0, 1, 2, 5)))
        if k and k % 97 == 0:
            p.cycle(rst=0)
    p.drain()
    return p.rows


def observed_limit(parameters):
    """Largest x or y error of the integer model over the probe set (a measurement, not a bound)."""
    w, n, g = parameters['WIDTH'], parameters['ITER'], parameters['GUARD']
    radius = (1 << (w - 1)) - 1
    return max(max(M.errors(0, radius, 0, z, w, n, g)[:2]) for z in range(0, M.TURN, PROBE_STEP))


def counts(rows):
    cycles = [r for r in rows if r[0] == 0]
    done = [r for r in cycles if r[7]]
    return dict(accepted=sum(bool(r[1] and r[2]) for r in cycles), completed=len(done),
                rotations=sum(bool(r[1] and r[2] and not r[3]) for r in cycles),
                vectorings=sum(bool(r[1] and r[2] and r[3]) for r in cycles),
                inexact=sum(r[8:11] != r[11:14] for r in done))


def make_cases(args, parameters):
    baseline = boundary_vectors(parameters)
    step = SWEEP_STEP[args.profile]

    def case(name, vectors, category='functional', mutation=args.demo_bug, expected=None):
        return dict(id=name, vectors=vectors, mutation=mutation, category=category, expected_failure=expected,
                    counts=counts(vectors))

    cases = [case('boundaries', baseline),
             case('sweep-rotation', sweep_vectors(parameters, 0, step[0], args.seed)),
             case('sweep-vectoring', sweep_vectors(parameters, 1, step[1], args.seed))]
    for seed in range(args.seed, args.seed + (3 if args.profile == 'nightly' else 1)):
        cases.append(case(f'random-seed{seed}', random_vectors(seed, args.iterations, parameters)))
    limit = observed_limit(parameters)
    # The largest error that the probe set produces passes, and one unit less fails:
    # the tolerance check of the testbench is live at exactly that unit.
    cases.append(case('limit-observed', sweep_vectors(parameters, 0, PROBE_STEP, tighten=limit)))
    cases.append(case('limit-one-less', sweep_vectors(parameters, 0, PROBE_STEP, tighten=limit - 1),
                      category='diagnostic', mutation=0, expected='CORDIC_TOLERANCE'))
    for m in range(1, MUTANTS + 1):
        cases.append(case(f'detect-mutation{m}', baseline, category='mutation', mutation=m, expected=LABELS[m]))
    return cases


if __name__ == '__main__':
    spec = importlib.util.spec_from_file_location('local_runner', HERE.parent / 'local-common/runner.py')
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)
    sys.exit(runner.main(sys.modules[__name__]))

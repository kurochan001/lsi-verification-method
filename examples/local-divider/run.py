#!/usr/bin/env python3
"""Iterative divider in simulation at 32 and 8 bits: RISC-V special cases, latency, flush and backpressure."""
import importlib.util
from pathlib import Path
import random
import sys

HERE = Path(__file__).resolve().parent
NAME = 'local-divider'
TOP = 'divider_tb'
CONFIGS = {'w32': {'W': 32}, 'w8': {'W': 8}}
ITERATIONS = {'smoke': 200, 'nightly': 2000}
SOURCES = [HERE / 'rtl/divider.sv', HERE / 'tb/divider_tb.sv']
LABELS = {1: 'DIV_DATA', 2: 'DIV_DATA', 3: 'DIV_CONTROL', 4: 'DIV_CONTROL'}


def to_signed(x, w):
    return x - (1 << w) if x >> (w - 1) & 1 else x


def reference(a, b, signed, w):
    """Quotient and remainder as the RISC-V M extension defines them, as w-bit patterns."""
    mask = (1 << w) - 1
    if signed:
        a, b = to_signed(a, w), to_signed(b, w)
    if b == 0:
        return mask, a & mask                          # quotient all ones, remainder the dividend
    if signed and a == -(1 << (w - 1)) and b == -1:
        return a & mask, 0                             # overflow: quotient the dividend, remainder 0
    q = abs(a) // abs(b)                               # rounds toward zero
    if (a < 0) != (b < 0):
        q = -q
    return q & mask, (a - q * b) & mask                # the remainder takes the dividend's sign


def short(a, b, signed, w):
    """Divisions that finish one cycle after acceptance."""
    if signed:
        a, b = to_signed(a, w), to_signed(b, w)
    return b == 0 or (signed and a == -(1 << (w - 1)) and b == -1) or abs(a) < abs(b)


def edges(w):
    top = 1 << (w - 1)
    return [0, 1, 2, 3, 7, top - 1, top, top + 1, (1 << w) - 2, (1 << w) - 1]


class Model:
    """Cycle model: outputs during a cycle, then the state after its edge."""

    def __init__(self, w):
        self.w = w
        self.reset()

    def reset(self):
        self.busy, self.left, self.valid, self.result, self.pending = 0, 0, 0, (0, 0), (0, 0)

    def step(self, rst_n, flush, valid, signed, a, b, ready):
        in_ready = int(bool(rst_n and not self.busy and not self.valid and not flush))
        outputs = [in_ready, self.valid, *self.result]
        if not rst_n:
            self.reset()
        elif flush:
            self.busy, self.valid = 0, 0
        elif valid and in_ready:
            if short(a, b, signed, self.w):
                self.valid, self.result = 1, reference(a, b, signed, self.w)
            else:
                self.busy, self.left, self.pending = 1, self.w, reference(a, b, signed, self.w)
        elif self.busy:
            self.left -= 1
            if not self.left:
                self.busy, self.valid, self.result = 0, 1, self.pending
        elif self.valid and ready:
            self.valid = 0
        return outputs


class Plan:
    def __init__(self, w, rng=None):
        self.w, self.model, self.rows, self.rng = w, Model(w), [], rng

    def cycle(self, rst_n=1, flush=0, valid=0, signed=0, a=0, b=0, ready=1):
        if not valid and self.rng:  # unused operand lines carry unrelated values
            a, b = self.rng.getrandbits(self.w), self.rng.getrandbits(self.w)
        outputs = self.model.step(rst_n, flush, valid, signed, a, b, ready)
        self.rows.append([rst_n, flush, valid, signed, a, b, ready, *outputs])
        return outputs

    def accept(self, a, b, signed):
        while not self.cycle(valid=1, signed=signed, a=a, b=b, ready=0)[0]:
            pass

    def divide(self, a, b, signed, hold=0):
        """Accept, wait for the result, keep it waiting for hold cycles, then take it."""
        self.accept(a, b, signed)
        while not self.model.valid:
            self.cycle(ready=0)
        for _ in range(hold):
            self.cycle(ready=0)
        self.cycle(ready=1)


def boundary_vectors(w):
    p = Plan(w)
    mask, top = (1 << w) - 1, 1 << (w - 1)
    for _ in range(3):
        p.cycle(rst_n=0)
    for signed in (1, 0):                                  # every pair of edge values
        for a in edges(w):
            for b in edges(w):
                p.divide(a, b, signed)
    for a, b in ((5, -5), (-5, 5), (-5, -5), (top - 1, top + 1), (top, top),  # equal magnitudes
                 (7, -2), (-7, 2), (-7, -2), (-(top - 1), 3)):              # signs of the remainder
        p.divide(a & mask, b & mask, 1)
    p.divide(top | 5, top | 3, 0)
    p.divide(100, 7, 1, hold=3)                            # a held normal result
    p.divide(0, 0, 1, hold=2)                              # a held one-cycle result
    for age in range(1, w + 2):                            # flush at every step and on the result
        p.accept(100, 7, 1)
        for _ in range(age - 1):
            p.cycle(ready=0)
        p.cycle(flush=1, ready=0)
        p.cycle()
    p.accept(3, 7, 0)                                      # flush of an unread one-cycle result
    p.cycle(ready=0)
    p.cycle(flush=1, ready=0)
    p.accept(100, 7, 1)                                    # reset in the middle of a division
    for _ in range(3):
        p.cycle(ready=0)
    p.cycle(rst_n=0)
    p.cycle(rst_n=0)
    p.divide(100, 7, 1)
    return p.rows


def random_vectors(w, seed, divisions):
    rng = random.Random(seed)
    p = Plan(w, rng)
    mask = (1 << w) - 1

    def operand():
        return rng.choice(edges(w)) if rng.random() < 0.3 else rng.getrandbits(w)
    for _ in range(2):
        p.cycle(rst_n=0)
    for _ in range(divisions):
        signed = rng.randrange(2)
        a, b = operand(), operand()
        if rng.random() < 0.1:
            b = (-a if rng.randrange(2) else a) & mask
        roll = rng.random()
        if roll < 0.03:
            p.accept(a, b, signed)
            for _ in range(rng.randrange(w + 2)):
                p.cycle(ready=0)
            p.cycle(flush=1, ready=0)
        elif roll < 0.04:
            p.accept(a, b, signed)
            p.cycle(rst_n=0)
        else:
            p.divide(a, b, signed, hold=rng.choice((0, 0, 1, 3)))
        for _ in range(rng.choice((0, 0, 1, 2))):
            p.cycle(ready=rng.randrange(2))
    return p.rows


def counts(rows):
    accepted = completed = flushed = pending = previous = 0
    for row in rows:
        rst_n, flush, valid, ready_in, out_valid = row[0], row[1], row[2], row[7], row[8]
        if not rst_n:
            pending = 0
        else:
            if out_valid and not previous:
                completed, pending = completed + 1, 0
            if flush and pending:
                flushed, pending = flushed + 1, 0
            if valid and ready_in:
                accepted, pending = accepted + 1, 1
        previous = out_valid
    return dict(accepted=accepted, completed=completed, flushed=flushed)


def make_cases(args, parameters):
    w = parameters['W']
    base = boundary_vectors(w)
    cases = [dict(id='boundaries', vectors=base, mutation=args.demo_bug, category='functional',
                  expected_failure=None)]
    for seed in range(args.seed, args.seed + (3 if args.profile == 'nightly' else 1)):
        cases.append(dict(id=f'random-seed{seed}', vectors=random_vectors(w, seed, args.iterations),
                          mutation=args.demo_bug, category='functional', expected_failure=None))
    for mutation in range(1, 5):
        cases.append(dict(id=f'detect-mutation{mutation}', vectors=base, mutation=mutation,
                          category='mutation', expected_failure=LABELS[mutation]))
    for case in cases:
        case['counts'] = counts(case['vectors'])
    return cases


if __name__ == '__main__':
    spec = importlib.util.spec_from_file_location('local_runner', HERE.parent / 'local-common/runner.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    sys.exit(module.main(sys.modules[__name__]))

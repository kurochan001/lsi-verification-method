#!/usr/bin/env python3
"""Long counter: three ways to shorten the test (narrow width, test load, force) and the mutants each one sees."""
import importlib.util
from pathlib import Path
import random
import sys

HERE = Path(__file__).resolve().parent
NAME = 'local-long-counter'
TOP = 'long_counter_tb'
# METHOD: 0 count from zero at a reduced width, 1 test load through the pins, 2 force.
CONFIGS = {
    'narrow8': dict(WIDTH=8, SPLIT=16, METHOD=0),    # width cut below the first carry cut: one adder
    'scaled8': dict(WIDTH=8, SPLIT=4, METHOD=0),     # width and carry cut reduced together
    'preload32': dict(WIDTH=32, SPLIT=16, METHOD=1),
    'force32': dict(WIDTH=32, SPLIT=16, METHOD=2),
}
ITERATIONS = {'smoke': 200, 'nightly': 2000}
SOURCES = [HERE / 'rtl/long_counter.sv', HERE / 'tb/long_counter_tb.sv']
MUTANTS = 6
LABELS = {1: 'CNT_WRAP', 2: 'CNT_TICK', 3: 'CNT_COUNT', 4: 'CNT_COUNT', 5: 'CNT_COUNT', 6: 'CNT_COUNT'}
NONE, LOAD, FORCE, FORCE_COUNT_ONLY, LOAD_IGNORED = range(5)
JUMP = {1: LOAD, 2: FORCE}


def visible(parameters):
    """Mutants whose changed logic exists in this configuration and is reached by its fixed plan."""
    width, split, method = parameters['WIDTH'], parameters['SPLIT'], parameters['METHOD']
    seen = {1, 2}
    if width > split:
        seen |= {4, 6}                 # the comparison in two halves and the registered carry flag
        if width > split + 8:
            seen.add(3)                # the second cut of the upper part
        if method == 1:
            seen.add(5)                # only a plan that loads onto a carry stresses the load path
    return seen


class Model:
    """The specification: one integer, plus 1 modulo 2**width. It knows nothing of carry cuts."""

    def __init__(self, width):
        self.width, self.mask, self.count = width, (1 << width) - 1, 0

    def step(self, rst_n=1, enable=0, clear=0, op=NONE, value=0, limit=None):
        limit = self.mask if limit is None else limit
        tick = 0
        if not rst_n:
            self.count = 0
        elif op in (FORCE, FORCE_COUNT_ONLY):       # a force overrides whatever the design computes
            if enable or clear:
                raise ValueError('a forced row keeps the counter idle')
            self.count = value
        elif clear:
            self.count = 0
        elif op == LOAD:
            self.count = value
        elif enable:
            tick = int(self.count == limit)
            self.count = 0 if tick else (self.count + 1) & self.mask
        return [rst_n, enable, clear, op, value, limit, self.count, tick]


class Plan:
    def __init__(self, width, method):
        self.width, self.method, self.model, self.rows = width, method, Model(width), []
        self.mask = (1 << width) - 1

    def cycle(self, n=1, **inputs):
        for _ in range(n):
            self.rows.append(self.model.step(**inputs))

    def go(self, target):
        """Bring the counter to target: by counting at reduced width, otherwise by the method."""
        if self.method:
            self.cycle(op=JUMP[self.method], value=target)
            return
        if target < self.model.count:
            self.cycle(clear=1)
        self.cycle(target - self.model.count, enable=1)


def boundary_rows(width, method):
    p = Plan(width, method)
    mask, top, half = p.mask, 1 << (width - 1), width // 2
    p.cycle(2, rst_n=0)
    p.cycle(3, enable=1)
    p.cycle(2)                                   # hold
    p.cycle(enable=1, clear=1)                   # clear wins over counting
    p.cycle(3, enable=1, limit=0)                # limit 0: a tick on every enabled cycle
    p.cycle(3, enable=1, limit=3)                # 1, 2, 3
    p.cycle(2, limit=3)                          # paused on the limit: no tick, no return to 0
    p.cycle(5, enable=1, limit=3)                # returns to 0 with a tick, then counts again
    p.cycle(3, enable=1, limit=3)
    p.cycle(enable=1, clear=1, limit=3)          # clear on the matching cycle: no tick
    # Every carry, from just below it. The limit is all ones, so the top-bit case also passes
    # the value that differs from the limit in the top bit only.
    for k in range(1, width):
        p.go((1 << k) - 2)
        p.cycle(3, enable=1)
    p.go(mask - 1)
    p.cycle(3, enable=1)                         # the limit of all ones: tick and return to 0
    p.cycle(enable=1, clear=1)
    p.go(mask - 1)
    p.cycle(9, enable=1, limit=5)                # above the limit: around through 0 without a tick, then 5
    p.cycle(enable=1, clear=1)
    # Pauses around the carry out of the lower half.
    p.go((1 << half) - 3)
    p.cycle(enable=1)
    p.cycle(2)                                   # paused one below the carry
    p.cycle(enable=1)
    p.cycle(2)                                   # paused with the carry waiting
    p.cycle(2, enable=1)
    # Landing exactly on a carry instead of just below it.
    for k in (half, width - 1):
        p.go((1 << k) - 1)
        p.cycle(2, enable=1)
    # The test load path itself, away from any carry.
    p.cycle(enable=1, clear=1)
    middle = 0x5A5A5A5A5A5A5A5A & (mask >> 1)
    p.cycle(op=LOAD, value=middle)
    p.cycle(2, enable=1)
    p.cycle(op=LOAD_IGNORED, value=1)            # test_load without test_mode
    p.cycle(op=LOAD_IGNORED, value=1, enable=1)
    p.cycle(op=LOAD, value=3, enable=1, limit=p.model.count)   # load wins over a matching count
    p.cycle(2, enable=1)
    p.cycle(rst_n=0, enable=1)
    p.cycle(2)
    return p.rows


def random_rows(width, method, seed, iterations):
    rng = random.Random(seed)
    p = Plan(width, method)
    mask = p.mask
    p.cycle(rst_n=0)
    limit = mask
    for _ in range(iterations):
        roll = rng.random()
        if roll < 0.02:
            p.cycle(rst_n=0, enable=rng.randrange(2))
        elif roll < 0.05:
            p.cycle(clear=1, enable=rng.randrange(2), limit=limit)
        elif roll < 0.15:
            limit = rng.choice((mask, mask, (p.model.count + rng.randrange(1, 6)) & mask, rng.getrandbits(width)))
            p.cycle(enable=1, limit=limit)
        elif roll < 0.25 and method:
            k = rng.randrange(1, width + 1)
            p.cycle(op=JUMP[method], value=((1 << k) - rng.randrange(1, 4)) & mask, limit=limit)
        elif roll < 0.27:
            p.cycle(op=LOAD_IGNORED, value=rng.getrandbits(width), enable=rng.randrange(2), limit=limit)
        else:
            p.cycle(enable=int(rng.random() < 0.8), limit=limit)
    p.cycle(rst_n=0)
    p.cycle(2)
    return p.rows


def careless_force_rows(width, split):
    """Force count alone onto a carry of the cut chain: a correct design then fails the check."""
    p = Plan(width, 2)
    p.cycle(2, rst_n=0)
    p.cycle(op=FORCE_COUNT_ONLY, value=(1 << split) - 1)
    p.cycle(2, enable=1)
    return p.rows


def counts(rows):
    return dict(ticks=sum(r[7] for r in rows), jumps=sum(r[3] in (LOAD, FORCE, FORCE_COUNT_ONLY) for r in rows))


def make_cases(args, parameters):
    width, method = parameters['WIDTH'], parameters['METHOD']
    base = boundary_rows(width, method)
    cases = [dict(id='boundaries', vectors=base, mutation=args.demo_bug, category='functional', expected_failure=None)]
    for seed in range(args.seed, args.seed + (3 if args.profile == 'nightly' else 1)):
        cases.append(dict(id=f'random-seed{seed}', vectors=random_rows(width, method, seed, args.iterations),
                          mutation=args.demo_bug, category='functional', expected_failure=None))
    seen = visible(parameters)
    for mutation in range(1, MUTANTS + 1):
        if mutation in seen:
            cases.append(dict(id=f'detect-mutation{mutation}', vectors=base, mutation=mutation,
                              category='mutation', expected_failure=LABELS[mutation]))
        else:   # the same plan, with all its goals, passes on the mutant
            cases.append(dict(id=f'survive-mutation{mutation}', vectors=base, mutation=mutation,
                              category='diagnostic', expected_failure=None))
    if method == 2:
        cases.append(dict(id='careless-force', vectors=careless_force_rows(width, parameters['SPLIT']), mutation=0,
                          category='diagnostic', expected_failure='CNT_COUNT'))
    for case in cases:
        case['counts'] = counts(case['vectors'])
    return cases


if __name__ == '__main__':
    spec = importlib.util.spec_from_file_location('local_runner', HERE.parent / 'local-common/runner.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    sys.exit(module.main(sys.modules[__name__]))

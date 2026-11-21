#!/usr/bin/env python3
"""Token bucket rate limiter: cycle-exact model, window bound over every interval, and mutants."""
import importlib.util
from pathlib import Path
import random
import sys

HERE = Path(__file__).resolve().parent
NAME = 'local-rate-limiter'
TOP = 'token_bucket_tb'
CONFIGS = {
    'f4d4r8': dict(FRAC=4, DEPTH_W=4, RATE_W=8),   # 16 units per token, depth 0..15, refill 0..255 units
    'f2d2r3': dict(FRAC=2, DEPTH_W=2, RATE_W=3),   # the formal configuration: 4 units, depth 0..3, refill 0..7
}
ITERATIONS = {'smoke': 300, 'nightly': 1500}
SOURCES = [HERE / 'rtl/token_bucket.sv', HERE / 'tb/token_bucket_tb.sv']
EXTRA_INPUTS = [HERE / 'model.py']
MUTANTS = 5
# The first check each mutant breaks on the fixed plan (asserted by the self-tests).
LABELS = {1: 'RL_GRANT', 2: 'RL_TOKENS', 3: 'RL_TOKENS', 4: 'RL_GRANT', 5: 'RL_TOKENS'}
# Bit i of the tag column names the goal printed by the bench when the row passes.
TAGS = ['grant/exact-token', 'deny/one-unit-short', 'deny/empty', 'refill/saturate', 'refill/below-carry',
        'refill/carry', 'rate/zero', 'rate/max', 'rate/fraction', 'depth/zero', 'depth/max',
        'config/depth-down', 'config/rate-change', 'reset/mid-run', 'window/tight', 'burst/depth-then-deny']
BIT = {name: 1 << i for i, name in enumerate(TAGS)}

spec = importlib.util.spec_from_file_location('rate_limiter_model', HERE / 'model.py')
M = importlib.util.module_from_spec(spec)
spec.loader.exec_module(M)


class Plan:
    """Rows of one cycle each: rst_n, req, depth, rate, expected grant, expected level, tags."""

    def __init__(self, parameters):
        self.frac, self.depth_w, self.rate_w = parameters['FRAC'], parameters['DEPTH_W'], parameters['RATE_W']
        self.cost = 1 << self.frac
        self.level_limit = 1 << (self.depth_w + self.frac)
        self.max_depth, self.max_rate = (1 << self.depth_w) - 1, (1 << self.rate_w) - 1
        self.bucket, self.rows, self.trace = M.Bucket(self.frac), [], []
        self.previous = None                   # (depth, rate) of the last cycle out of reset
        self.run, self.full = 0, False         # consecutive grants since a full bucket, at rate 0

    def cycle(self, n=1, rst_n=1, req=0, depth=None, rate=None, tags=0):
        depth = self.max_depth if depth is None else depth
        rate = 0 if rate is None else rate
        if not (0 <= depth <= self.max_depth and 0 <= rate <= self.max_rate):
            raise ValueError('setting out of range')
        for _ in range(n):
            before = self.bucket.tokens
            grant, level, info = self.bucket.step(rst_n, req, depth, rate)
            tag = tags
            if not rst_n:
                if before is not None:
                    tag |= BIT['reset/mid-run']
                self.previous, self.run, self.full = None, 0, True
            else:
                total, avail = info['total'], info['avail']
                if grant and avail == self.cost:
                    tag |= BIT['grant/exact-token']
                if req and not grant:
                    tag |= BIT['deny/one-unit-short'] if avail == self.cost - 1 else BIT['deny/empty'] if avail == 0 else 0
                if info['saturated']:
                    tag |= BIT['refill/saturate']
                    if depth == self.max_depth:
                        tag |= BIT['depth/max']
                if total == self.level_limit - 1:
                    tag |= BIT['refill/below-carry']
                if total >= self.level_limit:
                    tag |= BIT['refill/carry']
                if req and rate == 0:
                    tag |= BIT['rate/zero']
                if rate == self.max_rate:
                    tag |= BIT['rate/max']
                if grant and 0 < rate < self.cost:
                    tag |= BIT['rate/fraction']
                if req and depth == 0:
                    tag |= BIT['depth/zero']
                if self.previous is not None:
                    if depth < self.previous[0] and before + rate > info['cap']:
                        tag |= BIT['config/depth-down']
                    if rate != self.previous[1]:
                        tag |= BIT['config/rate-change']
                # depth grants in a row from a full bucket without refill, then the next request refused
                if rate != 0 or not req:
                    self.full, self.run = False, 0
                elif self.full:
                    if grant:
                        self.run += 1
                    else:
                        if self.run == depth and depth > 0:
                            tag |= BIT['burst/depth-then-deny']
                        self.full = False
                self.previous = (depth, rate)
            self.rows.append([rst_n, req, depth, rate, grant, level, tag])
            self.trace.append((rst_n, grant, info['cap'], rate))

    def finish(self):
        """Check the window bound on the whole trace; mark the end of one tight window."""
        slack, _ = M.window_slack(self.cost, self.trace)
        if slack is None or slack < 0:
            raise ValueError(f'the model exceeds the window bound (slack {slack})')
        tight = tight_window(self.cost, self.trace)
        if tight is not None:
            self.rows[tight[1]][6] |= BIT['window/tight']
        return self.rows


def tight_window(cost, trace):
    """A window that reaches its bound exactly with more grants than one full bucket holds."""
    n = len(trace)
    for start in range(n):
        if not trace[start][0]:
            continue
        grants, units = 0, trace[start][2]
        for end in range(start, n):
            rst_n, grant, cap, rate = trace[end]
            if not rst_n:
                break
            units += rate if end > start else 0
            grants += grant
            if end - start >= 2 and grants > trace[start][2] // cost and units // cost == grants:
                return start, end
    return None


def boundary_rows(parameters):
    p = Plan(parameters)
    cost, top_d, top_r = p.cost, p.max_depth, p.max_rate
    d = min(3, top_d)
    p.cycle(2, rst_n=0, depth=d)
    p.cycle(d + 2, req=1, depth=d, rate=0)                 # exactly d grants from full, then refused
    p.cycle(2, depth=d, rate=0)                            # empty and no refill: nothing to spend
    p.cycle(rst_n=0, depth=d)                              # a reset in the middle refills the bucket
    p.cycle(3 * cost, req=1, depth=d, rate=1)              # one unit per cycle: one token per cost cycles
    p.cycle(cost - 1, depth=d, rate=1)                     # refill up to one unit short of a token
    p.cycle(req=1, depth=d, rate=0)                        # one unit short: refused
    p.cycle(req=1, depth=d, rate=1)                        # the last unit arrives: exactly one token, granted
    p.cycle(3, req=1, depth=d, rate=cost // 2 + 1)         # a fraction of a token per cycle
    p.cycle(4 * cost, depth=d, rate=cost - 1)              # refill until saturated
    p.cycle(3, req=1, depth=0, rate=top_r)                 # depth 0: never a token, at any rate
    p.cycle(top_d + 2, depth=top_d, rate=top_r)            # largest depth and rate: saturates past the carry
    p.cycle(req=1, depth=top_d, rate=top_r)
    p.cycle(depth=1, rate=0)                               # depth decreased below the level: clamp at once
    p.cycle(2, req=1, depth=1, rate=0)
    # One unit below the carry of the refill sum: a full bucket of the largest depth with a refill
    # that brings the sum to 2**level_width - 1 exactly.
    p.cycle(rst_n=0, depth=top_d)
    below = p.level_limit - 1 - p.bucket.tokens
    if 0 <= below <= top_r:
        p.cycle(depth=top_d, rate=below)
    p.cycle(req=1, depth=top_d, rate=cost)                 # one token per cycle: every request granted
    p.cycle(2, req=1, depth=top_d, rate=top_r)
    p.cycle(rst_n=0, depth=d)                              # a long window from a full bucket: reaches its bound
    p.cycle(4 * cost, req=1, depth=d, rate=3 if cost > 3 else 1)
    return p.finish()


def random_rows(parameters, seed, iterations):
    rng = random.Random(seed)
    p = Plan(parameters)
    depth, rate = rng.randrange(p.max_depth + 1), rng.randrange(p.max_rate + 1)
    p.cycle(rst_n=0, depth=depth)
    for _ in range(iterations):
        roll = rng.random()
        if roll < 0.01:
            p.cycle(rst_n=0, depth=depth)
            continue
        if roll < 0.06:
            depth = rng.randrange(p.max_depth + 1)
        elif roll < 0.12:
            rate = rng.choice((0, 1, p.cost - 1, p.cost, p.max_rate, rng.randrange(p.max_rate + 1)))
        p.cycle(req=int(rng.random() < 0.7), depth=depth, rate=rate)
    return p.finish()


def counts(rows):
    return dict(grants=sum(r[4] for r in rows))


def make_cases(args, parameters):
    base = boundary_rows(parameters)
    cases = [dict(id='boundaries', vectors=base, mutation=args.demo_bug, category='functional', expected_failure=None)]
    for seed in range(args.seed, args.seed + (3 if args.profile == 'nightly' else 1)):
        cases.append(dict(id=f'random-seed{seed}', vectors=random_rows(parameters, seed, args.iterations),
                          mutation=args.demo_bug, category='functional', expected_failure=None))
    for mutation in range(1, MUTANTS + 1):
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

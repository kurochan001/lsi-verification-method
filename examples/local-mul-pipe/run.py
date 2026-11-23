#!/usr/bin/env python3
"""Pipelined 8x8 multiplier: an independent product queue plus a k-induction proof."""
import importlib.util
from pathlib import Path
import random
import sys

HERE = Path(__file__).resolve().parent
NAME = 'local-mul-pipe'
TOP = 'mul_pipe_tb'
CONFIGS = {'s2': {'STAGES': 2}, 's3': {'STAGES': 3}}
ITERATIONS = {'smoke': 200, 'nightly': 1000}
SOURCES = [HERE / 'rtl/mul_pipe.sv', HERE / 'tb/mul_pipe_tb.sv']


class Plan:
    def __init__(self, stages):
        self.stages = stages
        self.rows = []
        self.reset()

    def reset(self):
        self.prods = []
        self.vs = []

    def step(self, rst=1, vin=0, a=0, b=0):
        if not rst:
            self.rows.append([0, 0, 0, 0, 0, 0])
            self.reset()
            return
        exp_v = self.vs[-self.stages] if len(self.vs) >= self.stages else 0
        exp_p = self.prods[-self.stages] if len(self.prods) >= self.stages else 0
        self.rows.append([1, vin, a & 0xff, b & 0xff, exp_v, exp_p])
        self.prods.append((a * b) & 0xffff)
        self.vs.append(vin)

    def mul(self, a, b):
        self.step(vin=1, a=a, b=b)

    def idle(self, count=1):
        for _ in range(count):
            self.step()

    def fixed(self):
        self.step(rst=0)
        self.mul(3, 7)
        self.idle(4)  # one product alone drains the whole pipeline
        self.mul(255, 255)
        self.mul(0, 255)  # back-to-back: zero and maximum share stages
        self.mul(255, 255)
        self.mul(1, 1)
        self.idle(5)
        self.mul(16, 1)  # the hi-lane boundary: 256, not 16*0
        self.mul(15, 255)  # lo-only: the shifted lane stays zero
        self.mul(7, 7)  # same operands
        self.idle(3)
        self.mul(2, 3)
        self.mul(200, 200)
        self.mul(2, 3)  # a later small product must not reuse stale lanes
        self.idle(6)
        self.step(rst=0)
        self.mul(9, 9)  # reset/recovery: the first product after reset
        self.idle(4)

    def random(self, rng, count):
        self.step(rst=0)
        for _ in range(count):
            self.step(vin=int(rng.randrange(3) != 0), a=rng.randrange(256), b=rng.randrange(256))
            if rng.randrange(40) == 0:
                self.step(rst=0)
        self.idle(6)


def vectors(seed, iterations, parameters, boundary=False):
    p = Plan(parameters['STAGES'])
    p.fixed()
    if not boundary:
        p.random(random.Random(seed), iterations)
    p.idle(2)
    return p.rows


def make_cases(args, parameters):
    base = vectors(args.seed, 0, parameters, True)
    cases = [dict(id='boundaries', vectors=base, mutation=args.demo_bug,
                  category='functional', expected_failure=None)]
    for seed in range(args.seed, args.seed + (3 if args.profile == 'nightly' else 1)):
        cases.append(dict(id=f'random-seed{seed}', vectors=vectors(seed, args.iterations, parameters),
                          mutation=args.demo_bug, category='functional', expected_failure=None))
    for mutation, label in ((1, 'MUL_DATA'), (2, 'MUL_TIME'), (3, 'MUL_DATA'), (4, 'MUL_DATA')):
        cases.append(dict(id=f'detect-mutation{mutation}', vectors=base, mutation=mutation,
                          category='mutation', expected_failure=label))
    for case in cases:
        case['counts'] = {'steps': len(case['vectors'])}
    return cases


if __name__ == '__main__':
    spec = importlib.util.spec_from_file_location('local_runner', HERE.parent / 'local-common/runner.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    sys.exit(module.main(sys.modules[__name__]))

#!/usr/bin/env python3
"""Dual-core lockstep comparator with fault containment and recovery."""
import importlib.util
from pathlib import Path
import random
import sys

HERE = Path(__file__).resolve().parent
NAME = 'local-lockstep-monitor'
TOP = 'lockstep_monitor_tb'
CONFIGS = {'bit0': {'FAULT_BIT': 0}, 'bit7': {'FAULT_BIT': 7}}
ITERATIONS = {'smoke': 120, 'nightly': 600}
SOURCES = [HERE / 'rtl/lockstep_monitor.sv', HERE / 'tb/lockstep_monitor_tb.sv']


class Plan:
    def __init__(self, fault_bit):
        self.fault_bit = fault_bit
        self.rows = []
        self.reset()

    def reset(self):
        self.acc0 = 0
        self.acc1 = 0
        self.result = 0
        self.error = 0
        self.safe = 0
        self.code = 0
        self.done = 0

    def apply(self, acc, op, operand):
        if op == 0:
            return (acc + operand) & 0xff
        if op == 1:
            return (acc ^ operand) & 0xff
        if op == 2:
            return operand & 0xff
        return acc

    def step(self, rst=1, op_valid=0, op=0, operand=0, fault=0, recover=0):
        op &= 3
        operand &= 0xff
        if not rst:
            self.rows.append([0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0])
            self.reset()
            return
        self.rows.append([1, op_valid, op, operand, fault, recover,
                          self.result, self.error, self.safe, self.code, self.done])
        self.done = 0
        if recover and self.error:
            self.acc1 = self.acc0
            self.error = 0
            self.safe = 0
            self.code = 0
            self.result = self.acc0
        elif op_valid and not self.safe:
            self.done = 1
            if op == 3:
                self.error = 1
                self.safe = 1
                self.code = 2
                self.result = 0
            else:
                next0 = self.apply(self.acc0, op, operand)
                next1 = self.apply(self.acc1, op, operand)
                if fault:
                    next1 ^= 1 << self.fault_bit
                if next0 != next1:
                    self.error = 1
                    self.safe = 1
                    self.code = 1
                    self.result = 0
                else:
                    self.acc0 = next0
                    self.acc1 = next1
                    self.result = next0

    def fixed(self):
        self.step(rst=0)
        self.step(op_valid=1, op=0, operand=5)
        self.step(op_valid=1, op=1, operand=3)
        self.step(op_valid=1, op=2, operand=0xaa)
        self.step(op_valid=1, op=0, operand=1, fault=1)
        self.step(op_valid=1, op=0, operand=1)
        self.step(recover=1)
        self.step(op_valid=1, op=0, operand=1)
        self.step(op_valid=1, op=0, operand=2, fault=1)
        self.step(recover=1, fault=1)
        self.step(op_valid=1, op=0, operand=3, fault=1)
        self.step(recover=1)
        self.step(op_valid=1, op=3)
        self.step(recover=1)
        self.step(rst=0)
        self.step(op_valid=1, op=0, operand=7)

    def random(self, rng, count):
        self.step(rst=0)
        for _ in range(count):
            if rng.randrange(150) == 0:
                self.step(rst=0)
            if self.safe and rng.randrange(2) == 0:
                self.step(recover=1, fault=int(rng.randrange(3) == 0))
                continue
            self.step(op_valid=int(rng.randrange(4) != 0), op=rng.randrange(4),
                      operand=rng.getrandbits(8), fault=int(rng.randrange(12) == 0),
                      recover=int(rng.randrange(80) == 0))


def vectors(seed, iterations, parameters, boundary=False):
    p = Plan(parameters['FAULT_BIT'])
    p.fixed()
    if not boundary:
        p.random(random.Random(seed), iterations)
    p.step()  # Check the effect of the final operation, including done/error.
    return p.rows


def make_cases(args, parameters):
    base = vectors(args.seed, 0, parameters, True)
    cases = [dict(id='boundaries', vectors=base, mutation=args.demo_bug,
                  category='functional', expected_failure=None)]
    for seed in range(args.seed, args.seed + (3 if args.profile == 'nightly' else 1)):
        cases.append(dict(id=f'random-seed{seed}', vectors=vectors(seed, args.iterations, parameters),
                          mutation=args.demo_bug, category='functional', expected_failure=None))
    for mutation, label in ((1, 'LOCKSTEP_COMPARE'), (2, 'LOCKSTEP_CONTAIN'),
                            (3, 'LOCKSTEP_RESULT'), (4, 'LOCKSTEP_ILLEGAL')):
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

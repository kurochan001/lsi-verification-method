#!/usr/bin/env python3
"""Exercise a parallel LBIST controller, output faults and signature aliasing."""
import importlib.util
from pathlib import Path
import random
import sys

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('lbist_model', HERE / 'model.py')
M = importlib.util.module_from_spec(spec)
spec.loader.exec_module(M)
NAME = 'local-lbist'
TOP = 'lbist_tb'
CONFIGS = {'patterns16': {'PATTERNS': 16}, 'patterns32': {'PATTERNS': 32}}
ITERATIONS = {'smoke': 4, 'nightly': 20}
SOURCES = [HERE / 'rtl/lbist_logic.sv', HERE / 'rtl/lbist.sv', HERE / 'tb/lbist_tb.sv']
EXTRA_INPUTS = [HERE / 'model.py']


class Plan:
    def __init__(self, patterns):
        self.patterns = patterns
        self.busy = self.done = self.failed = self.error = 0
        self.sig = self.prpg = self.count = self.expected = 0
        self.rows = []

    def cycle(self, reset=1, mode=1, start=0, seed=1, expected=0, normal=1,
              fault=None, flip=0, tag=0):
        stimulus = self.prpg & 15 if mode and self.busy else normal
        raw = M.logic(stimulus, fault) ^ flip
        normal_out = 0 if mode else M.logic(normal, fault)
        if not reset or not mode:
            self.busy = self.done = self.failed = self.error = 0
            self.sig = self.prpg = self.count = self.expected = 0
        elif self.busy:
            self.sig = M.compact(self.sig, raw)
            self.prpg = M.prpg_step(self.prpg)
            self.count += 1
            if self.count == self.patterns:
                self.busy = 0
                self.done = 1
                self.failed = int(self.sig != self.expected)
        elif start:
            self.sig = self.count = self.done = self.failed = 0
            self.error = int(seed == 0)
            self.prpg = seed
            if seed:
                self.busy = 1
                self.expected = expected
        site, value = fault if fault is not None else (0, 0)
        self.rows.append([reset, mode, start, seed, expected, normal,
                          int(fault is not None), site, value, flip, tag,
                          self.busy, self.done, self.failed, self.error,
                          self.sig, self.prpg, self.count, normal_out, raw, M.logic(stimulus)])

    def transaction(self, seed=1, fault=None, wrong=False, alias=False, changes=True):
        expected = M.signature(seed, self.patterns) ^ int(wrong)
        tag = 20 if alias else 10 + M.FAULTS.index(fault) if fault is not None else 1
        self.cycle(start=1, seed=seed, expected=expected, fault=fault, tag=tag)
        for index in range(self.patterns):
            flip = (1 if index == 0 else 2 if index == 1 else 0) if alias else 0
            self.cycle(start=int(changes and index == self.patterns // 2),
                       seed=0, expected=expected ^ 255, fault=fault, flip=flip, tag=tag)
        # Done and its result must remain available until the next accepted start.
        self.cycle(fault=fault, tag=tag)
        self.cycle(fault=fault, tag=tag)

    def counts(self):
        previous = False
        completed = alias_changes = 0
        detected = set()
        for row in self.rows:
            if previous and row[12]:
                completed += 1
                if row[6] and row[13]:
                    detected.add(row[7] * 2 + row[8])
            if previous and row[0] and row[1] and row[10] == 20:
                alias_changes += int(row[19] != row[20])
            previous = bool(row[11])
        return dict(steps=len(self.rows), completed=completed,
                    detected_faults=len(detected), alias_changes=alias_changes)


def vectors(seed, iterations, patterns, alias=False):
    plan = Plan(patterns)
    plan.cycle(reset=0)
    if alias:
        plan.transaction(alias=True)
    else:
        plan.cycle(mode=0, start=1)  # Cannot enter test from functional mode.
        plan.cycle(start=1, seed=0)
        plan.cycle()
        for initial in (1, 0x5a, 0xa7):
            plan.transaction(seed=initial)
        plan.transaction(wrong=True)
        for fault in M.FAULTS:
            plan.transaction(fault=fault)
        for reset_abort in (True, False):
            plan.cycle(start=1, seed=1, expected=M.signature(1, patterns))
            plan.cycle()
            plan.cycle(reset=int(not reset_abort), mode=int(reset_abort))
            plan.cycle(mode=0, normal=7)
            plan.transaction(seed=0x5a)
        rng = random.Random(seed)
        for _ in range(iterations):
            plan.transaction(seed=rng.randrange(1, 256), wrong=bool(rng.randrange(2)))
    plan.cycle(mode=0, normal=5)
    return plan


def make_cases(args, parameters):
    patterns = parameters['PATTERNS']
    baseline = vectors(args.seed, 0, patterns)
    cases = [dict(id='boundaries', plan=baseline, mutation=args.demo_bug,
                  expected_failure=None, category='functional')]
    for seed in range(args.seed, args.seed + (3 if args.profile == 'nightly' else 1)):
        cases.append(dict(id=f'random-seed{seed}', plan=vectors(seed, args.iterations, patterns),
                          mutation=args.demo_bug, expected_failure=None, category='functional'))
    cases.append(dict(id='alias-diagnostic', plan=vectors(args.seed, 0, patterns, alias=True),
                      mutation=args.demo_bug, expected_failure=None, category='diagnostic'))
    for mutation, label in ((1, 'LBIST_SEQUENCE'), (2, 'LBIST_SIGNATURE'),
                            (3, 'LBIST_CONTROL'), (4, 'LBIST_RESULT')):
        cases.append(dict(id=f'detect-mutation{mutation}', plan=baseline, mutation=mutation,
                          expected_failure=label, category='mutation'))
    for case in cases:
        plan = case.pop('plan')
        case.update(vectors=plan.rows, counts=plan.counts())
    return cases


if __name__ == '__main__':
    spec = importlib.util.spec_from_file_location('runner', HERE.parent / 'local-common/runner.py')
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)
    sys.exit(runner.main(sys.modules[__name__]))

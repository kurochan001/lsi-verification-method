#!/usr/bin/env python3
"""Generate lock, counting-fence and rate-window transactions with expected pin values."""
import importlib.util
from pathlib import Path
import random
import sys

HERE = Path(__file__).resolve().parent
NAME = 'local-hw-semaphore'
TOP = 'semaphore_tb'
CONFIGS = {'w8k2': {'WIN': 8, 'KMAX': 2}, 'w16k3': {'WIN': 16, 'KMAX': 3}}
ITERATIONS = {'smoke': 200, 'nightly': 1000}
SOURCES = [HERE / 'rtl/hw_semaphore.sv', HERE / 'tb/semaphore_tb.sv']


class Plan:
    def __init__(self, win, limit):
        self.win, self.limit = win, limit
        self.rows = []
        self.reset()

    def reset(self):
        self.owned = set()
        self.counts = [0, 0]
        self.deadline = None
        self.accepted = 0
        self.now = 0

    def step(self, rst=1, claim=0, release=0, slot=0, inc=0, rearm=0, events=0):
        grant = passed = suppressed = 0
        if not rst:
            self.reset()
        else:
            if release:
                self.owned.discard(slot)
            elif claim and slot not in self.owned:
                self.owned.add(slot)
                grant = 1
            for lane in range(2):
                if rearm & (1 << lane):
                    self.counts[lane] = 0
                elif inc & (1 << lane):
                    self.counts[lane] = min(255, self.counts[lane] + 1)
            if self.deadline == self.now:
                suppressed = events
                self.deadline = None
            else:
                for lane in range(2):
                    if events & (1 << lane):
                        passed |= 1 << lane
                        if self.deadline is None:
                            self.deadline = self.now + self.win
                            self.accepted = 0
                        self.accepted += 1
                        if self.accepted == self.limit:
                            self.deadline = None
        owned = sum(1 << slot for slot in self.owned)
        done = sum((value == 255) << lane for lane, value in enumerate(self.counts))
        counts = self.counts[0] + (self.counts[1] << 8)
        self.rows.append([rst, claim, release, slot, inc, rearm, events, owned, grant,
                          counts, done, passed, suppressed, int(self.deadline is not None)])
        self.now += 1

    def fixed(self):
        self.step(rst=0)
        for slot in range(4):
            self.step(claim=1, slot=slot)
            self.step(claim=1, slot=slot)
            self.step(release=1, slot=slot)
            self.step(claim=1, slot=slot)
        for _ in range(257):
            self.step(inc=3)
        self.step(rearm=1, inc=3)
        self.step(rearm=2, inc=1)
        self.step(events=1)
        for _ in range(self.win - 1):
            self.step()
        self.step(events=3)
        self.step(events=1)
        for _ in range(self.limit - 2):
            self.step(events=1)
        self.step(events=3)  # lane 0 closes the window; lane 1 can open the next
        self.step(rst=0)
        for _ in range(self.limit):
            self.step(events=1)  # close on the last accepted event, even without a second lane
        self.step(claim=1)


def vectors(seed, iterations, parameters, boundary=False):
    plan = Plan(parameters['WIN'], parameters['KMAX'])
    plan.fixed()
    if not boundary:
        rng = random.Random(seed)
        for _ in range(iterations):
            plan.step(int(rng.randrange(80) != 0), rng.randrange(2), rng.randrange(2),
                      rng.randrange(4), rng.randrange(4), rng.randrange(4), rng.randrange(4))
    return plan.rows


def make_cases(args, parameters):
    base = vectors(args.seed, 0, parameters, True)
    cases = [dict(id='boundaries', vectors=base, mutation=args.demo_bug,
                  category='functional', expected_failure=None)]
    for seed in range(args.seed, args.seed + (3 if args.profile == 'nightly' else 1)):
        cases.append(dict(id=f'random-seed{seed}', vectors=vectors(seed, args.iterations, parameters),
                          mutation=args.demo_bug, category='functional', expected_failure=None))
    for mutation, label in ((1, 'SEM_STATE'), (2, 'FENCE'), (3, 'IRQ_LIMIT'), (4, 'IRQ_LIMIT')):
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

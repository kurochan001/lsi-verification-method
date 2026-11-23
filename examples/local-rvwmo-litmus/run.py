#!/usr/bin/env python3
"""Store-buffer litmus harness: a Python scheduler model plus a fenced-unreachable proof."""
import importlib.util
from pathlib import Path
import random
import sys

HERE = Path(__file__).resolve().parent
NAME = 'local-rvwmo-litmus'
TOP = 'litmus_tb'
CONFIGS = {'buf2': {'DRAIN': 2}, 'buf3': {'DRAIN': 3}}
ITERATIONS = {'smoke': 200, 'nightly': 1000}
SOURCES = [HERE / 'rtl/litmus.sv', HERE / 'tb/litmus_tb.sv']


class Plan:
    """Rows carry the pre-clock-edge state, so a load samples values the
    current edge has not published yet (same race rule as the RTL). A FENCE
    pulse that lands on the edge where the buffer drains retires immediately."""

    def __init__(self, drain):
        self.drain = drain
        self.rows = []
        self.check = False  # rows of fenced property rounds carry check=1
        self.reset()

    def reset(self):
        self.cycle = 0
        self.publish_at = [None, None]
        self.memory = [0, 0]
        self.fenced = [False, False]
        self.waiting = [False, False]
        self.loads = [None, None]

    def step(self, rst=1, i0=0, i1=0, rd0=0, rd1=0, f0=0, f1=0, check=None):
        if not rst:
            self.reset()
            self.check = False
        elif check is not None:
            self.check = check

        pending = [deadline is not None for deadline in self.publish_at]
        self.rows.append([rst, i0, i1, rd0, rd1, f0, f1, *self.memory, *self.memory,
                          *pending, *self.waiting, *(v is not None for v in self.loads),
                          *(v or 0 for v in self.loads), self.check])
        if not rst:
            return
        # All reads sample the same memory snapshot before either store publishes.
        before = self.memory.copy()
        for h, (issue, read, fence) in enumerate(((i0, rd0, f0), (i1, rd1, f1))):
            if read and self.loads[h] is None and not self.waiting[h]:
                self.loads[h] = before[1 - h]
            if fence and not self.fenced[h]:
                self.fenced[h] = True
                self.waiting[h] = pending[h]
            if self.publish_at[h] == self.cycle:
                self.memory[h] = 1
                self.waiting[h] = False
                self.publish_at[h] = None
            elif issue and not pending[h] and not before[h]:
                self.publish_at[h] = self.cycle + self.drain
        self.cycle += 1

    def litmus(self, fence=1, hold=6, stagger=0, late_loads=0):
        """One litmus round. Loads start one cycle after any FENCE pulse so the
        fence is definitely armed; rounds with a fence carry check=1."""
        self.step(rst=0)
        if late_loads:
            self.step(i0=1, i1=1)
            for _ in range(late_loads):
                self.step()  # both stores drain while no load or fence arrives
            self.step(f0=fence, f1=fence, check=bool(fence))  # retires on empty buffers
            for _ in range(4):
                self.step(rd0=1, rd1=1, check=bool(fence))
            return
        if stagger == 1:
            self.step(i1=1)
            self.step(i0=1)
        elif stagger == 2:
            self.step(i0=1)  # hart 0 early, hart 1 late
            self.step()
            self.step()
            self.step(i1=1)
        else:
            self.step(i0=1, i1=1)
        self.step(f0=fence, f1=fence, check=bool(fence))  # a cycle after the last store
        for _ in range(hold):
            self.step(rd0=1, rd1=1, check=bool(fence))

    def reset_mid(self):
        self.step(rst=0)
        self.step(i0=1, i1=1)
        self.step(f0=1, f1=1, check=True)  # stores still buffered when the run restarts
        self.litmus()  # reset/recovery: the same program runs again from reset

    def fixed(self):
        self.litmus(fence=1)
        self.step()
        self.litmus(fence=1, stagger=1)
        self.step()
        self.litmus(fence=1, stagger=2)
        self.step()
        self.litmus(fence=1, late_loads=4)
        self.step()
        self.litmus(fence=0)
        self.step()
        self.litmus(fence=0, stagger=1)
        self.step()
        self.litmus(fence=0, stagger=2)
        self.reset_mid()
        self.idle(3)

    def idle(self, count=1):
        for _ in range(count):
            self.step()

    def random(self, rng, count):
        self.step(rst=0)
        for _ in range(count):
            self.step(i0=int(rng.randrange(10) < 4), i1=int(rng.randrange(10) < 4),
                      rd0=int(rng.randrange(10) < 5), rd1=int(rng.randrange(10) < 5),
                      f0=int(rng.randrange(10) == 0), f1=int(rng.randrange(10) == 0))
            if rng.randrange(25) == 0:
                self.step(rst=0)
        self.idle(6)

    def outcome(self):
        return tuple(v is not None for v in self.loads) + tuple(v or 0 for v in self.loads)


def vectors(seed, iterations, parameters, boundary=False):
    p = Plan(parameters['DRAIN'])
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
    for mutation, label in ((1, 'MEM_ORD'), (2, 'MEM_DATA'), (3, 'MEM_DATA'), (4, 'MEM_DATA')):
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

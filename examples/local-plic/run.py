#!/usr/bin/env python3
"""PLIC-lite interrupt controller: priorities, threshold, claim/complete and repending."""
import importlib.util
from pathlib import Path
import random
import sys

HERE = Path(__file__).resolve().parent
NAME = 'local-plic'
TOP = 'plic_tb'
CONFIGS = {'n4': {'NS': 4}, 'n6': {'NS': 6}}
ITERATIONS = {'smoke': 200, 'nightly': 1000}
SOURCES = [HERE / 'rtl/plic.sv', HERE / 'tb/plic_tb.sv']


class Plan:
    def __init__(self, ns):
        self.ns = ns
        self.rows = []
        self.reset()

    def reset(self):
        self.pri = [0] * 8
        self.thresh = 0
        self.pending = 0
        self.inservice = 0

    def pack(self):
        value = 0
        for s in range(8):
            value |= self.pri[s] << (3 * s)
        return value

    def candidate(self):
        best, best_pri = 0, 0
        for s in range(self.ns):
            if (self.pending >> s) & 1 and not (self.inservice >> s) & 1 and \
                    self.pri[s] > self.thresh and self.pri[s] > best_pri:
                best, best_pri = s + 1, self.pri[s]
        return best

    def step(self, rst=1, psel=0, pwrite=0, reg=0, wdata=0, set_mask=0):
        if not rst:
            self.rows.append([0, 0, 0, 0, 0, 0, 0, 0, 0, 0])
            self.reset()
            return
        pick = self.candidate()
        claim_read = bool(psel and not pwrite and reg == 2)
        rdata = 0
        if psel:
            rdata = {0: self.pack(), 1: self.thresh, 2: (0 if pwrite else pick)}.get(reg, 0)
        self.rows.append([1, psel, pwrite, reg, wdata, set_mask & 0xff, rdata,
                          int(pick != 0), self.pending, self.inservice])
        set_bits = set_mask & ((1 << self.ns) - 1)
        next_pending = self.pending
        next_inservice = self.inservice
        if claim_read and pick:
            next_pending &= ~(1 << (pick - 1))
            next_inservice |= 1 << (pick - 1)
        next_pending |= set_bits
        if psel and pwrite:
            if reg == 0:
                for s in range(self.ns):
                    self.pri[s] = (wdata >> (3 * s)) & 7
            elif reg == 1:
                self.thresh = wdata & 7
            elif reg == 3:
                cid = wdata
                if 1 <= cid <= self.ns and (self.inservice >> (cid - 1)) & 1:
                    next_inservice &= ~(1 << (cid - 1))
        self.pending, self.inservice = next_pending, next_inservice

    def write(self, reg, value):
        self.step(psel=1, pwrite=1, reg=reg, wdata=value)

    def read(self, reg):
        self.step(psel=1, pwrite=0, reg=reg)

    def fire(self, source):
        self.step(set_mask=1 << source)

    def fixed(self):
        self.step(rst=0)
        self.write(0, (1 << 9) | (3 << 6) | (7 << 3) | 7)  # 7,7,3,1 for sources 0..3
        self.read(0)  # priority/pack-read
        self.fire(0)  # state/pending-set
        self.read(2)  # claim source 0
        self.write(3, 0x11)  # high bits must not alias an active ID
        self.fire(2)
        self.read(2)  # claim source 2 while source 0 is still in service
        self.write(3, 1)  # complete releases source 0
        for ignored in (1, 0, 7):
            self.write(3, ignored)  # not in service, ID 0 and out of range are ignored
        self.write(0, (1 << 9) | (3 << 6) | (5 << 3) | 5)  # sources 0 and 1 tie at 5
        self.fire(0)
        self.fire(1)
        self.read(2)  # the tie gives the lower source ID
        self.write(3, 1)
        self.read(2)  # claim source 1
        self.write(3, 2)
        self.write(3, 3)  # release source 2 so a later fire becomes a real candidate
        self.write(1, 3)  # priority equal to the threshold is not a candidate
        self.fire(2)
        self.read(2)  # claim denied while source 2 stays blocked
        self.write(1, 2)
        self.read(2)  # now source 2 passes
        self.write(3, 3)
        self.write(1, 7)
        self.read(2)  # threshold 7 blocks everything
        self.write(1, 0)
        self.write(0, (3 << 6) | (5 << 3) | 5)  # priority 0 for source 3: never a candidate
        self.fire(3)
        self.read(2)  # pending but never claimable
        self.fire(0)
        self.step(psel=1, pwrite=0, reg=2, set_mask=1)  # a re-fire during claim survives
        self.write(3, 1)  # completing releases the re-pended source
        self.read(2)  # the re-pended source is claimable again
        self.write(3, 1)
        self.fire(4)
        self.fire(5)  # sources 4 and 5 only exist when NS=6
        self.read(2)
        self.step(rst=0)
        self.read(0)  # reset/recovery: priorities read back as 0
        self.write(0, (4 << 6) | (2 << 3) | 1)
        self.read(0)

    def random(self, rng, count):
        self.step(rst=0)
        for _ in range(count):
            roll = rng.randrange(100)
            if roll == 0:
                self.step(rst=0)
            elif roll < 25:
                self.step(set_mask=rng.randrange(64))
            elif roll < 45:
                self.read(2)
            elif roll < 60:
                self.write(3, rng.randrange(8))
            elif roll < 72:
                self.write(0, sum(rng.randrange(8) << (3 * s) for s in range(6)))
            elif roll < 82:
                self.write(1, rng.randrange(8))
            elif roll < 88:
                self.read(rng.randrange(4))
            else:
                self.step()


def vectors(seed, iterations, parameters, boundary=False):
    p = Plan(parameters['NS'])
    p.fixed()
    if not boundary:
        p.random(random.Random(seed), iterations)
    for reg in (0, 1, 2, 3):
        p.read(reg)
    p.step()
    return p.rows


def make_cases(args, parameters):
    base = vectors(args.seed, 0, parameters, True)
    cases = [dict(id='boundaries', vectors=base, mutation=args.demo_bug,
                  category='functional', expected_failure=None)]
    for seed in range(args.seed, args.seed + (3 if args.profile == 'nightly' else 1)):
        cases.append(dict(id=f'random-seed{seed}', vectors=vectors(seed, args.iterations, parameters),
                          mutation=args.demo_bug, category='functional', expected_failure=None))
    for mutation, label in ((1, 'PLIC_IRQ'), (2, 'PLIC_STATE'), (3, 'PLIC_CLAIM'), (4, 'PLIC_STATE')):
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

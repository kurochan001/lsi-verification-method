#!/usr/bin/env python3
"""RTC with alarm W1C, slew rate adjust and two-flop capture."""
import importlib.util
from pathlib import Path
import random
import sys

HERE = Path(__file__).resolve().parent
NAME = 'local-rtc'
TOP = 'rtc_tb'
CONFIGS = {'div4': {'DIV': 4}, 'div9': {'DIV': 9}}
ITERATIONS = {'smoke': 200, 'nightly': 1000}
SOURCES = [HERE / 'rtl/rtc.sv', HERE / 'tb/rtc_tb.sv']


class Plan:
    def __init__(self, div):
        self.div = div
        self.rows = []
        self.reset()

    def reset(self):
        self.sub = 0
        self.sec = 0
        self.ctrl = 0  # [6:4] ADJ (signed), [1] slew, [0] en
        self.alarm = 0
        self.cap_sec = 0
        self.cap_sub = 0
        self.irq = 0
        self.cap_meta = 0
        self.cap_s = 0
        self.cap_p = 0

    @property
    def en(self):
        return self.ctrl & 1

    @property
    def slew(self):
        return (self.ctrl >> 1) & 1

    @property
    def set(self):
        return (self.ctrl >> 2) & 1

    @property
    def adj(self):
        a = (self.ctrl >> 4) & 7
        return a - 8 if a & 4 else a

    def inc(self):
        return max(0, 1 + self.adj) if self.slew else 1  # clamp 0..4: never rewinds

    def step(self, rst=1, wr=0, ridx=0, wdata=0, cap=0):
        if not rst:
            self.rows.append([0] * 10)
            self.reset()
            return
        rdata = 0 if wr else {0: self.ctrl,
                              1: ((self.irq & 1) << 7) | (self.alarm >> 1),
                              2: 0, 3: self.cap_sec}[ridx]
        self.rows.append([1, wr, ridx, wdata, cap, self.sec, self.sub, self.irq, rdata, self.cap_sub])
        # --- one posedge ---
        tick = bool(self.en) and self.sub == self.div - 1
        fire = bool(self.cap_s) and not self.cap_p
        newmatch = tick and self.alarm != 0 and (self.sec & 0xFF) == self.alarm
        w1c = bool(wr) and ridx == 1 and ((wdata >> 1) & 1)
        load = bool(wr) and ridx == 2 and bool(self.set)
        if fire:  # a snapshot of the pre-edge counter state; register writes never touch it
            self.cap_sec = self.sec & 0xFF
            self.cap_sub = self.sub
        # irq: a new match wins over a same-cycle W1C clear
        if newmatch:
            self.irq = 1
        elif w1c:
            self.irq = 0
        if tick and not self.set:
            self.sec = (self.sec + self.inc()) & 0xFFFF
        if self.en:
            self.sub = 0 if tick else self.sub + 1
        if wr:
            if ridx == 0:
                self.ctrl = wdata & 0x7F
            elif ridx == 1:
                self.alarm = wdata & 0xFF
            elif load:
                self.sec = wdata & 0xFF
                self.sub = 0
        self.cap_p = self.cap_s
        self.cap_s = self.cap_meta
        self.cap_meta = cap

    def write(self, ridx, value):
        self.step(wr=1, ridx=ridx, wdata=value)

    def read(self, ridx):
        self.step(wr=0, ridx=ridx)

    def set_ctrl(self, value):
        self.write(0, value)

    def jump(self, value):
        self.write(2, value)

    def wait(self, n, **kw):
        for _ in range(n):
            self.step(**kw)

    def until_sub(self, n=0):
        while self.sub != n:
            self.step()

    def until_sec(self, target, limit=600):
        while self.sec != target and limit > 0:
            self.step()
            limit -= 1
        if self.sec != target:
            raise ValueError(f"unreached second {target}")

    def fixed(self):
        self.step(rst=0)
        self.wait(2)
        self.set_ctrl(0x01)  # enable (reset/recovery)
        self.wait(self.div)
        self.read(0)  # reg/readback
        self.read(1)
        self.set_ctrl(0x05)  # set (jump) on
        self.jump(0xF8)  # time/set-load
        self.wait(self.div - 1)
        self.until_sub(self.div - 1)  # the frozen tick lands on this row
        self.step()  # time/set-freeze: seconds held while set is 1
        self.set_ctrl(0x01)  # leave jump-set
        self.wait(self.div + 2)
        self.wait(4)  # a capture pulse while counting
        self.step(cap=1)
        self.wait(4)
        self.read(3)  # cap/readback
        self.jump(0x00)  # still in jump-set? no (set off): ignored - proves the gate
        self.read(3)
        # alarm: match one cycle of seconds later, pending, read, W1C
        self.set_ctrl(0x01)
        self.set_ctrl(0x05)
        self.jump(0x03)
        self.set_ctrl(0x01)
        self.write(1, 0x04)
        self.until_sec(4)
        self.until_sub(self.div - 1)
        self.step()  # compare against 4 on a prescaler wrap
        self.step()
        self.read(1)  # bit7 mirrors irq
        self.wait(2)
        self.write(1, 0x02)  # W1C: write 1 clears (irq/w1c-clear)
        self.read(1)
        # slew: ADJ=+2 then ADJ=+3, then ADJ=-1 (pause) and ADJ=-2 (hold, never rewind)
        self.set_ctrl(0x23)  # slew, ADJ=2
        self.until_sub(0)
        self.wait(self.div, cap=1)  # capture while the rate runs up (cap/phase-freeze)
        self.wait(3 * self.div)
        self.set_ctrl(0x33)  # slew, ADJ=3 -> the maximum rate of +4/s
        self.wait(2 * self.div)
        self.set_ctrl(0x73)  # ADJ=-1 -> zero increment
        self.wait(2 * self.div)
        self.set_ctrl(0x63)  # ADJ=-2 -> still zero (mutation 3 rewinds here)
        self.wait(2 * self.div)
        self.set_ctrl(0x01)  # slew off
        self.wait(self.div)
        # the W1C-vs-new-match race: park at the alarm value, then clear exactly on a tick
        self.write(1, 0x2A)
        self.set_ctrl(0x05)
        self.jump(0x2A)
        self.until_sub(0)
        self.wait(self.div - 1)
        self.until_sub(self.div - 1)
        self.write(1, 0x02)  # W1C on the matching tick: the new match wins
        self.wait(2)
        self.read(1)  # irq is still pending (irq/race-win)
        self.write(1, 0x02)  # a quiet W1C finally clears it
        self.read(1)
        # reset/recovery and a short run at the base rate
        self.step(rst=0)
        self.wait(2)
        self.set_ctrl(0x01)
        self.wait(2 * self.div + 1)
        self.read(0)

    def random(self, rng, count):
        self.step(rst=0)
        self.set_ctrl(0x01)
        for _ in range(count):
            roll = rng.randrange(100)
            if roll == 0:
                self.step(rst=0)
                self.set_ctrl(0x01)
            elif roll < 55:
                self.wait(rng.randrange(1, 3 * self.div))
            elif roll < 68:
                self.step(cap=1)
                self.wait(rng.randrange(1, 3))
            elif roll < 82:
                self.set_ctrl(rng.randrange(0x80) | 0x01)
            elif roll < 89:
                self.write(1, rng.randrange(256))
            elif roll < 93:
                self.jump(rng.randrange(256))
            else:
                self.read(rng.randrange(4))


def vectors(seed, iterations, parameters, boundary=False):
    p = Plan(parameters['DIV'])
    p.fixed()
    if not boundary:
        p.random(random.Random(seed), iterations)
    p.wait(2)
    p.step(rst=0)
    return p.rows


def make_cases(args, parameters):
    base = vectors(args.seed, 0, parameters, True)
    cases = [dict(id='boundaries', vectors=base, mutation=args.demo_bug,
                  category='functional', expected_failure=None)]
    for seed in range(args.seed, args.seed + (3 if args.profile == 'nightly' else 1)):
        cases.append(dict(id=f'random-seed{seed}', vectors=vectors(seed, args.iterations, parameters),
                          mutation=args.demo_bug, category='functional', expected_failure=None))
    for mutation, label in ((1, 'RTC_TIME'), (2, 'RTC_IRQ'), (3, 'RTC_ADJ'), (4, 'RTC_IRQ')):
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

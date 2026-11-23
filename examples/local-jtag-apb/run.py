#!/usr/bin/env python3
"""Drive serial scans and predict APB transactions from whole command words."""
import importlib.util
from pathlib import Path
import random
import sys

HERE = Path(__file__).resolve().parent
NAME = 'local-jtag-apb'
TOP = 'jtag_apb_tb'
CONFIGS = {'w0': {'WAIT': 0}, 'w2': {'WAIT': 2}}
ITERATIONS = {'smoke': 20, 'nightly': 80}
SOURCES = [HERE / 'rtl/jtag_apb.sv', HERE / 'tb/jtag_apb_tb.sv']
# Destination for TMS=0,1, indexed by the sixteen TAP states.
NEXT = ((1,0),(1,2),(3,9),(4,5),(4,5),(6,8),(6,7),(4,8),
        (1,2),(10,0),(11,12),(11,12),(13,15),(13,14),(11,15),(1,2))
IDCODE = 0xB7071149


class Plan:
    def __init__(self, wait):
        self.wait = wait
        self.rows = []
        self.reset()

    def reset(self):
        self.state, self.ir = 0, 1
        self.ram = [0] * 8
        self.last_read = self.err = self.phase = self.delay = 0
        self.addr = self.data = self.write = 0

    def tick(self, tms=0, tdi=0, rst=1, tdo=0, update_ir=None, command=None, hold=0):
        if not rst:
            self.reset()
        else:
            if self.phase == 1:
                self.phase = 2
            elif self.phase == 2:
                if self.delay:
                    self.delay -= 1
                elif not hold:
                    self.phase = 0
                    if self.addr & 0x80:
                        self.err = 1
                    elif self.write:
                        self.ram[self.addr & 7] = self.data
                    else:
                        self.last_read = self.ram[self.addr & 7]
                        if self.last_read & 0x80:
                            self.err = 0
            if command is not None and command & 2:
                self.addr, self.data = command >> 24, (command >> 16) & 255
                self.write = (command >> 2) & 1
                self.phase, self.delay = 1, self.wait
            if self.state == 0 or NEXT[self.state][tms] == 0:
                self.ir = 1
            if update_ir is not None:
                self.ir = update_ir
            self.state = NEXT[self.state][tms]
        self.rows.append([rst,tms,tdi,hold,tdo,self.state,self.ir,self.phase,
                          self.write,self.addr,self.data,self.err])

    def scan(self, value, bits, expected, instruction=False):
        assert self.state == 1
        self.tick(1)
        if instruction:
            self.tick(1)
        self.tick(0)
        self.tick(0)
        for bit in range(bits):
            self.tick(int(bit == bits-1), (value >> bit) & 1, tdo=(expected >> bit) & 1)
        self.tick(1)
        self.tick(update_ir=value if instruction else None,
                  command=value if not instruction and self.ir == 3 else None)

    def transaction(self, addr, data=0, write=0, extra=0):
        word = (addr << 24) | (data << 16) | (write << 2) | 2
        self.scan(word, 32, (self.last_read << 16) | self.err)
        self.tick()
        for cycle in range(self.wait + extra + 1):
            self.tick(hold=int(cycle < self.wait + extra))

    def fixed(self):
        self.tick(rst=0)
        self.tick()
        self.scan(0, 32, IDCODE)
        self.scan(2, 2, 1, instruction=True)
        self.scan(5, 4, (5 << 1) & 15)
        for _ in range(6):
            self.tick(1)
        self.tick()
        self.scan(3, 2, 1, instruction=True)
        self.transaction(3, 0xA7, write=1, extra=1)
        self.transaction(5)
        self.transaction(0x83, write=1)
        self.transaction(5)  # successful read with bit 7 clear preserves error
        self.transaction(3)  # reading A7 clears sticky error
        self.scan(0, 32, self.last_read << 16)


def vectors(seed, iterations, parameters, boundary=False):
    plan = Plan(parameters['WAIT'])
    plan.fixed()
    if not boundary:
        rng = random.Random(seed)
        for _ in range(iterations):
            plan.transaction(rng.choice([0,0,0,128]) | rng.randrange(8), rng.randrange(256),
                             rng.randrange(2), rng.randrange(3))
        plan.scan(0, 32, (plan.last_read << 16) | plan.err)
    return plan.rows


def make_cases(args, parameters):
    base = vectors(args.seed, 0, parameters, True)
    cases = [dict(id='boundaries', vectors=base, mutation=args.demo_bug,
                  category='functional', expected_failure=None)]
    for seed in range(args.seed, args.seed + (3 if args.profile == 'nightly' else 1)):
        cases.append(dict(id=f'random-seed{seed}', vectors=vectors(seed, args.iterations, parameters),
                          mutation=args.demo_bug, category='functional', expected_failure=None))
    for mutation, label in ((1, 'JAPB_TAP'), (2, 'JAPB_ERR'), (3, 'JAPB_ERR'), (4, 'JAPB_DATA')):
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

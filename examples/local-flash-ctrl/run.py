#!/usr/bin/env python3
"""Check SPI frames, NOR operations, XIP and bounded completion."""
import importlib.util
from pathlib import Path
import random
import sys

HERE = Path(__file__).resolve().parent
NAME = 'local-flash-ctrl'
TOP = 'flash_tb'
CONFIGS = {'div1': {'DIV': 1}, 'div4': {'DIV': 4}}
ITERATIONS = {'smoke': 20, 'nightly': 100}
SOURCES = [HERE / 'rtl/flash_ctrl.sv', HERE / 'rtl/flash_model.sv', HERE / 'tb/flash_tb.sv']
READ, WREN, PROGRAM, SECTOR, ERASE, CLEAR = 0x03, 0x06, 0xA0, 0x32, 0xD8, 0xC7
COMMANDS = {READ, WREN, PROGRAM, SECTOR, ERASE, CLEAR}


class Plan:
    """Command-level oracle. The device is a byte array and serial frames are byte strings."""
    def __init__(self):
        self.rows = []
        self.reset()

    def reset(self, abort=False):
        self.mem = bytearray(i ^ 0xa0 for i in range(16))
        self.wel = self.fault = self.wip = False
        self.last = 0
        self.rows.append([3 if abort else 0] + [0] * 11)

    def xip(self, addr):
        self.rows.append([2, ERASE, addr, 0, 0, 0, 0, 0, self.byte(addr), self.wel, 0, self.wip])

    def byte(self, addr):
        return self.mem[addr] if addr < 16 else 0xff

    def command(self, op, addr=0, data=0, stuck=False):
        frame = b''
        polls = 0
        modifying = op in (PROGRAM, ERASE, SECTOR)
        error = op not in COMMANDS or (modifying and not self.wel)
        if not error:
            payload = {READ: [addr, 0, 0], PROGRAM: [addr, data], SECTOR: [addr]}.get(op, [])
            frame = bytes([op, *payload])
            self.wel = op == WREN
            if op == READ:
                self.last = self.byte(addr)
                error = self.wip = self.fault
            elif op == CLEAR:
                polls = 4 if self.fault else 0
                self.fault = False
            elif op == PROGRAM:
                if addr >= 16 or data & ~self.byte(addr):
                    self.fault = True
                elif not self.fault:
                    self.mem[addr] = data
                polls = 4
            elif op == SECTOR:
                if addr >= 16:
                    self.fault = True
                elif not self.fault:
                    base = addr & ~3
                    self.mem[base:base+4] = b'\xff' * 4
                polls = 6
            elif op == ERASE:
                if not self.fault:
                    self.mem[:] = b'\xff' * 16
                polls = 6
            if modifying or op == CLEAR:
                if self.fault or stuck:
                    polls, error = 7, True
                self.wip = error
        self.rows.append([1, op, addr, data, stuck, len(frame), int.from_bytes(frame, 'big'),
                          error, self.last, self.wel, polls, self.wip])

    def fixed(self):
        self.xip(0)
        self.command(0x9f)
        self.command(PROGRAM, 2, 0x02)
        self.command(WREN)
        self.command(PROGRAM, 2, 0x82)
        self.command(READ, 2)
        self.xip(2)
        self.command(WREN)
        self.command(SECTOR, 5)
        for addr in range(16):
            self.xip(addr)
        self.command(WREN)
        self.command(PROGRAM, 2, 0xff)  # would restore a cleared bit
        self.command(READ, 2)
        self.command(CLEAR)
        self.command(READ, 2)
        self.command(WREN)
        self.command(ERASE)
        for addr in range(16):
            self.command(READ, addr)
        self.command(WREN)
        self.command(PROGRAM, 16, 0)
        self.xip(16)
        self.command(CLEAR)
        self.command(WREN)
        self.command(PROGRAM, 15, 0x9a, stuck=True)
        self.command(READ, 15)
        self.reset(abort=True)
        self.command(READ, 15)

    def random(self, rng, count):
        for _ in range(count):
            addr, data = rng.randrange(18), rng.randrange(256)
            op = rng.choice([READ, PROGRAM, SECTOR, ERASE, CLEAR, 0x7f])
            if op in (PROGRAM, SECTOR, ERASE) and rng.randrange(4):
                self.command(WREN)
            self.command(op, addr, data)
            self.xip(addr)


def make_cases(args, parameters):
    boundary = Plan()
    boundary.fixed()
    cases = [dict(id='boundaries', vectors=boundary.rows, mutation=args.demo_bug,
                  category='functional', expected_failure=None)]
    seeds = 3 if args.profile == 'nightly' else 1
    for seed in range(args.seed, args.seed + seeds):
        p = Plan()
        p.fixed()
        p.random(random.Random(seed), args.iterations)
        cases.append(dict(id=f'random-seed{seed}', vectors=p.rows, mutation=args.demo_bug,
                          category='functional', expected_failure=None))
    for mutant, label in enumerate(['FLASH_CTRL', 'FLASH_CTRL', 'FLASH_DATA', 'FLASH_STATE'], 1):
        cases.append(dict(id=f'detect-mutation{mutant}', vectors=boundary.rows, mutation=mutant,
                          category='mutation', expected_failure=label))
    for case in cases:
        case['counts'] = {'steps': len(case['vectors'])}
    return cases


if __name__ == '__main__':
    spec = importlib.util.spec_from_file_location('local_runner', HERE.parent / 'local-common/runner.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    sys.exit(module.main(sys.modules[__name__]))

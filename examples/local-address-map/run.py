#!/usr/bin/env python3
"""Address decode, byte strobes and interrupt-map example with an independent register model."""
import importlib.util
from pathlib import Path
import random
import sys

HERE = Path(__file__).resolve().parent
NAME = 'local-address-map'
TOP = 'address_map_tb'
CONFIGS = {'alias': {'ALIAS': 1}, 'strict': {'ALIAS': 0}}
ITERATIONS = {'smoke': 200, 'nightly': 1000}
SOURCES = [HERE / 'rtl/address_map.sv', HERE / 'tb/address_map_tb.sv']


class Plan:
    def __init__(self, alias):
        self.alias = alias
        self.rows = []
        self.reset()

    def reset(self):
        self.ram = [0] * 64
        self.ctrl = 0
        self.match = 0
        self.count = 0
        self.edge = 0
        self.gpio_out = 0
        self.gpio_prev = 0
        self.irq = [0, 0]

    def decode(self, addr, write, strb):
        if addr & 3:
            return None, 1
        region = (addr >> 8) & 0xf
        offset = addr & 0xff
        if region == 0 or (self.alias and region == 4):
            return ('ram', (addr >> 2) & 0x3f), 0
        if region == 1:
            if offset not in (0x00, 0x04, 0x08, 0x0c):
                return None, 1
            if write and (offset == 0x04 or strb != 0xf):
                return None, 1
            return ('timer', offset), 0
        if region == 2:
            if offset not in (0x00, 0x04, 0x08, 0x0c):
                return None, 1
            if write and (offset == 0x04 or strb != 0xf):
                return None, 1
            return ('gpio', offset), 0
        return None, 1

    def read(self, target, gpio_in):
        kind, index = target
        if kind == 'ram':
            return self.ram[index]
        if kind == 'timer':
            return {0x00: self.ctrl, 0x04: self.count, 0x08: self.match,
                    0x0c: self.irq[0]}[index]
        if kind == 'gpio':
            return {0x00: self.gpio_out, 0x04: gpio_in, 0x08: self.edge,
                    0x0c: self.irq[1]}[index]
        return 0

    def step(self, rst=1, psel=0, pwrite=0, paddr=0, pwdata=0, pstrb=0, gpio_in=0):
        paddr &= 0xfff
        pstrb &= 0xf
        gpio_in &= 0xf
        if not rst:
            self.rows.append([0, 0, 0, paddr, 0, 0, 0, 0, 0, 1, 0, 0])
            self.reset()
            return
        target, error = (None, 0)
        data = 0
        if psel:
            target, error = self.decode(paddr, bool(pwrite), pstrb)
            if not error:
                data = self.read(target, gpio_in)
        self.rows.append([1, psel, pwrite, paddr, pwdata, pstrb, gpio_in,
                          data, error, 1, (self.irq[0] | (self.irq[1] << 1)), self.gpio_out])
        old_ctrl, old_count, old_match = self.ctrl, self.count, self.match
        old_edge, old_prev = self.edge, self.gpio_prev
        if psel and not error and pwrite:
            if target[0] == 'ram':
                index = target[1]
                if pstrb & 1: self.ram[index] = (self.ram[index] & 0xffffff00) | (pwdata & 0xff)
                if pstrb & 2: self.ram[index] = (self.ram[index] & 0xffff00ff) | (pwdata & 0xff00)
                if pstrb & 4: self.ram[index] = (self.ram[index] & 0xff00ffff) | (pwdata & 0xff0000)
                if pstrb & 8: self.ram[index] = (self.ram[index] & 0x00ffffff) | (pwdata & 0xff000000)
            elif target[0] == 'timer':
                if target[1] == 0x00: self.ctrl = pwdata
                elif target[1] == 0x08: self.match = pwdata
                elif target[1] == 0x0c: self.irq[0] &= (~pwdata) & 1
            elif target[0] == 'gpio':
                if target[1] == 0x00: self.gpio_out = pwdata & 0xf
                elif target[1] == 0x08: self.edge = pwdata
                elif target[1] == 0x0c: self.irq[1] &= (~pwdata) & 1
        next_count = (old_count + 1) & 0xffff
        if old_ctrl & 1:
            self.count = next_count
            if next_count == (old_match & 0xffff) and (old_ctrl & 2):
                self.irq[0] = 1
        if gpio_in & ~old_prev & old_edge & 0xf:
            self.irq[1] = 1
        self.gpio_prev = gpio_in

    def write(self, addr, data, strb=0xf, gpio_in=0):
        self.step(psel=1, pwrite=1, paddr=addr, pwdata=data, pstrb=strb, gpio_in=gpio_in)

    def read_step(self, addr, strb=0xf, gpio_in=0):
        self.step(psel=1, pwrite=0, paddr=addr, pstrb=strb, gpio_in=gpio_in)

    def idle(self, count=1, gpio_in=0):
        for _ in range(count):
            self.step(gpio_in=gpio_in)

    def fixed(self):
        self.step(rst=0)
        self.write(0x000, 0x11223344)
        self.read_step(0x000)
        self.write(0x000, 0x000000aa, 0x1)
        self.read_step(0x000)
        self.write(0x000, 0x55667788, 0x5)
        self.read_step(0x000)
        self.read_step(0x400)
        self.write(0x400, 0xdeadbeef)
        self.read_step(0x000)
        self.write(0x108, 5)
        self.write(0x100, 3)
        self.idle(8)
        self.read_step(0x104)
        self.read_step(0x10c)
        self.write(0x200, 5)
        self.write(0x208, 0xf)
        self.step(gpio_in=1)
        self.step(gpio_in=0)
        self.step(gpio_in=1)
        self.read_step(0x204, gpio_in=1)
        self.read_step(0x20c, gpio_in=1)
        self.read_step(0x10c, gpio_in=1)
        self.write(0x10c, 1, gpio_in=1)
        self.read_step(0x10c, gpio_in=1)
        self.write(0x20c, 1, gpio_in=1)
        self.read_step(0x20c, gpio_in=1)
        self.write(0x100, 0xffffffff, 0x3)
        self.read_step(0x100)
        self.read_step(0x300)
        self.write(0x300, 0x99999999)
        self.read_step(0x000)
        # Both IRQ sources must win over a simultaneous W1C.
        self.step(rst=0)
        self.write(0x108, 2)
        self.write(0x100, 3)
        self.idle()
        self.write(0x10c, 1)
        self.read_step(0x10c)
        self.write(0x208, 1)
        self.write(0x20c, 1, gpio_in=1)
        self.read_step(0x20c, gpio_in=1)
        self.write(0x0fc, 0x55aa33cc)
        self.read_step(0x4fc)
        self.read_step(0x0fc)
        self.write(0x0fc, 0xffffffff, 0)
        self.read_step(0x0fc)
        self.write(0x003, 0x99999999)
        self.read_step(0x000)
        self.step(rst=0)
        self.write(0x000, 0x0badf00d)
        self.read_step(0x000)

    def random(self, rng, count):
        self.step(rst=0)
        addresses = [0x000, 0x004, 0x008, 0x100, 0x104, 0x108, 0x10c,
                     0x200, 0x204, 0x208, 0x20c, 0x300, 0x400, 0x404]
        for _ in range(count):
            if rng.randrange(150) == 0:
                self.step(rst=0)
            self.step(psel=int(rng.randrange(6) != 0), pwrite=rng.randrange(2),
                      paddr=rng.choice(addresses) | rng.randrange(4),
                      pwdata=rng.getrandbits(32), pstrb=rng.randrange(16),
                      gpio_in=rng.randrange(16))


def vectors(seed, iterations, parameters, boundary=False):
    p = Plan(parameters['ALIAS'])
    p.fixed()
    if not boundary:
        p.random(random.Random(seed), iterations)
    # Read back every RAM word so a final write cannot escape checking.
    for addr in range(0, 0x100, 4):
        p.read_step(addr)
    p.idle()
    return p.rows


def make_cases(args, parameters):
    base = vectors(args.seed, 0, parameters, True)
    cases = [dict(id='boundaries', vectors=base, mutation=args.demo_bug,
                  category='functional', expected_failure=None)]
    for seed in range(args.seed, args.seed + (3 if args.profile == 'nightly' else 1)):
        cases.append(dict(id=f'random-seed{seed}', vectors=vectors(seed, args.iterations, parameters),
                          mutation=args.demo_bug, category='functional', expected_failure=None))
    for mutation, label in ((1, 'MAP_DECODE'), (2, 'MAP_DATA'),
                            (3, 'MAP_IRQ'), (4, 'MAP_DATA')):
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

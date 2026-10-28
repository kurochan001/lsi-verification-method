#!/usr/bin/env python3
"""Secure lifecycle and debug authentication example with independent access model."""
import importlib.util
from pathlib import Path
import random
import sys

HERE = Path(__file__).resolve().parent
NAME = 'local-secure-lifecycle'
TOP = 'secure_lifecycle_tb'
CONFIGS = {
    'limit3': {'ATTEMPT_LIMIT': 3, 'DEBUG_KEY': 0xa55a},
    'limit2': {'ATTEMPT_LIMIT': 2, 'DEBUG_KEY': 0x5aa5},
}
ITERATIONS = {'smoke': 120, 'nightly': 600}
SOURCES = [HERE / 'rtl/secure_lifecycle.sv', HERE / 'tb/secure_lifecycle_tb.sv']

KEY0, KEY1, CFG, STATUS = 0x00, 0x04, 0x08, 0x0c
SCRATCH, IRQ, LOCK, DEBUG = 0x10, 0x14, 0x18, 0x1c
KNOWN = {KEY0, KEY1, CFG, STATUS, SCRATCH, IRQ, LOCK, DEBUG}
SECURE_REGS = {KEY0, KEY1, CFG, STATUS, IRQ, LOCK, DEBUG}


class Plan:
    def __init__(self, limit, key):
        self.limit = limit
        self.key = key
        self.rows = []
        self.reset()

    def reset(self):
        self.key0 = self.key1 = 0
        self.cfg = self.scratch = 0
        self.irq_bits = [0, 0]
        self.locked = self.unlocked = self.tamper_latched = self.lockout = 0
        self.attempts = 0

    def status(self):
        return (self.attempts << 4) | (self.lockout << 3) | (self.tamper_latched << 2) | (self.unlocked << 1) | self.locked

    def read(self, addr, secure):
        if addr not in KNOWN:
            return 0, 1
        if addr in SECURE_REGS and not secure:
            return 0, 1
        if addr == KEY0:
            return self.key0, 0
        if addr == KEY1:
            return self.key1, 0
        if addr == CFG:
            return self.cfg, 0
        if addr == STATUS:
            return self.status(), 0
        if addr == SCRATCH:
            return self.scratch, 0
        if addr == IRQ:
            return self.irq_bits[0] | (self.irq_bits[1] << 1), 0
        return 0, 0

    def write_test(self, lifecycle, tamper):
        return lifecycle == 0 and not self.locked and not self.tamper_latched and not tamper

    def write_error(self, addr, secure, lifecycle, tamper):
        if tamper:
            return 1
        if addr not in KNOWN:
            return 1
        if addr in SECURE_REGS and not secure:
            return 1
        writable = self.write_test(lifecycle, tamper)
        if addr in (KEY0, KEY1, CFG, LOCK):
            return int(not writable)
        if addr == DEBUG:
            return int(not (writable and not self.lockout and not self.unlocked and secure))
        if addr == STATUS:
            return 1
        if addr == IRQ:
            return int(not secure)
        return 0

    def step(self, rst=1, cs=0, we=0, re=0, addr=0, wdata=0, secure=0, lifecycle=0, debug_key=0, tamper=0):
        addr &= 0xff
        rdata = error = 0
        if rst and cs:
            if re:
                rdata, error = self.read(addr, secure)
            if we:
                error |= self.write_error(addr, secure, lifecycle, tamper)
        if not rst:
            rdata = error = 0
        self.rows.append([rst, cs, we, re, addr, wdata, secure, lifecycle, debug_key, tamper,
                          rdata, error, int(rst and (self.irq_bits[0] or self.irq_bits[1]))])
        if not rst:
            self.reset()
            return
        if tamper:
            self.key0 = self.key1 = 0
            self.tamper_latched = 1
            self.irq_bits[0] = 1
            return
        if not (cs and we):
            return
        if addr not in KNOWN or (addr in SECURE_REGS and not secure):
            return
        writable = self.write_test(lifecycle, tamper)
        if addr == KEY0 and writable:
            self.key0 = wdata & 0xffff
        elif addr == KEY1 and writable:
            self.key1 = wdata & 0xffff
        elif addr == CFG and writable:
            self.cfg = wdata & 0xffffffff
        elif addr == SCRATCH:
            self.scratch = wdata & 0xffffffff
        elif addr == IRQ and secure:
            self.irq_bits[0] &= ~wdata & 1
            self.irq_bits[1] &= (~wdata >> 1) & 1
        elif addr == LOCK and writable and (wdata & 1):
            self.locked = 1
        elif addr == DEBUG and writable and not self.lockout and not self.unlocked and secure:
            if debug_key & 0xffff == self.key:
                self.unlocked = 1
            else:
                if self.attempts + 1 >= self.limit:
                    self.lockout = 1
                    self.irq_bits[1] = 1
                if self.attempts < self.limit:
                    self.attempts += 1

    def fixed(self):
        self.step(rst=0)
        # Test-visible key slots and secure configuration.
        self.step(cs=1, we=1, addr=KEY0, wdata=0x11111111, secure=1)
        self.step(cs=1, we=1, addr=KEY1, wdata=0x22222222, secure=1)
        self.step(cs=1, re=1, addr=KEY0, secure=1)
        self.step(cs=1, re=1, addr=KEY1, secure=1)
        self.step(cs=1, we=1, addr=CFG, wdata=0x0000000f, secure=1)
        self.step(cs=1, re=1, addr=CFG, secure=1)
        # Non-secure read and write are rejected without changing the key slot.
        self.step(cs=1, re=1, addr=KEY0, secure=0)
        self.step(cs=1, we=1, addr=KEY0, wdata=0xdeadbeef, secure=0)
        self.step(cs=1, re=1, addr=KEY0, secure=1)
        # Non-secure scratch is allowed; unknown and write-only reads are separate.
        self.step(cs=1, we=1, addr=SCRATCH, wdata=0xabcd1234, secure=0)
        self.step(cs=1, re=1, addr=SCRATCH, secure=0)
        self.step(cs=1, re=1, addr=0x20, secure=1)
        self.step(cs=1, we=1, addr=0x20, wdata=0xdeadbeef, secure=1)
        self.step(cs=1, re=1, addr=SCRATCH, secure=0)
        self.step(cs=1, re=1, addr=LOCK, secure=1)
        # Wrong attempts below the limit, then the correct key.
        for _ in range(self.limit - 1):
            self.step(cs=1, we=1, addr=DEBUG, debug_key=self.key ^ 0xffff, secure=1)
        self.step(cs=1, we=1, addr=DEBUG, debug_key=self.key, secure=1)
        self.step(cs=1, re=1, addr=STATUS, secure=1)
        # Lock is sticky and blocks key, configuration and debug writes.
        self.step(cs=1, we=1, addr=LOCK, wdata=1, secure=1)
        self.step(cs=1, we=1, addr=LOCK, wdata=1, secure=1)
        self.step(cs=1, we=1, addr=KEY0, wdata=0x33333333, secure=1)
        self.step(cs=1, re=1, addr=KEY0, secure=1)
        # A fresh reset reaches the attempt limit and the lockout IRQ.
        self.step(rst=0)
        for _ in range(self.limit):
            self.step(cs=1, we=1, addr=DEBUG, debug_key=self.key ^ 1, secure=1)
        self.step(cs=1, re=1, addr=STATUS, secure=1)
        self.step(cs=1, we=1, addr=DEBUG, debug_key=self.key, secure=1)
        self.step(cs=1, re=1, addr=IRQ, secure=1)
        self.step(cs=1, we=1, addr=IRQ, wdata=2, secure=1)
        self.step(cs=1, re=1, addr=IRQ, secure=1)
        # Tamper zeroizes both key slots and latches a visible event.
        self.step(rst=0)
        self.step(cs=1, we=1, addr=KEY0, wdata=0x44444444, secure=1)
        self.step(cs=1, we=1, addr=KEY1, wdata=0x55555555, secure=1)
        self.step(tamper=1)
        self.step(cs=1, re=1, addr=KEY0, secure=1)
        self.step(cs=1, re=1, addr=KEY1, secure=1)
        self.step(cs=1, re=1, addr=STATUS, secure=1)
        self.step(cs=1, re=1, addr=IRQ, secure=1)
        self.step(cs=1, we=1, addr=IRQ, wdata=1, secure=1)
        self.step(cs=1, re=1, addr=IRQ, secure=1)
        self.step(cs=1, we=1, addr=SCRATCH, wdata=0x55aa55aa, secure=0)
        self.step(cs=1, re=1, addr=SCRATCH, secure=0)
        self.step(cs=1, we=1, addr=0x24, wdata=0x99999999, secure=1)
        self.step(cs=1, re=1, addr=SCRATCH, secure=0)

    def random(self, rng, count):
        self.step(rst=0)
        addresses = sorted(KNOWN) + [0x20, 0x24, 0x03, 0x1e]
        for _ in range(count):
            if rng.randrange(80) == 0:
                self.step(rst=0)
                continue
            both = rng.randrange(20) == 0
            re = int(rng.randrange(2) or both)
            we = int(not re or both)
            self.step(rst=1, cs=int(rng.randrange(5) != 0), we=we, re=re,
                      addr=rng.choice(addresses), wdata=rng.getrandbits(32),
                      secure=rng.randrange(2), lifecycle=rng.randrange(4),
                      debug_key=self.key if rng.randrange(4) == 0 else rng.getrandbits(16),
                      tamper=int(rng.randrange(50) == 0))


def vectors(seed, iterations, parameters, boundary=False):
    p = Plan(parameters['ATTEMPT_LIMIT'], parameters['DEBUG_KEY'])
    p.fixed()
    if not boundary:
        p.random(random.Random(seed), iterations)
    # Observe all readable state after the final randomized access/event.
    for addr in sorted(KNOWN):
        p.step(cs=1, re=1, addr=addr, secure=1)
    p.step()
    return p.rows


def make_cases(args, parameters):
    base = vectors(args.seed, 0, parameters, True)
    cases = [dict(id='boundaries', vectors=base, mutation=args.demo_bug,
                  category='functional', expected_failure=None)]
    for seed in range(args.seed, args.seed + (3 if args.profile == 'nightly' else 1)):
        cases.append(dict(id=f'random-seed{seed}', vectors=vectors(seed, args.iterations, parameters),
                          mutation=args.demo_bug, category='functional', expected_failure=None))
    for mutation, label in ((1, 'SECURE_ACCESS'), (2, 'SECURE_DATA'),
                            (3, 'SECURE_DATA'), (4, 'SECURE_DATA')):
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

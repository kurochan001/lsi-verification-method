#!/usr/bin/env python3
"""LR/SC and AMO on a memory shared by two harts, checked against the history of operations and litmus outcomes."""
import importlib.util
from pathlib import Path
import random
import sys

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('atomic_litmus', HERE / 'litmus.py')
L = importlib.util.module_from_spec(spec)
spec.loader.exec_module(L)
NAME = 'local-riscv-atomic'
TOP = 'atomic_tb'
MUTANTS = 6
CONFIGS = {'word': {'GRAIN': 0}, 'pair': {'GRAIN': 1}}
ITERATIONS = {'smoke': 200, 'nightly': 2000}
SOURCES = [HERE / 'rtl/atomic_mem.sv', HERE / 'tb/atomic_tb.sv']
EXTRA_INPUTS = [HERE / 'litmus.py']
LABELS = {1: 'ATOM_SC', 2: 'ATOM_SC', 3: 'ATOM_SC', 4: 'ATOM_AMO', 5: 'ATOM_MEMORY', 6: 'ATOM_MEMORY'}
LOAD, STORE, LR, SC, AMO = range(5)
SWAP, ADD, XOR, AND, OR, MIN, MAX, MINU, MAXU = range(9)
MASK = 0xffffffff
# Why the scenario issues this request; the bench reports it as a goal when the request is taken.
NOTES = {name: number for number, name in enumerate(
    ('no-reservation', 'other-store', 'other-sc', 'other-amo', 'other-address', 'second-sc', 'own-store',
     'neighbour-store', 'after-reset', 'signed-compare', 'own-amo', 'new-lr'), 1)}


def signed(value):
    return value - (1 << 32) if value >> 31 else value


def amo_result(fn, old, operand):
    """The value an AMO writes, from the definition of each function on 32-bit words."""
    if fn == SWAP:
        return operand
    if fn == ADD:
        return (old + operand) & MASK
    if fn in (XOR, AND, OR):
        return {XOR: old ^ operand, AND: old & operand, OR: old | operand}[fn]
    if fn in (MIN, MAX):
        return (min if fn == MIN else max)(old, operand, key=signed)
    if fn in (MINU, MAXU):
        return (min if fn == MINU else max)(old, operand)
    raise ValueError('unknown AMO function')


class Plan:
    """Expected outputs of every cycle. Whether an SC succeeds is decided from the log of
    operations since the last reset, not from a copy of the reservation registers."""

    def __init__(self, grain):
        self.grain = grain
        self.rows = []
        self.counts = dict(steps=0, loads=0, stores=0, reservations=0, sc_success=0, sc_failure=0, amos=0)
        self.clear()

    def clear(self):
        self.memory = [0, 0, 0, 0]
        self.response = [None, None]   # (operation, data) until the hart takes it
        self.amo = None                # (hart, fn, address, operand, old) in its second cycle
        self.log = []                  # (time, hart, 'lr' | 'sc' | 'write', address)

    def sc_succeeds(self, hart, address):
        own = [entry for entry in self.log if entry[1] == hart and entry[2] in ('lr', 'sc')]
        if not own or own[-1][2] == 'sc':
            return False  # no LR yet, or an SC of this hart since its last LR
        since, _, _, reserved = own[-1]
        if reserved != address:
            return False
        return not any(time > since and writer != hart and kind == 'write' and
                       where >> self.grain == reserved >> self.grain
                       for time, writer, kind, where in self.log)

    def cycle(self, rst=1, valid=0, hart=0, op=0, fn=0, address=0, data=0, ready=3, tag=0, note=0):
        if not rst:
            self.clear()
        busy = self.amo is not None
        legal = op <= AMO and (op != AMO or fn <= MAXU)
        accept = int(bool(rst and legal and not busy and self.response[hart] is None))
        pending = [r or (0, 0) for r in self.response]
        self.rows.append([rst, valid, hart, op, fn, address, data, ready, tag, accept, int(busy),
                          sum(1 << h for h in (0, 1) if self.response[h]), pending[0][1], pending[1][1],
                          sum(word << (32 * i) for i, word in enumerate(self.memory)),
                          pending[0][0] | pending[1][0] << 4, note])
        self.counts['steps'] += 1
        if not rst:
            return accept
        time = len(self.rows)
        for h in (0, 1):
            if self.response[h] and ready >> h & 1:
                if self.response[h][0] == SC:
                    self.counts['sc_failure' if self.response[h][1] else 'sc_success'] += 1
                self.response[h] = None
        if busy:
            owner, function, where, operand, old = self.amo
            self.memory[where] = amo_result(function, old, operand)
            self.log.append((time, owner, 'write', where))
            self.response[owner], self.amo = (AMO, old), None
        elif valid and accept:
            if op == LOAD:
                self.response[hart] = (LOAD, self.memory[address])
                self.counts['loads'] += 1
            elif op == STORE:
                self.memory[address] = data
                self.log.append((time, hart, 'write', address))
                self.response[hart] = (STORE, 0)
                self.counts['stores'] += 1
            elif op == LR:
                self.log.append((time, hart, 'lr', address))
                self.response[hart] = (LR, self.memory[address])
                self.counts['reservations'] += 1
            elif op == SC:
                success = self.sc_succeeds(hart, address)
                self.log.append((time, hart, 'sc', address))
                if success:
                    self.memory[address] = data
                    self.log.append((time, hart, 'write', address))
                self.response[hart] = (SC, int(not success))
            else:
                self.amo = (hart, fn, address, data, self.memory[address])
                self.counts['amos'] += 1
        return accept

    def transfer(self, hart, op, address=0, data=0, fn=0, note=0, stall=0):
        """One operation from request to the taken response; returns the response data."""
        if not self.cycle(valid=1, hart=hart, op=op, fn=fn, address=address, data=data, note=note):
            raise ValueError('request blocked')
        if op == AMO:
            self.cycle()
        value = self.response[hart][1]
        for _ in range(stall):
            self.cycle(ready=0)
        self.cycle()
        return value

    def sc(self, hart, address, data, succeeds, note=0):
        """An SC whose result the scenario states in advance."""
        if self.transfer(hart, SC, address, data, note=note) != int(not succeeds):
            raise ValueError('the scenario expects another SC result')


def fixed_scenario(grain):
    p = Plan(grain)
    n = NOTES
    p.cycle(rst=0)
    # Success, and the reservation is used up by it.
    p.transfer(0, STORE, 0, 0x10)
    if p.transfer(0, LR, 0) != 0x10:
        raise ValueError('LR must return the stored word')
    p.sc(0, 0, 0x11, True)
    p.sc(0, 0, 0x12, False, n['second-sc'])
    p.sc(1, 1, 0x13, False, n['no-reservation'])
    # What the other hart does between LR and SC.
    p.transfer(0, LR, 0); p.transfer(1, STORE, 0, 0x20); p.sc(0, 0, 0x21, False, n['other-store'])
    p.transfer(0, LR, 0); p.transfer(1, LR, 0); p.sc(1, 0, 0x30, True); p.sc(0, 0, 0x31, False, n['other-sc'])
    p.transfer(1, LR, 2); p.transfer(0, AMO, 2, 5, fn=ADD); p.sc(1, 2, 0x40, False, n['other-amo'])
    # A failed SC of the other hart writes nothing, so it takes nothing away.
    p.transfer(0, LR, 3); p.sc(1, 3, 0x50, False); p.sc(0, 3, 0x51, True)
    # The address of the SC, and a second LR.
    p.transfer(0, LR, 0); p.sc(0, 1, 0x60, False, n['other-address'])
    p.transfer(0, LR, 0); p.transfer(0, LR, 2); p.sc(0, 2, 0x61, True, n['new-lr'])
    p.transfer(0, LR, 0); p.transfer(0, LR, 2); p.sc(0, 0, 0x62, False, n['other-address'])
    # Writes of the hart itself keep its reservation.
    p.transfer(1, LR, 1); p.transfer(1, STORE, 1, 0x70); p.sc(1, 1, 0x71, True, n['own-store'])
    p.transfer(1, LR, 1); p.transfer(1, AMO, 1, 1, fn=ADD); p.sc(1, 1, 0x72, True, n['own-amo'])
    # The neighbouring word: another reservation set with GRAIN=0, the same set with GRAIN=1.
    p.transfer(0, LR, 2); p.transfer(1, STORE, 3, 0x80); p.sc(0, 2, 0x81, grain == 0, n['neighbour-store'])
    p.transfer(0, LR, 2); p.transfer(1, STORE, 1, 0x82); p.sc(0, 2, 0x83, True)
    # Every AMO function; MIN and MAX on words whose order depends on the sign.
    p.transfer(0, STORE, 3, 0x0f0f00ff)
    for fn, operand in ((SWAP, 0x12345678), (ADD, 0xfffffff0), (XOR, 0x0ff0ff00), (AND, 0xff00ffff), (OR, 0x000000a5)):
        p.transfer(fn & 1, AMO, 3, operand, fn=fn)
    for fn in (MIN, MAX, MINU, MAXU):
        for old, operand in ((0x80000000, 1), (5, 0xfffffffe), (7, 9)):
            p.transfer(0, STORE, 3, old)
            p.transfer(1, AMO, 3, operand, fn=fn, note=n['signed-compare'] if fn in (MIN, MAX) else 0)
    # The second cycle of an AMO: the other hart and the same hart must both wait.
    p.transfer(0, STORE, 2, 100)
    p.cycle(valid=1, hart=0, op=AMO, fn=ADD, address=2, data=1)
    p.cycle(valid=1, hart=1, op=STORE, address=2, data=500)
    p.cycle(valid=1, hart=1, op=STORE, address=2, data=500)
    p.cycle()
    p.cycle(valid=1, hart=1, op=AMO, fn=SWAP, address=2, data=7)
    p.cycle(valid=1, hart=1, op=LOAD, address=2)
    p.cycle()
    # Responses of both harts wait at once; a hart with a waiting response is not served.
    p.cycle(valid=1, hart=0, op=LOAD, address=2, ready=0)
    p.cycle(valid=1, hart=1, op=LR, address=2, ready=0)
    p.cycle(valid=1, hart=0, op=STORE, address=2, data=9, ready=0)
    p.cycle(ready=1)
    p.cycle(valid=1, hart=0, op=STORE, address=2, data=9, ready=0)
    p.cycle(ready=2)
    p.sc(1, 2, 0x90, False, n['other-store'])
    p.cycle()
    # Requests the port does not know.
    p.cycle(valid=1, hart=0, op=5)
    p.cycle(valid=1, hart=0, op=AMO, fn=9, address=1, data=1)
    # Reset in the second cycle of an AMO and with a reservation.
    p.transfer(1, LR, 1)
    p.cycle(valid=1, hart=0, op=AMO, fn=ADD, address=0, data=1)
    p.cycle(rst=0)
    p.sc(1, 1, 0xa0, False, n['after-reset'])
    p.transfer(0, LOAD, 0)
    return p


def litmus_traces(p):
    """One trace per outcome of every program. The abstract model and the plan must agree on every response."""
    for name in L.PROGRAMS:
        for outcome, events in sorted(L.explore(name)['witnesses'].items()):
            p.cycle(rst=0, tag=L.IDS[name])
            for hart, op, fn, address, data, expected in events:
                if p.transfer(hart, op, address, data, fn=fn) != expected:
                    raise ValueError(f'{name}: the plan and the abstract model disagree')
            if p.memory[L.COUNTER] != outcome[0]:
                raise ValueError(f'{name}: another final counter')
            p.cycle(tag=8 + L.IDS[name])


def random_cycles(p, seed, iterations):
    rng = random.Random(seed)
    words = (0, 1, 2, 5, 0x7fffffff, 0x80000000, 0xfffffffe, MASK)
    for _ in range(3 * iterations):
        if rng.random() < 0.01:
            p.cycle(rst=0)
            continue
        op = rng.choices((LOAD, STORE, LR, SC, AMO, 6), (2, 3, 4, 5, 3, 0.1))[0]
        data = rng.choice(words) if rng.random() < 0.5 else rng.getrandbits(32)
        p.cycle(valid=int(rng.random() < 0.8), hart=rng.randrange(2), op=op, fn=rng.randrange(9),
                address=rng.randrange(4), data=data, ready=rng.choice((3, 3, 3, 1, 2, 0)))
    for _ in range(3):
        p.cycle()


def vectors(seed, iterations, grain, boundary=False):
    p = fixed_scenario(grain)
    litmus_traces(p)
    if not boundary:
        p.cycle(rst=0)
        random_cycles(p, seed, iterations)
    p.cycle()
    return p.rows, p.counts


def make_cases(args, parameters):
    grain = parameters['GRAIN']
    base, counts = vectors(args.seed, 0, grain, True)
    cases = [dict(id='boundaries', vectors=base, counts=counts, mutation=args.demo_bug, expected_failure=None,
                  category='functional')]
    for seed in range(args.seed, args.seed + (3 if args.profile == 'nightly' else 1)):
        rows, stats = vectors(seed, args.iterations, grain)
        cases.append(dict(id=f'random-seed{seed}', vectors=rows, counts=stats, mutation=args.demo_bug,
                          expected_failure=None, category='functional'))
    for mutation, label in LABELS.items():
        cases.append(dict(id=f'detect-mutation{mutation}', vectors=base, counts=counts, mutation=mutation,
                          expected_failure=label, category='mutation'))
    return cases


if __name__ == '__main__':
    spec = importlib.util.spec_from_file_location('runner', HERE.parent / 'local-common/runner.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    sys.exit(module.main(sys.modules[__name__]))

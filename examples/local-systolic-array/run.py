#!/usr/bin/env python3
"""Weight-stationary INT8 systolic array: skew, deskew, stall, weight hazards and accumulator width."""
import importlib.util
from pathlib import Path
import random
import sys

HERE = Path(__file__).resolve().parent
NAME = 'local-systolic-array'
TOP = 'systolic_tb'
CONFIGS = {'n2': {'N': 2}, 'n4': {'N': 4}}
ITERATIONS = {'smoke': 96, 'nightly': 600}
SOURCES = [HERE / 'rtl/systolic_array.sv', HERE / 'tb/systolic_tb.sv']
EDGES = (-128, -127, -1, 0, 1, 127)


def pack(values, width):
    return sum((value & ((1 << width) - 1)) << (width * i) for i, value in enumerate(values))


def junk(n):
    # Driven on payloads that are not offered, so the DUT must use the valid qualifiers.
    return [(0x5a + 0x35 * i) % 256 - 128 for i in range(n)]


class Model:
    """Transaction model: each accepted vector leaves after a fixed number of pipeline slots.

    The result is the matrix product computed at acceptance; skew, PE order and
    deskew registers are deliberately not modelled.
    """

    def __init__(self, n):
        self.n = n
        self.reset()

    def reset(self):
        self.weights = [[0] * self.n for _ in range(self.n)]
        self.slots = [None] * (2 * self.n - 1)

    def product(self, vector):
        return [sum(vector[r] * self.weights[r][c] for r in range(self.n)) for c in range(self.n)]

    def step(self, rst, write, vector, ready):
        if not rst:
            self.reset()
            return [0, 0, 0, 0]
        result = self.slots[-1]
        stall = result is not None and not ready
        w_ready = int(all(slot is None for slot in self.slots))
        a_ready = int(not stall and write is None)
        outputs = [w_ready, a_ready, int(result is not None), 0 if result is None else pack(result, 32)]
        if write is not None and w_ready:
            self.weights[write[0]] = list(write[1])
        if not stall:
            accepted = vector is not None and a_ready
            self.slots = [self.product(vector) if accepted else None] + self.slots[:-1]
        return outputs


class Plan:
    def __init__(self, n):
        self.n = n
        self.model = Model(n)
        self.rows = []

    def cycle(self, rst=1, write=None, vector=None, ready=1):
        outputs = self.model.step(rst, write, vector, ready)
        row = [rst, int(write is not None), self.n - 1 if write is None else write[0],
               pack(junk(self.n) if write is None else write[1], 8),
               int(vector is not None), pack(junk(self.n) if vector is None else vector, 8),
               ready, *outputs]
        self.rows.append(row)
        return row

    def send(self, vector, ready=1):
        while not self.cycle(vector=vector, ready=ready)[8]:
            pass

    def write(self, row, values, vector=None):
        while not self.cycle(write=(row, values), vector=vector)[7]:
            pass

    def load(self, matrix):
        for row, values in enumerate(matrix):
            self.write(row, values)

    def drain(self):
        while any(slot is not None for slot in self.model.slots):
            self.cycle()


def mixed_matrix(n):
    return [[(-128, 127, r - c)[(r + c) % 3] for c in range(n)] for r in range(n)]


def boundary_vectors(n):
    p = Plan(n)
    p.cycle(rst=0)
    p.send([-128] * n)          # weights are cleared by reset: zero results
    p.drain()
    p.load(mixed_matrix(n))
    p.send([1, -1] * (n // 2))  # isolated vector: fixed latency
    p.drain()
    burst = [[(17 * i + 29 * r) % 256 - 128 for r in range(n)] for i in range(2 * n + 2)]
    for vector in burst:        # back-to-back until every slot is occupied
        p.send(vector)
    for _ in range(3):          # full pipeline stalled; the next vector stays offered
        p.cycle(vector=[5] * n, ready=0)
    p.send([5] * n)
    p.cycle()
    p.send([0] * n)             # a bubble separates the two vectors
    p.send([-3] * n)
    p.write(0, [2] * n)         # weight write waits for the vectors in flight
    p.drain()
    p.write(1, [-2] * n, vector=[9] * n)  # a write takes priority over an offered vector
    p.send([9] * n)
    p.drain()
    p.load([[-128] * n for _ in range(n)])
    p.send([-128] * n)          # largest positive products, sum beyond 16 bits
    p.send([127] * n)           # most negative products
    p.drain()
    p.load([[127] * n for _ in range(n)])
    p.send([-128] * n)
    p.send([127] * n)
    for vector in burst[:n + 1]:
        p.send(vector)
    p.cycle(rst=0)              # reset with vectors in flight
    p.send([7] * n)
    p.drain()
    p.load(mixed_matrix(n))
    p.send(burst[0])
    p.drain()
    return p.rows


def random_matrix(rng, n):
    return [[rng.choice(EDGES) if rng.randrange(4) == 0 else rng.randrange(-128, 128) for _ in range(n)]
            for _ in range(n)]


def random_vectors(seed, iterations, n):
    rng = random.Random(seed)
    p = Plan(n)
    p.cycle(rst=0)
    p.load(random_matrix(rng, n))
    accepted, pending = 0, None
    while accepted < iterations:
        choice = rng.randrange(100)
        if choice == 0:
            p.cycle(rst=0)
            pending = None
            p.load(random_matrix(rng, n))
            continue
        if choice < 4:
            for row, values in enumerate(random_matrix(rng, n)):
                while not p.cycle(write=(row, values), vector=pending, ready=int(rng.randrange(3) != 0))[7]:
                    pass
            continue
        if pending is None and rng.randrange(4) != 0:
            pending = random_matrix(rng, n)[0]
        row = p.cycle(vector=pending, ready=int(rng.randrange(3) != 0))
        if pending is not None and row[8]:
            accepted += 1
            pending = None
    p.drain()
    return p.rows


def counts(rows):
    return dict(accepted=sum(bool(r[0] and r[4] and r[8]) for r in rows),
                completed=sum(bool(r[0] and r[9] and r[6]) for r in rows),
                writes=sum(bool(r[0] and r[1] and r[7]) for r in rows))


def make_cases(args, parameters):
    n = parameters['N']
    base = boundary_vectors(n)
    cases = [dict(id='boundaries', vectors=base, mutation=args.demo_bug, category='functional',
                  expected_failure=None)]
    for seed in range(args.seed, args.seed + (3 if args.profile == 'nightly' else 1)):
        cases.append(dict(id=f'random-seed{seed}', vectors=random_vectors(seed, args.iterations, n),
                          mutation=args.demo_bug, category='functional', expected_failure=None))
    for mutation, label in ((1, 'SA_DATA'), (2, 'SA_DATA'), (3, 'SA_HOLD'), (4, 'SA_DATA')):
        cases.append(dict(id=f'detect-mutation{mutation}', vectors=base, mutation=mutation,
                          category='mutation', expected_failure=label))
    for case in cases:
        case['counts'] = counts(case['vectors'])
    return cases


if __name__ == '__main__':
    spec = importlib.util.spec_from_file_location('local_runner', HERE.parent / 'local-common/runner.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    sys.exit(module.main(sys.modules[__name__]))

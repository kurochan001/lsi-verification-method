#!/usr/bin/env python3
"""AES-128 encryption core: FIPS 197 examples, an independent model, fixed latency and zeroization."""
import importlib.util
from pathlib import Path
import random
import sys
HERE = Path(__file__).resolve().parent
NAME = 'local-aes'
TOP = 'aes_tb'
CONFIGS = {'core': {}}
ITERATIONS = {'smoke': 12, 'nightly': 60}
MUTANTS = 9
SOURCES = [HERE / 'rtl/aes128_core.sv', HERE / 'tb/aes_tb.sv']
EXTRA_INPUTS = [HERE / 'model.py']
_spec = importlib.util.spec_from_file_location('local_aes_model', HERE / 'model.py')
MODEL = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(MODEL)
LATENCY = 11          # clocks from the accepting clock to the first result clock
ROUNDS = 10
ONES = (1 << 128) - 1
LABELS = {1: 'AES_TIMING', 2: 'AES_ZERO', 3: 'AES_ZERO', 4: 'AES_LEAK',
          5: 'AES_DATA', 6: 'AES_DATA', 7: 'AES_DATA', 8: 'AES_DATA', 9: 'AES_DATA'}


class Plan:
    """Clock-level schedule of the public signals. It never looks at the key or the data, so the
    expected ready/busy/out_valid/progress columns are the same for every secret input; the bench
    compares the core with them on every clock. Ciphertexts come from model.py."""

    def __init__(self):
        self.rows = []
        self.results = 0
        self.reset()

    def reset(self):
        self.round = 0
        self.valid = 0
        self.out = 0
        self.pending = None

    def cycle(self, rst=1, start=0, cancel=0, out_ready=0, key=0, block=0):
        ready = int(self.round == 0 and not self.valid)
        self.rows.append([rst, start, cancel, out_ready, key, block, ready, int(self.round != 0),
                          self.valid, self.round, self.out if self.valid else 0])
        accepted = bool(rst and not cancel and start and ready)
        if not rst or cancel:
            self.reset()
        elif self.valid:
            if out_ready:
                self.results += 1
                self.reset()
        elif self.round == 0:
            if start:
                self.round = 1
                self.pending = MODEL.encrypt(key, block)
        elif self.round == ROUNDS:
            self.round = 0
            self.valid = 1
            self.out = self.pending
        else:
            self.round += 1
        return accepted

    def operation(self, key, block, hold=0, start_while_busy=False, change_inputs=False):
        """Wait for ready, start one encryption, wait for the result, hold it, then take it."""
        while not self.cycle(start=1, key=key, block=block):
            pass
        for step in range(ROUNDS):
            noise = (step + 1) * 0x0101010101010101 if change_inputs else 0
            self.cycle(start=int(start_while_busy), key=key ^ noise, block=block ^ (noise << 64))
        for _ in range(hold):
            self.cycle(start=int(start_while_busy), key=key, block=block)
        self.cycle(out_ready=1)


def boundaries():
    p = Plan()
    p.cycle(rst=0)
    p.cycle()
    p.cycle()
    b, c1 = MODEL.FIPS_APPENDIX_B, MODEL.FIPS_APPENDIX_C1
    p.operation(b['key'], b['block'], hold=3, start_while_busy=True, change_inputs=True)
    p.cycle()
    # Back to back: start is already high on the clock after the result is taken.
    p.operation(c1['key'], c1['block'])
    p.operation(c1['key'], c1['block'] ^ 1)
    for key, block in ((0, 0), (ONES, ONES), (0, b['block']), (b['key'], 0), (ONES, 0)):
        p.operation(key, block, hold=1)
    # Abort while busy, while holding, while idle and together with a start.
    while not p.cycle(start=1, key=b['key'], block=b['block']):
        pass
    for _ in range(4):
        p.cycle()
    p.cycle(cancel=1)
    p.cycle()
    p.operation(c1['key'], c1['block'], hold=2)
    while not p.cycle(start=1, key=b['key'], block=c1['block']):
        pass
    for _ in range(ROUNDS):
        p.cycle()
    p.cycle()
    p.cycle(cancel=1)
    p.cycle()
    p.cycle(cancel=1)
    p.cycle(cancel=1, start=1, key=b['key'], block=b['block'])
    p.cycle()
    # Reset while busy and while holding.
    while not p.cycle(start=1, key=c1['key'], block=b['block']):
        pass
    for _ in range(7):
        p.cycle()
    p.cycle(rst=0)
    p.cycle()
    while not p.cycle(start=1, key=b['key'], block=b['block']):
        pass
    for _ in range(ROUNDS + 2):
        p.cycle()
    p.cycle(rst=0)
    p.cycle()
    p.operation(b['key'], b['block'])
    p.cycle()
    return p


def random_plan(seed, iterations):
    """Uniform 128-bit keys and blocks: no special values, so data-dependent shortcuts stay hidden."""
    rng = random.Random(seed)
    p = Plan()
    p.cycle(rst=0)
    p.cycle()
    for _ in range(iterations):
        key, block = rng.getrandbits(128), rng.getrandbits(128)
        roll = rng.random()
        if roll < 0.1:
            while not p.cycle(start=1, key=key, block=block):
                pass
            for _ in range(rng.randrange(ROUNDS + 3)):
                p.cycle(start=rng.randrange(2), key=rng.getrandbits(128))
            if rng.randrange(2):
                p.cycle(cancel=1)
            else:
                p.cycle(rst=0)
        else:
            p.operation(key, block, hold=rng.randrange(4), start_while_busy=bool(rng.randrange(2)),
                        change_inputs=bool(rng.randrange(2)))
        for _ in range(rng.randrange(3)):
            p.cycle(start=0, key=rng.getrandbits(128), block=rng.getrandbits(128))
    p.cycle()
    return p


def make_cases(args, parameters):
    base = boundaries()

    def case(name, plan, mutation, expected=None, category='functional'):
        return dict(id=name, vectors=plan.rows, counts={'steps': len(plan.rows), 'results': plan.results},
                    mutation=mutation, expected_failure=expected, category=category)
    cases = [case('boundaries', base, args.demo_bug)]
    seeds = range(args.seed, args.seed + (3 if args.profile == 'nightly' else 1))
    for seed in seeds:
        cases.append(case(f'random-seed{seed}', random_plan(seed, args.iterations), args.demo_bug))
    cases += [case(f'detect-mutation{m}', base, m, LABELS[m], 'mutation') for m in range(1, MUTANTS + 1)]
    # Random data never holds the all-zero block, so the data-dependent shortcut survives it.
    cases.append(case('random-misses-mutation1', random_plan(args.seed, args.iterations), 1, None, 'diagnostic'))
    return cases


if __name__ == '__main__':
    spec = importlib.util.spec_from_file_location('runner', HERE.parent / 'local-common/runner.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    sys.exit(module.main(sys.modules[__name__]))

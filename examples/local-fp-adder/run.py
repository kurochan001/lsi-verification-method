#!/usr/bin/env python3
"""Floating-point adder against an exact rational model: every input of an 8-bit format, and binary32 at its borders."""
import importlib.util
from pathlib import Path
import random
import sys

HERE = Path(__file__).resolve().parent
NAME = 'local-fp-adder'
TOP = 'fp_adder_tb'
MUTANTS = 7
CONFIGS = {'small': {'EXP': 4, 'FRAC': 3}, 'binary32': {'EXP': 8, 'FRAC': 23}}
ITERATIONS = {'smoke': 100, 'nightly': 1000}   # rows of 32 operations each, per seed
SOURCES = [HERE / 'rtl/fp_adder.sv', HERE / 'tb/fp_adder_tb.sv']
EXTRA_INPUTS = [HERE / 'model.py']
LABELS = {1: 'FP_FLAGS', 2: 'FP_VALUE', 3: 'FP_VALUE', 4: 'FP_VALUE', 5: 'FP_VALUE', 6: 'FP_VALUE', 7: 'FP_FLAGS'}
EXHAUSTIVE_BITS = 8   # formats up to this width get every operand pair

spec = importlib.util.spec_from_file_location('fp_adder_model', HERE / 'model.py')
M = importlib.util.module_from_spec(spec)
spec.loader.exec_module(M)
ADDERS = {}


def adder(parameters):
    key = parameters['EXP'], parameters['FRAC']
    if key not in ADDERS:
        ADDERS[key] = M.Adder(*key)
    return ADDERS[key]


def row(model, sub, mode, a, operands):
    """One vector row: an operation, a rounding mode, one a and up to 256 values of b with their results.

    Fields: sub, mode, a, count, the b values packed, {result, flags} packed, tag word.
    """
    width = model.fmt.width
    packed_b = packed_r = tags = 0
    if not 0 < len(operands) <= 4096 // (width + 5):
        raise ValueError('row does not fit the vector word')
    for index, b in enumerate(operands):
        code, flags, word = model.compute(sub, mode, a, b)
        packed_b |= b << (index * width)
        packed_r |= (code << 5 | flags) << (index * (width + 5))
        tags |= word
    return [sub, mode, a, len(operands), packed_b, packed_r, tags]


def boundary_vectors(parameters):
    """Every pair of border values, in every rounding mode, added and subtracted."""
    model = adder(parameters)
    codes = M.edges(model.fmt)
    return [row(model, sub, mode, a, codes) for sub in (0, 1) for mode in range(5) for a in codes]


def exhaustive_vectors(parameters, sub, mode):
    model = adder(parameters)
    codes = list(range(1 << model.fmt.width))
    return [row(model, sub, mode, a, codes) for a in codes]


def random_vectors(parameters, seed, rows):
    model = adder(parameters)
    fmt = model.fmt
    rng = random.Random(seed)
    codes = M.edges(fmt)
    mask, top = (1 << fmt.width) - 1, 1 << (fmt.width - 1)

    def near(a):
        """A partner that makes the alignment and the cancellation matter."""
        roll = rng.random()
        if roll < 0.25:
            return (a ^ top) + rng.choice((-2, -1, 0, 1, 2)) & mask          # nearly the negation
        if roll < 0.5:
            sign, exponent, _ = fmt.fields(a)
            other = min(max(exponent + rng.randint(-fmt.frac - 4, fmt.frac + 4), 0), fmt.ones - 1)
            return fmt.pack(rng.randrange(2), other, rng.getrandbits(fmt.frac))
        if roll < 0.7:
            return rng.choice(codes)
        return rng.getrandbits(fmt.width)
    result = []
    for _ in range(rows):
        a = rng.choice(codes) if rng.random() < 0.2 else rng.getrandbits(fmt.width)
        result.append(row(model, rng.randrange(2), rng.randrange(5), a, [near(a) for _ in range(32)]))
    return result


def counts(parameters, rows):
    """What the bench counts from the outputs of the design: operations and the two flags that occur."""
    width = parameters['EXP'] + parameters['FRAC'] + 1
    totals = dict(additions=0, subtractions=0, invalid=0, inexact=0)
    for sub, _, _, count, _, results, _ in rows:
        totals['subtractions' if sub else 'additions'] += count
        for index in range(count):
            flags = results >> (index * (width + 5)) & 31
            totals['invalid'] += flags >> 4 & 1
            totals['inexact'] += flags & 1
    return totals


def make_cases(args, parameters):
    base = boundary_vectors(parameters)
    cases = [dict(id='boundaries', vectors=base, mutation=args.demo_bug, category='functional',
                  expected_failure=None)]
    for seed in range(args.seed, args.seed + (3 if args.profile == 'nightly' else 1)):
        cases.append(dict(id=f'random-seed{seed}', vectors=random_vectors(parameters, seed, args.iterations),
                          mutation=args.demo_bug, category='functional', expected_failure=None))
    if parameters['EXP'] + parameters['FRAC'] + 1 <= EXHAUSTIVE_BITS:
        for mode, name in enumerate(M.MODES):
            for sub in (0, 1):
                cases.append(dict(id=f"exhaustive-{name}-{'sub' if sub else 'add'}",
                                  vectors=exhaustive_vectors(parameters, sub, mode), mutation=args.demo_bug,
                                  category='functional', expected_failure=None))
    for mutation in range(1, MUTANTS + 1):
        cases.append(dict(id=f'detect-mutation{mutation}', vectors=base, mutation=mutation,
                          category='mutation', expected_failure=LABELS[mutation]))
    for case in cases:
        case['counts'] = counts(parameters, case['vectors'])
    return cases


if __name__ == '__main__':
    spec = importlib.util.spec_from_file_location('local_runner', HERE.parent / 'local-common/runner.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    sys.exit(module.main(sys.modules[__name__]))

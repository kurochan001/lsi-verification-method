#!/usr/bin/env python3
"""Renaming, free list and reorder buffer in simulation: flush, precise exceptions, exhaustion and six mutants."""
import importlib.util
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
NAME = 'local-rename-rob'
TOP = 'rename_rob_tb'
MUTANTS = 6
# rob4: the reorder buffer fills first. free3-rob8: the free list empties first.
CONFIGS = {'rob4': {'LREGS': 4, 'PREGS': 10, 'ROB': 4}, 'free3-rob8': {'LREGS': 4, 'PREGS': 7, 'ROB': 8}}
ITERATIONS = {'smoke': 300, 'nightly': 3000}
SOURCES = [HERE / 'rtl/rename_rob.sv', HERE / 'tb/rename_rob_tb.sv']
EXTRA_INPUTS = [HERE / 'model.py']
LABELS = {1: 'RR_LEAK', 2: 'RR_DOUBLE', 3: 'RR_RESTORE', 4: 'RR_READY', 5: 'RR_FLUSH', 6: 'RR_TRAP'}

spec = importlib.util.spec_from_file_location('rename_rob_model', HERE / 'model.py')
MODEL = importlib.util.module_from_spec(spec)
spec.loader.exec_module(MODEL)


def sizes(parameters):
    return parameters['LREGS'], parameters['PREGS'], parameters['ROB']


def make_cases(args, parameters):
    base, base_counts = MODEL.boundary(*sizes(parameters))
    cases = [dict(id='boundaries', vectors=base, counts=base_counts, mutation=args.demo_bug,
                  category='functional', expected_failure=None)]
    for seed in range(args.seed, args.seed + (3 if args.profile == 'nightly' else 1)):
        rows, counts = MODEL.random_rows(*sizes(parameters), seed, args.iterations)
        cases.append(dict(id=f'random-seed{seed}', vectors=rows, counts=counts, mutation=args.demo_bug,
                          category='functional', expected_failure=None))
    for mutation in range(1, MUTANTS + 1):
        cases.append(dict(id=f'detect-mutation{mutation}', vectors=base, counts=base_counts, mutation=mutation,
                          category='mutation', expected_failure=LABELS[mutation]))
    return cases


if __name__ == '__main__':
    spec = importlib.util.spec_from_file_location('local_runner', HERE.parent / 'local-common/runner.py')
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)
    sys.exit(runner.main(sys.modules[__name__]))

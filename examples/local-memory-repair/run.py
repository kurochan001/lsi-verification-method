#!/usr/bin/env python3
"""Memory test, repair analysis with spare rows and columns, fuses, and the test after the repair."""
import importlib.util
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


MODEL = load('memory_repair_model', HERE / 'model.py')
NAME = 'local-memory-repair'
TOP = 'repair_tb'
MUTANTS = 6
CONFIGS = {'s1x1': dict(ROWS=4, COLS=4, SR=1, SC=1), 's2x2': dict(ROWS=8, COLS=8, SR=2, SC=2)}
ITERATIONS = {'smoke': 16, 'nightly': 80}
SOURCES = [HERE / 'rtl/mem_repair.sv', HERE / 'rtl/fuse_bank.sv', HERE / 'tb/repair_tb.sv']
EXTRA_INPUTS = [HERE / 'model.py']
LABELS = {1: 'REPAIR_VERDICT', 2: 'REPAIR_UNREPAIRABLE', 3: 'REPAIR_REMAP', 4: 'REPAIR_COVER',
          5: 'REPAIR_LOAD', 6: 'REPAIR_UNREPAIRABLE'}


def make_cases(args, parameters):
    base = MODEL.boundary_vectors(parameters)
    cases = [dict(id='boundaries', vectors=base, mutation=args.demo_bug, category='functional', expected_failure=None)]
    for seed in range(args.seed, args.seed + (3 if args.profile == 'nightly' else 1)):
        cases.append(dict(id=f'random-seed{seed}', vectors=MODEL.random_vectors(parameters, seed, args.iterations),
                          mutation=args.demo_bug, category='functional', expected_failure=None))
    for mutation, label in LABELS.items():
        cases.append(dict(id=f'detect-mutation{mutation}', vectors=base, mutation=mutation, category='mutation',
                          expected_failure=label))
    for case in cases:
        case['counts'] = MODEL.counts(case['vectors'])
    return cases


if __name__ == '__main__':
    RUNNER = load('local_runner', HERE.parent / 'local-common/runner.py')
    sys.exit(RUNNER.main(sys.modules[__name__]))

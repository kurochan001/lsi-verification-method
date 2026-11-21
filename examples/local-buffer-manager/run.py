#!/usr/bin/env python3
"""Buffer manager with linked queues and a free list in simulation: every buffer in exactly one place, seven mutants."""
import importlib.util
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
NAME = 'local-buffer-manager'
TOP = 'buffer_manager_tb'
MUTANTS = 7
CONFIGS = {'b16-q4': {'NB': 16, 'NQ': 4}, 'b8-q2': {'NB': 8, 'NQ': 2}}
ITERATIONS = {'smoke': 400, 'nightly': 3000}
SOURCES = [HERE / 'rtl/buffer_manager.sv', HERE / 'tb/buffer_manager_tb.sv']
EXTRA_INPUTS = [HERE / 'model.py']
LABELS = {1: 'BM_LEAK', 2: 'BM_RELEASE', 3: 'BM_LINK', 4: 'BM_LINK', 5: 'BM_EMPTY', 6: 'BM_FULL', 7: 'BM_LINK'}

spec = importlib.util.spec_from_file_location('buffer_manager_model', HERE / 'model.py')
MODEL = importlib.util.module_from_spec(spec)
spec.loader.exec_module(MODEL)


def sizes(parameters):
    return parameters['NB'], parameters['NQ']


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

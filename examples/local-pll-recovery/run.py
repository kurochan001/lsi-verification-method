#!/usr/bin/env python3
"""Verify PLL lock qualification, missing clock detection and reset recovery."""
import importlib.util
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


MODEL = load('pll_scenarios', HERE / 'model.py')
NAME = 'local-pll-recovery'
TOP = 'pll_guard_tb'
CONFIGS = {
    'slow-pll': dict(PLL_HALF=17, PLL_PHASE=2, LOCK_CYCLES=5, TIMEOUT=24),
    'fast-pll': dict(PLL_HALF=2, PLL_PHASE=1, LOCK_CYCLES=7, TIMEOUT=16),
}
ITERATIONS = {'smoke': 10, 'nightly': 50}
SOURCES = [HERE / 'rtl/pll_guard.sv', HERE / 'tb/pll_guard_tb.sv']
EXTRA_INPUTS = [HERE / 'model.py']


def make_cases(args, parameters):
    fixed = MODEL.vectors(parameters, args.seed, 0)

    def case(name, rows, mutation, expected=None):
        return dict(id=name, vectors=rows, counts={'steps': len(rows)}, mutation=mutation,
                    expected_failure=expected, category='mutation' if expected else 'functional')

    result = [case('boundaries', fixed, args.demo_bug)]
    seeds = range(args.seed, args.seed + (3 if args.profile == 'nightly' else 1))
    for seed in seeds:
        result.append(case(f'random-seed{seed}', MODEL.vectors(parameters, seed, args.iterations), args.demo_bug))
    for mutation, label in enumerate(('PLL_LOCK_QUALIFY', 'PLL_LOCK_LOSS', 'PLL_STOPPED_RESET', 'PLL_RESET_SYNC'), 1):
        result.append(case(f'mutation-{mutation}', fixed, mutation, label))
    return result


if __name__ == '__main__':
    runner = load('local_runner', HERE.parent / 'local-common/runner.py')
    sys.exit(runner.main(sys.modules[__name__]))

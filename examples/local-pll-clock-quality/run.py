#!/usr/bin/env python3
"""Check PLL clock quality from observed timestamps while the guard stays locked."""
import importlib.util
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


MODEL = load('clock_stimulus', HERE / 'model.py')
NAME = 'local-pll-clock-quality'
TOP = 'pll_clock_quality_tb'
CONFIGS = {}
for period, minimum in ((20000, 8000), (34000, 13500)):
    CONFIGS[f'p{period//1000}ns'] = dict(
        PERIOD_PS=period, MIN_PULSE_PS=minimum,
        PERIOD_TOL_PS=800, TIE_LIMIT_PS=1000, STEP_LIMIT_PS=1200)
ITERATIONS = {'smoke': 48, 'nightly': 256}
MUTANTS = 5
SOURCES = [HERE.parent/'local-pll-recovery/rtl/pll_guard.sv', HERE/'tb/pll_clock_quality_tb.sv']
EXTRA_INPUTS = [HERE/'model.py']
FAULTS = (
    ('short-high', 'PLL_SHORT_HIGH'),
    ('short-low', 'PLL_SHORT_LOW'),
    ('period', 'PLL_PERIOD'),
    ('phase-drift', 'PLL_TIE'),
    ('cycle-step', 'PLL_CYCLE_STEP'),
)


def make_cases(args, parameters):
    def case(name, seed, intervals, fault, expected=None):
        rows = MODEL.vectors(parameters, seed, intervals, fault)
        return dict(id=name, vectors=rows, counts={'steps': len(rows)}, mutation=0,
                    expected_failure=expected, category='mutation' if expected else 'functional')

    result = [case('boundaries', args.seed, 0, args.demo_bug)]
    seeds = range(args.seed, args.seed + (3 if args.profile == 'nightly' else 1))
    for seed in seeds:
        result.append(case(f'random-seed{seed}', seed, args.iterations, args.demo_bug))
    for fault, (label, failure) in enumerate(FAULTS, 1):
        result.append(case(f'detect-{label}', args.seed, 0, fault, failure))
    return result


if __name__ == '__main__':
    runner = load('local_runner', HERE.parent / 'local-common/runner.py')
    sys.exit(runner.main(sys.modules[__name__]))

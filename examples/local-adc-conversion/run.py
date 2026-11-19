#!/usr/bin/env python3
"""Verify sampled ADC codes, conversion timing, backpressure and reset."""
import importlib.util
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


MODEL = load('adc_oracle', HERE / 'model.py')
NAME = 'local-adc-conversion'
TOP = 'adc_capture_tb'
CONFIGS = {
    'acq2-conv4': dict(BITS=8, LSB_UV=1000, ACQUIRE=2, CONVERT=4),
    'acq1-conv1': dict(BITS=8, LSB_UV=750, ACQUIRE=1, CONVERT=1),
}
ITERATIONS = {'smoke': 100, 'nightly': 800}
SOURCES = [HERE / 'rtl/adc_capture.sv', HERE / 'tb/adc_capture_tb.sv']
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
    for mutation, label in enumerate(('ADC_CODE', 'ADC_CODE', 'ADC_VALID', 'ADC_BUSY'), 1):
        result.append(case(f'mutation-{mutation}', fixed, mutation, label))
    return result


if __name__ == '__main__':
    runner = load('local_runner', HERE.parent / 'local-common/runner.py')
    sys.exit(runner.main(sys.modules[__name__]))

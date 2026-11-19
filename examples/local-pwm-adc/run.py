#!/usr/bin/env python3
"""Verify center-aligned PWM sampling events and their end-to-end ADC results."""
import importlib.util
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
ADC = HERE.parent / 'local-adc-conversion'


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


MODEL = load('pwm_oracle', HERE / 'model.py')
ADC_ORACLE = load('adc_oracle', ADC / 'model.py').AdcOracle
NAME = 'local-pwm-adc'
TOP = 'pwm_adc_tb'
CONFIGS = {
    'period16': dict(HALF_PERIOD=8, ACQUIRE=2, CONVERT=4),
    'period10': dict(HALF_PERIOD=5, ACQUIRE=1, CONVERT=2),
}
ITERATIONS = {'smoke': 128, 'nightly': 1024}
MUTANTS = 5
SOURCES = [ADC / 'rtl/adc_capture.sv', HERE / 'rtl/pwm_adc_trigger.sv', HERE / 'tb/pwm_adc_tb.sv']
EXTRA_INPUTS = [HERE / 'model.py', ADC / 'model.py']


def make_cases(args, parameters):
    fixed = MODEL.vectors(parameters, ADC_ORACLE, args.seed, 0)

    def case(name, rows, mutation, expected=None):
        return dict(id=name, vectors=rows, counts={'steps': len(rows)}, mutation=mutation,
                    expected_failure=expected, category='mutation' if expected else 'functional')

    result = [case('boundaries', fixed, args.demo_bug)]
    seeds = range(args.seed, args.seed + (3 if args.profile == 'nightly' else 1))
    for seed in seeds:
        rows = MODEL.vectors(parameters, ADC_ORACLE, seed, args.iterations)
        result.append(case(f'random-seed{seed}', rows, args.demo_bug))
    labels = ('PWM_TRIGGER', 'PWM_CONFIG', 'PWM_TRIGGER', 'PWM_CONFIG', 'PWM_TRIGGER')
    for mutation, label in enumerate(labels, 1):
        result.append(case(f'mutation-{mutation}', fixed, mutation, label))
    return result


if __name__ == '__main__':
    runner = load('local_runner', HERE.parent / 'local-common/runner.py')
    sys.exit(runner.main(sys.modules[__name__]))

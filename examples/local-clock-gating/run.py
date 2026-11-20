#!/usr/bin/env python3
"""Clock gate, glitch-free clock switch and odd divider, judged from the real edge times of their outputs."""
import importlib.util
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


MODEL = load('clock_gating_model', HERE / 'model.py')
NAME = 'local-clock-gating'
TOP = 'clock_gating_tb'
CONFIGS = {'a10-b14-div3': dict(PERIOD_A=10000, PERIOD_B=14000, DIV=3),
           'a16-b10-div5': dict(PERIOD_A=16000, PERIOD_B=10000, DIV=5)}
ITERATIONS = {'smoke': 24, 'nightly': 160}
MUTANTS = 5
SOURCES = [HERE / 'rtl/clock_gate.sv', HERE / 'rtl/clock_switch.sv', HERE / 'rtl/odd_divider.sv',
           HERE / 'tb/clock_gating_tb.sv']
EXTRA_INPUTS = [HERE / 'model.py']
# Mutant: (what is wrong, the check that must report it)
FAULTS = {1: ('and-gate', 'CG_SHORT_HIGH'), 2: ('latch-polarity', 'CG_SHORT_HIGH'),
          3: ('plain-mux', 'CS_SHORT_HIGH'), 4: ('no-break-before-make', 'CS_OVERLAP'),
          5: ('single-edge-divider', 'DIV_DUTY')}


def make_cases(args, parameters):
    def case(name, seed, operations, mutation, expected=None):
        rows, counts = MODEL.vectors(parameters, seed, operations)
        return dict(id=name, vectors=rows, counts=counts, mutation=mutation, expected_failure=expected,
                    category='mutation' if expected else 'functional')

    cases = [case('boundaries', args.seed, 0, args.demo_bug)]
    for seed in range(args.seed, args.seed + (3 if args.profile == 'nightly' else 1)):
        cases.append(case(f'random-seed{seed}', seed, args.iterations, args.demo_bug))
    for mutation, (_, label) in FAULTS.items():
        cases.append(case(f'detect-mutation{mutation}', args.seed, 0, mutation, label))
    return cases


if __name__ == '__main__':
    runner = load('local_runner', HERE.parent / 'local-common/runner.py')
    sys.exit(runner.main(sys.modules[__name__]))

#!/usr/bin/env python3
"""Reset and unknown values in simulation: power-up from X and from chosen values, and two mutants that X-optimism hides."""
import importlib.util
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
NAME = 'local-reset-x-formal'
TOP = 'reset_x_tb'
MUTANTS = 6
CONFIGS = {'stages3': {'WIDTH': 8, 'STAGES': 3}, 'stages2': {'WIDTH': 4, 'STAGES': 2}}
ITERATIONS = {'smoke': 300, 'nightly': 3000}
SOURCES = [HERE / 'rtl/reset_x_unit.sv', HERE / 'tb/reset_x_tb.sv']
EXTRA_INPUTS = [HERE / 'model.py']
# Seen from X: the unknown value reaches a compared output, or the behaviour is wrong with any start.
LABELS = {1: 'RX_COUNT', 2: 'RX_ODD', 3: 'RX_READY', 6: 'RX_COUNT'}
# Not seen from X: an if or a case on the unknown flush counter takes the branch that resets.
# Not seen from all ones either: the flush counter must be 0 at power-up for the reset to be skipped.
HIDDEN = (4, 5)
# Seen with the flush counter at 0 and the flags at 1 before the first clock edge.
MIXED = {4: 'RX_ERR', 5: 'RX_COUNT'}

spec = importlib.util.spec_from_file_location('reset_x_model', HERE / 'model.py')
MODEL = importlib.util.module_from_spec(spec)
spec.loader.exec_module(MODEL)


def make_cases(args, parameters):
    size = parameters['WIDTH'], parameters['STAGES']

    def case(name, power, mutation=args.demo_bug, category='functional', expected=None):
        rows, counts = MODEL.boundary(*size, power)
        return dict(id=name, vectors=rows, counts=counts, mutation=mutation, category=category,
                    expected_failure=expected)
    cases = [case('boundaries-power-x', None), case('boundaries-power-zeros', MODEL.ZEROS),
             case('boundaries-power-ones', MODEL.ONES), case('boundaries-power-mixed', MODEL.MIXED)]
    for seed in range(args.seed, args.seed + (3 if args.profile == 'nightly' else 1)):
        rows, counts = MODEL.random_rows(*size, seed, args.iterations)
        cases.append(dict(id=f'random-seed{seed}', vectors=rows, counts=counts, mutation=args.demo_bug,
                          category='functional', expected_failure=None))
    cases += [case(f'detect-mutation{m}', None, m, 'mutation', LABELS[m]) for m in sorted(LABELS)]
    cases += [case(f'x-hides-mutation{m}', None, m, 'diagnostic') for m in HIDDEN]
    cases += [case(f'ones-hides-mutation{m}', MODEL.ONES, m, 'diagnostic') for m in HIDDEN]
    cases += [case(f'mixed-detect-mutation{m}', MODEL.MIXED, m, 'mutation', MIXED[m]) for m in sorted(MIXED)]
    return cases


if __name__ == '__main__':
    spec = importlib.util.spec_from_file_location('local_runner', HERE.parent / 'local-common/runner.py')
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)
    sys.exit(runner.main(sys.modules[__name__]))

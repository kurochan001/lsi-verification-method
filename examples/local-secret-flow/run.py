#!/usr/bin/env python3
"""Two copies with different secrets and the same public inputs: the outputs the policy calls public must agree."""
import importlib.util
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
NAME = 'local-secret-flow'
TOP = 'secret_flow_tb'
MUTANTS = 5
CONFIGS = {'kw8': {'KW': 8}, 'kw16': {'KW': 16}}
ITERATIONS = {'smoke': 300, 'nightly': 2000}
SOURCES = [HERE / 'rtl/secret_block.sv', HERE / 'tb/secret_flow_tb.sv']
EXTRA_INPUTS = [HERE / 'model.py']
# The first check each leak breaks in the fixed scenario: always a flow check between the copies.
LABELS = {1: 'SF_FLOW_SCAN', 2: 'SF_FLOW_DBG', 3: 'SF_FLOW_ERR', 4: 'SF_FLOW_ERASED', 5: 'SF_FLOW_STATUS'}
# With the same secret in both copies, no flow can show; only the comparison with the model sees the leak.
EQUAL_LABELS = {2: 'SF_DBG'}

spec = importlib.util.spec_from_file_location('secret_flow_model', HERE / 'model.py')
MODEL = importlib.util.module_from_spec(spec)
spec.loader.exec_module(MODEL)


def make_cases(args, parameters):
    kw = parameters['KW']

    def case(name, steps, mutation=args.demo_bug, category='functional', expected=None):
        rows, counts = MODEL.vectors(kw, steps)
        return dict(id=name, vectors=rows, counts=counts, mutation=mutation, category=category,
                    expected_failure=expected)
    fixed = MODEL.boundaries(kw)
    cases = [case('boundaries', fixed)]
    for seed in range(args.seed, args.seed + (3 if args.profile == 'nightly' else 1)):
        cases.append(case(f'random-seed{seed}', MODEL.random_steps(kw, seed, args.iterations)))
    cases += [case(f'detect-mutation{m}', fixed, m, 'mutation', LABELS[m]) for m in sorted(LABELS)]
    equal = MODEL.boundaries(kw, equal=True)
    cases += [case(f'equal-secrets-detect-mutation{m}', equal, m, 'mutation', EQUAL_LABELS[m]) for m in sorted(EQUAL_LABELS)]
    return cases


if __name__ == '__main__':
    spec = importlib.util.spec_from_file_location('local_runner', HERE.parent / 'local-common/runner.py')
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)
    sys.exit(runner.main(sys.modules[__name__]))

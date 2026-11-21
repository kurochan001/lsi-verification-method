#!/usr/bin/env python3
"""OTP controller with three copies and a lock row, losses of power, stuck cells and the lifecycle it loads."""
import importlib.util
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
NAME = 'local-otp-fuse'
TOP = 'otp_tb'
MUTANTS = 7
CONFIGS = {'prog3': {'NW': 16, 'WB': 8, 'PROG': 3}, 'prog5': {'NW': 16, 'WB': 8, 'PROG': 5}}
ITERATIONS = {'smoke': 150, 'nightly': 600}
LIFECYCLE = HERE.parent / 'local-secure-lifecycle/rtl/secure_lifecycle.sv'
SOURCES = [HERE / 'rtl/otp_ctrl.sv', HERE / 'rtl/otp_lifecycle_top.sv', LIFECYCLE, HERE / 'tb/otp_tb.sv']
EXTRA_INPUTS = [HERE / 'model.py']
LABELS = {1: 'OTP_LOCKED', 2: 'OTP_DATA', 3: 'OTP_FLAG', 4: 'OTP_ORDER', 5: 'OTP_PULSE', 6: 'OTP_RESET',
          7: 'LC_STATE'}

spec = importlib.util.spec_from_file_location('otp_model', HERE / 'model.py')
MODEL = importlib.util.module_from_spec(spec)
spec.loader.exec_module(MODEL)


def sizes(parameters):
    return parameters['NW'], parameters['WB'], parameters['PROG']


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

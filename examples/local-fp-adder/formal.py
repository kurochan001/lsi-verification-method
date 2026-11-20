#!/usr/bin/env python3
"""Floating-point adder proved equal, for every operand pair and mode, to an exact wide sum rounded once."""
import importlib.util
from pathlib import Path
import sys
HERE = Path(__file__).resolve().parent
TOP = 'fp_adder_formal'
CONFIGS = {'e4f3': dict(EXP=4, FRAC=3), 'e5f4': dict(EXP=5, FRAC=4)}
BOUND = 8          # the design is combinational: one step holds every case
TIMEOUT = 1200
MUTANTS = 7
SOURCES = [HERE / 'rtl/fp_adder.sv', HERE / 'fp_adder_formal.sv']
SCOPE = ('Proof, for every pair of operand codes, both operations and the five rounding modes, that the '
         'result and the flags equal those of a reference that adds exact integers and rounds once. '
         'Formats of 8 bits (exponent 4, fraction 3) and 10 bits (exponent 5, fraction 4). '
         'Rounding mode codes 5 to 7 are excluded by an assumption.')
COVERS = {'cp_tie', 'cp_carry', 'cp_overflow_finite', 'cp_subnormal', 'cp_negative_zero',
          'cp_invalid_infinities', 'cp_cancellation'}
FAILURES = {1: 'ap_flags', 2: 'ap_result', 3: 'ap_result', 4: 'ap_result', 5: 'ap_result', 6: 'ap_result', 7: 'ap_flags'}


def properties(parameters, case):
    only = case['parameters']['ONLY']
    asserts = {'ap_result', 'ap_flags'} - ({'ap_flags'} if only == 1 else {'ap_result'} if only == 2 else set())
    return {'assert': asserts, 'assume': {'as_mode'}, 'cover': COVERS}


def plan(bound, demo_bug):
    def case(name, mode='prove', expect='PASS', mutation=0, category='normal', failure=None):
        return dict(id=name, mode=mode, expect=expect, depth=bound, category=category, failure=failure,
                    parameters=dict(MUTATION=mutation, ONLY=0 if failure is None else 1 if failure == 'ap_result' else 2))
    return [case('adder-proof', mutation=demo_bug), case('scenario-cover', 'cover')] + [
        case(f'detect-mutation{m}', 'bmc', 'FAIL', m, 'mutation', FAILURES[m]) for m in range(1, MUTANTS + 1)]


if __name__ == '__main__':
    spec = importlib.util.spec_from_file_location('formal_runner', HERE.parent / 'local-formal-common/runner.py')
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    sys.exit(m.main(sys.modules[__name__]))

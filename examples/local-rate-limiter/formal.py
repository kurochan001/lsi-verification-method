#!/usr/bin/env python3
"""Token bucket: the window bound over every interval, proved by induction, and what it cannot see."""
import importlib.util
from pathlib import Path
import sys
HERE = Path(__file__).resolve().parent
TOP = 'rate_limiter_formal'
CONFIGS = {'f2d2r3': dict(FRAC=2, DEPTH_W=2, RATE_W=3), 'f3d3r4': dict(FRAC=3, DEPTH_W=3, RATE_W=4)}
BOUND = 16
PROOF_DEPTH = 3
TIMEOUT = 300
MUTANTS = 5
SOURCES = [HERE / 'rtl/token_bucket.sv', HERE / 'rate_limiter_formal.sv']
SCOPE = ('Unbounded proof by k-induction that, for every window that starts at any cycle out of '
         'reset and lasts any length up to the next reset, cost * grants <= cap at the start + the '
         'refill of every later cycle of the window, for every request, depth and rate sequence. '
         'A second proof keeps only the window bound and its lemma. Bounded checks show which '
         'mutants the window bound alone refutes and which it cannot see.')
WINDOW = {'ap_window'}
LEMMA = {'ai_slack'}
STEPS = {'ap_grant', 'ap_level', 'ap_reset'}
COVERS = {'cp_burst', 'cp_carry', 'cp_short', 'cp_clamp', 'cp_zero_rate'}
# First property broken by a bounded check from reset, with every check and with the window only.
FAILURES = {1: 'ap_grant', 2: 'ap_grant', 3: 'ap_grant', 4: 'ap_grant', 5: 'ap_level'}
WINDOW_REFUTES = (1, 3, 4)          # mutants that grant more than the bound allows
WINDOW_BLIND = (2, 5)               # mutants that grant less: the bound still holds


def properties(parameters, case):
    checks = case['parameters']['CHECKS']
    asserts = WINDOW | (LEMMA if checks != 2 else set()) | (STEPS if checks == 0 else set())
    return {'assert': asserts, 'assume': {'as_initial_reset'}, 'cover': COVERS if checks == 0 else set()}


def plan(bound, demo_bug):
    def case(name, mode='prove', expect='PASS', mutation=0, category='normal', failure=None, checks=0):
        return dict(id=name, mode=mode, expect=expect, depth=PROOF_DEPTH if mode == 'prove' else bound,
                    category=category, failure=failure, parameters=dict(MUTATION=mutation, CHECKS=checks))
    return ([case('full-proof', mutation=demo_bug), case('window-proof', mutation=demo_bug, checks=1),
             case('scenario-cover', 'cover')] +
            [case(f'detect-mutation{m}', 'bmc', 'FAIL', m, 'mutation', FAILURES[m]) for m in range(1, MUTANTS + 1)] +
            [case(f'window-refutes-mutation{m}', 'bmc', 'FAIL', m, 'mutation', 'ap_window', 2) for m in WINDOW_REFUTES] +
            # The bound is proved, not only checked to a depth, for the mutants that grant less.
            [case(f'window-blind-mutation{m}', 'prove', 'PASS', m, 'diagnostic', None, 1) for m in WINDOW_BLIND])


if __name__ == '__main__':
    spec = importlib.util.spec_from_file_location('formal_runner', HERE.parent / 'local-formal-common/runner.py')
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    sys.exit(m.main(sys.modules[__name__]))

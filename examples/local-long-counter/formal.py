#!/usr/bin/env python3
"""Long counter proved by induction, at 32 and 64 bits, equal to one full-width addition per step."""
import importlib.util
from pathlib import Path
import sys
HERE = Path(__file__).resolve().parent
TOP = 'long_counter_formal'
CONFIGS = {'w32': dict(WIDTH=32, SPLIT=16), 'w64': dict(WIDTH=64, SPLIT=16)}
BOUND = 16
PROOF_DEPTH = 3   # one step is compared at a time; two more steps let the checks that wait for reset take part
TIMEOUT = 300
MUTANTS = 6
SOURCES = [HERE / 'rtl/long_counter.sv', HERE / 'long_counter_formal.sv']
SCOPE = ('Unbounded proof by k-induction, for every count value, limit and input sequence, that each '
         'clock edge gives the count and the tick of the specification (reset, clear, test load, '
         'return to 0 at the limit, plus 1 modulo 2**WIDTH), with the carry chain cut at bit 16 and '
         'again at bit 24. WIDTH = 32 and 64. A second proof keeps test_mode low.')
ASSERTS = {'ap_reset', 'ap_count', 'ap_tick', 'ai_carry'}
COVERS = {'cp_wrap', 'cp_rollover', 'cp_low_carry', 'cp_stage_carry', 'cp_top_carry', 'cp_pause'}
# The flag invariant breaks one step before the count does, so it is what a bounded check reports
# for the two mutants that corrupt the flag.
FAILURES = {1: 'ap_count', 2: 'ap_tick', 3: 'ap_count', 4: 'ap_count', 5: 'ai_carry', 6: 'ai_carry'}


def properties(parameters, case):
    assumes = {'as_initial_reset'} | ({'as_functional'} if case['parameters']['FUNCTIONAL'] else set())
    return {'assert': ASSERTS, 'assume': assumes, 'cover': COVERS}


def plan(bound, demo_bug):
    def case(name, mode='prove', expect='PASS', mutation=0, category='normal', failure=None, functional=0):
        return dict(id=name, mode=mode, expect=expect, depth=PROOF_DEPTH if mode == 'prove' else bound,
                    category=category, failure=failure, parameters=dict(MUTATION=mutation, FUNCTIONAL=functional))
    return [case('counter-proof', mutation=demo_bug), case('functional-proof', mutation=demo_bug, functional=1),
            case('scenario-cover', 'cover')] + [
        case(f'detect-mutation{m}', 'bmc', 'FAIL', m, 'mutation', FAILURES[m]) for m in range(1, MUTANTS + 1)] + [
        # Without the test path, a bounded check from reset stops far short of bit 23.
        case('bounded-misses-mutation3', 'bmc', 'PASS', 3, 'diagnostic', functional=1)]


if __name__ == '__main__':
    spec = importlib.util.spec_from_file_location('formal_runner', HERE.parent / 'local-formal-common/runner.py')
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    sys.exit(m.main(sys.modules[__name__]))

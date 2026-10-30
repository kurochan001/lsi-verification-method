#!/usr/bin/env python3
"""Top-K selection by a sorting network, proved for every score vector, with four mutants."""
import importlib.util
from pathlib import Path
import sys
HERE = Path(__file__).resolve().parent
TOP = 'topk_formal'
CONFIGS = {'n4-k2': dict(N=4, K=2), 'n8-k3': dict(N=8, K=3)}
BOUND = 8
PROOF_DEPTH = 4  # the base case must reach a checked valid result: reset, input, output, check
TIMEOUT = 600     # the N=8 proof takes about two minutes here
SOURCES = [HERE / 'rtl/topk_select.sv', HERE / 'topk_formal.sv']
SCOPE = ('Unbounded proof that each registered result is the stable top-K of the previous scores, '
         'for every signed 8-bit score vector. One output register, no backpressure, synchronous reset.')
ASSERTS = {'ap_valid', 'ap_index', 'ap_distinct', 'ap_sorted', 'ap_ties', 'ap_topk'}
COVERS = {'cp_all_equal', 'cp_boundary_tie', 'cp_all_negative', 'cp_ascending', 'cp_max_last', 'cp_min_selected'}
FAILURES = {1: 'ap_ties', 2: 'ap_topk', 3: 'ap_index', 4: 'ap_topk'}


def properties(parameters, case):
    return {'assert': ASSERTS, 'assume': {'as_initial_reset'}, 'cover': COVERS}


def plan(bound, demo_bug):
    def case(name, mode='prove', expect='PASS', mutation=0, category='normal', failure=None):
        return dict(id=name, mode=mode, expect=expect, depth=PROOF_DEPTH if mode == 'prove' else bound,
                    category=category, failure=failure, parameters=dict(MUTATION=mutation))
    return [case('topk-proof', mutation=demo_bug), case('scenario-cover', 'cover')] + [
        case(f'detect-mutation{m}', 'bmc', 'FAIL', m, 'mutation', FAILURES[m]) for m in range(1, 5)]


if __name__ == '__main__':
    spec = importlib.util.spec_from_file_location('formal_runner', HERE.parent / 'local-formal-common/runner.py')
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    sys.exit(m.main(sys.modules[__name__]))

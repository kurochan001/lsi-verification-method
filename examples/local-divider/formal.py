#!/usr/bin/env python3
"""Iterative divider proved equal to Verilog / and % for every operand at 4 and 8 bits, with four mutants."""
import importlib.util
from pathlib import Path
import sys
HERE = Path(__file__).resolve().parent
TOP = 'divider'
CONFIGS = {'w4': dict(W=4), 'w8': dict(W=8)}
BOUND = 16        # a full 8-bit division with a flush on its last step fits in 12 steps
PROOF_DEPTH = 12  # the base case contains a whole 8-bit division, so a wrong result fails there
TIMEOUT = 600
SOURCES = [HERE / 'rtl/divider.sv']
SCOPE = ('Unbounded proof, for every operand pair and every input sequence, that each result '
         'equals Verilog / and % with the RISC-V special cases, arrives after the specified '
         'latency, is held under backpressure and is discarded by flush and reset. W = 4 and 8.')
ASSERTS = {'ap_reset', 'ap_flush', 'ap_hold', 'ap_latency', 'ap_quotient', 'ap_remainder',
           'ai_exclusive', 'ai_operands', 'ai_signs', 'ai_age', 'ai_partial'}
COVERS = {'cp_zero', 'cp_overflow', 'cp_equal', 'cp_mixed', 'cp_unsigned_top', 'cp_hold', 'cp_flush_last'}
FAILURES = {1: 'ap_quotient', 2: 'ap_remainder', 3: 'ap_latency', 4: 'ap_flush'}


def properties(parameters, case):
    return {'assert': ASSERTS, 'assume': {'as_initial_reset'}, 'cover': COVERS}


def plan(bound, demo_bug):
    def case(name, mode='prove', expect='PASS', mutation=0, category='normal', failure=None):
        return dict(id=name, mode=mode, expect=expect, depth=PROOF_DEPTH if mode == 'prove' else bound,
                    category=category, failure=failure, parameters=dict(MUTATION=mutation))
    return [case('divider-proof', mutation=demo_bug), case('scenario-cover', 'cover')] + [
        case(f'detect-mutation{m}', 'bmc', 'FAIL', m, 'mutation', FAILURES[m]) for m in range(1, 5)]


if __name__ == '__main__':
    spec = importlib.util.spec_from_file_location('formal_runner', HERE.parent / 'local-formal-common/runner.py')
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    sys.exit(m.main(sys.modules[__name__]))

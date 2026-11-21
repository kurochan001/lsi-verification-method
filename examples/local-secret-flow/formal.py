#!/usr/bin/env python3
"""No flow from the key to scan, debug and error outputs, proved by self-composition of two copies."""
import importlib.util
from pathlib import Path
import sys
HERE = Path(__file__).resolve().parent
TOP = 'secret_flow_formal'
CONFIGS = {'kw8': dict(KW=8), 'kw16': dict(KW=16)}
BOUND = 12
PROOF_DEPTH = 4
TIMEOUT = 300
SOURCES = [HERE / 'rtl/secret_block.sv', HERE / 'secret_flow_formal.sv']
SCOPE = ('Unbounded proof by k-induction over two copies that share every input except the written key: '
         'status, error record and the result while it is not valid never differ; the scan output never differs '
         'in production; the debug read data differs only for a development key read or a valid result read; '
         'after reset, erase or production scan entry nothing differs, outputs or internal key and result registers, '
         'until a key is written again. Only the initial reset is assumed. One clock, synchronous reset, '
         'two-valued, digital port values and cycles only: no power, timing or fault side channel.')
PORTS = {'ap_status', 'ap_scan', 'ap_dbg', 'ap_err', 'ap_ct', 'ap_erased'}
INTERNAL = {'ap_erased_internal'}
AUX = {'ai_copies', 'ai_clean_idle', 'ai_clean_secret', 'ai_prod_scan'}
COVERS = {'cp_ct_differs', 'cp_prod_ct_read', 'cp_dev_key_read', 'cp_dev_scan_differs', 'cp_prod_denied',
          'cp_no_key', 'cp_prod_scan_shift', 'cp_erased_dev_read'}
# The property each leak breaks first. Mutant 4 is seen at the ports only in development.
FAILURES = {1: 'ap_scan', 2: 'ap_dbg', 3: 'ap_err', 4: 'ap_erased', 5: 'ap_status'}


def properties(parameters, case):
    p = case['parameters']
    asserts = PORTS | (INTERNAL if p['INTERNAL'] else set()) | (AUX if p['AUX'] else set())
    assumes = {'as_initial_reset'} | ({'as_prod'} if p['PROD_ONLY'] else set())
    return {'assert': asserts, 'assume': assumes, 'cover': COVERS}


def plan(bound, demo_bug):
    def case(name, mode, expect='PASS', mutation=0, category='normal', failure=None, aux=0, internal=0, prod_only=0):
        return dict(id=name, mode=mode, expect=expect, depth=PROOF_DEPTH if mode == 'prove' else bound,
                    category=category, failure=failure,
                    parameters=dict(MUTATION=mutation, AUX=aux, INTERNAL=internal, PROD_ONLY=prod_only))
    cases = [case('flow-proof', 'prove', mutation=demo_bug, aux=1, internal=1),
             case('scenario-cover', 'cover', aux=1, internal=1)]
    cases += [case(f'detect-mutation{m}', 'bmc', 'FAIL', m, 'mutation', FAILURES[m]) for m in sorted(FAILURES)]
    # In production the left-over copy never reaches a port: the port checks pass, the internal check fails.
    cases += [case('prod-ports-miss-mutation4', 'bmc', 'PASS', 4, 'diagnostic', prod_only=1),
              case('prod-internal-detect-mutation4', 'bmc', 'FAIL', 4, 'mutation', 'ap_erased_internal',
                   internal=1, prod_only=1)]
    return cases


if __name__ == '__main__':
    spec = importlib.util.spec_from_file_location('formal_runner', HERE.parent / 'local-formal-common/runner.py')
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    sys.exit(m.main(sys.modules[__name__]))

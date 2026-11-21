#!/usr/bin/env python3
"""Prove that the AES-128 core's public timing does not depend on the key or the data, and that it clears."""
import importlib.util
from pathlib import Path
import sys
HERE = Path(__file__).resolve().parent
TOP = 'aes_ct_formal'
CONFIGS = {'core': {}}
BOUND = 16   # the first result appears at step 13; holding it and starting the next take one more step each
PROOF_DEPTH = 3   # the invariants inside the core are checked from the second clock; one more step lets them take part
TIMEOUT = 600
SOURCES = [HERE / 'rtl/aes128_core.sv', HERE / 'aes_ct_formal.sv']
SCOPE = ('Unbounded self-composition proof by k-induction: two copies of the core with the same reset, start, '
         'cancel and out_ready and independent keys and blocks give equal ready, busy, out_valid and progress on '
         'every clock. In each copy, an idle core holds zero state, round key and round constant, a held result '
         'has a zero round key, and out_block is zero while out_valid is low. Ciphertext values are not part of '
         'this proof; they are checked by the simulation against an independent model. This is a cycle-level '
         'property of the digital ports, not a statement about power or electromagnetic leakage.')
ASSERTS = {'ap_timing', 'ai_round', 'ai_idle_clear', 'ai_valid_clear', 'ai_gate'}
COVERS = {'cp_done', 'cp_cancel_busy', 'cp_hold', 'cp_back_to_back'}
FAILURES = {1: 'ap_timing', 2: 'ai_idle_clear', 3: 'ai_idle_clear', 4: 'ai_gate'}


def properties(parameters, case):
    return {'assert': ASSERTS, 'assume': {'as_initial_reset'}, 'cover': COVERS}


def plan(bound, demo_bug):
    def case(name, mode='prove', expect='PASS', mutation=0, category='normal', failure=None):
        return dict(id=name, mode=mode, expect=expect, depth=PROOF_DEPTH if mode == 'prove' else bound,
                    category=category, failure=failure, parameters={'MUTATION': mutation})
    return [case('constant-time-proof', mutation=demo_bug), case('scenario-cover', 'cover')] + [
        case(f'detect-mutation{m}', 'bmc', 'FAIL', m, 'mutation', FAILURES[m]) for m in FAILURES] + [
        # A wrong MixColumns coefficient changes every ciphertext but not the timing: the proof holds.
        case('timing-proof-misses-mutation7', mutation=7, category='diagnostic')]


if __name__ == '__main__':
    spec = importlib.util.spec_from_file_location('formal_runner', HERE.parent / 'local-formal-common/runner.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    sys.exit(module.main(sys.modules[__name__]))

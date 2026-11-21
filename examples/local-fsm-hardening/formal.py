#!/usr/bin/env python3
"""Hardened access lock: proofs that bit flips on any edge never grant and always reach ERROR."""
import importlib.util
from pathlib import Path
import sys
HERE = Path(__file__).resolve().parent
TOP = 'fsm_hardening_formal'
CONFIGS = {'tries3': dict(MAX_TRIES=3), 'tries2': dict(MAX_TRIES=2)}
BOUND = 16
PROOF_DEPTH = 3
TIMEOUT = 300
MUTANTS = 8
SOURCES = [HERE / 'rtl/hardened_lock.sv', HERE / 'fsm_hardening_formal.sv']
SCOPE = ('Unbounded proof by k-induction, for every input sequence and every flip mask of at most '
         'one bit on every clock edge outside reset, that the hardened lock grants only where the '
         'lock without faults grants, matches it until the first flip, and is in ERROR from the '
         'second edge after the first flip until reset. Two-bit flips of the state code are proved '
         'too; two-bit flips that include the counter, three-bit flips of the state code and the '
         'binary code have counterexamples. MAX_TRIES = 3 and 2.')
ASSERTS = {'ap_match', 'ap_no_escalation', 'ap_detect'}
AIDS = {'ai_age', 'ai_clean', 'ai_first', 'ai_after'}
COVERS = {'cp_recovered_open', 'cp_lockout', 'cp_grant_removed', 'cp_count_flip_detected', 'cp_flip_in_error'}
FAILURES = {1: 'ap_no_escalation', 2: 'ap_detect', 3: 'ap_detect', 4: 'ap_detect',
            5: 'ap_match', 6: 'ap_detect', 7: 'ap_match', 8: 'ap_no_escalation'}


def properties(parameters, case):
    p = case['parameters']
    asserts = ASSERTS - ({'ap_detect'} if p['ESCALATION_ONLY'] else set())
    if p['PROOF_AIDS'] and p['HARDENED']:
        asserts = asserts | AIDS
    return {'assert': asserts, 'assume': {'as_initial_reset', 'as_fault_shape'}, 'cover': COVERS}


def plan(bound, demo_bug):
    def case(name, mode='prove', expect='PASS', category='normal', failure=None, hardened=1, mutation=0,
             bits=1, state_only=0, aids=0, escalation_only=0):
        return dict(id=name, mode=mode, expect=expect, depth=PROOF_DEPTH if mode == 'prove' else bound,
                    category=category, failure=failure,
                    parameters=dict(HARDENED=hardened, MUTATION=mutation, FAULT_BITS=bits, STATE_ONLY=state_only,
                                    PROOF_AIDS=aids, ESCALATION_ONLY=escalation_only))
    return [case('single-flip-proof', mutation=demo_bug, aids=1),
            case('scenario-cover', 'cover'),
            # Outside the guarantee: two bits of the state code still cannot make a valid code.
            case('double-state-flip-proof', category='diagnostic', bits=2, state_only=1, aids=1),
            # The same bit of the counter and of its copy: the pair agrees, and a key past the limit opens.
            case('double-counter-flip-escalates', 'bmc', 'FAIL', 'counterexample', 'ap_no_escalation',
                 bits=2, escalation_only=1),
            # ERROR is three bits from every state: a first flip into ERROR, then three bits into OPEN.
            case('triple-state-flip-escalates', 'bmc', 'FAIL', 'counterexample', 'ap_no_escalation',
                 bits=3, state_only=1),
            # The same lock with binary codes: LOCKED and OPEN are one bit apart.
            case('binary-code-escalates', 'bmc', 'FAIL', 'counterexample', 'ap_no_escalation', hardened=0)] + [
        case(f'detect-mutation{m}', 'bmc', 'FAIL', 'mutation', FAILURES[m], mutation=m) for m in range(1, MUTANTS + 1)]


if __name__ == '__main__':
    spec = importlib.util.spec_from_file_location('formal_runner', HERE.parent / 'local-formal-common/runner.py')
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    sys.exit(m.main(sys.modules[__name__]))

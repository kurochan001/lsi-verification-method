#!/usr/bin/env python3
"""8b/10b proved by induction: decode(encode(x)) = x, encode(decode(c)) = c for every accepted code, and the line properties."""
import importlib.util
from pathlib import Path
import sys
HERE = Path(__file__).resolve().parent
TOP = 'linecode_formal'
CONFIGS = {'codec': {}}
BOUND = 8
PROOF_DEPTH = 2
TIMEOUT = 300
MUTANTS = 7      # the two mutants of the word aligner are outside this harness
SOURCES = [HERE / 'rtl/enc_8b10b_comb.sv', HERE / 'rtl/enc_8b10b.sv', HERE / 'rtl/dec_8b10b_comb.sv',
           HERE / 'rtl/dec_8b10b.sv', HERE / 'linecode_formal.sv']
SCOPE = ('Unbounded proof by k-induction, for every character, both running disparities and every '
         'sequence of characters, idle cycles and resets: the decoder returns what the encoder was given, '
         'without an error; every ten-bit code the decoder accepts for a disparity is the code the encoder '
         'sends for the decoded character and that disparity; code weight, stream disparity, the longest '
         'run inside a code and across two codes, and the positions of the comma. The word aligner is not '
         'part of this proof.')
FORWARD = {'ai_rd_equal', 'ai_previous', 'ap_k_err', 'ap_roundtrip', 'ap_disparity', 'ap_run', 'ap_comma', 'ap_rd_step'}
BACKWARD = {'ap_accept', 'ap_other', 'ap_dec_rd'}
FORWARD_COVERS = {'cp_comma_minus', 'cp_comma_plus', 'cp_d7_plus', 'cp_alternate_7', 'cp_run_across', 'cp_false_comma'}
BACKWARD_COVERS = {'cp_disparity_error', 'cp_balanced_reject'}
ALL, FORWARD_ONLY, BACKWARD_ONLY, OTHER_ONLY = 0, 1, 2, 3
# Mutants of the encoder are shown against the forward side, mutants of the decoder against the backward side.
FAILURES = {1: (FORWARD_ONLY, 'ap_roundtrip'), 2: (FORWARD_ONLY, 'ap_roundtrip'), 3: (FORWARD_ONLY, 'ap_rd_step'),
            4: (FORWARD_ONLY, 'ap_roundtrip'), 5: (BACKWARD_ONLY, 'ap_accept'), 6: (OTHER_ONLY, 'ap_other'),
            7: (BACKWARD_ONLY, 'ap_dec_rd')}
# Mutant 6 can break ap_accept or ap_other, depending on the counterexample the solver picks
# (macOS and Linux picked different ones), so its task checks ap_other alone.
# The round trip never shows the decoder a code the encoder does not send: these decoder mutants pass it.
FORWARD_BLIND = (5, 6, 7)


def properties(parameters, case):
    side = case['parameters']['SIDE']
    forward = side in (ALL, FORWARD_ONLY)
    backward = {ALL: BACKWARD, BACKWARD_ONLY: BACKWARD, OTHER_ONLY: {'ap_other'}}.get(side, set())
    return {'assert': (FORWARD if forward else set()) | backward,
            'assume': {'as_initial_reset'},
            'cover': (FORWARD_COVERS if forward else set()) | (BACKWARD_COVERS if side != FORWARD_ONLY else set())}


def plan(bound, demo_bug):
    def case(name, mode='prove', expect='PASS', mutation=0, category='normal', failure=None, side=ALL):
        return dict(id=name, mode=mode, expect=expect, depth=PROOF_DEPTH if mode == 'prove' else bound,
                    category=category, failure=failure, parameters=dict(MUTATION=mutation, SIDE=side))
    return [case('codec-proof', mutation=demo_bug), case('scenario-cover', 'cover')] + [
        case(f'detect-mutation{m}', 'bmc', 'FAIL', m, 'mutation', FAILURES[m][1], FAILURES[m][0])
        for m in range(1, MUTANTS + 1)] + [
        case(f'forward-misses-mutation{m}', mutation=m, category='diagnostic', side=FORWARD_ONLY) for m in FORWARD_BLIND]


if __name__ == '__main__':
    spec = importlib.util.spec_from_file_location('formal_runner', HERE.parent / 'local-formal-common/runner.py')
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    sys.exit(m.main(sys.modules[__name__]))

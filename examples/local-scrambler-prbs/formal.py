#!/usr/bin/env python3
"""One bit per clock and W bits per clock proved equal, for the generator, the scrambler, the descrambler and the checker."""
import importlib.util
from pathlib import Path
import sys
HERE = Path(__file__).resolve().parent
TOP = 'scrambler_prbs_formal'
CONFIGS = {'n7-w8': dict(N=7, TAP=6, W=8), 'n31-w8': dict(N=31, TAP=28, W=8), 'n58-w8': dict(N=58, TAP=39, W=8)}
# Bounded depth for the mutants and the covers. After reset both taps of the 58-bit history read
# the reset value for 39 bits, so a wrong tap or a wrong history first shows in the fifth word.
BOUND = 48
# Induction depth: one word plus two clocks, so that every window of that length starts at or
# before a word boundary where the two states are compared.
PROOF_DEPTH = 10
TIMEOUT = 600
SOURCES = [HERE / 'rtl/prbs_gen.sv', HERE / 'rtl/prbs_check.sv', HERE / 'rtl/ss_scrambler.sv',
           HERE / 'rtl/ss_descrambler.sv', HERE / 'scrambler_prbs_formal.sv']
SCOPE = ('Unbounded proof by k-induction that W clocks of the one-bit module and one clock of the '
         'W-bit module give the same output bits in the same order and reach the same state, for '
         'every state, word, valid pattern and reset. Modules: PRBS generator, self-synchronizing '
         'scrambler and descrambler, PRBS checker. Polynomials x^7+x^6+1, x^31+x^28+1 and '
         'x^58+x^39+1, each at W=8. The proof compares two descriptions of the same recurrence; it says '
         'nothing about the polynomial or the lock rules being the intended ones.')
TARGETS = {'gen': 0, 'scr': 1, 'dsc': 2, 'chk': 3}
ASSERTS = {'ap_word', 'ai_state'}
COVERS = {'cp_word', 'cp_idle_word', 'cp_two_words', 'cp_reset_after_run'}
# (target, mutant, the property that the shortest counterexample breaks)
MUTANTS = [('gen', 1, 'ap_word'), ('gen', 4, 'ai_state'), ('scr', 8, 'ai_state'), ('scr', 11, 'ai_state'),
           ('dsc', 9, 'ap_word')]


def properties(parameters, case):
    return {'assert': ASSERTS, 'assume': {'as_initial_reset'}, 'cover': COVERS}


def plan(bound, demo_bug):
    def case(name, target, mode='prove', expect='PASS', mutation=0, category='normal', failure=None):
        return dict(id=name, mode=mode, expect=expect, depth=PROOF_DEPTH if mode == 'prove' else bound,
                    category=category, failure=failure, parameters=dict(TARGET=TARGETS[target], MUTATION=mutation))
    cases = [case(f'{t}-proof', t, mutation=demo_bug if t == 'gen' else 0) for t in TARGETS]
    cases.append(case('scenario-cover', 'gen', 'cover'))
    cases += [case(f'detect-mutation{m}', t, 'bmc', 'FAIL', m, 'mutation', f) for t, m, f in MUTANTS]
    return cases


if __name__ == '__main__':
    spec = importlib.util.spec_from_file_location('formal_runner', HERE.parent / 'local-formal-common/runner.py')
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    sys.exit(m.main(sys.modules[__name__]))

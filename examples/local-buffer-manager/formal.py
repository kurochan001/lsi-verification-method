#!/usr/bin/env python3
"""Buffer manager: every buffer is free, in exactly one queue, or held, proved for all input sequences."""
import importlib.util
from pathlib import Path
import sys
HERE = Path(__file__).resolve().parent
TOP = 'buffer_manager'
# Four buffers with two and with four queues. With eight buffers the proof did not finish in
# several minutes; that size is checked in simulation only.
CONFIGS = {'b4-q2': dict(NB=4, NQ=2), 'b4-q4': dict(NB=4, NQ=4)}
BOUND = 14
PROOF_DEPTH = 2
TIMEOUT = 600
SOURCES = [HERE / 'rtl/buffer_manager.sv']
SCOPE = ('Unbounded proof by k-induction, for every sequence of enqueues, dequeues and releases after an '
         'initial reset, all three possible in one cycle: one buffer chosen freely is free, in exactly one '
         'queue, or held; every nonempty list ends at its tail; a release, a dequeue and an enqueue are taken '
         'only for a held buffer, a nonempty queue and a nonempty free list. Four buffers with two and with '
         'four queues. Buffer contents are not modelled.')
PROPERTIES = {'ap_no_leak', 'ap_no_double', 'ap_tail', 'ap_release_held', 'ap_deq_nonempty', 'ap_enq_room'}
AUXILIARY = {'ai_distinct', 'ai_disjoint', 'ai_cover', 'ai_counts'}
ASSERTS = PROPERTIES | AUXILIARY
COVERS = {'cp_full', 'cp_same_one', 'cp_free_swap', 'cp_refused_release', 'cp_three'}
# The check that the counterexample of each mutant must violate.
FAILURES = {1: 'ai_cover', 2: 'ap_release_held', 3: 'ap_tail', 4: 'ap_tail', 5: 'ap_deq_nonempty',
            6: 'ap_enq_room', 7: 'ap_tail'}


def properties(parameters, case):
    return {'assert': ASSERTS, 'assume': {'as_initial_reset'}, 'cover': COVERS}


def plan(bound, demo_bug):
    def case(name, mode='prove', expect='PASS', mutation=0, category='normal', failure=None):
        return dict(id=name, mode=mode, expect=expect, depth=PROOF_DEPTH if mode == 'prove' else bound,
                    category=category, failure=failure, parameters=dict(MUTATION=mutation))
    return [case('conservation-proof', mutation=demo_bug), case('scenario-cover', 'cover')] + [
        case(f'detect-mutation{m}', 'bmc', 'FAIL', m, 'mutation', FAILURES[m]) for m in sorted(FAILURES)]


if __name__ == '__main__':
    spec = importlib.util.spec_from_file_location('formal_runner', HERE.parent / 'local-formal-common/runner.py')
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    sys.exit(m.main(sys.modules[__name__]))

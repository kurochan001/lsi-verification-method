#!/usr/bin/env python3
"""Renaming, free list and reorder buffer: every physical register is in exactly one place, proved for all input sequences."""
import importlib.util
from pathlib import Path
import sys
HERE = Path(__file__).resolve().parent
TOP = 'rename_rob'
# rob4: the reorder buffer fills first (six spare registers, four entries).
# free3: the free list empties first (three spare registers, four entries).
CONFIGS = {'rob4': dict(LREGS=4, PREGS=10, ROB=4), 'free3': dict(LREGS=4, PREGS=7, ROB=4)}
BOUND = 12
PROOF_DEPTH = 4
TIMEOUT = 600
SOURCES = [HERE / 'rtl/rename_rob.sv']
SCOPE = ('Unbounded proof by k-induction, for every sequence of allocations, completions, flushes and '
         'commits after an initial reset: each physical register is free, mapped, or kept by exactly one '
         'reorder buffer entry; a walk restores the mapping; committed values change only by retirement. '
         'Four logical registers; 10 physical with 4 entries, and 7 physical with 8 entries. '
         'One allocation and one retirement per cycle. Values of instructions in flight are not proved.')
PROPERTIES = {'ap_no_leak', 'ap_no_double', 'ap_owner', 'ap_restore', 'ap_stall', 'ap_trap',
              'ap_flush_keeps', 'ap_committed_stable'}
AUXILIARY = {'ai_chain', 'ai_range', 'ai_count'}
ASSERTS = PROPERTIES | AUXILIARY
COVERS = {'cp_stall', 'cp_retire_alloc', 'cp_undo_same', 'cp_trap_younger', 'cp_reuse'}
# The check that the counterexample of each mutant must violate.
FAILURES = {1: 'ap_no_leak', 2: 'ap_no_double', 3: 'ap_restore', 4: 'ap_stall', 5: 'ap_flush_keeps', 6: 'ap_trap'}


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

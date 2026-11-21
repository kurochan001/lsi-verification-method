#!/usr/bin/env python3
"""Follow one freely chosen item through a FIFO, an AXI4-Stream FIFO and a width converter, proved for all input sequences."""
import importlib.util
from pathlib import Path
import sys
HERE = Path(__file__).resolve().parent
TOP = 'data_integrity_formal'
# One configuration: the target, its depth and the checks compiled in are parameters of each task.
CONFIGS = {'one-item': {}}
BOUND = 24
PROOF_DEPTH = 4
TIMEOUT = 300
SOURCES = [HERE.parent / 'local-fifo/rtl/sync_fifo.sv', HERE.parent / 'local-axis/rtl/axis_packet_fifo.sv',
           HERE / 'rtl/width_downsizer.sv', HERE / 'data_integrity_formal.sv']
SCOPE = ('Unbounded proof by k-induction, for every input sequence after an initial reset, that one arbitrary '
         'item (anyconst value, anyseq choice among equal values) leaves unchanged, once, after exactly the '
         'items accepted before it. Synchronous FIFO of 3 and 12 entries with 8-bit data, AXI4-Stream FIFO of '
         '2 and 4 beats of 37 bits, 16-to-8 width converter holding one word. Single clock, two-valued. '
         'Internal registers are reached by flattening and connecting, and the invariants about them are '
         'asserted, not assumed. Liveness is not proved: only that held data is offered in the same cycle.')
TARGETS = {'fifo': 0, 'axis': 1, 'width': 2}
CHECKS = {'ap_content', 'ap_no_spurious', 'ap_no_overflow'}
AUXILIARY = {'fifo': {'ai_count', 'ai_pointer', 'ai_slot'}, 'axis': {'ai_count', 'ai_pointer', 'ai_slot'},
             'width': {'ai_state', 'ai_slot'}}
COVERS = {'fifo': {'cp_start', 'cp_wait', 'cp_exit', 'cp_last_slot', 'cp_through'},
          'axis': {'cp_start', 'cp_wait', 'cp_exit', 'cp_sparse_last', 'cp_through'},
          'width': {'cp_low', 'cp_high', 'cp_handoff', 'cp_stall'}}
# Internal registers of the unmodified designs, by the name of the harness wire they are connected to.
REGISTERS = {'fifo': {'x_rd_ptr': 'rd_ptr', 'x_wr_ptr': 'wr_ptr'},
             'axis': {'x_head': 'head', 'x_tail': 'tail', 'x_count': 'count'},
             'width': {'x_busy': 'busy', 'x_phase': 'phase', 'x_word': 'word'}}
MEMORY_WIDTH = {'fifo': 8, 'axis': 37}
# Mutant -> the check its shortest counterexample violates.
DETECTED = {
    'fifo3': {1: 'ap_content', 2: 'ap_no_overflow', 3: 'ap_no_spurious'},
    'axis4': {1: 'ap_content', 2: 'ap_content', 3: 'ap_content', 4: 'ap_no_overflow'},
    'width': {1: 'ap_content', 2: 'ap_no_overflow', 3: 'ap_content', 4: 'ap_content', 5: 'ap_available', 6: 'ap_available'},
}
SHAPES = {'fifo3': ('fifo', 3), 'fifo12': ('fifo', 12), 'axis2': ('axis', 2), 'axis4': ('axis', 4), 'width': ('width', 3)}


def target_of(case):
    return next(name for name, number in TARGETS.items() if number == case['parameters']['TARGET'])


def properties(parameters, case):
    target = target_of(case)
    p = case['parameters']
    return {'assert': CHECKS | ({'ap_available'} if p['AVAILABLE'] else set()) | (AUXILIARY[target] if p['AUXILIARY'] else set()),
            'assume': {'as_initial_reset'}, 'cover': COVERS[target]}


def connections(case):
    """Yosys commands that give the harness the registers of the flattened design."""
    target = target_of(case)
    prefix = f'{target}.check.'
    lines = [f'connect -set {prefix}{wire} {prefix}dut.{register}' for wire, register in REGISTERS[target].items()]
    if target in MEMORY_WIDTH:
        width = MEMORY_WIDTH[target]
        lines += [f'connect -set {prefix}x_memory[{(i + 1) * width - 1}:{i * width}] {prefix}dut.memory[{i}]'
                  for i in range(case['parameters']['DEPTH'])]
    return lines


def prepare(parameters, case):
    names = ' '.join(p.name for p in SOURCES)
    chparam = 'chparam ' + ' '.join(f'-set {k} {v}' for k, v in case['parameters'].items()) + ' ' + TOP
    return '\n'.join([f'read -formal -sv {names}', chparam, f'hierarchy -top {TOP}', 'proc', 'flatten', 'memory_map',
                      *connections(case)]) + '\n'


def plan(bound, demo_bug):
    def case(shape, name, mode='prove', expect='PASS', mutation=0, category='normal', failure=None, depth=None,
             auxiliary=1, available=1, sideband=1):
        target, entries = SHAPES[shape]
        return dict(id=f'{shape}-{name}', mode=mode, expect=expect, category=category, failure=failure,
                    depth=depth or (PROOF_DEPTH if mode == 'prove' else bound),
                    parameters=dict(TARGET=TARGETS[target], DEPTH=entries, MUTATION=mutation, AUXILIARY=auxiliary,
                                    AVAILABLE=available, SIDEBAND=sideband))
    cases = [case(shape, 'integrity-proof', mutation=demo_bug if shape == 'axis4' else 0) for shape in SHAPES]
    cases += [case(shape, 'tracking-cover', 'cover') for shape in ('fifo3', 'axis4', 'width')]
    for shape, table in DETECTED.items():
        cases += [case(shape, f'detect-mutation{m}', 'bmc', 'FAIL', m, 'mutation', label, auxiliary=0)
                  for m, label in sorted(table.items())]
    cases += [
        # A bounded check passes although the design overwrites data: twelve writes do not fit in ten cycles.
        case('fifo12', 'bound10-misses-mutation2', 'bmc', mutation=2, category='diagnostic', depth=10, auxiliary=0),
        case('fifo12', 'detect-mutation2', 'bmc', 'FAIL', 2, 'mutation', 'ap_no_overflow', auxiliary=0),
        # Following TDATA alone proves a design whose TLAST or TKEEP is wrong.
        case('axis4', 'data-only-misses-mutation1', mutation=1, category='diagnostic', sideband=0),
        case('axis4', 'data-only-misses-mutation2', mutation=2, category='diagnostic', sideband=0),
        # Without the availability check the proof holds for a design that never offers some words.
        case('width', 'tracking-only-misses-mutation5', mutation=5, category='diagnostic', available=0),
    ]
    return cases


if __name__ == '__main__':
    spec = importlib.util.spec_from_file_location('formal_runner', HERE.parent / 'local-formal-common/runner.py')
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    sys.exit(m.main(sys.modules[__name__]))

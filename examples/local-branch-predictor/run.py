#!/usr/bin/env python3
"""Branch prediction on the RV32I pipeline: every predictor retires what the ISS retires, and the counters match."""
import importlib.util
from pathlib import Path
import random
import sys

HERE = Path(__file__).resolve().parent
CORE = HERE.parent / 'local-riscv-iss'
spec = importlib.util.spec_from_file_location('riscv_iss_run', CORE / 'run.py')
BASE = importlib.util.module_from_spec(spec)
spec.loader.exec_module(BASE)
ISS = BASE.ISS
NAME = 'local-branch-predictor'
TOP = 'core_tb'
CONFIGS = {'none': {'PREDICT': 0}, 'static': {'PREDICT': 1}, 'dynamic': {'PREDICT': 2}}
ITERATIONS = {'smoke': 300, 'nightly': 2000}  # instructions in each random program
SOURCES = BASE.SOURCES
EXTRA_INPUTS = [CORE / 'iss.py', CORE / 'run.py']
LOOP_EXIT, SHADOW = 1 << 13, 1 << 14  # coverage bits beyond the ISS example's tags
# Expected first failing check of mutations 5 to 8 in each configuration; None means the
# mutant cannot change anything there, so it must pass (a diagnostic).
LABELS = {'none': {5: None, 6: None, 7: None, 8: None},
          'static': {5: 'ISS_FLOW', 6: 'ISS_PERF', 7: 'ISS_PERF', 8: 'ISS_FLOW'},
          'dynamic': {5: 'ISS_FLOW', 6: 'ISS_PERF', 7: None, 8: 'ISS_FLOW'}}
BRANCH, JAL, JALR = 0x63, 0x6f, 0x67


def branch_offset(insn):
    return ISS.sext((insn >> 31) << 12 | (insn >> 7 & 1) << 11 | (insn >> 25 & 0x3f) << 5 | (insn >> 8 & 0xf) << 1, 13)


def predicted_taken(insn, predict):
    """The static predictors as the core defines them: none, or JAL and backward branches taken."""
    op = insn & 0x7f
    return predict == 1 and (op == JAL or (op == BRANCH and branch_offset(insn) < 0))


def counters(trace, predict):
    """Resolved branches and jumps, and the flushes a static predictor causes (direction misses)."""
    ctrl = flush = 0
    for r in trace:
        op = r.insn & 0x7f
        if op in (BRANCH, JAL, JALR):
            ctrl += 1
            flush += (r.taken if op == BRANCH else True) != predicted_taken(r.insn, predict)
    return ctrl, flush


def dynamic_flushes(trace):
    """The flushes of dynamic prediction. Exact while branches that share a counter (pc bits 5:2)
    are at least three retired instructions apart: a branch then reads its counter in IF after
    the one before it has updated the counter in EX."""
    bht, last, flush = [1] * 16, {}, 0  # weakly not taken, as the core resets them
    for i, r in enumerate(trace):
        op = r.insn & 0x7f
        if op == BRANCH:
            index = r.pc >> 2 & 15
            if i - last.get(index, -3) < 3:
                raise ValueError(f'branches at {trace[last[index]].pc:#x} and {r.pc:#x} share a counter too closely')
            last[index] = i
            flush += r.taken != (bht[index] >= 2)
            bht[index] = min(bht[index] + 1, 3) if r.taken else max(bht[index] - 1, 0)
        elif op == JALR:
            flush += 1
    return flush


def predictor_vectors(program, data, wait, predict):
    """The ISS example's rows, two more coverage tags, and the expected counters."""
    rows = BASE.vectors(program, data, wait)
    words = {r[1]: r[2] for r in rows if r[0] == 0}
    trace = ISS.execute(ISS.assemble(program), data)
    retired = [r for r in rows if r[0] == 3]
    for row, rec in zip(retired, trace):
        if rec.insn & 0x7f == BRANCH:
            offset = branch_offset(rec.insn)
            if offset < 0 and not rec.taken:
                row[8] |= LOOP_EXIT
            shadow = words.get((rec.pc >> 2) + 2, 0)
            if rec.taken and offset > 0 and (shadow & 0x7f == JAL or (shadow & 0x7f == BRANCH and branch_offset(shadow) < 0)):
                row[8] |= SHADOW  # from the instruction words alone; PREDICT decides what IF does with it
    ctrl, flush = counters(trace, predict)
    return rows + [[4, ctrl, flush, int(predict != 2)] + [0] * 7]


def directed_program():
    """Loops, forward branches both ways, a predicted jump in the shadow of a miss, JALR."""
    base = ISS.BASE
    return [
        ('addi', 10, 0, base), ('addi', 2, 0, 0), ('addi', 9, 0, 0),  # registers are read only after a write
        ('addi', 1, 0, 6), 'loop1:', ('addi', 2, 2, 3), ('addi', 1, 1, -1), ('bne', 1, 0, 'loop1'),
        ('addi', 3, 0, 3), 'outer:', ('addi', 4, 0, 3), 'inner:', ('addi', 4, 4, -1), ('bne', 4, 0, 'inner'),
        ('addi', 3, 3, -1), ('bne', 3, 0, 'outer'),
        ('beq', 0, 0, 'f1'), ('addi', 5, 0, 99), 'f1:', ('bne', 0, 0, 'f2'), ('addi', 5, 0, 1), 'f2:',
        ('beq', 0, 0, 's1'), ('addi', 6, 0, 99), ('jal', 0, 'bad'), 's1:',
        ('beq', 0, 0, 's2'), ('addi', 6, 0, 98), ('bne', 0, 1, 'loop1'), 's2:',
        ('addi', 7, 0, 8), 'alt:', ('andi', 8, 7, 1), ('beq', 8, 0, 'even'), ('addi', 9, 9, 1), 'even:',
        ('addi', 7, 7, -1), ('bne', 7, 0, 'alt'),
        ('sw', 2, 0, 10), ('lw', 1, 0, 10), ('beq', 1, 2, 'f3'), ('addi', 5, 0, 97), 'f3:',
        ('jal', 1, 'f4'), ('addi', 5, 0, 96), 'f4:',
        'here:', ('auipc', 5, 0), ('jalr', 6, ('off', 'f5', 'here'), 5), ('addi', 5, 0, 95), 'f5:',
        ('ebreak',), 'bad:', ('addi', 5, 0, 94), ('ebreak',)]


def counter_program():
    """Where dynamic_flushes is exact: counters saturate both ways and keep their direction after
    one opposite outcome; branches 64 bytes apart share a counter, 4 and 32 bytes apart do not."""
    program = []

    def fill(address):  # NOPs up to a byte address, to put the next branch on a chosen counter
        program.extend([('addi', 0, 0, 0)] * ((address - 4 * sum(not isinstance(x, str) for x in program)) // 4))
    program += [('addi', 2, 0, 0), ('addi', 3, 0, 2), 'outer:', ('addi', 1, 0, 6), 'up:', ('addi', 1, 1, -1), ('addi', 2, 2, 1),
                ('bne', 1, 0, 'up'), ('addi', 3, 3, -1), ('addi', 2, 2, 1), ('bne', 3, 0, 'outer')]
    program += [('addi', 1, 0, 5), 'down:', ('bne', 0, 0, 'bad'), ('addi', 1, 1, -1), ('addi', 2, 2, 1), ('bne', 1, 0, 'down')]
    fill(0x7c)
    program += [('addi', 1, 0, 4), 'far:', ('beq', 0, 0, 'far1'), 'far1:']
    fill(0xa0)
    program += [('bne', 0, 0, 'bad'), ('addi', 1, 1, -1), ('addi', 2, 2, 1), ('bne', 1, 0, 'far')]
    fill(0xbc)
    program += [('addi', 1, 0, 4), 'near:', ('beq', 0, 0, 'near1'), 'near1:', ('bne', 0, 0, 'bad'), ('addi', 1, 1, -1),
                ('addi', 2, 2, 1), ('bne', 1, 0, 'near')]
    fill(0x138)
    program += [('beq', 0, 0, 'share')]
    fill(0x170)
    program += ['share:', ('addi', 2, 2, 1), ('addi', 2, 2, 1), ('beq', 0, 0, 'jumps'), 'jumps:', ('jal', 0, 'j1'), ('addi', 2, 0, 99), 'j1:',
                'here:', ('auipc', 5, 0), ('jalr', 0, ('off', 'j2', 'here'), 5), ('addi', 2, 0, 98), 'j2:',
                ('ebreak',), 'bad:', ('addi', 2, 0, 97), ('ebreak',)]
    return program


def counter_vectors():
    """The case that checks the flushes of dynamic prediction, with their exact count."""
    program, data = counter_program(), [0] * ISS.DATA_WORDS
    rows = BASE.vectors(program, data, lambda access, trace, i: 0)
    trace = ISS.execute(ISS.assemble(program), data)
    return rows + [[4, counters(trace, 2)[0], dynamic_flushes(trace), 1] + [0] * 7]


def boundary_vectors(predict):
    def wait(access, trace, i):
        return access % 4
    return predictor_vectors(directed_program(), ISS.directed_data(), wait, predict)


def random_vectors(seed, count, predict):
    rng = random.Random(seed)
    program, data = ISS.random_program(rng, count, loops=True), ISS.random_data(rng)
    return predictor_vectors(program, data, lambda access, trace, i: rng.choice((1, 2, 3)) if rng.random() < 0.25 else 0,
                             predict)


def make_cases(args, parameters):
    predict = parameters['PREDICT']
    configuration = next(k for k, v in CONFIGS.items() if v['PREDICT'] == predict)
    base = boundary_vectors(predict)
    demo = args.demo_bug + 4 if args.demo_bug else 0  # --demo-bug 1..4 selects mutations 5..8 of the core
    cases = [dict(id='boundaries', vectors=base, mutation=demo, category='functional', expected_failure=None)]
    for seed in range(args.seed, args.seed + (3 if args.profile == 'nightly' else 1)):
        cases.append(dict(id=f'random-seed{seed}', vectors=random_vectors(seed, args.iterations, predict),
                          mutation=demo, category='functional', expected_failure=None))
    exact = counter_vectors() if predict == 2 else None  # only here do the flushes of dynamic prediction have an expected value
    if exact:
        cases.append(dict(id='counters', vectors=exact, mutation=demo, category='functional', expected_failure=None))
    for mutation, label in LABELS[configuration].items():
        if label:
            cases.append(dict(id=f'detect-mutation{mutation}', vectors=exact if exact and label == 'ISS_PERF' else base,
                              mutation=mutation, category='mutation', expected_failure=label))
        else:
            cases.append(dict(id=f'unaffected-mutation{mutation}', vectors=base, mutation=mutation,
                              category='diagnostic', expected_failure=None))
    for case in cases:
        case['counts'] = BASE.counts(case['vectors'])
    return cases


if __name__ == '__main__':
    spec = importlib.util.spec_from_file_location('local_runner', HERE.parent / 'local-common/runner.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    sys.exit(module.main(sys.modules[__name__]))

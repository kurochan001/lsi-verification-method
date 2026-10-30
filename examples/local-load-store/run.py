#!/usr/bin/env python3
"""Byte, halfword and word loads and stores on the RV32I pipeline, compared with the ISS."""
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
NAME = 'local-load-store'
TOP = 'core_tb'
CONFIGS = {'rv32i': {}}
ITERATIONS = {'smoke': 300, 'nightly': 2000}  # instructions in each random program
SOURCES = BASE.SOURCES
EXTRA_INPUTS = [CORE / 'iss.py', CORE / 'run.py']
LSU_TAGS = ['lsu/negative-subword-load', 'lsu/subword-store-then-word-load', 'lsu/subword-load-use',
            'lsu/odd-byte', 'lsu/upper-half']  # coverage bits 15 to 19 of the bench
SUBWORD = {'lb', 'lh', 'lbu', 'lhu', 'sb', 'sh'}
LABELS = {9: 'ISS_DATA', 10: 'ISS_DATA', 11: 'ISS_DATA', 12: 'ISS_DATA'}


def lsu_tags(trace):
    """Per retired instruction, the sub-word situations it exercises (program order)."""
    bit = {name: 1 << (15 + i) for i, name in enumerate(LSU_TAGS)}
    last_store = {}  # data word -> name of the store that last wrote it
    tags = []
    for i, r in enumerate(trace):
        name, t = ISS.name_of(r.insn), 0
        if r.kind:
            index = r.addr >> 2
            if name in ('lb', 'lh') and r.data >> 31:
                t |= bit['lsu/negative-subword-load']
            if name == 'lw' and last_store.get(index) in ('sb', 'sh'):
                t |= bit['lsu/subword-store-then-word-load']
            if name in ('lb', 'lbu', 'sb') and r.addr & 1:
                t |= bit['lsu/odd-byte']
            if name in ('lh', 'lhu', 'sh') and r.addr & 2:
                t |= bit['lsu/upper-half']
            if r.kind == 2:
                last_store[index] = name
            if name in ('lb', 'lh', 'lbu', 'lhu') and r.rd and i + 1 < len(trace) and r.rd in ISS.sources(trace[i + 1].insn):
                t |= bit['lsu/subword-load-use']
        tags.append(t)
    return tags


def lsu_vectors(program, data, wait):
    rows = BASE.vectors(program, data, wait, required=ISS.LOAD_STORE)
    trace = ISS.execute(ISS.assemble(program), data)
    for row, t in zip((r for r in rows if r[0] == 3), lsu_tags(trace)):
        row[8] |= t
    return rows


def directed_program():
    """The ISS example's fixed program (every word instruction), then every size at every lane,
    signs at the edges, and sub-word stores merged into words."""
    word_program = ISS.directed_program()
    assert word_program[-1] == ('ebreak',)
    return word_program[:-1] + [
        ('addi', 10, 0, ISS.BASE),
        ('lui', 4, 0x12345), ('addi', 4, 4, 0x678),        # 0x12345678
        ('lui', 5, 0xfedcc), ('addi', 5, 5, -0x568),       # 0xfedcba98
        ('addi', 1, 0, 0x80), ('addi', 2, 0, -1), ('lui', 3, 0x8), ('addi', 3, 3, -0x100),  # 0x80, -1, 0x7f00
        ('sw', 4, 0, 10), ('lb', 6, 0, 10), ('lb', 6, 1, 10), ('lb', 6, 2, 10), ('lb', 6, 3, 10),
        ('lbu', 6, 0, 10), ('lbu', 6, 1, 10), ('lbu', 6, 2, 10), ('lbu', 6, 3, 10),
        ('lh', 6, 0, 10), ('lh', 6, 2, 10), ('lhu', 6, 0, 10), ('lhu', 6, 2, 10),
        ('sw', 5, 4, 10), ('lb', 7, 4, 10), ('lb', 7, 5, 10), ('lb', 7, 6, 10), ('lb', 7, 7, 10),
        ('lbu', 7, 7, 10), ('lh', 7, 4, 10), ('lh', 7, 6, 10), ('lhu', 7, 6, 10),
        ('sw', 0, 8, 10), ('sb', 1, 8, 10), ('sb', 2, 9, 10), ('sb', 3, 10, 10), ('sb', 4, 11, 10), ('lw', 8, 8, 10),
        ('sw', 0, 12, 10), ('sh', 3, 12, 10), ('sh', 5, 14, 10), ('lw', 8, 12, 10),
        ('lb', 9, 5, 10), ('add', 12, 9, 0),               # a sub-word load used at once
        ('lhu', 9, 6, 10), ('add', 12, 9, 9),
        ('lb', 13, 6, 10), ('sb', 13, 17, 10), ('lw', 14, 16, 10),
        ('lb', 0, 1, 10), ('add', 15, 0, 0),
        ('ebreak',)]


def boundary_vectors():
    return lsu_vectors(directed_program(), ISS.directed_data(), lambda access, trace, i: access % 4)


def random_vectors(seed, count):
    rng = random.Random(seed)
    program, data = ISS.random_program(rng, count, subword=True), ISS.random_data(rng)
    return lsu_vectors(program, data, lambda access, trace, i: rng.choice((1, 2, 3)) if rng.random() < 0.25 else 0)


def make_cases(args, parameters):
    base = boundary_vectors()
    demo = args.demo_bug + 8 if args.demo_bug else 0  # --demo-bug 1..4 selects mutations 9..12 of the core
    cases = [dict(id='boundaries', vectors=base, mutation=demo, category='functional', expected_failure=None)]
    for seed in range(args.seed, args.seed + (3 if args.profile == 'nightly' else 1)):
        cases.append(dict(id=f'random-seed{seed}', vectors=random_vectors(seed, args.iterations),
                          mutation=demo, category='functional', expected_failure=None))
    for mutation, label in LABELS.items():
        cases.append(dict(id=f'detect-mutation{mutation}', vectors=base, mutation=mutation,
                          category='mutation', expected_failure=label))
    for case in cases:
        case['counts'] = BASE.counts(case['vectors'])
    return cases


if __name__ == '__main__':
    spec = importlib.util.spec_from_file_location('local_runner', HERE.parent / 'local-common/runner.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    sys.exit(module.main(sys.modules[__name__]))

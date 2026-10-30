#!/usr/bin/env python3
"""Precise exceptions, an external interrupt and MRET on the RV32I pipeline, compared with the ISS."""
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
NAME = 'local-riscv-traps'
TOP = 'core_tb'
CONFIGS = {'traps': {'TRAPS': 1, 'PREDICT': 0}, 'traps-predict': {'TRAPS': 1, 'PREDICT': 2}}
ITERATIONS = {'smoke': 300, 'nightly': 2000}  # instructions in each random program
SOURCES = BASE.SOURCES
EXTRA_INPUTS = [CORE / 'iss.py', CORE / 'run.py', HERE.parent / 'local-riscv-decoder/generate.py']
TRAP_TAGS = ['trap/illegal', 'trap/ecall', 'trap/misaligned-load', 'trap/misaligned-store', 'trap/interrupt',
             'trap/enabled-by-csr', 'trap/mret', 'csr/use-at-once']  # coverage bits 20 to 27 of the bench
LABELS = {13: 'ISS_DATA', 14: 'ISS_DATA', 15: 'ISS_DATA', 16: 'ISS_DATA'}
IRQ_ADDRESS = 4 * ISS.IRQ_WORD
ILLEGAL = [0x00000000, 0xffffffff, 0x02000033, 0x7c002073, 0x0000100f, 0x00004073]  # zero, ones, MUL, unknown CSR, FENCE.I, funct3 4
# The handler sits at address 4. An exception returns past the faulting instruction; an
# interrupt clears the line and returns to the interrupted one.
HANDLER = [('jal', 0, 'main'), 'handler:',
           ('csrrs', 20, 'mcause', 0), ('csrrs', 21, 'mepc', 0), ('csrrs', 22, 'mtval', 0),
           ('blt', 20, 0, 'interrupt'), ('addi', 21, 21, 4), ('csrrw', 0, 'mepc', 21), ('mret',),
           'interrupt:', ('sw', 0, IRQ_ADDRESS, 0), ('mret',), 'main:']
SETUP = [('addi', 10, 0, ISS.BASE), ('addi', 1, 0, 4), ('csrrw', 0, 'mtvec', 1),
         ('lui', 2, 1), ('addi', 2, 2, -2048), ('csrrw', 0, 'mie', 2), ('csrrsi', 0, 'mstatus', 8)]


def trap_tags(trace):
    bit = {name: 1 << (20 + i) for i, name in enumerate(TRAP_TAGS)}
    causes = {2: 'trap/illegal', 11: 'trap/ecall', 4: 'trap/misaligned-load', 6: 'trap/misaligned-store',
              0x8000000b: 'trap/interrupt'}
    enabling = {ISS.MRET} | {ISS.CSRS[c] for c in ('mstatus', 'mie')}
    tags = []
    for i, r in enumerate(trace):
        t = 0
        if r.kind == 3:
            t |= bit[causes[r.addr]]
            previous = trace[i - 1] if i else None
            if r.addr >> 31 and previous and previous.kind != 3 and (previous.insn == ISS.MRET or (
                    previous.insn & 0x7f == 0x73 and previous.insn >> 20 in enabling)):
                t |= bit['trap/enabled-by-csr']
        elif r.insn == ISS.MRET:
            t |= bit['trap/mret']
        elif r.insn & 0x7f == 0x73 and r.rd and i + 1 < len(trace) and trace[i + 1].kind != 3 and \
                r.rd in ISS.sources(trace[i + 1].insn):
            t |= bit['csr/use-at-once']
        tags.append(t)
    return tags


def trap_vectors(program, data, wait):
    rows = BASE.vectors(program, data, wait, traps=True)
    trace = ISS.execute(ISS.assemble(program), data, traps=True)
    for row, t in zip((r for r in rows if r[0] == 3), trap_tags(trace)):
        row[8] |= t
    return rows


def directed_program():
    return HANDLER + SETUP + [
        ('ecall',), ('addi', 3, 0, 1),                                    # an environment call, then on
        *[('word', w) for w in ILLEGAL[:5]],                              # illegal words are skipped
        ('addi', 4, 0, 0x55), ('sw', 4, 0, 10),
        ('lw', 5, 2, 10), ('lh', 5, 1, 10), ('sw', 4, 2, 10), ('sh', 4, 3, 10), ('lw', 6, 0, 10), ('add', 19, 6, 6),  # misaligned; memory unchanged
        ('csrrw', 7, 'mscratch', 4), ('csrrs', 8, 'mscratch', 0), ('add', 9, 8, 8),          # CSR value at once
        ('csrrc', 0, 'mscratch', 4), ('csrrwi', 7, 'mscratch', 7), ('csrrs', 8, 'mscratch', 0),
        ('addi', 11, 0, 1), ('sw', 11, IRQ_ADDRESS, 0), ('addi', 12, 0, 2),  # interrupt before addi x12
        ('csrrci', 0, 'mstatus', 8), ('sw', 11, IRQ_ADDRESS, 0), ('addi', 13, 0, 3), ('addi', 14, 0, 4),
        ('csrrsi', 0, 'mstatus', 8), ('addi', 15, 0, 5),                 # enabling takes it before addi x15
        ('csrrs', 16, 'mip', 0), ('csrrs', 17, 'mcause', 0), ('add', 18, 17, 0),
        ('ebreak',)]


def random_program(rng, count):
    """The ISS example's random program with exceptions, CSR accesses and interrupts mixed in."""
    body = ISS.random_program(rng, count, subword=True)

    def read_and_use():  # a CSR read whose value the next instruction needs
        r = rng.randrange(1, 10)
        return [('csrrs', r, rng.choice(('mscratch', 'mstatus', 'mie', 'mepc')), 0), ('add', rng.randrange(1, 10), r, rng.randrange(0, 10))]
    events = [lambda: [('ecall',)], lambda: [('word', rng.choice(ILLEGAL))],
              lambda: [(rng.choice(('lw', 'lh', 'lhu')), rng.randrange(1, 10), rng.choice((1, 2, 3)) | 1, 10)],
              lambda: [(rng.choice(('sw', 'sh')), rng.randrange(1, 10), rng.choice((1, 3, 5)), 10)],
              lambda: [('csrrw', rng.randrange(0, 10), 'mscratch', rng.randrange(1, 10))],
              read_and_use,
              lambda: [('addi', 12, 0, 1), ('sw', 12, IRQ_ADDRESS, 0)],
              lambda: [('csrrci', 0, 'mstatus', 8), ('addi', 12, 0, 1), ('sw', 12, IRQ_ADDRESS, 0), ('csrrsi', 0, 'mstatus', 8)]]
    # Events go after the generator has written x10 and x1 to x9, and never between a B label,
    # its AUIPC and the JALR that adds an offset to that address.
    program, computing = body[:10], False
    for item in body[10:-1]:
        if not computing and rng.random() < 0.08:
            program += rng.choice(events)()
        program.append(item)
        if isinstance(item, str) and item.startswith('B'):
            computing = True
        elif isinstance(item, tuple) and item[0] == 'jalr':
            computing = False
    return HANDLER + SETUP + program + [body[-1]]


def boundary_vectors():
    return trap_vectors(directed_program(), ISS.directed_data(), lambda access, trace, i: access % 4)


def random_vectors(seed, count):
    rng = random.Random(seed)
    program, data = random_program(rng, count), ISS.random_data(rng)
    data[ISS.IRQ_WORD] = 0
    return trap_vectors(program, data, lambda access, trace, i: rng.choice((1, 2, 3)) if rng.random() < 0.25 else 0)


def make_cases(args, parameters):
    base = boundary_vectors()
    demo = args.demo_bug + 12 if args.demo_bug else 0  # --demo-bug 1..4 selects mutations 13..16 of the core
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

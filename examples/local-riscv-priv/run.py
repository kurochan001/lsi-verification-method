#!/usr/bin/env python3
"""Machine and user mode, physical memory protection, three interrupt sources, vectored traps and WFI on the RV32I pipeline, compared with the ISS."""
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
NAME = 'local-riscv-priv'
TOP = 'core_tb'
CONFIGS = {'priv': {'TRAPS': 1, 'PRIV': 1, 'PREDICT': 0}, 'priv-predict': {'TRAPS': 1, 'PRIV': 1, 'PREDICT': 2}}
ITERATIONS = {'smoke': 300, 'nightly': 2000}  # instructions in the body of each random program
PMP = HERE.parent / 'local-riscv-pmp/rtl/pmp.sv'
SOURCES = [BASE.SOURCES[0], BASE.SOURCES[1], PMP, BASE.SOURCES[2]]
EXTRA_INPUTS = [CORE / 'iss.py', CORE / 'run.py', HERE.parent / 'local-riscv-decoder/generate.py']
MUTANTS = 6
FIRST_MUTATION = 18  # --demo-bug 1..6 selects mutations 18..23 of the core
LABELS = {18: 'ISS_DATA', 19: 'ISS_DATA', 20: 'ISS_DATA', 21: 'ISS_DATA', 22: 'ISS_FLOW', 23: 'ISS_DATA'}
IRQ, TIMER = 4 * ISS.IRQ_WORD, 4 * ISS.TIMER_WORD
EXTERNAL, TIMER_LINE, SOFTWARE = 1, 2, 4            # bits of the word stored to IRQ
READ_ONLY, EXECUTE_ONLY = 0x80, 0x100              # addresses that the PMP settings of SETUP protect
ILLEGAL = [0x00000000, 0xffffffff, 0x02000033, 0x7c002073, 0x0000100f]  # zero, ones, MUL, unknown CSR, FENCE.I
NOP = ('addi', 0, 0, 0)
RETURN = [('mret',), NOP, NOP, ('jal', 0, 'lost')]  # behind each MRET sits a jump that a predictor would follow

# Registers the handler owns: x19 mstatus, x20 mcause, x21 mepc, x22 mtval, x24 scratch, x26/x27
# saved mepc/mstatus of an outer handler, x28 the vector entry taken. The program tells it what
# to do through x1 (where to resume after a fetch fault), x17 (nonzero: an environment call from
# user mode returns in machine mode), x23 (lines to drive when an exception returns) and x25
# (nonzero: the next interrupt handler drives these lines and enables interrupts, so that
# another interrupt nests inside it).
HANDLER = [
    ('jal', 0, 'main'),
    'handler:',
    ('csrrs', 20, 'mcause', 0), ('csrrs', 21, 'mepc', 0), ('csrrs', 22, 'mtval', 0), ('csrrs', 19, 'mstatus', 0),
    ('blt', 20, 0, 'interrupt'),
    ('addi', 24, 0, 1), ('beq', 20, 24, 'fetch'),
    ('addi', 21, 21, 4), ('csrrw', 0, 'mepc', 21),                      # other exceptions skip the instruction
    ('addi', 24, 0, 8), ('bne', 20, 24, 'leave'), ('beq', 17, 0, 'leave'),
    ('lui', 24, 2), ('addi', 24, 24, -2048), ('csrrs', 0, 'mstatus', 24),  # MPP = M: return in machine mode
    'leave:', ('sw', 23, IRQ, 0), *RETURN,
    'fetch:', ('csrrw', 0, 'mepc', 1), *RETURN,                          # an instruction access fault resumes at x1
    'interrupt:', ('beq', 25, 0, 'plain'),
    ('addi', 26, 21, 0), ('addi', 27, 19, 0), ('sw', 25, IRQ, 0), ('addi', 25, 0, 0), ('csrrsi', 0, 'mstatus', 8),
    NOP,                                                                 # the nested interrupt is taken before this
    ('csrrci', 0, 'mstatus', 8), ('csrrw', 0, 'mepc', 26), ('csrrw', 0, 'mstatus', 27), *RETURN,
    'plain:', ('sw', 0, IRQ, 0), *RETURN,
    # Vector table: entry 0 serves exceptions; entries 3, 7 and 11 the three interrupts.
    'vtable:', ('jal', 0, 'handler'), *[('jal', 0, f'vec{n}' if n in (3, 7, 11) else 'lost') for n in range(1, 12)],
    'vec3:', ('addi', 28, 0, 3), ('jal', 0, 'handler'),
    'vec7:', ('addi', 28, 0, 7), ('jal', 0, 'handler'),
    'vec11:', ('addi', 28, 0, 11), ('jal', 0, 'handler'),
    'lost:', ('ebreak',), 'main:']
# PMP for user mode: entry 0 lets it read and write 0x40..0x7f (the data the programs use), entry 1
# read 0x80..0xbf, entry 3 execute anywhere. Entries are searched in order, so user mode can
# neither execute from the first two regions nor read or write anything else.
SETUP = [
    ('addi', 10, 0, ISS.BASE), ('addi', 1, 0, ('abs', 'handler')), ('csrrw', 0, 'mtvec', 1),
    ('addi', 23, 0, 0), ('addi', 25, 0, 0), ('addi', 17, 0, 0),
    ('lui', 2, 1), ('addi', 2, 2, -0x778), ('csrrw', 0, 'mie', 2),       # MEIE, MTIE, MSIE
    ('addi', 2, 0, 0x17), ('csrrw', 0, 'pmpaddr0', 2), ('addi', 2, 0, 0x27), ('csrrw', 0, 'pmpaddr1', 2),
    ('lui', 2, 4), ('addi', 2, 2, -1), ('csrrw', 0, 'pmpaddr3', 2),
    ('lui', 2, 0x1c002), ('addi', 2, 2, -0x6e5), ('csrrw', 0, 'pmpcfg0', 2),  # 0x1c00191b
    ('csrrsi', 0, 'mstatus', 8)]
TO_M = [('addi', 17, 0, 1), ('ecall',), ('addi', 17, 0, 0)]  # in machine mode already, the call is just skipped


def to_user(n):
    """MRET with MPP = U to the next instruction. In user mode the CSR instructions and the
    MRET are illegal and skipped, so execution continues in user mode either way."""
    return [f'u{n}h:', ('auipc', 13, 0), ('addi', 13, 13, ('off', f'u{n}t', f'u{n}h')), ('csrrw', 0, 'mepc', 13),
            ('lui', 14, 2), ('addi', 14, 14, -2048), ('csrrc', 0, 'mstatus', 14), ('mret',), f'u{n}t:']


def raise_lines(value):
    return [('addi', 12, 0, value), ('sw', 12, IRQ, 0)]


def wait_for_timer(delay):
    """Clear the lines, arm the timer and wait: the bench raises the timer line during the WFI."""
    return [('sw', 0, IRQ, 0), ('addi', 12, 0, delay), ('sw', 12, TIMER, 0), ('wfi',)]


def directed_program():
    return HANDLER + SETUP + [
        # the PMP CSRs read back what was written; the value is used at once
        ('csrrs', 3, 'pmpcfg0', 0), ('csrrs', 4, 'pmpaddr0', 0), ('add', 5, 3, 4), ('csrrs', 6, 'pmpaddr3', 0),
        # MPP holds M or U only: writing 2 reads back as U
        ('lui', 2, 1), ('addi', 2, 2, -2048), ('csrrc', 0, 'mstatus', 2), ('csrrs', 3, 'mstatus', 0),
        # MPRV with MPP = U: machine-mode loads and stores are checked as user accesses
        ('addi', 4, 0, 0x55), ('lui', 2, 0x20), ('csrrs', 0, 'mstatus', 2),
        ('lw', 3, 0, 10), ('sw', 4, 4, 10), ('lw', 3, EXECUTE_ONLY, 0), ('sw', 4, READ_ONLY, 0), ('lw', 5, READ_ONLY, 0),
        ('csrrc', 0, 'mstatus', 2), ('lw', 6, EXECUTE_ONLY, 0), ('lw', 7, READ_ONLY, 0), ('add', 8, 7, 7),
        # user mode: permitted and denied accesses, machine-only instructions, an environment call
        *to_user(1),
        ('addi', 3, 0, 7), ('sw', 3, 8, 10), ('lw', 4, 8, 10), ('lw', 5, READ_ONLY, 0), ('sw', 3, READ_ONLY, 0),
        ('lw', 6, EXECUTE_ONLY, 0), ('sb', 3, IRQ, 0), ('lh', 7, 1, 10),
        ('csrrs', 8, 'mstatus', 0), ('csrrw', 0, 'mscratch', 3), ('mret',), ('word', ILLEGAL[2]),
        ('jalr', 1, 0x44, 0), ('addi', 9, 0, 1),                       # executing from the data region: fetch fault
        ('ecall',), ('jal', 0, 'past1'), 'past1:', ('addi', 9, 9, 1),
        *TO_M, ('csrrs', 3, 'mstatus', 0),
        # an interrupt pending while MIE is 0 is taken as soon as user mode is entered
        ('addi', 2, 0, 0x88), ('csrrc', 0, 'mstatus', 2), *raise_lines(EXTERNAL), ('csrrs', 4, 'mip', 0),
        *to_user(2), ('addi', 5, 0, 5), *TO_M, ('csrrsi', 0, 'mstatus', 8),
        # the three sources, alone and together: external before software before timer
        *raise_lines(SOFTWARE), ('addi', 3, 0, 1), *raise_lines(TIMER_LINE), ('addi', 3, 0, 2),
        ('csrrci', 0, 'mstatus', 8), *raise_lines(7), ('csrrs', 4, 'mip', 0), ('csrrsi', 0, 'mstatus', 8), ('addi', 3, 0, 3),
        *raise_lines(SOFTWARE | TIMER_LINE), ('addi', 3, 0, 4),
        # mie selects: with MEIE off the external line waits and the timer goes first
        ('addi', 2, 0, 0x88), ('csrrw', 5, 'mie', 2), *raise_lines(EXTERNAL), ('addi', 3, 0, 5),
        *raise_lines(EXTERNAL | TIMER_LINE), ('addi', 3, 0, 6), ('csrrw', 0, 'mie', 5), ('csrrs', 6, 'mie', 0),
        # vectored mtvec: interrupts enter at base + 4 * cause, exceptions at the base
        ('addi', 1, 0, ('abs', 'vtable')), ('ori', 1, 1, 1), ('csrrw', 0, 'mtvec', 1), ('csrrs', 3, 'mtvec', 0),
        *raise_lines(SOFTWARE), ('addi', 4, 0, 1), *raise_lines(TIMER_LINE), ('addi', 4, 0, 2),
        *raise_lines(EXTERNAL), ('addi', 4, 0, 3), ('ecall',), ('word', ILLEGAL[0]),
        ('ori', 1, 1, 2), ('csrrw', 0, 'mtvec', 1), ('csrrs', 3, 'mtvec', 0),      # mode 3 reads back as 1
        ('addi', 1, 0, ('abs', 'handler')), ('ori', 1, 1, 2), ('csrrw', 0, 'mtvec', 1), ('csrrs', 3, 'mtvec', 0),  # mode 2 as 0
        # nesting: the timer handler raises the external line and enables interrupts
        ('addi', 25, 0, EXTERNAL), *raise_lines(TIMER_LINE), ('addi', 4, 0, 4),
        *to_user(3), ('addi', 25, 0, SOFTWARE), ('ecall',), ('addi', 23, 0, 0),    # x23 is 0: no line yet
        *TO_M, ('addi', 23, 0, TIMER_LINE), ('ecall',), ('addi', 23, 0, 0), ('addi', 4, 0, 5),  # raised by the handler: nested from machine mode
        # WFI: wakes on the timer and the interrupt is taken after it; with MIE 0 it just continues
        *wait_for_timer(6), ('addi', 3, 0, 7),
        ('csrrci', 0, 'mstatus', 8), *wait_for_timer(3), ('csrrs', 4, 'mip', 0), ('addi', 3, 0, 8), ('csrrsi', 0, 'mstatus', 8),
        ('addi', 3, 0, 9),
        *raise_lines(EXTERNAL), ('addi', 3, 0, 10),
        ('csrrci', 0, 'mstatus', 8), *raise_lines(SOFTWARE), ('wfi',), ('csrrsi', 0, 'mstatus', 8), ('addi', 3, 0, 11),  # already pending: no wait
        # TW makes WFI illegal in user mode
        ('lui', 2, 0x200), ('csrrs', 0, 'mstatus', 2), *to_user(4), ('wfi',), ('addi', 3, 0, 12), *TO_M,
        ('csrrc', 0, 'mstatus', 2),
        # MRET to user mode clears MPRV
        ('lui', 2, 0x20), ('csrrs', 0, 'mstatus', 2), ('csrrs', 3, 'mstatus', 0), *to_user(5), ('addi', 4, 0, 6), *TO_M,
        ('csrrs', 3, 'mstatus', 0),
        # beyond the 64 KiB of physical memory: access faults in machine mode too
        ('lui', 3, 0x10), ('lw', 4, 0, 3), ('sw', 4, 4, 3), ('jalr', 1, 0, 3), ('addi', 5, 0, 1),
        # a PMP change takes effect at the next instruction: user mode may now write 0x80..0xbf
        ('addi', 2, 0, 0x200), ('csrrs', 6, 'pmpcfg0', 2), *to_user(6), ('sw', 4, READ_ONLY + 4, 0), ('lw', 5, READ_ONLY + 4, 0),
        *TO_M, ('csrrc', 0, 'pmpcfg0', 2), *to_user(7), ('sw', 4, READ_ONLY + 8, 0), *TO_M,
        # A locked entry binds machine mode and can no longer be changed. Entry 2 covers the four
        # bytes at 'locked' with no permission: the instruction there, already fetched when
        # pmpcfg0 is written, must not execute, and machine mode cannot read or write the word.
        ('addi', 2, 0, ('abs', 'locked')), ('srli', 2, 2, 2), ('csrrw', 0, 'pmpaddr2', 2),
        ('addi', 1, 0, ('abs', 'after')), ('lui', 2, 0x900), ('csrrs', 0, 'pmpcfg0', 2),
        'locked:', ('addi', 9, 0, 99),
        'after:', ('lw', 3, ('abs', 'locked'), 0), ('sw', 3, ('abs', 'locked'), 0), ('lw', 3, 0, 10),
        ('addi', 4, 0, 0x55), ('csrrw', 5, 'pmpaddr2', 4), ('csrrs', 6, 'pmpaddr2', 0),
        ('csrrc', 5, 'pmpcfg0', 2), ('csrrs', 6, 'pmpcfg0', 0), ('lw', 3, ('abs', 'locked'), 0),
        ('ebreak',)]


def random_program(rng, count):
    """The ISS example's random program with privilege changes, PMP faults, interrupts on the
    three lines, nesting, vectored mode and timer waits mixed in. Every event is safe in either
    mode: what user mode may not do traps and is skipped by the handler."""
    body = ISS.random_program(rng, count, subword=True)
    serial = iter(range(100, 100000))

    def data_access():
        name = rng.choice(('lw', 'lh', 'lbu', 'sw', 'sh', 'sb'))
        base, offset = rng.choice(((10, 4 * rng.randrange(16)), (0, READ_ONLY + 4 * rng.randrange(16)), (0, EXECUTE_ONLY)))
        return (name, rng.randrange(1, 10), offset, base)

    events = [
        lambda: [('ecall',)],
        lambda: [('word', rng.choice(ILLEGAL))],
        lambda: [(rng.choice(('lw', 'lh', 'sw', 'sh')), rng.randrange(1, 10), rng.choice((1, 3, 5)), 10)],
        lambda: [('csrrw', rng.randrange(0, 10), 'mscratch', rng.randrange(1, 10))],
        lambda: [('csrrs', 12, rng.choice(('mstatus', 'mie', 'mip', 'mepc', 'mcause', 'pmpcfg0', 'pmpaddr1')), 0),
                 ('add', rng.randrange(1, 10), 12, rng.randrange(0, 10))],
        lambda: to_user(next(serial)),
        lambda: to_user(next(serial)) + [data_access() for _ in range(rng.randrange(1, 4))],
        lambda: to_user(next(serial)) + [('jalr', 1, rng.choice((0x40, 0x44, 0x80, 0xbc)), 0)],   # fetch fault in user mode
        lambda: list(TO_M),
        lambda: TO_M + raise_lines(rng.randrange(1, 8)),
        lambda: TO_M + [('csrrci', 0, 'mstatus', 8)] + raise_lines(rng.randrange(1, 8)) + [('csrrsi', 0, 'mstatus', 8)],
        lambda: TO_M + [('csrrci', 0, 'mstatus', 8)] + raise_lines(rng.randrange(1, 8)) + to_user(next(serial)),
        lambda: [('addi', 25, 0, rng.randrange(1, 8))],                                          # the next interrupt nests
        lambda: [('addi', 23, 0, rng.randrange(1, 8)), ('ecall',), ('addi', 23, 0, 0)],
        lambda: TO_M + [('lui', 14, 2), ('addi', 14, 14, -2048), ('csrrc', 0, 'mstatus', 14), ('lui', 13, 0x20),
                        ('csrrs', 0, 'mstatus', 13)] + [data_access() for _ in range(rng.randrange(1, 4))] + [('csrrc', 0, 'mstatus', 13)],
        lambda: TO_M + [('addi', 13, 0, ('abs', 'vtable')), ('ori', 13, 13, 1), ('csrrw', 0, 'mtvec', 13)],
        lambda: TO_M + [('addi', 13, 0, ('abs', 'handler')), ('csrrw', 0, 'mtvec', 13)],
        lambda: TO_M + wait_for_timer(rng.randrange(3, 12)),
        lambda: TO_M + [('csrrci', 0, 'mstatus', 8)] + wait_for_timer(rng.randrange(3, 12)) + [('csrrsi', 0, 'mstatus', 8)],
        lambda: TO_M + [('addi', 13, 0, 0x200), (rng.choice(('csrrs', 'csrrc')), 0, 'pmpcfg0', 13)],  # entry 1: read-only or read-write
        lambda: TO_M + [('lui', 13, 0x10), (rng.choice(('lw', 'sw')), rng.randrange(1, 10), 0, 13)],
    ]
    # Events go after the generator has written x10 and x1 to x9, and never between a B label,
    # its AUIPC and the JALR that adds an offset to that address.
    program, computing = body[:10], False
    for item in body[10:-1]:
        if not computing and rng.random() < 0.1:
            program += rng.choice(events)()
        program.append(item)
        if isinstance(item, str) and item.startswith('B'):
            computing = True
        elif isinstance(item, tuple) and item[0] == 'jalr':
            computing = False
    return HANDLER + SETUP + program + [body[-1]]


def vectors(program, data, wait):
    """Rows for the bench, as the ISS example builds them, from the privileged ISS. The coverage
    of this example goes in bits 31:8 of column 9; the every-instruction goal is not used."""
    words = ISS.assemble(program)
    final = []
    trace = ISS.tag(ISS.execute(words, data, traps=True, priv=True, memory=final))
    if len(words) > BASE.IMEM_WORDS or len(trace) > BASE.RETIRE_LIMIT:
        raise ValueError(f'program of {len(words)} words retiring {len(trace)} instructions exceeds the bench')
    waits, access = [0] * len(trace), 0
    for i, r in enumerate(trace):
        if r.kind in (1, 2):
            waits[i] = wait(access, trace, i)
            access += 1
    slow = sum(16 for r in trace if r.insn == ISS.WFI) + sum(4 for r in trace if r.insn >> 20 == 0x3a0 and r.insn & 0x7f == 0x73)
    limit = 4 * len(trace) + sum(waits) + slow + 100
    number = {name: i for i, name in enumerate(ISS.NAMES)}
    rows = [[2, limit] + [0] * 9]
    rows += [[0, i, w] + [0] * 8 for i, w in enumerate(words)]
    rows += [[1, i, d] + [0] * 8 for i, d in enumerate(data) if d]
    rows += [[3, r.pc, r.insn, r.rd, r.wdata, r.kind, r.addr, r.data, r.tags,
              number.get(ISS.name_of(r.insn), 63) | r.more << 8, waits[i]] for i, r in enumerate(trace)]
    rows += [[5, i, d] + [0] * 8 for i, d in enumerate(final)]
    return rows


def clean(data):
    data[ISS.IRQ_WORD] = data[ISS.TIMER_WORD] = 0
    return data


def boundary_vectors():
    return vectors(directed_program(), clean(ISS.directed_data()), lambda access, trace, i: access % 4)


def random_vectors(seed, count):
    rng = random.Random(seed)
    program, data = random_program(rng, count), clean(ISS.random_data(rng))
    return vectors(program, data, lambda access, trace, i: rng.choice((1, 2, 3)) if rng.random() < 0.25 else 0)


def make_cases(args, parameters):
    base = boundary_vectors()
    demo = args.demo_bug + FIRST_MUTATION - 1 if args.demo_bug else 0
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

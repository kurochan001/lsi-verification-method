#!/usr/bin/env python3
"""A five-stage RV32I pipeline compared, instruction by instruction, with an instruction set simulator."""
import importlib.util
from pathlib import Path
import random
import sys

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('rv32i_iss', HERE / 'iss.py')
ISS = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ISS)
NAME = 'local-riscv-iss'
TOP = 'core_tb'
CONFIGS = {'rv32i': {}}
ITERATIONS = {'smoke': 300, 'nightly': 2000}  # instructions in each random program
SOURCES = [HERE / 'rtl/rv32i_core.sv', HERE / 'tb/core_tb.sv']
EXTRA_INPUTS = [HERE / 'iss.py']
TAGS = ISS.TAGS + ['mem/wait-forwarding']
LABELS = {1: 'ISS_DATA', 2: 'ISS_DATA', 3: 'ISS_FLOW', 4: 'ISS_DATA'}


IMEM_WORDS = RETIRE_LIMIT = 16384  # sizes of the bench's instruction memory and expected-retirement table


def forwards_past_wait(trace, i, stale):
    """Memory access i sits between a producer and its consumer with no bubble: while it
    waits in MEM, the producer is in WB and the consumer in EX. stale is the producer's
    destination value before it wrote, which EX holds if it misses the forwarded value."""
    if not 0 < i < len(trace) - 1:
        return False
    p, m, c = trace[i - 1], trace[i], trace[i + 1]
    return (m.pc == p.pc + 4 and c.pc == m.pc + 4 and p.insn & 0x7f not in (0x6f, 0x67) and  # no jump flush
            p.rd != 0 and p.rd in ISS.sources(c.insn) and p.wdata != stale and m.rd != p.rd and
            not (p.kind == 1 and p.rd in ISS.sources(m.insn)) and
            not (m.kind == 1 and m.rd and m.rd in ISS.sources(c.insn)))


def stale_values(trace):
    """For each retired instruction, the value its destination held before it wrote."""
    regs, before = [0] * 32, []
    for r in trace:
        before.append(regs[r.rd])
        if r.rd:
            regs[r.rd] = r.wdata
    return before


def vectors(program, data, wait):
    """Rows for the bench. wait(index, trace, i) gives the wait cycles of each data access."""
    words = ISS.assemble(program)
    trace = ISS.tag(ISS.execute(words, data))
    if len(words) > IMEM_WORDS or len(trace) > RETIRE_LIMIT:
        raise ValueError(f'program of {len(words)} words retiring {len(trace)} instructions exceeds the bench')
    before = stale_values(trace)
    waits, access = [0] * len(trace), 0
    for i, r in enumerate(trace):
        if r.kind:
            waits[i] = wait(access, trace, i)
            access += 1
            if waits[i] and forwards_past_wait(trace, i, before[i - 1]):
                trace[i + 1].tags |= 1 << TAGS.index('mem/wait-forwarding')
    limit = 4 * len(trace) + sum(waits) + 100
    rows = [[2, limit] + [0] * 9]
    rows += [[0, i, w] + [0] * 8 for i, w in enumerate(words)]
    rows += [[1, i, d] + [0] * 8 for i, d in enumerate(data) if d]
    rows += [[3, r.pc, r.insn, r.rd, r.wdata, r.kind, r.addr, r.data, r.tags, ISS.NAMES.index(ISS.name_of(r.insn)),
              waits[i]] for i, r in enumerate(trace)]
    return rows


def boundary_vectors():
    def wait(access, trace, i):  # 0 to 3 cycles in turn; at least 2 where a forwarded value must survive
        return max(access % 4, 2 if forwards_past_wait(trace, i, stale_values(trace)[i - 1]) else 0)
    return vectors(ISS.directed_program(), ISS.directed_data(), wait)


def random_vectors(seed, count):
    rng = random.Random(seed)
    program, data = ISS.random_program(rng, count), ISS.random_data(rng)
    return vectors(program, data, lambda access, trace, i: rng.choice((1, 2, 3)) if rng.random() < 0.25 else 0)


def counts(rows):
    retired = [r for r in rows if r[0] == 3]
    return dict(retired=len(retired), loads=sum(r[5] == 1 for r in retired), stores=sum(r[5] == 2 for r in retired))


def make_cases(args, parameters):
    base = boundary_vectors()
    cases = [dict(id='boundaries', vectors=base, mutation=args.demo_bug, category='functional', expected_failure=None)]
    for seed in range(args.seed, args.seed + (3 if args.profile == 'nightly' else 1)):
        cases.append(dict(id=f'random-seed{seed}', vectors=random_vectors(seed, args.iterations),
                          mutation=args.demo_bug, category='functional', expected_failure=None))
    for mutation in range(1, 5):
        cases.append(dict(id=f'detect-mutation{mutation}', vectors=base, mutation=mutation,
                          category='mutation', expected_failure=LABELS[mutation]))
    for case in cases:
        case['counts'] = counts(case['vectors'])
    return cases


if __name__ == '__main__':
    spec = importlib.util.spec_from_file_location('local_runner', HERE.parent / 'local-common/runner.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    sys.exit(module.main(sys.modules[__name__]))

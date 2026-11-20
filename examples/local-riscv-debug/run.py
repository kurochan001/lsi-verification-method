#!/usr/bin/env python3
"""Halt, resume, single step and register access through a debug module on the JTAG TAP, with the retired instructions compared with the ISS."""
import importlib.util
from pathlib import Path
import random
import sys

HERE = Path(__file__).resolve().parent
CORE = HERE.parent / 'local-riscv-iss'


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ISS = load('rv32i_iss_debug', CORE / 'iss.py')
M = load('riscv_debug_model', HERE / 'model.py')
NAME = 'local-riscv-debug'
TOP = 'debug_tb'
CONFIGS = {'debug': {'PREDICT': 0}, 'debug-predict': {'PREDICT': 2}}
ITERATIONS = {'smoke': 120, 'nightly': 500}  # instructions in the random part of each random program
SOURCES = [CORE / 'rtl/rv32i_core.sv', HERE.parent / 'local-riscv-decoder/rtl/rv32i_decoder.sv',
           HERE.parent / 'local-jtag-tap/rtl/jtag_tap.sv', HERE / 'rtl/rv32i_debug_core.sv', HERE / 'rtl/debug_dtm.sv',
           HERE / 'rtl/debug_module.sv', HERE / 'rtl/debug_system.sv', HERE / 'tb/debug_tb.sv']
EXTRA_INPUTS = [CORE / 'iss.py', HERE / 'model.py']
MUTANTS = 6
FIRST_MUTATION = 24  # --demo-bug 1..6 selects mutations 24..29 (24 to 27 in the core, 28 and 29 in the debug module)
LABELS = {24: 'DBG_DPC', 25: 'DBG_DPC', 26: 'ISS_FLOW', 27: 'ISS_FLOW', 28: 'DBG_DATA', 29: 'DBG_CMDERR'}
IRQ = 4 * ISS.IRQ_WORD
RETIRE_LIMIT = SCRIPT_LIMIT = 16384   # tables of the bench
SPACING = 400                         # retired instructions between two halt requests

# The handler skips an instruction that raised an exception and, for the interrupt, lowers the line.
PROLOGUE = [
    ('jal', 0, 'main'),
    'handler:', ('csrrs', 20, 'mcause', 0), ('csrrs', 21, 'mepc', 0), ('blt', 20, 0, 'interrupt'),
    ('addi', 21, 21, 4), ('csrrw', 0, 'mepc', 21), ('mret',),
    'interrupt:', ('sw', 0, IRQ, 0), ('mret',),
    'main:', ('addi', 10, 0, ISS.BASE), ('addi', 1, 0, ('abs', 'handler')), ('csrrw', 0, 'mtvec', 1),
    ('lui', 2, 1), ('addi', 2, 2, -2048), ('csrrw', 0, 'mie', 2), ('csrrsi', 0, 'mstatus', 8)]


def busy_loop(name, iterations, interrupts):
    """A loop for halt requests to land in: loads and stores, a misaligned load (an exception
    every time round), a branch taken every other time and, with interrupts, the line raised."""
    return [('addi', 11, 0, iterations), ('addi', 4, 0, 0), f'{name}:',
            ('addi', 11, 11, -1), ('lw', 3, 0, 10), ('add', 4, 3, 4), ('sw', 4, 4, 10), ('lh', 3, 1, 10),
            ('andi', 2, 11, 1), ('beq', 2, 0, f'{name}skip'), ('addi', 4, 4, 3), f'{name}skip:',
            *([('addi', 12, 0, 1), ('sw', 12, IRQ, 0)] if interrupts else []),
            ('addi', 4, 4, 1), ('bne', 11, 0, name)]


TAIL = [('addi', 6, 6, 1), ('sw', 6, 8, 10)] * 20 + [('ebreak',)]


def directed_program(loop_a, loop_b, loop_c):
    return PROLOGUE + [
        ('sw', 5, 0, 10), ('add', 6, 5, 5),                # x5 comes from the debugger
        ('ebreak',),                                        # stop 1
        ('addi', 7, 6, 1), ('beq', 0, 0, 'target'), ('addi', 7, 0, 99),
        'target:', ('lw', 8, 0, 10), ('lh', 9, 1, 10),      # stepped: sequential, taken branch, load, exception
        ('add', 9, 8, 7),
        ('csrrci', 0, 'mstatus', 8), ('addi', 12, 0, 1), ('sw', 12, IRQ, 0),
        ('ebreak',),                                        # stop 2: the interrupt is pending and disabled
        ('csrrsi', 0, 'mstatus', 8), ('addi', 13, 0, 5),    # stepped: enabled now, but not taken during a step
        ('addi', 14, 0, 6),                                 # the interrupt is taken before this one
        ('ebreak',),                                        # stops 3 and 4: resumed where it stopped, then moved
        ('addi', 15, 0, 99),
        'moved:', ('addi', 15, 0, 3),
        'region-a:', *busy_loop('a', loop_a, True),
        'region-b:', *busy_loop('b', loop_b, False),
        # A short loop that raises the interrupt line every time round: requests arrive one clock
        # cycle later each time, so that one of them meets the cycle the interrupt would be taken in.
        'region-c:', ('addi', 11, 0, loop_c), 'c:', ('addi', 11, 11, -1), ('addi', 12, 0, 1), ('sw', 12, IRQ, 0),
        ('bne', 11, 0, 'c'),
        'last:', ('addi', 0, 0, 0), ('ebreak',),            # stop 5: EBREAK ends the program again
        *TAIL]


DIRECTED_PLANS = [
    [('write', 5, 0x1234abcd), ('read', 5), ('zero',), ('ebreakm', 1)],
    [('read', 10), ('read', 6), ('cover', 'reg/gpr-write-visible'), ('write', 6, 77), ('errors',), ('dpc', None), ('step', 4)],
    [('dpc', None), ('step', 2), ('cover', 'step/interrupt-masked'), ('read', 13)],
    [],
    [('dpc', 'moved')],
    [('ebreakm', 0), ('dpc', None)]]


def clean(program):
    """Labels may carry a dash for readability; the assembler wants plain names."""
    return [x.replace('-', '_') if isinstance(x, str) else
            tuple(y.replace('-', '_') if isinstance(y, str) and y not in ISS.OPS and y not in ISS.CSRS else y for y in x)
            for x in program]


def build(program, data, plans, requests, wait):
    """Rows for the bench. requests(trace, labels) returns the debugger's actions at places not
    fixed in the program: (retired count, function that writes them into a script)."""
    program = clean(program)
    words, labels = ISS.assemble(program), ISS.label_addresses(program)
    script = M.Script()
    script.start()
    groups = [[-1, 0]]                    # retired count each group of rows waits for, and its first row
    debugger = M.Debugger(script, plans, labels)
    original = debugger.stop

    def stop(cause, pc, regs, words_, trace, first=False):
        if cause != 'step' and not first:
            groups.append([len(trace), len(script.rows)])
        debugger.halts += 1
        return original(cause, pc, regs, words_, trace, first)
    debugger.halts, debugger.stop = 0, stop
    final = []
    trace = ISS.execute(words, data, traps=True, memory=final, debug=debugger)
    if not callable(plans) and debugger.stops != len(plans):
        raise ValueError(f'{debugger.stops} stops for {len(plans)} plans')
    parts = [(at, script.rows[start:end]) for (at, start), end in
             zip(groups, [g[1] for g in groups[1:]] + [len(script.rows)])]
    halts, scans, goals = debugger.halts, script.scans, list(script.goals)
    for at, write in requests(trace, labels):
        extra = M.Script()
        halts += write(extra, at) or 0
        parts.append((at, extra.rows))
        scans += extra.scans
        goals += extra.goals
    parts.sort(key=lambda part: part[0])
    rows = [row for _, part in parts for row in part]
    if len(words) > 16384 or len(trace) > RETIRE_LIMIT or len(rows) > SCRIPT_LIMIT:
        raise ValueError('the scenario exceeds the tables of the bench')
    waits, access = [0] * len(trace), 0
    for i, r in enumerate(trace):
        if r.kind in (1, 2):
            waits[i] = wait(access)
            access += 1
    polls = sum(row[0] == M.POLL for row in rows)
    limit = 4 * len(trace) + sum(waits) + M.SCAN_CLOCKS * (scans + 8 * polls) + sum(row[1] for row in rows if row[0] == M.IDLE) + 2000
    out = [[M.LIMIT, limit] + [0] * 6]
    out += [[M.IMEM, i, w] + [0] * 5 for i, w in enumerate(words)]
    out += [[M.DMEM, i, d] + [0] * 5 for i, d in enumerate(data) if d]
    out += [[M.RETIRE, r.pc, r.insn, r.rd, r.wdata, r.kind | waits[i] << 4, r.addr, r.data] for i, r in enumerate(trace)]
    out += [[M.FINAL, i, d] + [0] * 5 for i, d in enumerate(final)]
    return out + rows, dict(halts=halts, scans=scans, goals=goals, trace=trace, labels=labels, stops=debugger.kinds)


def region(trace, labels, first, last):
    """Indices of the first retirement at label `first` and at label `last`."""
    start = next(i for i, r in enumerate(trace) if r.pc == labels[first])
    end = next(i for i, r in enumerate(trace) if r.pc == labels[last])
    return start, end


def spread(start, end, count, extra=0):
    """Places for `count` halt requests between two retirements, clear of both ends."""
    room = end - start - extra - 2 * SPACING
    if count and room < (count - 1) * SPACING:
        raise ValueError(f'no room for {count} halt requests in {end - start} instructions')
    return [start + extra + SPACING // 2 + i * SPACING + 3 * i for i in range(count)]


def directed_requests(plain, stepped, swept):
    def requests(trace, labels):
        a0, a1 = region(trace, labels, 'region_a', 'region_b')
        b0, b1 = region(trace, labels, 'region_b', 'region_c')
        c0, c1 = region(trace, labels, 'region_c', 'last')
        out = []
        # In the loop with interrupts: no steps, a different delay every time.
        for i, at in enumerate(spread(a0, a1, plain) if plain else []):
            out.append((at, lambda s, at, i=i: M.asynchronous(s, at, (7 * i) % 23, 0, 4 if i % 2 else 10, thorough=i == 0) or 1))
        if stepped:
            out.append((b0 + 20, lambda s, at: M.running_command(s, at, 10)))
        for i, at in enumerate(spread(b0, b1, stepped, 1600) if stepped else []):
            out.append((at, lambda s, at, i=i: M.asynchronous(s, at, 5 * i, 1 + i, 4) or 2 + i))
        if swept and c1 - c0 < 250 * swept + 600:
            raise ValueError('no room for the swept halt requests')
        for i in range(swept):  # always at the same place of the loop, one cycle later each time
            out.append((c0 + 200 + 250 * i, lambda s, at, i=i: M.asynchronous(s, at, i, 0, 11) or 1))
        return out
    return requests


def directed(plain=6, stepped=4, swept=20):
    """The fixed scenario: rows and facts. The three loops are as long as the halt requests need:
    about 25, 16 and 10 instructions retire each time round."""
    program = directed_program((plain + 3) * SPACING // 25 + 10 if plain else 4,
                               (stepped + 7) * SPACING // 16 + 10 if stepped else 4, 25 * swept + 80 if swept else 4)
    return build(program, ISS.directed_data(), DIRECTED_PLANS, directed_requests(plain, stepped, swept),
                 lambda access: (0, 0, 1, 3)[access % 4])


def boundary_vectors():
    return directed()[0]


def add_arguments(parser):
    # One run of the fixed scenario simulates some four hundred thousand clock cycles.
    parser.set_defaults(timeout=60.0)


def random_scenario(seed, count):
    """A random program with EBREAKs put into it. At each one the debugger reads and writes
    registers, steps and resumes as the seed says; the ISS goes on with what it wrote."""
    rng = random.Random(seed)
    body = ISS.random_program(rng, count, loops=True)[:-1]
    places = [i for i, item in enumerate(body) if not isinstance(item, str) and i > 12]
    for place in sorted(rng.sample(places, min(3, len(places))), reverse=True):
        body.insert(place, ('ebreak',))
    requests_wanted = 2
    loop = (requests_wanted + 2) * SPACING // 16 + 40
    program = PROLOGUE + body + ['region-b:', *busy_loop('b', loop, False), 'last:', ('addi', 0, 0, 0), ('ebreak',), *TAIL]
    state = dict(first=True, again=None, rich=6)

    def plan(debugger, cause, pc, regs):
        if cause == 'haltreq':
            return [('write', 5, rng.getrandbits(32)), ('read', 5), ('ebreakm', 1)]
        if pc == debugger.labels['last'] + 4:
            return [('ebreakm', 0), ('dpc', None)]
        if state['again'] != pc and rng.random() < 0.2:   # resume on the EBREAK once: it stops again
            state['again'] = pc
            return []
        state['again'] = None
        actions = []
        if state['rich'] > 0:                              # a loop may come back here many times
            state['rich'] -= 1
            known = sorted(debugger.written - {0})
            actions += [('read', rng.choice(known)) for _ in range(rng.randrange(3))]
            if rng.random() < 0.6:
                actions.append(('write', rng.randrange(1, 10), rng.getrandbits(32)))
            actions.append(('dpc', None))
            if rng.random() < 0.7:
                actions.append(('step', rng.randrange(1, 4)))
            if rng.random() < 0.5:
                actions.append(('read', rng.choice(known)))
            return actions
        return [('dpc', None)]

    def requests(trace, labels):
        b0, b1 = region(trace, labels, 'region_b', 'last')
        return [(at, lambda s, at, n=rng.randrange(3), d=rng.randrange(40): M.asynchronous(s, at, d, n, 10) or 1 + n)
                for at in spread(b0, b1, requests_wanted)]
    data = ISS.random_data(rng)
    data[ISS.IRQ_WORD] = 0  # the interrupt line starts low; the random part never touches it
    return build(program, data, plan, requests, lambda access: rng.choice((1, 2, 3)) if rng.random() < 0.25 else 0)


def random_vectors(seed, count):
    return random_scenario(seed, count)[0]


def counts(rows):
    retired = [r for r in rows if r[0] == M.RETIRE]
    return dict(retired=len(retired), loads=sum(r[5] & 3 == 1 for r in retired), stores=sum(r[5] & 3 == 2 for r in retired),
                scans=sum(r[0] == M.SCAN_DR for r in rows))


def make_cases(args, parameters):
    base, facts = directed()
    mutation = FIRST_MUTATION + args.demo_bug - 1 if args.demo_bug else 0
    cases = [dict(id='boundaries', vectors=base, mutation=mutation, category='functional', expected_failure=None,
                  counts=dict(counts(base), halts=facts['halts']))]
    for seed in range(args.seed, args.seed + (3 if args.profile == 'nightly' else 1)):
        rows, facts = random_scenario(seed, args.iterations)
        cases.append(dict(id=f'random-seed{seed}', vectors=rows, mutation=mutation, category='functional',
                          expected_failure=None, counts=dict(counts(rows), halts=facts['halts'])))
    # The mutants meet the same stops without the long loops: every one of them fails at a stop.
    short = directed(0, 0, 0)[0]
    for mutation in range(FIRST_MUTATION, FIRST_MUTATION + MUTANTS):
        cases.append(dict(id=f'detect-mutation{mutation - FIRST_MUTATION + 1}', vectors=short, mutation=mutation,
                          category='mutation', expected_failure=LABELS[mutation], counts=dict(counts(short), halts=0)))
    return cases


if __name__ == '__main__':
    runner = load('local_runner', HERE.parent / 'local-common/runner.py')
    sys.exit(runner.main(sys.modules[__name__]))

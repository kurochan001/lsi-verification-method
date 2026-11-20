#!/usr/bin/env python3
"""Explore every interleaving of small two-hart programs on an abstract atomic memory.

Each memory operation is one indivisible step. A hart holds at most one reservation; a write by
the other hart to the reserved word, or any SC of its own, removes it. The model never lets an SC
fail without such a cause, although the ISA would allow it."""
from collections import deque
import json

LOCK, COUNTER = 0, 2
LOAD, STORE, LR, SC, AMO = range(5)
AMOADD = 1
# Instructions: (kind, address, operand). The operand 'r+1' is the last value read plus one.
# ('bnez', target) repeats from `target` while the last result is not zero; it is not a memory operation.
PROGRAMS = {
    'spinlock': dict(code=[('lr', LOCK), ('bnez', 0), ('sc', LOCK, 1), ('bnez', 0),
                           ('load', COUNTER), ('store', COUNTER, 'r+1'), ('store', LOCK, 0)], critical=(4, 5, 6)),
    'lrsc': dict(code=[('lr', COUNTER), ('sc', COUNTER, 'r+1'), ('bnez', 0)], critical=()),
    'amoadd': dict(code=[('amoadd', COUNTER, 1)], critical=()),
    'plain': dict(code=[('load', COUNTER), ('store', COUNTER, 'r+1')], critical=()),
    'taslock': dict(code=[('load', LOCK), ('bnez', 0), ('store', LOCK, 1),
                          ('load', COUNTER), ('store', COUNTER, 'r+1'), ('store', LOCK, 0)], critical=(3, 4, 5)),
}
IDS = {name: number for number, name in enumerate(PROGRAMS, 1)}


def step(code, hart, pc, reg, memory, reserved):
    """Run the memory operation at pc and the branches after it. Returns the new state and the event."""
    kind, address, *rest = code[pc]
    operand = rest[0] if rest else 0
    value = (reg + 1) & 0xffffffff if operand == 'r+1' else operand
    memory, reserved, other = list(memory), list(reserved), 1 - hart
    wrote = False
    if kind == 'load':
        reg, event = memory[address], (hart, LOAD, 0, address, 0, memory[address])
    elif kind == 'lr':
        reg, event = memory[address], (hart, LR, 0, address, 0, memory[address])
        reserved[hart] = address
    elif kind == 'store':
        memory[address], wrote, event = value, True, (hart, STORE, 0, address, value, 0)
    elif kind == 'sc':
        success = reserved[hart] == address
        reserved[hart] = None
        if success:
            memory[address], wrote = value, True
        reg, event = int(not success), (hart, SC, 0, address, value, int(not success))
    elif kind == 'amoadd':
        old = memory[address]
        memory[address], wrote, reg = (old + value) & 0xffffffff, True, old
        event = (hart, AMO, AMOADD, address, value, old)
    else:
        raise ValueError(kind)
    if wrote and reserved[other] == address:
        reserved[other] = None
    pc += 1
    while pc < len(code) and code[pc][0] == 'bnez':
        pc = code[pc][1] if reg else pc + 1
    return pc, reg, tuple(memory), tuple(reserved), event


def explore(name):
    """Breadth first over every choice of the next hart. One shortest witness per outcome."""
    program = PROGRAMS[name]
    code, critical = program['code'], program['critical']
    # pc0, pc1, reg0, reg1, memory, reservations, a failed SC per hart, both harts seen in the critical part
    initial = (0, 0, 0, 0, (0, 0, 0, 0), (None, None), (False, False), False)
    queue, seen, witnesses, overlaps = deque([(initial, [])]), {initial}, {}, 0
    while queue:
        state, path = queue.popleft()
        pcs, regs, memory, reserved, failed, overlap = state[:2], state[2:4], *state[4:]
        if all(pc == len(code) for pc in pcs):
            witnesses.setdefault((memory[COUNTER], *failed, overlap), path)
            continue
        for hart in (0, 1):
            if pcs[hart] == len(code):
                continue
            pc, reg, new_memory, new_reserved, event = step(code, hart, pcs[hart], regs[hart], memory, reserved)
            new_pcs, new_regs, new_failed = list(pcs), list(regs), list(failed)
            new_pcs[hart], new_regs[hart] = pc, reg
            if event[1] == SC and event[5]:
                new_failed[hart] = True
            both = all(p in critical for p in new_pcs)
            successor = (*new_pcs, *new_regs, new_memory, new_reserved, tuple(new_failed), overlap or both)
            if successor not in seen:
                seen.add(successor)
                overlaps += both
                queue.append((successor, path + [event]))
    return dict(states=len(seen), witnesses=witnesses, overlapping_states=overlaps)


def outcome_name(name, outcome):
    counter, failed0, failed1, _ = outcome
    return f'{name}-{counter}-{int(failed0)}{int(failed1)}'


if __name__ == '__main__':
    for name in PROGRAMS:
        result = explore(name)
        print(json.dumps(dict(program=name, states=result['states'], overlapping_states=result['overlapping_states'],
                              outcomes=sorted(outcome_name(name, o) + ('-overlap' if o[3] else '') for o in result['witnesses']))))

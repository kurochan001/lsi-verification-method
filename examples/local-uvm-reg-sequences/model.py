"""Independent register table, expected access counts and a replay model for the bus log.

Nothing here is derived from the UVM register model or from the RTL: the table restates the
specification in the README, and the counts restate what each built-in sequence is documented
to do (one read per register for the reset check, two writes and two reads per tested bit for
the bit bash, the walking pattern for the memory).
"""
import re

MASK = 0xffffffff
ID_VALUE = 0x52475351
#            name      address width access reset   volatile
REGISTERS = [('ctrl', 0x00, 8, 'RW', 0xa5, False),
             ('id', 0x04, 32, 'RO', ID_VALUE, False),
             ('status', 0x08, 8, 'RO', 0, True),
             ('irq', 0x0c, 4, 'W1C', 0, False),
             ('scratch', 0x10, 32, 'RW', 0, False),
             ('cmd', 0x14, 1, 'WO', 0, False)]
ADDRESS = {name: address for name, address, *_ in REGISTERS}
MEMORY_BASE, MEMORY_WORDS = 0x40, 16
UNMAPPED = [a for a in range(0x18, 0x100, 4) if not MEMORY_BASE <= a < MEMORY_BASE + 4 * MEMORY_WORDS]
BACKDOOR = ('ctrl', 'scratch')
BUILTIN_STAGES = ('hw_reset', 'access', 'preload', 'bit_bash', 'mem_walk')
DIRECTED_STAGES = ('mirror_after_builtin', 'cross_register', 'unmapped', 'unmapped_mirror', 'w1c', 'soft_reset', 'mem_unique')


def expected_counts(iterations, builtin_only=False, status_volatile=True, excluded=(), bit_bash_excluded=(), backdoor=True):
    """Return {stage: {(address, is_write): count}} for one planned run."""
    excluded, bit_bash_excluded = set(excluded), set(bit_bash_excluded)
    plan = {stage: {} for stage in BUILTIN_STAGES + (() if builtin_only else DIRECTED_STAGES)}

    def add(stage, address, write, count=1):
        key = (address, int(write))
        plan[stage][key] = plan[stage].get(key, 0) + count
    for name, address, width, access, _, volatile in REGISTERS:
        unchecked = volatile and (name != 'status' or status_volatile)
        if name in excluded:
            continue
        # Reset check: one read, unless no field of the register is compared.
        if not unchecked:
            add('hw_reset', address, 0)
        # Access check: only read-write registers that have a backdoor.
        if backdoor and name in BACKDOOR:
            add('access', address, 1)
            add('access', address, 0)
        # Bit bash: every bit of the 32-bit word except volatile and write-only field bits.
        if name not in bit_bash_excluded:
            bits = 32 - (width if unchecked or access == 'WO' else 0)
            add('bit_bash', address, 1, 2 * bits)
            add('bit_bash', address, 0, 2 * bits)
    add('preload', ADDRESS['ctrl'], 1)
    add('preload', ADDRESS['scratch'], 1)
    for word in range(MEMORY_WORDS):
        address = MEMORY_BASE + 4 * word
        add('mem_walk', address, 1, 1 if word == MEMORY_WORDS - 1 else 2)
        add('mem_walk', address, 0)
    if builtin_only:
        return plan
    mirrored = [address for name, address, *_ in REGISTERS if name != 'status']

    def mirror(stage, count=1):
        for address in mirrored:
            add(stage, address, 0, count)
    mirror('mirror_after_builtin')
    rounds = iterations + 2
    add('cross_register', ADDRESS['ctrl'], 1, rounds)
    add('cross_register', ADDRESS['scratch'], 1, rounds)
    mirror('cross_register', rounds)
    for address in UNMAPPED:
        add('unmapped', address, 1)
        add('unmapped', address, 0)
    mirror('unmapped_mirror')
    add('w1c', ADDRESS['irq'], 0, 7)
    add('w1c', ADDRESS['irq'], 1, 7)
    add('soft_reset', ADDRESS['ctrl'], 1)
    add('soft_reset', ADDRESS['scratch'], 1)
    add('soft_reset', ADDRESS['cmd'], 1, 2)
    mirror('soft_reset', 2)
    for word in range(MEMORY_WORDS):
        add('mem_unique', MEMORY_BASE + 4 * word, 1)
        add('mem_unique', MEMORY_BASE + 4 * word, 0)
    return plan


def totals(plan):
    reads = sum(n for stage in plan.values() for (_, write), n in stage.items() if not write)
    writes = sum(n for stage in plan.values() for (_, write), n in stage.items() if write)
    errors = sum(plan.get('unmapped', {}).values())
    return dict(reads=reads, writes=writes, errors=errors)


BUS = re.compile(r'REGLOG BUS age=(\d+) w=([01]) addr=([0-9a-f]+) wdata=([0-9a-f]+) rdata=([0-9a-f]+) err=([01]) ev=([0-9a-f])')
EVENT = re.compile(r'REGLOG EVT age=(\d+) ev=([0-9a-f])')
POKE = re.compile(r'REGLOG POKE target=([01]) value=([0-9a-f]+)')
STAGE = re.compile(r'STAGE (\w+)')


def replay(log):
    """Check every recorded bus access against the specification and count accesses per stage.

    The cycle stamp of each line is taken from the monitor; the model checks that it only moves
    forward and uses it for the value of STATUS. Everything else is computed here.
    """
    state = None
    memory = {}
    stage = None
    observed = {}
    last_age = -1
    events = 0
    for number, line in enumerate(log.splitlines(), 1):
        if line == 'REGLOG RST':
            state = dict(ctrl=0xa5, irq=0, scratch=0)
            last_age = -1
            continue
        m = STAGE.fullmatch(line)
        if m:
            stage = m[1]
            if stage in observed:
                raise ValueError(f'line {number}: stage {stage} repeated')
            observed[stage] = {}
            continue
        m = POKE.fullmatch(line)
        if m:
            if state is None:
                raise ValueError(f'line {number}: deposit before reset')
            if m[1] == '1':
                state['scratch'] = int(m[2], 16)
            else:
                state['ctrl'] = int(m[2], 16) & 0xff
            continue
        m = EVENT.fullmatch(line)
        if m:
            age, ev = int(m[1]), int(m[2], 16)
            if state is None or age <= last_age or ev == 0:
                raise ValueError(f'line {number}: malformed event record')
            last_age = age
            state['irq'] |= ev
            events += 1
            continue
        if not line.startswith('REGLOG'):
            continue
        m = BUS.fullmatch(line)
        if not m:
            raise ValueError(f'line {number}: malformed log record')
        age, write, address, wdata, rdata, error, ev = int(m[1]), int(m[2]), int(m[3], 16), int(m[4], 16), int(m[5], 16), int(m[6]), int(m[7], 16)
        if state is None or stage is None or age <= last_age:
            raise ValueError(f'line {number}: access outside a stage or out of order')
        last_age = age
        events += ev != 0
        observed[stage][(address, write)] = observed[stage].get((address, write), 0) + 1
        word = (address - MEMORY_BASE) // 4
        is_memory = MEMORY_BASE <= address < MEMORY_BASE + 4 * MEMORY_WORDS and address % 4 == 0
        mapped = is_memory or address in ADDRESS.values()
        if error != (not mapped):
            raise ValueError(f'line {number}: error response differs at {address:#x}')
        if is_memory:
            expected = memory.get(word)
            if not write and expected is None:
                raise ValueError(f'line {number}: read of memory word {word} before any write')
        else:
            expected = {0x00: state['ctrl'], 0x04: ID_VALUE, 0x08: age & 0xff, 0x0c: state['irq'], 0x10: state['scratch']}.get(address, 0)
        # Read data is only meaningful on a read; the value shown during a write is ignored.
        if not write and rdata != expected:
            raise ValueError(f'line {number}: {address:#x} returned {rdata:#x}, expected {expected:#x}')
        clear = 0
        if write and mapped:
            if address == 0x00:
                state['ctrl'] = wdata & 0xff
            elif address == 0x0c:
                clear = wdata & 0xf
            elif address == 0x10:
                state['scratch'] = wdata & MASK
            elif is_memory:
                memory[word] = wdata & MASK
        state['irq'] = (state['irq'] & ~clear) | ev
        if write and address == 0x14 and wdata & 1:
            state.update(ctrl=0xa5, irq=0, scratch=0)
    return dict(stages=observed, events=events)

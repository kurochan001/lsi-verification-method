"""What the driver run must produce, written from the driver's and the peripherals' contract.

Neither platform is consulted: the timer's answers (status, overrun, EXPIRED after a restart)
follow from the register description, not from the TLM model or the RTL. The only value that
depends on timing is COUNT, so its read data is left open (None).
"""
import re

MASK = 0xffffffff
MEM, TIMER, UNMAPPED = 0x0000, 0x1000, 0x2000
LOAD, CTRL, STATUS, COUNT, EXPIRED = TIMER, TIMER + 4, TIMER + 8, TIMER + 0xc, TIMER + 0x10
CATEGORIES = ('PLAT_EVENT', 'PLAT_ACCESS', 'PLAT_MEMORY', 'PLAT_RESULT')
# Far away, one past the memory, one past the last timer register, one past the timer window, misaligned.
HOLES = (UNMAPPED, MEM + 0x100, TIMER + 0x14, TIMER + 0x20, MEM + 2)


def pattern(seed, index):
    x = ((seed * 0x9e3779b1) & MASK) ^ ((index * 0x85ebca6b) & MASK) ^ ((index << 7) & MASK)
    return x ^ (x >> 13)


def expected(config):
    """config: irqs, load, seed, race (lead and wait_limit change timing only)."""
    if not 1 <= config['irqs'] <= 16 or not 0 < config['load'] <= 0xffff:
        raise ValueError('irqs must be 1..16 and load 1..65535')
    memory = [0] * 64
    access, notes = [], []

    def write(address, value):
        access.append(('W', address, value & MASK, 0))
        if address < 0x100:
            memory[address // 4] = value & MASK

    def read(address, value):
        access.append(('R', address, value, 0))
        return value

    for k in range(16):
        write(MEM + 4 * k, pattern(config['seed'], k))
    for hole in HOLES:
        access.append(('R', hole, 0, 1))
    write(MEM + 0xc4, (1 << len(HOLES)) - 1)
    write(LOAD, 5)
    write(CTRL, 1)
    notes.append(('irq_level_masked', 0))   # pending is set, the enable is not
    write(MEM + 0xc8, 0)
    write(CTRL, 0)
    s1 = read(STATUS, 3)                    # several expiries: pending and overrun
    write(STATUS, 1)
    s2 = read(STATUS, 2)                    # acknowledging pending keeps overrun
    write(STATUS, 2)
    s3 = read(STATUS, 0)
    write(MEM + 0xcc, s1 | s2 << 4 | s3 << 8)
    write(LOAD, config['load'])
    write(CTRL, 3)
    acc = 0
    for k in range(config['irqs']):
        notes.append(('irq', k))
        status = read(STATUS, 1)
        expired = read(EXPIRED, (k + 1) & 0xff)  # no interrupt is lost or merged
        if config['race']:
            read(COUNT, None)
        write(STATUS, 1)
        word = read(MEM + 4 * (k % 16), memory[k % 16])
        acc = (acc + (word ^ expired)) & MASK
        write(MEM + 0x40 + 4 * (k % 16), expired | status << 16)
        write(MEM + 0x80 + 4 * (k % 16), acc)
    write(CTRL, 0)
    write(MEM + 0xc0, acc)
    write(MEM + 0xd0, read(CTRL, 0))
    write(MEM + 0xd4, read(LOAD, config['load']))
    return dict(access=access, notes=notes, memory=memory, result=0)


def parse(log):
    """Read one platform's log. Raises ValueError for anything that is not a complete run."""
    access, notes, memory, covers, fails, result, end = [], [], {}, set(), [], None, False
    for line in log.splitlines():
        if m := re.fullmatch(r'ACCESS ([RW]) ([0-9a-f]{8}) ([0-9a-f]{8}) ([01])', line):
            access.append((m[1], int(m[2], 16), int(m[3], 16), int(m[4])))
        elif m := re.fullmatch(r'NOTE ([a-z_]+) ([0-9a-f]{8})', line):
            notes.append((m[1], int(m[2], 16)))
        elif m := re.fullmatch(r'MEM ([0-9a-f]{2}) ([0-9a-f]{8})', line):
            word = int(m[1], 16)
            if word in memory or word >= 64:
                raise ValueError('duplicate or out-of-range memory word')
            memory[word] = int(m[2], 16)
        elif m := re.fullmatch(r'COVER (\S+)', line):
            covers.add(m[1])
        elif m := re.fullmatch(r'CHECK_FAIL (\w+)', line):
            fails.append(m[1])
        elif m := re.fullmatch(r'RESULT app=(-?\d+) cycles=\d+', line):
            if result is not None:
                raise ValueError('duplicate result')
            result = int(m[1])
        elif line == 'END':
            end = True
        elif line.startswith(('ACCESS', 'NOTE', 'MEM', 'COVER', 'CHECK_FAIL', 'RESULT')):
            raise ValueError('malformed line: ' + line)
    complete = end and result is not None and not fails and sorted(memory) == list(range(64))
    return dict(access=access, notes=notes, memory=[memory.get(i) for i in range(64)], result=result,
                covers=covers, fails=fails, complete=complete)


def masked(record):
    """A platform record with the timing-dependent COUNT read data left open."""
    return dict(record, access=[(op, a, None if (op, a) == ('R', COUNT) else d, e) for op, a, d, e in record['access']])


def differences(observed, reference):
    """Categories in which observed differs from reference, in a fixed order, with the first detail."""
    found = []
    if observed['notes'] != reference['notes']:
        found.append(('PLAT_EVENT', first(observed['notes'], reference['notes'])))
    if not same_access(observed['access'], reference['access']):
        found.append(('PLAT_ACCESS', first(observed['access'], reference['access'], same_item)))
    if observed['memory'] != reference['memory']:
        found.append(('PLAT_MEMORY', first(observed['memory'], reference['memory'])))
    if observed['result'] != reference['result']:
        found.append(('PLAT_RESULT', dict(observed=observed['result'], expected=reference['result'])))
    return found


def same_item(a, b):
    return a[:2] == b[:2] and a[3] == b[3] and (a[2] is None or b[2] is None or a[2] == b[2])


def same_access(a, b):
    return len(a) == len(b) and all(same_item(x, y) for x, y in zip(a, b))


def first(a, b, equal=lambda x, y: x == y):
    for i, (x, y) in enumerate(zip(a, b)):
        if not equal(x, y):
            return dict(index=i, observed=x, expected=y)
    return dict(index=min(len(a), len(b)), observed_length=len(a), expected_length=len(b))

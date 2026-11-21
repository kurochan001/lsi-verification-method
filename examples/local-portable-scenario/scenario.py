"""Scenario model of the portable scenario example.

A scenario is a list of actions on resources: two DMA channels and eight memory regions of 16
words. The same scenario is realized twice: as rows that a block-level bench executes against
the DMA alone, and as an RV32I program that the CPU of a small SoC executes against the same DMA.
Both realizations write a result record (one word per wait and per check) and leave memory;
both are compared with what this model predicts, under one scenario ID.

This copies the idea of portable stimulus (actions, resources, constraints, one intent and
several realizations) in a few hundred lines of Python. It does not read or run the Accellera
Portable Test and Stimulus Standard language.

The constraint checker (check) is written separately from the generator (generate) and replays
a scenario from scratch, so a generator that forgets a rule produces a scenario the checker
refuses.
"""
import importlib.util
from pathlib import Path
import random
import sys

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('portable_scenario_isa', HERE.parent / 'local-riscv-iss/iss.py')
ISA = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = ISA
spec.loader.exec_module(ISA)

CHANNELS = 2
REGIONS = 8
REGION_WORDS = 16
REGION_BASE = 64          # word index of region 0 in the 256-word RAM
RECORD_WORDS = 30         # words 0..29 hold the record, word 31 the end marker
DONE = 0x5CE7E7D0
TIMEOUT = 0xDEAD0000      # | wait number: the completion the scenario waits for never came
SOC_POLLS = 400           # polls of a wait before the program gives up
BLOCK_POLL_CYCLES = 1500  # cycles of a wait before the block bench gives up
RAM_BYTE_BASE = 0x2000
DMA_BASE = 0x40000000

# Coverage goals. The first group describes the structure of a scenario: it is credited when a
# run of that scenario passes. The second group is observed from the circuit by the bench.
STRUCTURE_GOALS = (
    'action/fill', 'action/copy-ch0', 'action/copy-ch1', 'action/wait', 'action/check',
    'concurrent/two-copies', 'concurrent/fill-during-copy', 'concurrent/check-during-copy',
    'conflict/channel-reuse', 'conflict/read-after-copy', 'conflict/shared-source',
    'order/wait-reversed', 'error/len-zero', 'error/len-over', 'error/range',
    'boundary/len-one', 'boundary/len-max', 'boundary/last-region')
OBSERVED_GOALS = ('observed/both-active', 'observed/ch1-first', 'observed/poll-repeated',
                  'observed/memory-stall', 'observed/ram-contention', 'mode/block', 'mode/soc')
GOALS = STRUCTURE_GOALS + OBSERVED_GOALS


def region_word(region, k=0):
    return REGION_BASE + REGION_WORDS * region + k


def status_word(err, moved):
    """CHn STATUS after completion: bit 0 busy (0), bit 1 error, bits 12..8 words moved."""
    return (moved & 0x1F) << 8 | (err & 1) << 1


def is_error(src, dst, length):
    return length == 0 or length > 16 or src + length > 256 or dst + length > 256


def rotate_xor(signature, word):
    return ((signature << 1 | signature >> 31) & 0xFFFFFFFF) ^ word


class Rejected(ValueError):
    def __init__(self, reason, index):
        super().__init__(f'{reason} at action {index}')
        self.reason = reason
        self.index = index


# ---------------------------------------------------------------- constraint checker
def check(actions):
    """Replay a scenario and refuse the first broken rule. Independent of generate().

    Actions: ('fill', region, values) / ('copy', ch, src_word, dst_word, length) with word
    indices into the 256-word RAM / ('wait', ch) / ('check', region, length).
    Rules: a channel holds one copy from its start to its wait; every copy is waited; a region
    an outstanding copy writes is not touched by anything else, and one it reads is not written;
    only defined words are read; a copy that is meant to succeed moves 1..16 words between two
    different regions; the record fits in the mailbox."""
    defined = set()
    outstanding = {}   # ch -> (src words, dst words)
    records = 0
    for index, action in enumerate(actions):
        kind = action[0]
        locked_w = set().union(*(d for _, d in outstanding.values())) if outstanding else set()
        locked_r = set().union(*(s for s, _ in outstanding.values())) if outstanding else set()
        if kind == 'fill':
            _, region, values = action
            if not 0 <= region < REGIONS or len(values) != REGION_WORDS:
                raise Rejected('out-of-range', index)
            words = {region_word(region, k) for k in range(REGION_WORDS)}
            if words & (locked_w | locked_r):
                raise Rejected('conflict', index)
            defined |= words
        elif kind == 'copy':
            _, ch, src, dst, length = action
            if ch not in range(CHANNELS) or not 0 <= src < 256 or not 0 <= dst < 256:
                raise Rejected('out-of-range', index)
            if ch in outstanding:
                raise Rejected('channel-busy', index)
            if is_error(src, dst, length):
                outstanding[ch] = (set(), set())
                continue
            src_words = set(range(src, src + length))
            dst_words = set(range(dst, dst + length))
            regions = {(w - REGION_BASE) // REGION_WORDS for w in src_words | dst_words}
            if min(src_words | dst_words) < REGION_BASE or max(src_words | dst_words) >= region_word(REGIONS):
                raise Rejected('out-of-range', index)
            if (src - REGION_BASE) // REGION_WORDS == (dst - REGION_BASE) // REGION_WORDS or len(regions) != 2:
                raise Rejected('same-region', index)
            if not src_words <= defined:
                raise Rejected('undefined-read', index)
            if src_words & locked_w or dst_words & (locked_w | locked_r):
                raise Rejected('conflict', index)
            outstanding[ch] = (src_words, dst_words)
            defined |= dst_words
        elif kind == 'wait':
            _, ch = action
            if ch not in outstanding:
                raise Rejected('wait-idle', index)
            del outstanding[ch]
            records += 1
        elif kind == 'check':
            _, region, length = action
            if not 0 <= region < REGIONS or not 1 <= length <= REGION_WORDS:
                raise Rejected('out-of-range', index)
            words = {region_word(region, k) for k in range(length)}
            if not words <= defined:
                raise Rejected('undefined-read', index)
            if words & locked_w:
                raise Rejected('conflict', index)
            records += 1
        else:
            raise Rejected('unknown-action', index)
        if records > RECORD_WORDS:
            raise Rejected('mailbox-full', index)
    if outstanding:
        raise Rejected('unwaited', len(actions))
    return True


# ---------------------------------------------------------------- expected outcome
def expect(actions):
    """Record words, final memory of the defined words, and the structural goals covered."""
    memory, status, outstanding, record = {}, {}, {}, []
    goals = set()
    used = set()
    starts = []                  # channel start order of outstanding copies
    written_by_copy = set()
    for action in actions:
        kind = action[0]
        if kind == 'fill':
            _, region, values = action
            goals.add('action/fill')
            if outstanding:
                goals.add('concurrent/fill-during-copy')
            if region == REGIONS - 1:
                goals.add('boundary/last-region')
            for k, v in enumerate(values):
                memory[region_word(region, k)] = v
        elif kind == 'copy':
            _, ch, src, dst, length = action
            goals.add(f'action/copy-ch{ch}')
            if ch in used:
                goals.add('conflict/channel-reuse')
            used.add(ch)
            if is_error(src, dst, length):
                goals.add('error/len-zero' if length == 0 else 'error/len-over' if length > 16 else 'error/range')
                status[ch] = status_word(1, 0)
            else:
                if length == 1:
                    goals.add('boundary/len-one')
                if length == 16:
                    goals.add('boundary/len-max')
                if any(w in written_by_copy for w in range(src, src + length)):
                    goals.add('conflict/read-after-copy')
                if any(s & set(range(src, src + length)) for s, _ in outstanding.values()):
                    goals.add('conflict/shared-source')
                if REGIONS - 1 in ((src - REGION_BASE) // REGION_WORDS, (dst - REGION_BASE) // REGION_WORDS):
                    goals.add('boundary/last-region')
                for k in range(length):
                    memory[dst + k] = memory[src + k]
                written_by_copy |= set(range(dst, dst + length))
                status[ch] = status_word(0, length)
            if outstanding:
                goals.add('concurrent/two-copies')
            outstanding[ch] = (set(range(src, src + length)) if not is_error(src, dst, length) else set(), None)
            starts.append(ch)
        elif kind == 'wait':
            _, ch = action
            goals.add('action/wait')
            if starts and starts[0] != ch:
                goals.add('order/wait-reversed')
            starts.remove(ch)
            del outstanding[ch]
            record.append(status[ch])
        elif kind == 'check':
            _, region, length = action
            goals.add('action/check')
            if outstanding:
                goals.add('concurrent/check-during-copy')
            if region == REGIONS - 1:
                goals.add('boundary/last-region')
            words = [region_word(region, k) for k in range(length)]
            if any(w in written_by_copy for w in words):
                goals.add('conflict/read-after-copy')
            signature = 0
            for w in words:
                signature = rotate_xor(signature, memory[w])
            record.append(signature)
    return dict(record=record, memory=dict(sorted(memory.items())), goals=goals,
                copies=sum(a[0] == 'copy' for a in actions))


# ---------------------------------------------------------------- generator
def fill_values(rng):
    return tuple(rng.getrandbits(32) for _ in range(REGION_WORDS))


def generate(seed, steps=12, *, ignore_locks=False):
    """A random legal scenario. ignore_locks is the deliberate generator bug of the self-tests:
    it forgets that an outstanding copy holds its regions."""
    rng = random.Random(seed)
    actions = []
    defined = {}                   # region -> number of defined words from its start
    outstanding = {}               # ch -> (src region, dst region)
    records = 0

    def locked(region, writing):
        for s, d in outstanding.values():
            if ignore_locks:
                continue
            if region == d or (writing and region == s):
                return True
        return False

    def add_wait(ch):
        nonlocal records
        actions.append(('wait', ch))
        del outstanding[ch]
        records += 1

    for _ in range(steps):
        options = []
        free_fill = [r for r in range(REGIONS) if not locked(r, True)]
        if free_fill:
            options.append('fill')
        idle = [c for c in range(CHANNELS) if c not in outstanding]
        if idle and defined:
            options += ['copy', 'copy', 'error']
        if outstanding:
            options += ['wait', 'wait']
        readable = [r for r in defined if not locked(r, False)]
        if readable:
            options.append('check')
        choice = rng.choice(options)
        if records >= RECORD_WORDS - CHANNELS - 1 and choice in ('check', 'copy', 'error'):
            choice = 'wait' if outstanding else 'fill'
            if choice == 'fill' and not free_fill:
                break
        if choice == 'fill':
            r = rng.choice(free_fill)
            actions.append(('fill', r, fill_values(rng)))
            defined[r] = REGION_WORDS
        elif choice in ('copy', 'error'):
            ch = rng.choice(idle)
            src_choices = [r for r in defined if not locked(r, False) or ignore_locks]
            if not src_choices:
                continue
            src = rng.choice(src_choices)
            if choice == 'error':
                kind = rng.choice(('zero', 'over', 'range'))
                if kind == 'zero':
                    actions.append(('copy', ch, region_word(src), region_word((src + 1) % REGIONS), 0))
                elif kind == 'over':
                    actions.append(('copy', ch, region_word(src), region_word((src + 1) % REGIONS), 17))
                else:  # the destination runs past the last RAM word; the index itself stays below 256
                    length = rng.randint(2, 16)
                    actions.append(('copy', ch, region_word(src), 256 - length + rng.randint(1, length - 1), length))
                outstanding[ch] = (None, None)
                continue
            dst_choices = [r for r in range(REGIONS) if r != src and not locked(r, True)]
            if not dst_choices:
                continue
            dst = rng.choice(dst_choices)
            length = rng.choice((1, 16, rng.randint(1, defined[src])))
            length = min(length, defined[src])
            actions.append(('copy', ch, region_word(src), region_word(dst), length))
            outstanding[ch] = (src, dst)
            defined[dst] = max(defined.get(dst, 0), length)
        elif choice == 'wait':
            add_wait(rng.choice(sorted(outstanding)))
        else:
            r = rng.choice(readable)
            actions.append(('check', r, rng.randint(1, defined[r])))
            records += 1
    for ch in sorted(outstanding):
        add_wait(ch)
    return actions


def directed():
    """Named scenarios; together they reach every structural goal."""
    rng = random.Random(2026)
    f = [fill_values(rng) for _ in range(REGIONS)]
    w = region_word
    return {
        # Two concurrent full copies, waited in reverse order, then a one-word copy from a copied region.
        'basic': [('fill', 0, f[0]), ('fill', 1, f[1]), ('copy', 0, w(0), w(2), 16), ('copy', 1, w(1), w(3), 16),
                  ('wait', 1), ('wait', 0), ('check', 2, 16), ('check', 3, 16),
                  ('copy', 0, w(2), w(4), 1), ('wait', 0), ('check', 4, 1)],
        # The three refused copies; after them each channel makes a good copy (the error must not stay).
        'errors': [('fill', 5, f[5]), ('copy', 0, w(5), w(6), 0), ('wait', 0), ('copy', 1, w(5), w(6), 17), ('wait', 1),
                   ('copy', 0, w(5), 250, 8), ('wait', 0), ('copy', 1, w(5), w(7), 16), ('wait', 1), ('check', 7, 16),
                   ('copy', 0, w(5), w(6), 4), ('wait', 0), ('check', 6, 4)],
        # A long and a one-word copy from the same source: both are pending before the first acknowledge.
        # Channel 1 is used again for a good copy: its word count must start from 0.
        'both-pending': [('fill', 0, f[0]), ('copy', 0, w(0), w(1), 16), ('copy', 1, w(0), w(2), 1),
                         ('wait', 0), ('wait', 1), ('check', 1, 16), ('check', 2, 1),
                         ('copy', 1, w(1), w(3), 5), ('wait', 1), ('check', 3, 5)],
        # The CPU fills another region and reads the source while a copy runs.
        'contention': [('fill', 0, f[0]), ('copy', 0, w(0), w(1), 16), ('fill', 2, f[2]), ('check', 0, 16),
                       ('wait', 0), ('check', 1, 16), ('check', 2, 16)],
    }


# ---------------------------------------------------------------- realizations
# Rows of the vectors file: kind a b c.
MODE, ROM, ACT, EXP_REC, EXP_MEM, META, GOAL = range(1, 8)
FILLW, REGW, WAIT, CHECK, END = range(1, 6)
META_IDS = dict(max_cycles=1, records=2, copies=3, stall=4)
BLOCK, SOC = 1, 2


def block_rows(actions):
    """The block realization: memory writes, register writes, polled waits and signatures."""
    rows, waits = [], 0
    for action in actions:
        kind = action[0]
        if kind == 'fill':
            _, region, values = action
            rows += [(ACT, FILLW, region_word(region, k), v) for k, v in enumerate(values)]
        elif kind == 'copy':
            _, ch, src, dst, length = action
            base = 0x10 * ch
            rows += [(ACT, REGW, base, src), (ACT, REGW, base + 4, dst), (ACT, REGW, base + 8, length),
                     (ACT, REGW, base + 0xC, 1)]
        elif kind == 'wait':
            rows.append((ACT, WAIT, action[1], waits))
            waits += 1
        else:
            _, region, length = action
            rows.append((ACT, CHECK, region_word(region), length))
    rows.append((ACT, END, 0, 0))
    return rows


def li(register, value):
    value &= 0xFFFFFFFF
    low = ISA.sext(value, 12)
    return [('lui', register, (value - low) >> 12 & 0xFFFFF), ('addi', register, register, low)]


def program(actions):
    """The SoC realization: an RV32I program. x27 holds the DMA base, x29 the RAM base; the
    record goes to RAM words 0..29 and the end marker to word 31."""
    p = [('lui', 27, DMA_BASE >> 12), ('lui', 29, RAM_BYTE_BASE >> 12)]
    record, waits = 0, 0
    for n, action in enumerate(actions):
        kind = action[0]
        if kind == 'fill':
            _, region, values = action
            for k, v in enumerate(values):
                p += [*li(1, v), ('sw', 1, 4 * region_word(region, k), 29)]
        elif kind == 'copy':
            _, ch, src, dst, length = action
            base = 0x10 * ch
            p += [('addi', 1, 0, src), ('sw', 1, base, 27), ('addi', 1, 0, dst), ('sw', 1, base + 4, 27),
                  ('addi', 1, 0, length), ('sw', 1, base + 8, 27), ('addi', 1, 0, 1), ('sw', 1, base + 0xC, 27)]
        elif kind == 'wait':
            ch = action[1]
            p += [('addi', 5, 0, SOC_POLLS), f'poll{n}:', ('lw', 2, 0x20, 27), ('andi', 3, 2, 1 << ch),
                  ('bne', 3, 0, f'got{n}'), ('addi', 5, 5, -1), ('bne', 5, 0, f'poll{n}'),
                  *li(1, TIMEOUT | waits), ('sw', 1, 4 * record, 29), ('jal', 0, f'next{n}'),
                  f'got{n}:', ('addi', 1, 0, 1 << ch), ('sw', 1, 0x20, 27),
                  ('lw', 2, 0x10 * ch + 0xC, 27), ('sw', 2, 4 * record, 29), f'next{n}:']
            record += 1
            waits += 1
        else:
            _, region, length = action
            p.append(('addi', 6, 0, 0))
            for k in range(length):
                p += [('lw', 2, 4 * region_word(region, k), 29), ('slli', 3, 6, 1), ('srli', 4, 6, 31),
                      ('or', 6, 3, 4), ('xor', 6, 6, 2)]
            p.append(('sw', 6, 4 * record, 29))
            record += 1
    p += [*li(1, DONE), ('sw', 1, 4 * 31, 29), ('ebreak',)]
    return ISA.assemble(p)


def rows(actions, mode, stall=False):
    """All rows of one run. The expectations are the same for both modes."""
    check(actions)
    out = expect(actions)
    r = [(MODE, mode, 0, 0)]
    if mode == SOC:
        words = program(actions)
        if len(words) > 4096:
            raise ValueError('program larger than the ROM')
        r += [(ROM, i, w, 0) for i, w in enumerate(words)]
        cycles = 40 * len(words) + 4000
    else:
        r += block_rows(actions)
        cycles = 10 * len(r) + BLOCK_POLL_CYCLES * sum(a[0] == 'wait' for a in actions) + 2000
    r += [(EXP_REC, i, v, 0) for i, v in enumerate(out['record'])]
    r += [(EXP_MEM, a, v, 0) for a, v in out['memory'].items()]
    r += [(META, META_IDS['max_cycles'], cycles, 0), (META, META_IDS['records'], len(out['record']), 0),
          (META, META_IDS['copies'], out['copies'], 0), (META, META_IDS['stall'], int(stall), 0)]
    r += [(GOAL, STRUCTURE_GOALS.index(g), 0, 0) for g in sorted(out['goals'])]
    counts = dict(records=len(out['record']), copies=out['copies'])
    return r, counts


def coverage(scenarios):
    """Share of the structural scenario space a set of scenarios reaches, and the ordered pairs
    of action kinds that follow each other (a coarse view of the sequence space)."""
    goals, pairs = set(), set()
    kinds = ('fill', 'copy', 'error', 'wait', 'check')
    for actions in scenarios:
        goals |= expect(actions)['goals']
        names = ['error' if a[0] == 'copy' and is_error(*a[2:5]) else a[0] for a in actions]
        pairs |= set(zip(names, names[1:]))
    return dict(goals=sorted(goals), goal_share=len(goals) / len(STRUCTURE_GOALS),
                pairs=sorted(pairs), pair_share=len(pairs) / len(kinds) ** 2)

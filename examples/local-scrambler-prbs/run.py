#!/usr/bin/env python3
"""PRBS generator and self-synchronizing checker, scrambler and descrambler, word-parallel RTL against bit-serial models."""
import copy
import importlib.util
from pathlib import Path
import random
import sys

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('scrambler_prbs_model', HERE / 'model.py')
MODEL = importlib.util.module_from_spec(spec)
spec.loader.exec_module(MODEL)

NAME = 'local-scrambler-prbs'
TOP = 'scrambler_prbs_tb'
# PRBS polynomial (PN, PTAP), scrambler polynomial (SN, STAP), bits per clock.
CONFIGS = {
    'p7-w1': dict(PN=7, PTAP=6, SN=58, STAP=39, W=1),
    'p7-w8': dict(PN=7, PTAP=6, SN=58, STAP=39, W=8),      # a word longer than the PRBS history
    'p15-w8': dict(PN=15, PTAP=14, SN=58, STAP=39, W=8),
    'p31-w16': dict(PN=31, PTAP=28, SN=58, STAP=39, W=16),
}
ITERATIONS = {'smoke': 400, 'nightly': 3000}
SOURCES = [HERE / 'rtl/prbs_gen.sv', HERE / 'rtl/prbs_check.sv', HERE / 'rtl/ss_scrambler.sv',
           HERE / 'rtl/ss_descrambler.sv', HERE / 'tb/scrambler_prbs_tb.sv']
EXTRA_INPUTS = [HERE / 'model.py']
MUTANTS = 12
LABELS = {1: 'GEN_DATA', 2: 'GEN_DATA', 3: 'GEN_ZERO', 4: 'GEN_DATA', 5: 'CHK_COUNT', 6: 'CHK_LOCK',
          7: 'CHK_LOCK', 8: 'SCR_DATA', 9: 'DSC_DATA', 10: 'DSC_DATA', 11: 'SCR_DATA', 12: 'CHK_LOCK'}
PARALLEL_ONLY = {4, 11}      # mutants of the word-parallel update; they change nothing at W = 1
LOCK, LOSS, COUNT_BITS = 32, 8, 6     # the test bench instantiates the checker with these
COUNT_MAX = (1 << COUNT_BITS) - 1
# Tags tell the test bench which fixed scene a row belongs to. They only select cover lines.
G_IDLE, G_LOAD, G_ZERO, G_RECOVER = 1, 2, 3, 4
C_IDLE, C_SINGLE, C_SLIP, C_BELOW, C_STUCK = 1, 2, 3, 4, 5
S_IDLE, S_ZERO, S_LOCKUP, S_AFTER = 1, 2, 3, 4
D_START, D_ACQUIRED, D_ERROR, D_AFTER_ERROR, D_SLIP, D_AFTER_SLIP, D_IDLE = 1, 2, 3, 4, 5, 6, 7


def visible(parameters):
    return set(range(1, MUTANTS + 1)) - (PARALLEL_ONLY if parameters['W'] == 1 else set())


class Bits:
    """A bit stream with one tag per bit, cut into words of W bits."""

    def __init__(self, width):
        self.width, self.bits, self.tags, self.extra = width, [], [], []

    def add(self, bit, tag=0, extra=0):
        self.bits.append(bit)
        self.tags.append(tag)
        self.extra.append(extra)

    def room(self):
        return -len(self.bits) % self.width

    def words(self):
        if self.room():
            raise ValueError('stream does not end on a word')
        w = self.width
        for i in range(0, len(self.bits), w):
            yield MODEL.pack(self.bits[i:i + w]), max(self.tags[i:i + w]), MODEL.pack(self.extra[i:i + w])


class Session:
    """The four circuits between two resets. Each method advances one circuit by one clock
    and returns that circuit's columns; rows() joins them, idling the circuits that are done."""

    def __init__(self, parameters, rng):
        p = parameters
        self.w, self.rng = p['W'], rng
        self.pn, self.ptap, self.sn, self.stap = p['PN'], p['PTAP'], p['SN'], p['STAP']
        self.mask = (1 << self.w) - 1
        self.gen = MODEL.Generator(self.pn, self.ptap)
        self.chk = MODEL.Checker(self.pn, self.ptap, LOCK, LOSS, COUNT_BITS)
        self.scr = MODEL.Scrambler(self.sn, self.stap)
        self.dsc = MODEL.Descrambler(self.sn, self.stap)
        self.columns = [[], [], [], []]

    def gen_clock(self, enable=1, load=0, seed=0, tag=0):
        word = MODEL.pack(self.gen.peek(self.w))
        if load:
            self.gen.load(seed)
        elif enable:
            for _ in range(self.w):
                self.gen.bit()
        self.columns[0].append([tag, enable, load, seed, word, self.gen.zero()])

    def chk_clock(self, word, valid=1, tag=0):
        flags = [self.chk.bit(word >> i & 1) for i in range(self.w)] if valid else []
        self.columns[1].append([tag, valid, word, MODEL.pack(flags), self.chk.locked, self.chk.count, self.chk.stuck()])

    def scr_clock(self, word, valid=1, tag=0):
        model = self.scr if valid else copy.deepcopy(self.scr)      # the output is combinational
        out = MODEL.pack([model.bit(word >> i & 1) for i in range(self.w)])
        self.columns[2].append([tag, valid, word, out])

    def dsc_clock(self, word, original, valid=1, tag=0):
        model = self.dsc if valid else copy.deepcopy(self.dsc)
        out = MODEL.pack([model.bit(word >> i & 1) for i in range(self.w)])
        self.columns[3].append([tag, valid, word, out, original])

    def rows(self, reset_cycles=2):
        """Reset rows, then one row per clock. A circuit whose scenes are over holds its state."""
        hold = [[0, 0, 0, 0, MODEL.pack(self.gen.peek(self.w)), self.gen.zero()],
                [0, 0, 0, 0, self.chk.locked, self.chk.count, self.chk.stuck()],
                [0, 0, 0, MODEL.pack(self._peek(self.scr))],
                [0, 0, 0, MODEL.pack(self._peek(self.dsc)), 0]]
        out = [[0] * 23 for _ in range(reset_cycles)]
        for i in range(max(len(c) for c in self.columns)):
            row = [1]
            for column, idle in zip(self.columns, hold):
                row += column[i] if i < len(column) else idle
            out.append(row)
        return out

    def _peek(self, model):
        model = copy.deepcopy(model)
        return [model.bit(0) for _ in range(self.w)]


def checker_stream(s, random_tail):
    """The fixed scenes of the checker as one bit stream; returns the Bits and facts for the tests."""
    n, tap, w, rng = s.pn, s.ptap, s.w, s.rng
    source = MODEL.Generator(n, tap)
    shadow = MODEL.Checker(n, tap, LOCK, LOSS, COUNT_BITS)    # follows the stream to steer the scenes
    b, facts = Bits(w), {}

    def put(bit, tag=0):
        b.add(bit, tag)
        return shadow.bit(bit)

    def clean(count, tag=0):
        return sum(put(source.bit(), tag) for _ in range(count))

    def settle(tag=0):
        clean(b.room())
        clean(w, tag)

    def errors(offsets, span, tag=0):
        return sum(put(source.bit() ^ (i in offsets), tag) for i in range(span))

    clean(n + LOCK + 8)                                   # fill, then lock
    settle()
    facts['single'] = errors({0}, n + 1, C_SINGLE)        # one wrong bit: flags at 0, TAP and N
    clean(LOCK + 4)
    settle()
    # LOSS - 1 flags with fewer than LOCK clean bits between them keep the lock ...
    shadow.peak_bad = 0
    facts['below'] = errors({0, n + 2, n + 2 + tap}, 2 * n + tap + 3)
    facts['below_peak'], facts['below_locked'] = shadow.peak_bad, shadow.locked
    settle(C_BELOW)
    clean(LOCK + 4)
    # ... and LOSS flags drop it, on the last one.
    span = 2 * (tap + n) + 3
    before = shadow.locked
    facts['at'] = errors({0, tap, tap + n + 2, 2 * tap + n + 2}, span)
    facts['at_locked'] = (before, shadow.locked)
    # An error while not locked is not counted. It is placed so that the LOCK-th clean bit after
    # its last flag is the first bit of a word: a lock that came one bit early would show one word early.
    clean(-(len(b.bits) + n + LOCK) % w)
    facts['relock_bit'] = len(b.bits) + n + LOCK
    put(source.bit() ^ 1)
    clean(n + LOCK + 8)                                   # locks again
    settle()
    source.bit()                                          # the channel drops one bit
    facts['slip_flags'] = clean(n + 4)
    facts['slip_lost'] = not shadow.locked
    clean(LOCK + 4)                                       # long enough to lock again if the slip cost the lock
    settle(C_SLIP)
    for _ in range(n + LOCK + 16):                        # stuck at 0: never error free, never locked
        put(0)
    while b.room():
        put(0)
    for _ in range(w):
        put(0, C_STUCK)
    clean(n + LOCK + 8)
    settle()
    while shadow.count < COUNT_MAX:                       # up to the counter limit, then one more
        errors({0}, n + 1)
        clean(LOCK + 4)
    facts['count_before_extra'] = shadow.count
    errors({0}, n + 1)
    clean(LOCK + 4)
    settle()
    for _ in range(random_tail):
        put(source.bit() ^ (rng.random() < 0.02))
    clean(b.room())
    facts['count'] = shadow.count
    return b, facts


def fixed_session(parameters, seed=1):
    rng = random.Random(seed)
    s = Session(parameters, rng)
    w, pn, sn, stap = s.w, s.pn, s.sn, s.stap
    # Generator: run through more than two periods of the shortest sequence, hold, load, all-zero, recover.
    for _ in range(-(-300 // w)):
        s.gen_clock()
    for _ in range(3):
        s.gen_clock(enable=0, tag=G_IDLE)
    for _ in range(4):
        s.gen_clock()
    s.gen_clock(load=1, seed=0x2A5A5A5A & ((1 << pn) - 1), tag=G_LOAD)     # load wins over enable
    for _ in range(4):
        s.gen_clock()
    for seed in (1, 1 << (pn - 1)):                       # one 1 at either end of the history is not zero
        s.gen_clock(enable=0, load=1, seed=seed)
        s.gen_clock(enable=0)
    s.gen_clock(enable=0, load=1, seed=0, tag=G_ZERO)
    for _ in range(3):
        s.gen_clock(tag=G_ZERO)
    s.gen_clock(load=1, seed=1 << (pn - 1), tag=G_RECOVER)
    for _ in range(-(-(2 * pn) // w)):
        s.gen_clock()
    # Checker.
    stream, facts = checker_stream(s, random_tail=0)
    words = list(stream.words())
    for index, (word, tag, _) in enumerate(words):
        if index in (5, len(words) // 2):                 # idle clocks with other data on the pins
            for _ in range(2):
                s.chk_clock(word ^ s.mask, valid=0, tag=C_IDLE)
        s.chk_clock(word, tag=tag)
    # Scrambler.
    b = Bits(w)
    for _ in range(200 + (-200 % w)):
        b.add(rng.getrandbits(1))
    for word, tag, _ in b.words():
        s.scr_clock(word, tag=tag)
    for _ in range(3):
        s.scr_clock(rng.getrandbits(w), valid=0, tag=S_IDLE)
    for _ in range(-(-(2 * sn) // w)):
        s.scr_clock(0, tag=S_ZERO)                        # zero data leaves the scrambler as non-zero bits
    b = Bits(w)
    shadow = copy.deepcopy(s.scr)
    for _ in range(sn):                                   # data equal to the feedback: sn zeros are sent
        bit = shadow.feedback()
        shadow.bit(bit)
        b.add(bit)
    for _ in range(b.room()):
        shadow.bit(0)
        b.add(0)
    for word, tag, _ in b.words():
        s.scr_clock(word, tag=tag)
    for _ in range(3):
        s.scr_clock(0, tag=S_LOCKUP)                      # the history is all zero: zero data stays zero
    s.scr_clock(1, tag=S_AFTER)                           # one data bit ends it
    for _ in range(-(-(2 * sn) // w)):
        s.scr_clock(0, tag=S_AFTER)
    # Descrambler, fed by a scrambler model that is already running.
    far = MODEL.Scrambler(sn, stap)
    for _ in range(100):
        far.bit(rng.getrandbits(1))
    b = Bits(w)

    def send(count, tag=0, flip=()):
        for i in range(count):
            data = rng.getrandbits(1)
            b.add(far.bit(data) ^ (i in flip), tag, data)

    def settle(tag):
        send(b.room())
        send(w, tag)

    send(sn, D_START)                                     # the history still holds the reset value
    settle(D_ACQUIRED)
    send(sn + 1, D_ERROR, flip={0})                       # one wrong bit: wrong data at 0, STAP and SN
    settle(D_AFTER_ERROR)
    far.bit(rng.getrandbits(1))                           # the channel drops one bit
    send(sn, D_SLIP)
    settle(D_AFTER_SLIP)
    words = list(b.words())
    for index, (word, tag, original) in enumerate(words):
        if index == len(words) // 2:
            for _ in range(3):
                s.dsc_clock(rng.getrandbits(w), original, valid=0, tag=D_IDLE)
        s.dsc_clock(word, original, tag=tag)
    return s, facts


def boundary_rows(parameters):
    s, _ = fixed_session(parameters)
    rows = s.rows()
    # A reset in the middle of operation, then a short second run from the reset values.
    t = Session(parameters, random.Random(2))
    for _ in range(4):
        t.gen_clock()
    source = MODEL.Generator(t.pn, t.ptap)
    for _ in range(-(-(t.pn + LOCK + 8) // t.w) + 1):
        t.chk_clock(MODEL.pack([source.bit() for _ in range(t.w)]))
    for _ in range(4):
        t.scr_clock(0)
        t.dsc_clock(t.mask, 0)
    return rows + t.rows(reset_cycles=1)


def random_rows(parameters, seed, iterations):
    rng = random.Random(seed)
    s = Session(parameters, rng)
    w, pn, sn, stap = s.w, s.pn, s.sn, s.stap
    source, far = MODEL.Generator(pn, s.ptap), MODEL.Scrambler(sn, stap)
    zeros = 0
    for _ in range(iterations):
        roll = rng.random()
        if roll < 0.03:
            s.gen_clock(enable=rng.getrandbits(1), load=1, seed=0 if rng.random() < 0.2 else rng.getrandbits(pn))
        else:
            s.gen_clock(enable=int(rng.random() < 0.85))
        bits = []
        for _ in range(w):
            if zeros:
                zeros -= 1
                bits.append(0)
                continue
            roll = rng.random()
            if roll < 0.003:
                source.bit()                              # slip
            elif roll < 0.006:
                zeros = rng.randrange(pn, pn + 2 * LOCK)
            bits.append(source.bit() ^ (rng.random() < 0.015))
        s.chk_clock(MODEL.pack(bits), valid=int(rng.random() < 0.9))
        s.scr_clock(0 if rng.random() < 0.05 else rng.getrandbits(w), valid=int(rng.random() < 0.9))
        sent, original = [], []
        for _ in range(w):
            if rng.random() < 0.003:
                far.bit(rng.getrandbits(1))               # slip
            data = rng.getrandbits(1)
            original.append(data)
            sent.append(far.bit(data) ^ (rng.random() < 0.01))
        s.dsc_clock(MODEL.pack(sent), MODEL.pack(original), valid=int(rng.random() < 0.9))
    return s.rows()


def counts(rows):
    ones = lambda value: bin(value).count('1')
    live = [r for r in rows if r[0]]
    return dict(gen_words=sum(r[2] and not r[3] for r in live), chk_flags=sum(ones(r[10]) for r in live if r[8]),
                scr_words=sum(r[15] for r in live), dsc_wrong=sum(ones(r[21] ^ r[22]) for r in live if r[19]))


def make_cases(args, parameters):
    base = boundary_rows(parameters)
    cases = [dict(id='boundaries', vectors=base, mutation=args.demo_bug, category='functional', expected_failure=None)]
    for seed in range(args.seed, args.seed + (3 if args.profile == 'nightly' else 1)):
        cases.append(dict(id=f'random-seed{seed}', vectors=random_rows(parameters, seed, args.iterations),
                          mutation=args.demo_bug, category='functional', expected_failure=None))
    seen = visible(parameters)
    for mutation in range(1, MUTANTS + 1):
        if mutation in seen:
            cases.append(dict(id=f'detect-mutation{mutation}', vectors=base, mutation=mutation,
                              category='mutation', expected_failure=LABELS[mutation]))
        else:   # the word-parallel update does not exist at one bit per clock
            cases.append(dict(id=f'survive-mutation{mutation}', vectors=base, mutation=mutation,
                              category='diagnostic', expected_failure=None))
    for case in cases:
        case['counts'] = counts(case['vectors'])
    return cases


if __name__ == '__main__':
    spec = importlib.util.spec_from_file_location('local_runner', HERE.parent / 'local-common/runner.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    sys.exit(module.main(sys.modules[__name__]))

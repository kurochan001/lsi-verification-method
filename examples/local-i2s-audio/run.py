#!/usr/bin/env python3
"""I2S transmitter and slave receiver: bit timing, channels, word and slot length, loopback."""
import importlib.util
from pathlib import Path
import random
import sys

HERE = Path(__file__).resolve().parent
NAME = 'local-i2s-audio'
TOP = 'i2s_tb'
CONFIGS = {'w16-s16': dict(WORD=16, SLOT=16), 'w24-s32': dict(WORD=24, SLOT=32)}
ITERATIONS = {'smoke': 24, 'nightly': 40}
SOURCES = [HERE / 'rtl/i2s_tx.sv', HERE / 'rtl/i2s_rx.sv', HERE / 'tb/i2s_tb.sv']
MUTANTS = 7
LABELS = {1: 'I2S_TX_WS', 2: 'I2S_TX_SD', 3: 'I2S_TX_SD', 4: 'I2S_TX_FLOW',
          5: 'I2S_RX_DATA', 6: 'I2S_RX_DATA', 7: 'I2S_RX_ERROR'}


def word_bits(value, word, slot):
    """One slot on the wire: the word most significant bit first, then zeros up to the slot."""
    return [(value >> (word - 1 - i)) & 1 for i in range(word)] + [0] * (slot - word)


def frame_bits(left, right, word, slot):
    return word_bits(left, word, slot) + word_bits(right, word, slot)


def bits_word(bits, word):
    """What a receiver keeps of a slot: the first WORD bits, missing ones read as zero."""
    kept = (list(bits) + [0] * word)[:word]
    return sum(bit << (word - 1 - i) for i, bit in enumerate(kept))


class Transmitter:
    """The transmitter as arithmetic on the number of clocks since reset; no shift register.

    After t clocks sck is t odd. ws and sd change on the even clocks. The u-th change shows
    position (u - 2) mod FRAME of the frame, the first two changes are the lead-in, and ws
    always shows the channel of the following position.
    """

    def __init__(self, word, slot):
        self.word, self.slot, self.frame = word, slot, 2 * slot
        self.reset()

    def reset(self):
        self.clocks, self.hold, self.bits, self.underrun = 0, None, [0] * self.frame, 0

    @property
    def pins(self):
        changes = self.clocks // 2
        position = (changes - 2) % self.frame
        sd = self.bits[position] if changes >= 2 else 0
        ws = int((position + 1) % self.frame >= self.slot) if changes else 1
        return self.clocks % 2, ws, sd

    def clock(self, in_valid, left, right):
        waiting, self.underrun = self.hold, 0
        if in_valid and waiting is None:
            self.hold = (left, right)
        self.clocks += 1
        if self.clocks % 2 == 0 and (self.clocks // 2 - 2) % self.frame == 0:
            self.bits = frame_bits(*waiting, self.word, self.slot) if waiting else [0] * self.frame
            self.underrun = int(waiting is None)
            if waiting:
                self.hold = None


class Receiver:
    """The receiver as a parser of the list of (ws, sd) samples taken on rising edges of sck."""

    def __init__(self, word, slot):
        self.word, self.slot = word, slot
        self.reset()

    def reset(self):
        self.samples, self.start, self.pending = [], None, None
        self.left = self.right = self.frames = self.errors = 0

    def sample(self, ws, sd):
        self.samples.append((ws, sd))
        index = len(self.samples) - 1
        if index == 0 or self.samples[index - 1][0] == ws:
            return
        if self.start is not None:
            channel = self.samples[self.start][0]                # the change announced this channel
            bits = [s[1] for s in self.samples[self.start + 1:index + 1]]
            if len(bits) != self.slot:
                self.errors = (self.errors + 1) & 0xff
            if channel == 0:
                self.pending = bits_word(bits, self.word)
            elif self.pending is not None:
                self.left, self.right, self.pending = self.pending, bits_word(bits, self.word), None
                self.frames = (self.frames + 1) & 0xff
        self.start = index


class Model:
    """Transmitter, receiver and the selector in front of the receiver, one row per clock."""

    def __init__(self, word, slot):
        self.tx, self.rx, self.level = Transmitter(word, slot), Receiver(word, slot), 0

    def wire(self, rst_n, sel_ext, ext):
        """The receiver sees the transmitter or the external pins; it samples on a rising sck."""
        sck, ws, sd = ext if sel_ext else self.tx.pins
        if rst_n and sck and not self.level:
            self.rx.sample(ws, sd)
        self.level = sck

    def step(self, rst_n=1, in_valid=0, left=0, right=0, sel_ext=0, ext_sck=0, ext_ws=0, ext_sd=0):
        if not rst_n:
            self.rx.reset()                                       # asynchronous
        ext = (ext_sck, ext_ws, ext_sd)
        self.wire(rst_n, sel_ext, ext)
        row = [rst_n, in_valid, left, right, sel_ext, ext_sck, ext_ws, ext_sd,
               int(self.tx.hold is None), *self.tx.pins, self.tx.underrun,
               self.rx.frames, self.rx.left, self.rx.right, self.rx.errors]
        if rst_n:
            self.tx.clock(in_valid, left, right)
        else:
            self.tx.reset()
        self.wire(rst_n, sel_ext, ext)
        return row


class Plan:
    def __init__(self, word, slot):
        self.word, self.slot, self.model, self.rows = word, slot, Model(word, slot), []
        self.sel, self.ext = 0, (0, 0, 0)

    def cycle(self, **inputs):
        sck, ws, sd = self.ext
        self.rows.append(self.model.step(sel_ext=self.sel, ext_sck=sck, ext_ws=ws, ext_sd=sd, **inputs))

    def reset(self, external=0, rows=2):
        """The selector only moves while the receiver is held in reset."""
        self.cycle(rst_n=0)
        moved, self.sel = external != self.sel, external
        self.ext = (0, 0, 0) if external else (0, 1, 1)           # ignored pins are not left at zero
        for _ in range(max(rows - 1, int(moved))):
            self.cycle(rst_n=0)

    def idle(self, rows=1):
        for _ in range(rows):
            self.cycle()

    def send(self, left, right, limit=None):
        """Offer one pair and keep offering it until it is taken."""
        for _ in range(limit or 8 * self.slot):
            taken = self.model.tx.hold is None
            self.cycle(in_valid=1, left=left, right=right)
            if taken:
                return
        raise ValueError('pair was never accepted')

    def frames(self, count=1):
        self.idle(4 * self.slot * count)

    # External pins: one sck period is some rows low, then some rows high. ws and sd change on
    # the first low row, and stay still on the row where sck rises.
    def period(self, ws, sd, low=1, high=1):
        self.ext = (0, ws, sd)
        self.idle(low)
        self.ext = (1, ws, sd)
        self.idle(high)

    def stream(self, slots, idle_ws, shape=None, tail=2):
        """Slots are (channel, bits). ws leads each slot by one period, as I2S requires."""
        shape = shape or (lambda n: (1, 1))
        data = [(channel, bit) for channel, bits in slots for bit in bits]
        self.period(idle_ws, 0, *shape(-2))
        self.period(idle_ws, 0, *shape(-1))
        previous = 0
        for index, (channel, bit) in enumerate(data):
            self.period(channel, previous, *shape(index))        # the bit before; ws already announces
            previous = bit
        if data:
            closing = 1 - data[-1][0]
            self.period(closing, previous, *shape(len(data)))    # last bit, with the closing change of ws
            for extra in range(tail):
                self.period(closing, 0, *shape(len(data) + 1 + extra))


def patterns(word):
    top, ones = 1 << (word - 1), (1 << word) - 1
    alt = int('a5' * (word // 8), 16)
    return [(top, 0), (0, top), (1, 0), (0, 1), (ones, 0), (0, ones), (alt, ones ^ alt), (top | 1, top >> 1)]


def ext_slot(channel, value, word, slot, length=None, extra=1):
    bits = word_bits(value, word, slot)
    if length is None:
        return channel, bits
    return channel, (bits + [extra] * length)[:length]


def counter_period(slot):
    """Period of the smallest binary counter that can count to SLOT + 1."""
    return 1 << (slot + 1).bit_length()


def boundary_vectors(word, slot):
    """Every goal and every rule on purpose."""
    p = Plan(word, slot)
    top, ones = 1 << (word - 1), (1 << word) - 1
    p.reset()
    p.idle(3)                                           # ready, nothing offered: the first frame is empty
    pairs = patterns(word)
    for left, right in pairs[:4]:
        p.send(left, right)                             # offered while the last one is still waiting
    p.frames(2)                                         # nothing offered: empty frames
    p.send(*pairs[4])
    p.idle(5)                                           # a gap that is not a whole frame
    for left, right in pairs[5:]:
        p.send(left, right)
    p.frames(3)
    p.send(0x1234 & ones, 0x0f0f & ones)
    p.idle(4 * slot + 2 * slot + 3)                     # stop part way through a frame
    p.reset(rows=1)                                     # reset in the middle of a frame
    p.send(ones, top)
    p.frames(3)

    # Slave reception from external pins with an uneven clock.
    stretched = lambda n: ((3, 1) if n % 7 == 3 else (1, 4) if n % 11 == 5 else (1, 1))
    p.reset(external=1)
    p.stream([ext_slot(1, ones, word, slot),            # starts on the right word: not delivered
              ext_slot(0, top | 1, word, slot), ext_slot(1, top >> 1, word, slot),
              ext_slot(0, 0, word, slot), ext_slot(1, ones, word, slot)], idle_ws=0, shape=stretched)
    p.reset(external=1)
    p.stream([ext_slot(0, ones, word, slot), ext_slot(1, 1, word, slot),                    # exactly SLOT
              ext_slot(0, ones, word, slot, slot - 1), ext_slot(1, top, word, slot),         # one short
              ext_slot(0, top, word, slot, slot + 1), ext_slot(1, 0, word, slot),            # one long, extra bit 1
              ext_slot(0, ones, word, slot, word - 3), ext_slot(1, ones, word, slot, 1),     # shorter than the word
              ext_slot(0, 1, word, slot), ext_slot(1, ones, word, slot, slot + 4),           # well past the slot
              ext_slot(0, top, word, slot), ext_slot(1, ones, word, slot, slot + counter_period(slot)),   # a length counter that wraps would call this good
              ext_slot(0, top, word, slot), ext_slot(1, 1, word, slot)], idle_ws=1)
    p.reset()                                           # back to the transmitter
    p.send(top, 1)
    p.send(1, top)
    p.frames(3)
    return p.rows


def random_vectors(seed, iterations, word, slot):
    rng = random.Random(seed)
    p = Plan(word, slot)
    ones = (1 << word) - 1
    p.reset()
    for _ in range(iterations):
        kind = rng.randrange(12)
        if kind == 0:
            p.reset(external=rng.randrange(2), rows=rng.randrange(1, 3))
        elif p.sel:
            slots = []
            channel = rng.randrange(2)
            for _ in range(rng.randrange(2, 7)):
                length = None if rng.randrange(10) < 7 else rng.randrange(1, slot + 4)
                slots.append(ext_slot(channel, rng.randrange(ones + 1), word, slot, length, rng.randrange(2)))
                channel ^= 1
            lows = [rng.randrange(1, 4) for _ in range(5)]
            highs = [rng.randrange(1, 4) for _ in range(7)]
            p.stream(slots, idle_ws=1 - slots[0][0] if rng.randrange(4) else slots[0][0],
                     shape=lambda n: (lows[n % 5], highs[n % 7]), tail=rng.randrange(1, 4))
        elif kind < 4:
            p.idle(rng.randrange(1, 3 * slot))
        else:
            for _ in range(rng.randrange(1, 4)):
                p.send(rng.choice((0, ones, 1 << (word - 1), rng.randrange(ones + 1))), rng.randrange(ones + 1))
    if not p.sel:
        p.frames(2)
    return p.rows


def counts(rows):
    accepted = sum(bool(r[0] and r[1] and r[8]) for r in rows)
    delivered = errors = 0
    last = (0, 0)
    for r in rows:
        now = (r[13], r[16]) if r[0] else (0, 0)
        if r[0]:
            delivered += now[0] != last[0]
            errors += now[1] != last[1]
        last = now
    return dict(accepted=accepted, delivered=delivered, errors=errors)


def make_cases(args, parameters):
    shape = (parameters['WORD'], parameters['SLOT'])
    baseline = boundary_vectors(*shape)
    cases = [dict(id='boundaries', vectors=baseline, mutation=args.demo_bug, category='functional', expected_failure=None)]
    for seed in range(args.seed, args.seed + (3 if args.profile == 'nightly' else 1)):
        cases.append(dict(id=f'random-seed{seed}', vectors=random_vectors(seed, args.iterations, *shape),
                          mutation=args.demo_bug, category='functional', expected_failure=None))
    for mutation in range(1, MUTANTS + 1):
        cases.append(dict(id=f'detect-mutation{mutation}', vectors=baseline, mutation=mutation,
                          category='mutation', expected_failure=LABELS[mutation]))
    for case in cases:
        case['counts'] = counts(case['vectors'])
    return cases


if __name__ == '__main__':
    spec = importlib.util.spec_from_file_location('local_runner', HERE.parent / 'local-common/runner.py')
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)
    sys.exit(runner.main(sys.modules[__name__]))

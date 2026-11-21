"""Reference for the OTP example: the cells as Python integers, and the rules of the specification.

The model keeps the four rows of every word and the faulty cells, and applies the documented
order of a write (three copies, read-back, lock) and its timing. It knows nothing of the state
machine. A row of the bench:

  op, addr, wdata, exp_data, exp_any, exp_status, exp_latency, aux, flags
  status = err | corrected << 1 | locked << 2.
  RESET: exp_data is the lifecycle after loading.       READ: addr.     WRITE: addr, wdata.
  CUT: a write of wdata to addr, cut by a loss of power after aux rising edges; exp_data is the
       lifecycle after the next loading.
  FAULT: addr = word, wdata = row, exp_data = bit, exp_any = 0 for stuck at 0, 1 for stuck at 1.
  KEYWRITE: wdata = the key; exp_status = the error expected.   KEYREAD: exp_data, exp_status.
  IDLE: aux = cycles.
"""
import random

RESET, READ, WRITE, CUT, FAULT, KEYWRITE, KEYREAD, IDLE = range(8)
LC_WORDS = 3
GOALS = ['read/blank', 'read/programmed', 'write/ok', 'write/refused-locked', 'write/verify-failed',
         'fault/corrected', 'fault/stuck-one', 'cut/data', 'cut/lock', 'cut/completed-later',
         'lc/test', 'lc/advanced', 'lc/cut-advance', 'lc/gap', 'key/allowed', 'key/refused',
         'busy/held-request', 'idle/ready', 'fault/lock-row']
FLAG = {goal: 1 << n for n, goal in enumerate(GOALS)}
HOLD = 1 << 31        # the bench keeps another request waiting while this one is busy


def majority(a, b, c):
    return (a & b) | (b & c) | (a & c)


class Model:
    def __init__(self, nw, wb, prog):
        self.nw, self.wb, self.prog = nw, wb, prog
        self.full = (1 << wb) - 1
        self.cells = [[0] * 4 for _ in range(nw)]
        self.stuck0 = [[0] * 4 for _ in range(nw)]
        self.stuck1 = [[0] * 4 for _ in range(nw)]
        self.key = 0
        self.lc = None
        self.cut_words = set()     # words whose last write was cut short
        self.rows = []
        self.counts = dict(steps=0, reads=0, writes=0, refused=0, cuts=0, resets=0, pulses=0)

    def row(self, op, addr=0, wdata=0, data=0, any_=0, status=0, latency=0, aux=0, flags=0):
        self.rows.append([op, addr, wdata, data, any_, status, latency, aux, flags])

    def cell(self, word, row):
        return (self.cells[word][row] & ~self.stuck0[word][row] & self.full) | self.stuck1[word][row]

    def copies(self, word):
        return [self.cell(word, r) for r in range(3)]

    def locked(self, word):
        bits = self.cell(word, 3)
        return majority(bits & 1, bits >> 1 & 1, bits >> 2 & 1) == 1

    def lifecycle(self):
        stages = [int(any(self.copies(w))) for w in range(LC_WORDS)]
        return {(0, 0, 0): 0, (1, 0, 0): 1, (1, 1, 0): 2}.get(tuple(stages), 3)

    # --- operations -------------------------------------------------------------------------
    def fault(self, word, row, bit, stuck_one):
        target = self.stuck1 if stuck_one else self.stuck0
        target[word][row] |= 1 << bit
        self.row(FAULT, word, row, bit, int(stuck_one))

    def reset(self, flags=0):
        self.lc = self.lifecycle()
        self.key = 0
        self.counts['resets'] += 1
        self.row(RESET, data=self.lc, flags=flags | self._lc_flags())

    def _lc_flags(self):
        flags = FLAG['lc/test'] if self.lc == 0 else FLAG['lc/advanced']
        stages = [int(any(self.copies(w))) for w in range(LC_WORDS)]
        if stages not in ([0, 0, 0], [1, 0, 0], [1, 1, 0], [1, 1, 1]):
            flags |= FLAG['lc/gap']
        if any(w in self.cut_words and majority(*self.copies(w)) == 0 and any(self.copies(w)) for w in range(LC_WORDS)):
            flags |= FLAG['lc/cut-advance']
        return flags

    def read(self, word, hold=False):
        c = self.copies(word)
        data, any_ = majority(*c), c[0] | c[1] | c[2]
        corrected = int(not (c[0] == c[1] == c[2]))
        status = corrected << 1 | int(self.locked(word)) << 2
        flags = FLAG['read/programmed'] if any_ else FLAG['read/blank']
        if corrected and (self.stuck0[word][0] | self.stuck0[word][1] | self.stuck0[word][2] |
                          self.stuck1[word][0] | self.stuck1[word][1] | self.stuck1[word][2]):
            flags |= FLAG['fault/stuck-one'] if any(self.stuck1[word][r] for r in range(3)) else FLAG['fault/corrected']
        self.counts['reads'] += 1
        self.row(READ, word, 0, data, any_, status, 4, 0, flags | (HOLD if hold else 0) |
                 (FLAG['busy/held-request'] if hold else 0))
        return data

    def _program(self, word, row, mask):
        self.cells[word][row] |= mask
        self.counts['pulses'] += 1

    def write(self, word, value, hold=False):
        self.counts['writes'] += 1
        flags = (HOLD | FLAG['busy/held-request']) if hold else 0
        if word in self.cut_words:
            flags |= FLAG['cut/completed-later']
        if (self.stuck0[word][3] | self.stuck1[word][3]) & 7:
            flags |= FLAG['fault/lock-row']
        if self.locked(word):
            self.counts['refused'] += 1
            self.row(WRITE, word, value, 0, 0, 1 | 1 << 2, 1, 0, flags | FLAG['write/refused-locked'])
            return False
        for r in range(3):
            self._program(word, r, value)
        c = self.copies(word)
        data, any_ = majority(*c), c[0] | c[1] | c[2]
        corrected = int(not (c[0] == c[1] == c[2]))
        if data != value:
            self.row(WRITE, word, value, data, any_, 1 | corrected << 1, 3 * self.prog + 4, 0,
                     flags | FLAG['write/verify-failed'])
            return False
        self._program(word, 3, 7)
        self.cut_words.discard(word)
        if corrected:
            flags |= FLAG['fault/corrected']
        self.row(WRITE, word, value, data, any_, corrected << 1 | 1 << 2, 4 * self.prog + 4, 0,
                 flags | FLAG['write/ok'])
        return True

    def cut(self, word, value, edges):
        """A write of value to word; the power goes after the given number of rising edges."""
        p = self.prog
        flags = 0
        if not self.locked(word):
            done = [r for r in range(3) if edges >= (r + 1) * p + 1]
            for r in done:
                self._program(word, r, value)
            if len(done) < 3:
                flags |= FLAG['cut/data']
            else:
                c = self.copies(word)
                if majority(*c) == value:
                    if edges >= 4 * p + 4:
                        self._program(word, 3, 7)
                    else:
                        flags |= FLAG['cut/lock']
            if not self.locked(word):
                self.cut_words.add(word)
        self.counts['cuts'] += 1
        self.lc = self.lifecycle()
        self.key = 0
        self.rows.append([CUT, word, value, self.lc, 0, 0, 0, edges, flags | self._lc_flags()])

    def key_write(self, value):
        error = int(self.lc != 0)
        if not error:
            self.key = value
        self.row(KEYWRITE, 0, value, 0, 0, error, 0, 0, FLAG['key/refused'] if error else FLAG['key/allowed'])

    def key_read(self):
        self.row(KEYREAD, 0, 0, self.key, 0, 0)

    def idle(self, cycles):
        self.row(IDLE, aux=cycles, flags=FLAG['idle/ready'])

    def finish(self):
        self.counts['steps'] = len(self.rows)
        return self.rows, self.counts


def boundary(nw, wb, prog):
    """The fixed scenario. The comment beside a step names the mutant that first goes wrong there."""
    m = Model(nw, wb, prog)
    p = prog
    m.reset()                                   # blank cells: TEST
    m.idle(3)                                   # ready without a request
    m.key_write(0x1234)                         # allowed in TEST
    m.key_read()
    m.read(5)                                   # a blank word
    m.write(5, 0xa5, hold=True)                 # mutants 4, 5: the order and the length of the pulses
    m.read(5)
    m.write(5, 0xff)                            # mutant 1: refused, the word is locked
    m.read(5)
    m.fault(6, 2, 1, False)                     # copy 2 of word 6 cannot hold bit 1
    m.write(6, 0x0f)                            # corrected by the majority
    m.read(6, hold=True)                        # mutant 3: the copies disagree
    m.fault(7, 0, 4, False)                     # copy 0 of word 7 cannot hold bit 4
    m.write(7, 0x30)
    m.read(7)                                   # mutant 2: copy 0 alone would give 0x20
    m.fault(4, 1, 7, True)                      # copy 1 of word 4 reads 1 at bit 7
    m.read(4)                                   # blank, but the copies disagree
    m.fault(3, 0, 2, False)
    m.fault(3, 1, 2, False)                     # two copies of one bit: beyond the guarantee
    m.write(3, 0x04)                            # the read-back differs: refused, not locked
    m.read(3)
    m.write(3, 0x08)                            # without bit 2 the majority holds
    # Losses of power.
    m.cut(4, 0x3c, p + 2)                       # mutant 6: during copy 1
    m.read(4)
    m.write(4, 0x3c)                            # the same value again completes the word
    m.read(4)
    m.cut(8, 0x77, 3 * p + 6)                   # during the pulse of the lock row
    m.read(8)
    m.write(8, 0x77)
    m.cut(9, 0xf0, 2 * p + 2)                   # two copies of 0xf0 are programmed
    m.read(9)
    m.write(9, 0x0f)                            # bits cannot be cleared: the read-back differs
    m.fault(12, 0, 7, False)
    m.fault(12, 1, 7, False)
    m.write(12, 0x80)                           # the read-back differs in the top bit alone
    # One faulty copy of the lock bit is outvoted, in both directions.
    m.fault(10, 3, 0, False)
    m.write(10, 0x11)
    m.write(10, 0x22)                           # refused: two of the three lock copies are set
    m.fault(11, 3, 0, True)
    m.write(11, 0x33)                           # taken: one lock copy reads 1, the word is not locked
    m.cut(5, 0x00, 2)                           # a locked word: nothing is programmed
    m.read(5)
    # The lifecycle.
    m.cut(0, 0x01, p + 2)                       # mutant 7: one copy of word 0 moves the stage on
    m.key_write(0x5678)                         # refused: no longer TEST
    m.key_read()
    m.write(0, 0x01)                            # completes word 0
    m.reset()
    m.write(2, 0x01)                            # word 2 without word 1: a gap
    m.reset()
    m.key_write(0x9abc)
    m.write(1, 0x01)
    m.reset()                                   # all three stages
    m.read(1)
    m.idle(2)
    return m.finish()


def random_rows(nw, wb, prog, seed, operations):
    rng = random.Random(seed)
    m = Model(nw, wb, prog)
    for _ in range(rng.randrange(4)):
        m.fault(rng.randrange(LC_WORDS, nw), rng.randrange(4), rng.randrange(wb), rng.random() < 0.3)
    m.reset()
    full = (1 << wb) - 1
    while len(m.rows) < operations:
        roll = rng.random()
        word = rng.randrange(LC_WORDS, nw) if rng.random() < 0.9 else rng.randrange(LC_WORDS)
        value = rng.choice((0, full, rng.randrange(full + 1)))
        if roll < 0.30:
            m.read(word, hold=rng.random() < 0.2)
        elif roll < 0.55:
            m.write(word, value, hold=rng.random() < 0.2)
        elif roll < 0.65:
            m.cut(word, value, rng.randrange(1, 4 * prog + 7))
        elif roll < 0.72:
            m.reset()
        elif roll < 0.80:
            m.key_write(rng.randrange(1 << 16))
        elif roll < 0.86:
            m.key_read()
        else:
            m.idle(rng.randrange(1, 4))
    return m.finish()

"""Reference for the synthesizable self-test, written from the specification as lists.

The stimulus is the list of LFSR states after the seed, the responses are the ALU of each
pattern and the signature folds that list. The cycle timeline is computed from offsets after
the start (no counters): this is the external view a logic analyzer or the full-view bench sees.
"""
POLY = 0x1021
SIG_MASK = 0xffff
RESP_W = 9


def lfsr_next(state):
    """Right shift; the new bit 15 is the XOR of bits 0, 2, 3 and 5 (x^16+x^14+x^13+x^11+1)."""
    bit = (state ^ (state >> 2) ^ (state >> 3) ^ (state >> 5)) & 1
    return (state >> 1) | (bit << 15)


def stimuli(seed, patterns):
    """The LFSR value presented for each pattern: the seed first, then one step per pattern."""
    states = [seed]
    while len(states) < patterns + 1:
        states.append(lfsr_next(states[-1]))
    return states                     # patterns + 1 values; the last stays after the run


def operands(state):
    return state & 0xff, state >> 8, (((state >> 12) & 1) << 1) | ((state >> 3) & 1)


def alu(a, b, op):
    """9-bit result {carry, value}: add, subtract (carry = no borrow), AND, XOR."""
    if op == 0:
        return a + b
    if op == 1:
        return a + (~b & 0xff) + 1
    return (a & b) if op == 2 else (a ^ b)


def response_of(state):
    return alu(*operands(state)) & ((1 << RESP_W) - 1)


def fold(signature, value):
    """One MISR step: shift left, feed back the polynomial when bit 15 leaves, add the response."""
    feedback = POLY if signature & 0x8000 else 0
    return (((signature << 1) & SIG_MASK) ^ feedback ^ value) & SIG_MASK


def signature_of(responses):
    signature = 0
    for value in responses:
        signature = fold(signature, value)
    return signature


def golden(seed, patterns):
    states = stimuli(seed, patterns)
    return signature_of([response_of(s) for s in states[:patterns]])


def cancelling_fault(first):
    """A second fault, one response later, that cancels the first in the signature.

    The difference left by `first` after one fold is fold(first, 0); injecting exactly that on
    the next response returns the difference to zero. It only fits when it is 9 bits wide.
    """
    second = fold(first, 0)
    if second >> RESP_W:
        raise ValueError('the cancelling fault does not fit in the response')
    return second


class Bench:
    """Rows of one clock each: [check, view, rst_n, start, fault, busy, done, pass, lfsr,
    response, signature]. The outputs are those seen before the edge of the row."""

    def __init__(self, seed, patterns, golden_signature):
        self.seed, self.patterns, self.golden = seed, patterns, golden_signature
        self.rows, self.view = [], 1
        self.unknown = True           # power-up: nothing is known before the first reset
        self._idle_state()

    def _idle_state(self):
        self.start_row = None         # row index of the first busy cycle of the current run
        self.faults = {}
        self.done = self.passed = 0
        self.lfsr = self.signature = 0
        self.raw = 0                  # the ALU output register

    def outputs(self, row):
        """busy, lfsr and signature from the offset into the current run."""
        if self.start_row is None:
            return 0, self.lfsr, self.signature
        k = row - self.start_row
        p = self.patterns
        states = self.states
        busy = int(k <= p)
        lfsr = states[min(k, p)]
        absorbed = [self.responses_seen[j] for j in range(min(max(k - 1, 0), p))]
        return busy, lfsr, signature_of(absorbed)

    def cycle(self, rst_n=1, start=0, fault=0):
        row = len(self.rows)
        busy, lfsr, signature = self.outputs(row)
        k = row - self.start_row if self.start_row is not None else None
        response = self.raw
        seen = response ^ fault
        if k is not None and 1 <= k <= self.patterns:
            self.responses_seen[k - 1] = seen          # this response enters the signature
        self.rows.append([0 if self.unknown else 1, self.view, rst_n, start, fault, busy, self.done,
                          self.passed, lfsr, response, signature])
        # The edge.
        if not rst_n:
            self.unknown = False
            self._idle_state()
            return
        if self.unknown:
            return
        self.raw = response_of(lfsr)
        if busy and k == self.patterns:
            self.done = 1
            final = signature_of(self.responses_seen)
            self.passed = int(final == self.golden)
            self.lfsr, self.signature = lfsr, final
            self.start_row = None
        elif not busy and start:
            self.start_row = row + 1
            self.states = stimuli(self.seed, self.patterns)
            self.responses_seen = [None] * self.patterns
            self.done = self.passed = 0
        elif not busy:
            self.lfsr, self.signature = lfsr, signature

    def run(self, faults=None, ignored_start_at=(), tail=2):
        """Start once, wait for done, then idle. faults maps a pattern index to the XOR applied
        to that pattern's response (it is shown in the row after the pattern was presented).
        ignored_start_at lists offsets into the run where start is held high while busy."""
        faults = dict(faults or {})
        self.cycle(start=1)
        for k in range(self.patterns + 1):
            fault = faults.get(k - 1, 0) if k >= 1 else 0
            self.cycle(start=int(k in ignored_start_at), fault=fault)
        for _ in range(tail):
            self.cycle()

    def reset(self, cycles=1):
        for _ in range(cycles):
            self.cycle(rst_n=0)

    def idle(self, cycles=1):
        for _ in range(cycles):
            self.cycle()

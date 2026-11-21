"""Specification of the access lock, and the analysis of its state codes under bit flips.

The lock itself is written as four named states and an integer counter. It has no codes, no
ERROR state and no faults: it is what the lock does when nothing goes wrong, and the test bench
compares against it. The second half of the file takes the code tables of the specification
and counts, for every valid word and every set of flipped bits, where the word lands.
"""
from itertools import combinations

LOCKED, CHECK, OPEN, LOCKOUT = 'LOCKED', 'CHECK', 'OPEN', 'LOCKOUT'
STATES = (LOCKED, CHECK, OPEN, LOCKOUT)
ERROR = 'ERROR'


class Lock:
    """The lock without faults. step() applies one clock edge and returns the outputs after it."""

    def __init__(self, max_tries):
        if not 1 <= max_tries <= 3:
            raise ValueError('MAX_TRIES is 1 to 3')
        self.max_tries = max_tries
        self.state, self.fails = LOCKED, 0

    def step(self, rst_n=1, start=0, key_ok=0, relock=0):
        if not rst_n:
            self.state, self.fails = LOCKED, 0
        elif self.state == LOCKED:
            if start:
                self.state = CHECK
        elif self.state == CHECK:
            if key_ok:
                self.state, self.fails = OPEN, 0
            else:
                self.fails += 1
                self.state = LOCKOUT if self.fails >= self.max_tries else LOCKED
        elif self.state == OPEN:
            if relock:
                self.state = LOCKED
        return self.outputs()

    def outputs(self):
        """grant, busy, lockout, alarm, fails. Without faults alarm is always 0."""
        return [int(self.state == OPEN), int(self.state == CHECK), int(self.state == LOCKOUT), 0, self.fails]


# Code tables of the specification. The binary table is the same lock with the plain codes
# that a tool would choose by default; it is here only to be compared with.
CODES = {
    'hardened': {LOCKED: 0b001011, CHECK: 0b010101, OPEN: 0b111000, LOCKOUT: 0b100110, ERROR: 0b011110},
    'binary': {LOCKED: 0b000, CHECK: 0b001, OPEN: 0b010, LOCKOUT: 0b011, ERROR: 0b100},
}
WIDTH = {'hardened': 6, 'binary': 3}


def distance(a, b):
    return bin(a ^ b).count('1')


def minimum_distance(table):
    return min(distance(a, b) for a, b in combinations(table.values(), 2))


def landing(encoding, state, mask):
    """Where a word lands when the bits of mask flip: 'invalid' (ERROR at the next edge),
    'error' (the ERROR word itself), 'privileged' (the OPEN word) or 'silent' (another
    working state, which nothing notices)."""
    table = CODES[encoding]
    word = table[state] ^ mask
    if word == table[state]:
        raise ValueError('empty flip')
    for name, code in table.items():
        if word == code:
            return 'error' if name == ERROR else 'privileged' if name == OPEN else 'silent'
    return 'invalid'


def flip_table(encoding, bits):
    """For each state, how its words land over every flip of exactly `bits` bits."""
    width = WIDTH[encoding]
    result = {}
    for state in CODES[encoding]:
        counts = dict(invalid=0, error=0, privileged=0, silent=0)
        for positions in combinations(range(width), bits):
            counts[landing(encoding, state, sum(1 << p for p in positions))] += 1
        result[state] = counts
    return result


def counter_flips(copy, bits):
    """Flips of the 2-bit counter and, if kept, its 2-bit complement copy: how many of them
    leave a pair that still agrees (the change goes unnoticed)."""
    width = 4 if copy else 2
    unnoticed = 0
    total = 0
    for positions in combinations(range(width), bits):
        total += 1
        mask = sum(1 << p for p in positions)
        count_mask, copy_mask = mask & 0b11, mask >> 2
        if not copy or count_mask == copy_mask:
            unnoticed += 1
    return dict(total=total, unnoticed=unnoticed)

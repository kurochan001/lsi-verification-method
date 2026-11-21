"""Bit-serial models. Each works on one bit at a time and keeps the stream as a list in time
order; the recurrences are written on the stream (bit n from bits n-TAP and n-N), not on a
shift-register word, so that the word-parallel RTL is checked against a different description."""

POLYNOMIALS = {'PRBS7': (7, 6), 'PRBS15': (15, 14), 'PRBS31': (31, 28), 'scrambler58': (58, 39)}


class Generator:
    """PRBS for x^N + x^TAP + 1: bit[n] = bit[n-N] ^ bit[n-TAP]. Reset leaves N ones behind."""

    def __init__(self, n, tap):
        self.n, self.tap = n, tap
        self.past = [1] * n            # time order, newest last

    def load(self, seed):
        """seed bit k-1 is the bit emitted k bits ago."""
        self.past = [(seed >> (self.n - 1 - t)) & 1 for t in range(self.n)]

    def zero(self):
        return int(not any(self.past))

    def bit(self):
        new = self.past[-self.n] ^ self.past[-self.tap]
        self.past = self.past[1:] + [new]
        return new

    def peek(self, count):
        saved = list(self.past)
        bits = [self.bit() for _ in range(count)]
        self.past = saved
        return bits


class Checker:
    """The checker of the README, one received bit at a time."""

    def __init__(self, n, tap, lock=32, loss=8, count_bits=16):
        self.n, self.tap, self.lock, self.loss = n, tap, lock, loss
        self.limit = (1 << count_bits) - 1
        self.past, self.good, self.bad, self.locked, self.count = [], 0, 0, 0, 0
        self.peak_bad = 0              # for the tests: the most error flags held against the lock

    def stuck(self):
        return int(len(self.past) == self.n and not any(self.past))

    def bit(self, received):
        flag = 0
        if len(self.past) == self.n:
            flag = received ^ self.past[-self.n] ^ self.past[-self.tap]
            if not any(self.past):                 # an all-zero history proves nothing
                self.good = self.bad = self.locked = 0
            elif flag:
                self.good = 0
                if self.locked:
                    self.count = min(self.count + 1, self.limit)
                    self.bad += 1
                    self.peak_bad = max(self.peak_bad, self.bad)
                    if self.bad == self.loss:
                        self.locked = self.bad = 0
            else:
                self.good = min(self.good + 1, self.lock)
                if self.good == self.lock:
                    self.locked, self.bad = 1, 0
        self.past = (self.past + [received])[-self.n:]
        return flag


class Scrambler:
    """s[n] = d[n] ^ s[n-TAP] ^ s[n-N]. Reset leaves N ones behind."""

    def __init__(self, n, tap):
        self.n, self.tap = n, tap
        self.sent = [1] * n

    def feedback(self):
        return self.sent[-self.n] ^ self.sent[-self.tap]

    def bit(self, data):
        out = data ^ self.feedback()
        self.sent = self.sent[1:] + [out]
        return out


class Descrambler:
    """d[n] = r[n] ^ r[n-TAP] ^ r[n-N]. Reset leaves N zeros behind."""

    def __init__(self, n, tap):
        self.n, self.tap = n, tap
        self.received = [0] * n

    def bit(self, received):
        out = received ^ self.received[-self.n] ^ self.received[-self.tap]
        self.received = self.received[1:] + [received]
        return out


def period(n, tap, limit=1 << 20):
    """Length of the cycle that the reset state is on, by counting."""
    g = Generator(n, tap)
    start, steps = list(g.past), 0
    while True:
        g.bit()
        steps += 1
        if g.past == start:
            return steps
        if steps > limit:
            raise ValueError('period above the counting limit')


def x_power_mod(exponent, n, tap):
    """x**exponent modulo x^N + x^TAP + 1 over GF(2), as an integer bit mask."""
    poly = (1 << n) | (1 << tap) | 1

    def mul(a, b):
        r = 0
        while b:
            if b & 1:
                r ^= a
            b >>= 1
            a <<= 1
            if a >> n & 1:
                a ^= poly
        return r

    result, base = 1, 2
    while exponent:
        if exponent & 1:
            result = mul(result, base)
        base = mul(base, base)
        exponent >>= 1
    return result


def maximal_length(n, tap, prime_factors):
    """True when x has order 2**N - 1 modulo the polynomial. prime_factors lists the prime
    factors of 2**N - 1; the caller is responsible for that list."""
    order = (1 << n) - 1
    return x_power_mod(order, n, tap) == 1 and all(x_power_mod(order // p, n, tap) != 1 for p in prime_factors)


def pack(bits):
    """Bit 0 of a word is its earliest bit."""
    return sum(b << i for i, b in enumerate(bits))

"""Independent model of the (7,5) rate-1/2 convolutional code, a hard-decision Viterbi
decoder with a decision memory and a traceback, the binary symmetric channel and the
statistics used to judge an error rate. Standard library only.

The RTL decoder keeps survivor paths in registers (register exchange). This model keeps
only the decisions and walks them backwards, so the two share the specification
(branch metrics, tie rules, depth) but not the method."""
import math
import random

INF = 8  # start metric of the three states the encoder cannot be in after reset


def parity(value):
    return bin(value).count('1') & 1


def symbol(state, bit):
    """state = (u[n-1] << 1) | u[n-2]. Returns (c0 << 1) | c1 for generators 7 and 5 (octal)."""
    previous, older = state >> 1, state & 1
    return ((bit ^ previous ^ older) << 1) | (bit ^ older)


def encode(bits, wrong_generator=False):
    state, out = 0, []
    for bit in bits:
        previous, older = state >> 1, state & 1
        c1 = bit ^ previous if wrong_generator else bit ^ older
        out.append(((bit ^ previous ^ older) << 1) | c1)
        state = (bit << 1) | previous
    return out


class Viterbi:
    """One symbol per step. After step n (counted from 0) the bit of step n - depth + 1 is known.

    upper_wins: on equal metrics choose the predecessor with u[n-2] = 1 (the RTL mutant 5).
    decide: decision depth actually used; the output is then delayed to the nominal depth
            (the RTL mutant 6). decide = depth is the specified decoder.
    highest_best: among equally good states start the traceback from the highest index
            (not an RTL mutant; used to find a frame on which the rule matters)."""

    def __init__(self, depth, upper_wins=False, decide=None, highest_best=False):
        if not 2 <= depth <= 64:
            raise ValueError('depth out of range')
        self.depth, self.upper_wins, self.highest_best = depth, upper_wins, highest_best
        self.decide = depth if decide is None else decide
        if not 1 <= self.decide <= depth:
            raise ValueError('decision depth out of range')
        self.reset()

    def reset(self):
        self.metric = [0, INF, INF, INF]
        self.history = []          # per step: the predecessor chosen for each state
        self.steps = 0
        self.late = [None] * (self.depth - self.decide)
        self.spread = INF

    def step(self, received):
        """Returns the decoded bit, or None while the first depth - 1 symbols are taken."""
        metric, chosen = [0] * 4, [0] * 4
        for state in range(4):
            bit, previous = state >> 1, state & 1
            lower, upper = previous << 1, (previous << 1) | 1
            m0 = self.metric[lower] + bin(received ^ symbol(lower, bit)).count('1')
            m1 = self.metric[upper] + bin(received ^ symbol(upper, bit)).count('1')
            take_upper = m1 <= m0 if self.upper_wins else m1 < m0
            metric[state], chosen[state] = (m1, upper) if take_upper else (m0, lower)
        low = min(metric)
        self.metric = [m - low for m in metric]
        self.spread = max(self.spread, max(self.metric))
        self.history.append(chosen)
        if len(self.history) > self.decide:
            self.history.pop(0)
        self.steps += 1
        bit = None
        if self.steps >= self.decide:
            state = self.metric.index(0)             # the best state; the lowest index on a tie
            if self.highest_best:
                state = 3 - self.metric[::-1].index(0)
            for chosen in reversed(self.history[1:]):
                state = chosen[state]
            bit = state >> 1                         # the input bit of the oldest step kept
        if self.late:
            self.late.append(bit)
            bit = self.late.pop(0)
        return bit


def decode(symbols, depth, **options):
    decoder = Viterbi(depth, **options)
    return [bit for bit in (decoder.step(s) for s in symbols) if bit is not None]


def flush_length(depth):
    return depth - 1


def frame_symbols(data, depth):
    """A terminated frame: the data, two zero tail bits and the zeros that push the last bits out."""
    return encode(list(data) + [0] * (2 + flush_length(depth)))


def channel(rng, count, probability):
    """Error patterns of a binary symmetric channel, one 2-bit pattern per symbol."""
    return [(int(rng.random() < probability) << 1) | int(rng.random() < probability) for _ in range(count)]


def run_frame(data, noise, depth, **options):
    """Decoded data of one frame. noise covers data and tail; the flush symbols arrive clean."""
    clean = frame_symbols(data, depth)
    received = [s ^ (noise[i] if i < len(noise) else 0) for i, s in enumerate(clean)]
    return decode(received, depth, **options)[:len(data)]


def measure(seed, frames, length, probability, depth, **options):
    """Bit errors per frame for independent frames of random data on the channel."""
    rng = random.Random(f'fec-ber/{seed}/{probability}/{length}')
    result = []
    for _ in range(frames):
        data = [rng.getrandbits(1) for _ in range(length)]
        noise = channel(rng, length + 2, probability)
        decoded = run_frame(data, noise, depth, **options)
        result.append(sum(a != b for a, b in zip(data, decoded)))
    return result


# ---- statistics -------------------------------------------------------------------------

def binomial_pmf(n, p):
    """All n + 1 probabilities, by the recurrence, in floating point (n is a few hundred)."""
    if not 0 < p < 1:
        raise ValueError('probability must be strictly between 0 and 1')
    pmf = [0.0] * (n + 1)
    pmf[0] = (1 - p) ** n
    for k in range(n):
        pmf[k + 1] = pmf[k] * (n - k) / (k + 1) * p / (1 - p)
    return pmf


def binomial_interval(n, p, alpha):
    """The central acceptance region [lo, hi] of Binomial(n, p): each tail outside holds at most alpha / 2."""
    pmf = binomial_pmf(n, p)
    lo, tail = 0, 0.0
    while tail + pmf[lo] <= alpha / 2:
        tail += pmf[lo]
        lo += 1
    hi, tail = n, 0.0
    while tail + pmf[hi] <= alpha / 2:
        tail += pmf[hi]
        hi -= 1
    return lo, hi


def normal_quantile(probability):
    """Inverse of the standard normal distribution function, by bisection on erf."""
    low, high = -10.0, 10.0
    for _ in range(80):
        middle = (low + high) / 2
        if 0.5 * (1 + math.erf(middle / math.sqrt(2))) < probability:
            low = middle
        else:
            high = middle
    return (low + high) / 2


def moments(histogram):
    """Mean, variance and skewness of a per-frame count from its histogram."""
    total = sum(histogram)
    mean = sum(k * c for k, c in enumerate(histogram)) / total
    variance = sum((k - mean) ** 2 * c for k, c in enumerate(histogram)) / total
    third = sum((k - mean) ** 3 * c for k, c in enumerate(histogram)) / total
    return mean, variance, third / variance ** 1.5


def sum_interval(n, mean, variance, skewness, alpha):
    """Acceptance region of a sum of n independent frame counts.

    Bit errors of a Viterbi decoder come in bursts, so the bits are not independent trials.
    The frames are: each has its own data, its own noise and a reset before it. The sum of
    the per-frame counts is close to normal, but a burst makes the count of one frame skewed,
    and the skewness of the sum, skewness / sqrt(n), still moves the 0.05 % points. The
    quantiles are corrected to first order for it (Cornish-Fisher): z + (z*z - 1) * g / 6."""
    z = normal_quantile(1 - alpha / 2)
    g = skewness / math.sqrt(n)
    deviation = math.sqrt(n * variance)
    low = n * mean + (-z + (z * z - 1) * g / 6) * deviation
    high = n * mean + (z + (z * z - 1) * g / 6) * deviation
    return max(0, math.floor(low)), math.ceil(high)


def pairwise_error(distance, probability):
    """Probability that a path at this Hamming distance beats the sent one on the channel."""
    p, q, total = probability, 1 - probability, 0.0
    for k in range(distance // 2 + 1, distance + 1):
        total += math.comb(distance, k) * p ** k * q ** (distance - k)
    if distance % 2 == 0:
        total += 0.5 * math.comb(distance, distance // 2) * (p * q) ** (distance // 2)
    return total


def union_bound(probability, terms=40):
    """Upper bound on the bit error rate of the (7,5) code with unlimited depth.

    From the transfer function D^5 N / (1 - 2 D N): at distance d there are 2^(d-5) paths,
    each with d - 4 wrong information bits."""
    return sum((d - 4) * 2 ** (d - 5) * pairwise_error(d, probability) for d in range(5, 5 + terms))

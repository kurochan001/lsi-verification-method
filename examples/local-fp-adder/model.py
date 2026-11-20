"""Exact reference for the adder: the rational sum, rounded to the format by the definition.

Nothing here follows the steps of the RTL (no alignment, no guard bits, no normalization).
An operand is decoded to a fractions.Fraction, the sum is formed exactly, and round_to()
looks for the two neighbours of that rational number in the format.
"""
from fractions import Fraction
from functools import lru_cache

RNE, RTZ, RDN, RUP, RMM = range(5)
MODES = ('rne', 'rtz', 'rdn', 'rup', 'rmm')
NV, DZ, OF, UF, NX = 16, 8, 4, 2, 1
# Classes of stimulus, one bit each in the tag word of a vector row; the names are the goals.
TAGS = ('operand/zero', 'operand/subnormal', 'operand/infinity', 'operand/quiet-nan', 'operand/signaling-nan',
        'result/positive-zero', 'result/negative-zero', 'result/subnormal', 'result/overflow-infinity',
        'result/overflow-largest-finite', 'result/invalid-infinities',
        'round/exact', 'round/tie', 'round/away', 'round/toward', 'round/carry-into-exponent',
        'align/cancellation', 'align/far',
        'operation/add', 'operation/subtract',
        'mode/rne', 'mode/rtz', 'mode/rdn', 'mode/rup', 'mode/rmm')


class Format:
    def __init__(self, exp, frac):
        self.exp, self.frac, self.width = exp, frac, exp + frac + 1
        self.bias = (1 << (exp - 1)) - 1
        self.emin, self.emax = 1 - self.bias, self.bias
        self.ones = (1 << exp) - 1
        self.quiet_nan = self.ones << frac | 1 << (frac - 1)

    def fields(self, code):
        return code >> (self.width - 1), code >> self.frac & self.ones, code & ((1 << self.frac) - 1)

    def pack(self, sign, exponent, fraction):
        return sign << (self.width - 1) | exponent << self.frac | fraction

    def kind(self, code):
        _, exponent, fraction = self.fields(code)
        if exponent == self.ones:
            return 'inf' if not fraction else 'qnan' if fraction >> (self.frac - 1) else 'snan'
        return 'zero' if not exponent and not fraction else 'subnormal' if not exponent else 'normal'

    def value(self, code):
        """The rational value of a finite code; the sign of a zero is not in it."""
        sign, exponent, fraction = self.fields(code)
        if exponent == self.ones:
            raise ValueError('not finite')
        significand = fraction | (1 << self.frac if exponent else 0)
        magnitude = Fraction(significand) * Fraction(2) ** (max(exponent, 1) - self.bias - self.frac)
        return -magnitude if sign else magnitude

    def infinity(self, sign):
        return self.pack(sign, self.ones, 0)

    def largest(self, sign):
        return self.pack(sign, self.ones - 1, (1 << self.frac) - 1)


def floor_log2(x):
    e = x.numerator.bit_length() - x.denominator.bit_length()
    return e if Fraction(2) ** e <= x else e - 1


def quantize(magnitude, exponent, fmt, mode, sign):
    """magnitude in units of 2**(exponent - frac), rounded to an integer in the given mode."""
    scaled = magnitude / Fraction(2) ** (exponent - fmt.frac)
    low = scaled.numerator // scaled.denominator
    rest = scaled - low
    if mode == RNE:
        up = rest > Fraction(1, 2) or (rest == Fraction(1, 2) and low & 1)
    elif mode == RMM:
        up = rest >= Fraction(1, 2)
    elif mode == RTZ:
        up = False
    else:
        up = rest != 0 and (mode == RDN) == bool(sign)
    return low + bool(up), rest


def round_to(value, fmt, mode):
    """Round a nonzero rational to the format. Returns the code, the flags and what the rounding did."""
    sign, magnitude = int(value < 0), abs(value)
    unbounded = floor_log2(magnitude)
    exponent = max(unbounded, fmt.emin)
    significand, rest = quantize(magnitude, exponent, fmt, mode, sign)
    carried = significand == 2 << fmt.frac
    if carried:
        significand, exponent = significand >> 1, exponent + 1
    info = dict(exact=rest == 0, tie=rest == Fraction(1, 2), away=rest != 0 and significand != 0 and
                Fraction(significand) * Fraction(2) ** (exponent - fmt.frac) > magnitude, carried=carried)
    flags = 0 if rest == 0 else NX
    # Tininess after rounding: round as if the exponent had no lower bound, then look at the result.
    if unbounded < fmt.emin:
        free, _ = quantize(magnitude, unbounded, fmt, mode, sign)
        tiny = unbounded + (free == 2 << fmt.frac) < fmt.emin
        if tiny and rest != 0:
            flags |= UF
    if exponent > fmt.emax:
        to_infinity = mode in (RNE, RMM) or (mode == RDN and sign) or (mode == RUP and not sign)
        info.update(overflow='infinity' if to_infinity else 'largest')
        return (fmt.infinity(sign) if to_infinity else fmt.largest(sign)), OF | NX, info
    if significand >> fmt.frac:
        return fmt.pack(sign, exponent + fmt.bias, significand & ((1 << fmt.frac) - 1)), flags, info
    return fmt.pack(sign, 0, significand), flags, info


class Adder:
    """a + b or a - b for one format, with the choices the README lists."""

    def __init__(self, exp, frac):
        self.fmt = Format(exp, frac)
        self.rounded = lru_cache(maxsize=None)(lambda value, mode: round_to(value, self.fmt, mode))

    def compute(self, sub, mode, a, b):
        """The result code, the flags and the tag word of this one operation."""
        fmt = self.fmt
        if not 0 <= mode <= RMM:
            raise ValueError('rounding mode outside the contract')
        kinds = fmt.kind(a), fmt.kind(b)
        a_sign, b_sign = a >> (fmt.width - 1), (b >> (fmt.width - 1)) ^ sub
        tags = {'operation/subtract' if sub else 'operation/add', 'mode/' + MODES[mode]}
        for kind, name in (('zero', 'zero'), ('subnormal', 'subnormal'), ('inf', 'infinity'),
                           ('qnan', 'quiet-nan'), ('snan', 'signaling-nan')):
            if kind in kinds:
                tags.add('operand/' + name)
        if 'snan' in kinds or 'qnan' in kinds:
            return fmt.quiet_nan, NV if 'snan' in kinds else 0, self.word(tags)
        if kinds == ('inf', 'inf') and a_sign != b_sign:
            return fmt.quiet_nan, NV, self.word(tags | {'result/invalid-infinities'})
        if 'inf' in kinds:
            return fmt.infinity(a_sign if kinds[0] == 'inf' else b_sign), 0, self.word(tags)
        x, y = fmt.value(a), fmt.value(b)
        if sub:
            y = -y
        total = x + y
        if total == 0:
            # Equal signs only when both operands are zeros of that sign; otherwise +0, or -0 when rounding down.
            sign = a_sign if a_sign == b_sign else int(mode == RDN)
            tags |= {'round/exact', 'result/negative-zero' if sign else 'result/positive-zero'}
            return fmt.pack(sign, 0, 0), 0, self.word(tags)
        code, flags, info = self.rounded(total, mode)
        tags.add('round/exact' if info['exact'] else 'round/away' if info['away'] else 'round/toward')
        if info['tie']:
            tags.add('round/tie')
        if info['carried']:
            tags.add('round/carry-into-exponent')
        if 'overflow' in info:
            tags.add('result/overflow-' + ('infinity' if info['overflow'] == 'infinity' else 'largest-finite'))
        elif fmt.kind(code) == 'subnormal':
            tags.add('result/subnormal')
        if x != 0 and y != 0:
            high, low = max(abs(x), abs(y)), min(abs(x), abs(y))
            if floor_log2(high) - floor_log2(low) > fmt.frac + 2:
                tags.add('align/far')
            if (x < 0) != (y < 0) and floor_log2(abs(total)) <= floor_log2(high) - 2:
                tags.add('align/cancellation')
        return code, flags, self.word(tags)

    @staticmethod
    def word(tags):
        return sum(1 << TAGS.index(tag) for tag in tags)


def edges(fmt):
    """Codes at the borders of the format, positive and negative."""
    one = fmt.bias
    def normal(exponent, fraction=0):
        return fmt.pack(0, exponent, fraction)
    top = (1 << fmt.frac) - 1
    positive = {
        0, 1, 2, top, top - 1,                                   # zero and subnormals
        normal(1), normal(1, 1), normal(2),                      # smallest normals
        normal(one - 1, top), normal(one), normal(one, 1), normal(one, top), normal(one + 1),
        normal(one, 1 << (fmt.frac - 1)),                        # 1.5
        normal(one - fmt.frac - 1), normal(one - fmt.frac - 2), normal(one - fmt.frac - 1, 1),  # half an ulp of 1.0 and near it
        normal(one - fmt.frac), normal(one - fmt.frac + 1),
        normal(one + fmt.frac - 1), normal(one + fmt.frac), normal(one + fmt.frac + 1),
        normal(one + fmt.frac + 2), normal(one + fmt.frac + 3),  # exponent distances around the fraction width
        fmt.largest(0), fmt.largest(0) - 1, normal(fmt.ones - 1), normal(fmt.ones - 2, top),
        fmt.infinity(0),
    }
    codes = positive | {code | 1 << (fmt.width - 1) for code in positive}
    codes |= {fmt.quiet_nan, fmt.quiet_nan | 1, fmt.pack(1, fmt.ones, 1), fmt.pack(0, fmt.ones, (1 << (fmt.frac - 1)) - 1)}
    return sorted(codes)

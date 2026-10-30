"""Exact rational oracle; no host floating-point arithmetic or RTL helper calls."""
from fractions import Fraction

QNAN = 0x7FC00000
INF = 0x7F800000
FP4 = tuple(Fraction(x, 2) for x in (0, 1, 2, 3, 4, 6, 8, 12))


def power2(exponent):
    return Fraction(2 ** exponent) if exponent >= 0 else Fraction(1, 2 ** -exponent)


def nearest_even(value):
    whole, remainder = divmod(value.numerator, value.denominator)
    return whole + (2 * remainder > value.denominator or
                    (2 * remainder == value.denominator and whole % 2 == 1))


def fp32(value, negative_zero=False, gradual=False):
    """Round each accumulation to 24 significant bits, then apply the range policy."""
    sign = int(value < 0 or (value == 0 and negative_zero)) << 31
    value = abs(value)
    if not value:
        return sign
    exponent = value.numerator.bit_length() - value.denominator.bit_length()
    if value < power2(exponent):
        exponent -= 1
    if exponent < -126 and gradual:
        return sign | nearest_even(value / power2(-149))
    significand = nearest_even(value / power2(exponent - 23))
    if significand == 2 ** 24:
        significand //= 2
        exponent += 1
    if exponent > 127:
        return sign | INF
    if exponent < -126:
        return sign
    return sign | ((exponent + 127) << 23) | (significand - 2 ** 23)


def finite32(bits, gradual=False):
    exponent = (bits >> 23) & 255
    if exponent == 255:
        raise ValueError('non-finite binary32')
    if not exponent:  # DAZ by default; gradual mode retains subnormal acc values.
        value = Fraction(bits & 0x7FFFFF) * power2(-149) if gradual else Fraction(0)
        return -value if bits >> 31 else value
    value = Fraction((bits & 0x7FFFFF) | 0x800000) * power2(exponent - 150)
    return -value if bits >> 31 else value


def element(code):
    value = FP4[code & 7]
    return -value if code & 8 else value


def encode(values, scale34=False):
    """32 binary32 bit patterns -> one logical 136-bit MXFP4 block."""
    if any(((x >> 23) & 255) == 255 for x in values):
        return 255 << 128
    exponent = max(((x >> 23) & 255 for x in values), default=0)
    scale = max(0, exponent - 2)
    if not exponent:
        return 0  # The source specifies a canonical all-zero block, including -0.
    payload = 0
    for i, bits in enumerate(values):
        value = abs(finite32(bits)) / power2(scale - 127)
        if scale34:
            value *= Fraction(3, 4)
        # Ties choose the encoding with even significand LSB.
        code = min(range(8), key=lambda j: (abs(value - FP4[j]), j % 2))
        payload |= (code | ((bits >> 31) << 3)) << (4 * i)
    return (scale << 128) | payload


def accumulate(accumulator, a, b, first=False, gradual=False):
    """Keep the block term's extended exponent through the addition (no pre-FTZ)."""
    sa, sb = a >> 128, b >> 128
    if sa == 255 or sb == 255:
        return QNAN
    if first:
        accumulator = 0
    if (accumulator & 0x7FFFFFFF) > INF:
        return QNAN
    if (accumulator & 0x7FFFFFFF) == INF:
        return accumulator
    term = sum((element(x) * element(y) for x, y in
                zip(unpack(a, 32, 4), unpack(b, 32, 4))), Fraction()) * power2(sa + sb - 254)
    return fp32(finite32(accumulator, gradual) + term, gradual=gradual)


def pack(values, width):
    return sum(value << (i * width) for i, value in enumerate(values))


def unpack(value, count, width):
    return [(value >> (i * width)) & ((1 << width) - 1) for i in range(count)]

"""Appendix B oracle: exact rational products, explicitly placed binary32 rounds."""
from fractions import Fraction
from functools import lru_cache
import reference as R

FP16, FP8, FP4 = 0, 1, 2
NAN = 'nan'
PINF, NINF = '+inf', '-inf'


@lru_cache(maxsize=None)
def decode(code, mode):
    if mode == FP4:
        return R.element(code)
    mantissa_bits, exponent_bits, bias = (10, 5, 15) if mode == FP16 else (3, 4, 7)
    sign = code >> (mantissa_bits + exponent_bits)
    exponent = (code >> mantissa_bits) & ((1 << exponent_bits)-1)
    mantissa = code & ((1 << mantissa_bits)-1)
    if mode == FP16 and exponent == 31:
        return NAN if mantissa else (NINF if sign else PINF)
    if mode == FP8 and exponent == 15 and mantissa == 7:
        return NAN
    magnitude = Fraction(mantissa, 1 << mantissa_bits) if not exponent else Fraction((1 << mantissa_bits)+mantissa, 1 << mantissa_bits)
    magnitude *= R.power2((exponent or 1)-bias)
    return -magnitude if sign else magnitude


def add32(a, b):
    aa, bb = a & 0x7FFFFFFF, b & 0x7FFFFFFF
    if aa > R.INF or bb > R.INF or (aa == bb == R.INF and (a ^ b) >> 31):
        return R.QNAN
    if aa == R.INF:
        return a
    if bb == R.INF:
        return b
    return R.fp32(R.finite32(a)+R.finite32(b), bool((a & b) >> 31))


def product16(a, b):
    x, y = decode(a, FP16), decode(b, FP16)
    if x == NAN or y == NAN:
        return R.QNAN
    if isinstance(x, str) or isinstance(y, str):
        if x == 0 or y == 0:
            return R.QNAN
        return R.INF | (((a ^ b) >> 15) << 31)
    return R.fp32(x*y, bool((a ^ b) >> 15))


def dot16(a, b):
    values = [product16(x, y) for x, y in zip(a, b)]
    while len(values) > 1:
        values = [add32(values[i], values[i+1]) for i in range(0, len(values), 2)]
    return values[0]


def dot8(a, b, sa, sb):
    values = [(decode(x, FP8), decode(y, FP8)) for x, y in zip(a, b)]
    if sa == 255 or sb == 255 or any(x == NAN or y == NAN for x, y in values):
        return R.QNAN
    return R.fp32(sum((x*y for x, y in values), Fraction()) * R.power2(sa+sb-254))


def coefficient8(a, b):
    """Independent s42 check, derived from numerical values rather than RTL shifts."""
    values = [(decode(x, FP8), decode(y, FP8)) for x, y in zip(a, b)]
    if any(x == NAN or y == NAN for x, y in values):
        return None
    exact = sum((x*y for x, y in values), Fraction()) * (1 << 18)
    assert exact.denominator == 1
    return int(exact) & ((1 << 42)-1)


def cast16(bits):
    exponent = (bits >> 23) & 255
    sign = bits >> 31
    if exponent == 255:
        return 0x7E00 if bits & 0x7FFFFF else (sign << 15) | 0x7C00
    value = abs(R.finite32(bits, gradual=True))
    if not value:
        return sign << 15
    e = value.numerator.bit_length()-value.denominator.bit_length()
    if value < R.power2(e):
        e -= 1
    if e < -14:
        return (sign << 15) | R.nearest_even(value / R.power2(-24))
    sig = R.nearest_even(value / R.power2(e-10))
    if sig == 2048:
        e += 1
        sig //= 2
    if e > 15:
        return (sign << 15) | 0x7C00
    return (sign << 15) | ((e+15) << 10) | (sig-1024)


FP8_POSITIVE = tuple(decode(code, FP8) for code in range(127))


def encode8(values):
    if any(((x >> 23) & 255) == 255 for x in values):
        return [255 << 128]*2
    maximum = max((x >> 23) & 255 for x in values)
    if maximum == 0:
        return [0, 0]
    scale = max(0, maximum-8)
    codes = []
    for bits in values:
        magnitude = abs(R.finite32(bits)) / R.power2(scale-127)
        # The exact value grid is deliberately different from the RTL exponent/GRS path.
        code = min(range(127), key=lambda i: (abs(magnitude-FP8_POSITIVE[i]), i % 2))
        codes.append(code | ((bits >> 31) << 7))
    return [(scale << 128) | R.pack(codes[i:i+16], 8) for i in (0, 16)]


def encode(values, mode):
    if mode == FP4:
        return [R.encode(values)]
    if mode == FP8:
        return encode8(values)
    codes = [cast16(value) for value in values]
    return [R.pack(codes[i:i+8], 16) for i in range(0, 32, 8)]


def half_to_fp32(code):
    value = decode(code, FP16)
    if value == NAN:
        return R.QNAN
    if isinstance(value, str):
        return R.INF | ((code >> 15) << 31)
    return R.fp32(value, bool(code >> 15))

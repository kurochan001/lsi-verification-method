"""Reference model of the rational resize, in exact rational arithmetic (fractions.Fraction).

The model computes each source coordinate directly from the specification, (x + 1/2) * in / out,
and never uses the accumulators of the design. A second function applies a fixed-point phase
step, as many scalers do, to show where a rounded step drifts away from the exact positions.
"""
from fractions import Fraction
from math import floor, gcd


def source_index(x, size_in, size_out):
    """Centre-aligned nearest neighbour: the source pixel whose span holds the output centre."""
    return floor(Fraction(2 * x + 1, 2) * Fraction(size_in, size_out))


def resize(pixels, size_in_w, size_in_h, size_out_w, size_out_h):
    """pixels: rows of the source frame. Returns the output rows."""
    if len(pixels) != size_in_h or any(len(row) != size_in_w for row in pixels):
        raise ValueError('frame does not have the stated size')
    return [[pixels[source_index(y, size_in_h, size_out_h)][source_index(x, size_in_w, size_out_w)]
             for x in range(size_out_w)] for y in range(size_out_h)]


def tie(x, size_in, size_out):
    """True when the output centre falls exactly on a source pixel boundary."""
    return (Fraction(2 * x + 1, 2) * Fraction(size_in, size_out)).denominator == 1


def period(size_in, size_out):
    """Outputs after which the phase is back where it started: out / gcd(in, out)."""
    return size_out // gcd(size_in, size_out)


def fixed_point_index(x, size_in, size_out, frac_bits):
    """The same mapping with a phase step rounded to frac_bits fractional bits and accumulated."""
    step = round(Fraction(size_in, size_out) * (1 << frac_bits))
    phase = step // 2 + x * step                  # centre of the first pixel, then one step per output
    return phase >> frac_bits


def first_drift(size_in, size_out, frac_bits, limit):
    """First output index below limit where the fixed-point mapping differs, or None."""
    for x in range(limit):
        if fixed_point_index(x, size_in, size_out, frac_bits) != source_index(x, size_in, size_out):
            return x
    return None

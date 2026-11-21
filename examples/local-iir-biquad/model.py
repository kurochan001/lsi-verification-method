"""Bit-exact integer model of the biquad, and the real-valued references used to judge it.

Two kinds of expected value live here and are kept apart:
  * step()/Biquad: Python integers only. The RTL must match it bit for bit.
  * design()/response()/bounds: floating point. Used only for tolerance checks,
    each with a bound that is derived below rather than tuned.
"""
import cmath
import math

DATA_W = 24
COEF_W = 16
MAX = (1 << (DATA_W - 1)) - 1
MIN = -(1 << (DATA_W - 1))
FLOOR, NEAREST, TOWARD_ZERO = 0, 1, 2
ROUND_NAMES = {FLOOR: 'floor', NEAREST: 'nearest', TOWARD_ZERO: 'toward-zero'}


def wrap(value, width=DATA_W):
    value &= (1 << width) - 1
    return value - (1 << width) if value >> (width - 1) else value


def quantize(acc, frac, rounding):
    """Drop frac fractional bits of an exact integer accumulator."""
    if rounding == FLOOR:
        return acc >> frac                      # Python's >> is an arithmetic shift: floor
    if rounding == NEAREST:
        return (acc + (1 << (frac - 1))) >> frac  # ties toward +infinity
    if rounding == TOWARD_ZERO:
        return -((-acc) >> frac) if acc < 0 else acc >> frac
    raise ValueError('unknown rounding mode')


def limit(value, saturate):
    """Returns (stored value, positive overflow, negative overflow)."""
    high, low = value > MAX, value < MIN
    if saturate:
        return (MAX if high else MIN if low else value), int(high), int(low)
    return wrap(value), int(high), int(low)


class Biquad:
    """Direct form I. coefficients are signed integers with frac fractional bits: b0 b1 b2 a1 a2."""

    def __init__(self, frac, rounding, saturate):
        self.frac, self.rounding, self.saturate = frac, rounding, saturate
        self.coefficients = [0, 0, 0, 0, 0]
        self.clear()

    def clear(self):
        self.x1 = self.x2 = self.y1 = self.y2 = 0

    def accumulate(self, x):
        b0, b1, b2, a1, a2 = self.coefficients
        return b0 * x + b1 * self.x1 + b2 * self.x2 - a1 * self.y1 - a2 * self.y2

    def step(self, x):
        y, high, low = limit(quantize(self.accumulate(x), self.frac, self.rounding), self.saturate)
        self.x2, self.x1, self.y2, self.y1 = self.x1, x, self.y1, y
        return y, high, low


def run(coefficients, samples, frac, rounding, saturate):
    filt = Biquad(frac, rounding, saturate)
    filt.coefficients = list(coefficients)
    return [filt.step(x) for x in samples]


# ---- real-valued references ------------------------------------------------------------------

def design_lowpass(cutoff, q):
    """Second-order low-pass by the bilinear transform. cutoff is a fraction of the sample rate.
    Returns real b0 b1 b2 a1 a2 with a0 normalized to 1. DC gain is exactly 1."""
    k = math.tan(math.pi * cutoff)
    norm = 1 / (1 + k / q + k * k)
    b0 = k * k * norm
    return [b0, 2 * b0, b0, 2 * (k * k - 1) * norm, (1 - k / q + k * k) * norm]


def to_fixed(real, frac):
    """Round each coefficient to the nearest multiple of 2**-frac; error at most 2**-(frac+1)."""
    fixed = [math.floor(value * (1 << frac) + 0.5) for value in real]
    if any(not -(1 << (COEF_W - 1)) <= value < (1 << (COEF_W - 1)) for value in fixed):
        raise ValueError('coefficient does not fit the coefficient word')
    return fixed


def to_real(fixed, frac):
    return [value / (1 << frac) for value in fixed]


def response(real, omega):
    b0, b1, b2, a1, a2 = real
    z1 = cmath.exp(-1j * omega)
    return (b0 + b1 * z1 + b2 * z1 * z1) / (1 + a1 * z1 + a2 * z1 * z1)


def denominator(real, omega):
    z1 = cmath.exp(-1j * omega)
    return 1 + real[3] * z1 + real[4] * z1 * z1


def grid(points):
    """points frequencies from DC to just below Nyquist."""
    return [math.pi * k / points for k in range(points)]


def dft(samples, omega):
    """Plain discrete-time Fourier transform of a finite sequence at one frequency."""
    return sum(value * cmath.exp(-1j * omega * n) for n, value in enumerate(samples))


def recursive_impulse(real, length):
    """Impulse response of 1/A(z): how one unit of rounding error travels to later outputs."""
    out, y1, y2 = [], 0.0, 0.0
    for n in range(length):
        y = (1.0 if n == 0 else 0.0) - real[3] * y1 - real[4] * y2
        out.append(y)
        y1, y2 = y, y1
    return out


def pole_radius(real):
    a1, a2 = real[3], real[4]
    disc = a1 * a1 - 4 * a2
    if disc < 0:
        return math.sqrt(a2)
    return max(abs((-a1 + math.sqrt(disc)) / 2), abs((-a1 - math.sqrt(disc)) / 2))


def rounding_step(rounding):
    """Largest magnitude of the error one rounding adds, in output LSBs."""
    return 0.5 if rounding == NEAREST else 1.0


def measurement_bound(fixed, frac, rounding, amplitude, length):
    """Upper bound on |DFT(measured)/amplitude - H_q| for an impulse of the given amplitude.

    measured[n] = amplitude*h_q[n] + d[n], where d is the rounding error e (|e| <= step) filtered
    by 1/A_q(z):  |d[n]| <= step * G,  G = sum_{k<length} |g[k]|.
    Summing length terms:  |DFT(d)| <= length * step * G.
    The response is cut after length samples: |sum_{n>=length} h_q[n] e^{-jwn}| <= tail, where
    tail sums |h_q[n]| over the next 7*length samples of the real recursion (added, not assumed zero).
    """
    real = to_real(fixed, frac)
    g = recursive_impulse(real, length)
    gain = sum(abs(v) for v in g)
    h = real_impulse(real, 8 * length)
    tail = sum(abs(v) for v in h[length:])
    return dict(noise_gain=gain, rounding=length * rounding_step(rounding) * gain / amplitude, tail=tail,
                total=length * rounding_step(rounding) * gain / amplitude + tail)


def real_impulse(real, length):
    b0, b1, b2, a1, a2 = real
    out, x1, x2, y1, y2 = [], 0.0, 0.0, 0.0, 0.0
    for n in range(length):
        x = 1.0 if n == 0 else 0.0
        y = b0 * x + b1 * x1 + b2 * x2 - a1 * y1 - a2 * y2
        out.append(y)
        x2, x1, y2, y1 = x1, x, y1, y
    return out


def coefficient_bound(design, fixed, frac, omega):
    """|H_q - H| <= delta * (3 + 2|H|) / |A_q|, delta = 2**-(frac+1).

    From H_q - H = (dB - H*dA) / A_q, where dB has three terms and dA two (a0 is exactly 1),
    each at most delta in magnitude. It is an identity plus the triangle inequality: no
    first-order approximation.
    """
    delta = 2.0 ** -(frac + 1)
    return delta * (3 + 2 * abs(response(design, omega))) / abs(denominator(to_real(fixed, frac), omega))

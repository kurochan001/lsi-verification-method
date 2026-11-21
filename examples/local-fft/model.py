"""Integer model of the sequential radix-2 FFT, its real-valued reference and the error bounds.

Four separate things live here, and the regression keeps them apart:
  fft()            the same integer arithmetic as the RTL, but written as a recursion over even and
                   odd samples (the RTL reorders the input by bit reversal and works in place).
                   The outputs must match bit for bit.
  reference()      the discrete Fourier transform from cmath, rounded to integers.
  tolerance()      an upper bound on |fft - reference| per component, derived from the algorithm.
  energy_window()  Parseval's relation: a window for the sum of |X[k]|**2 that depends only on the
                   input samples and the bound, not on the integer model.
"""
import cmath
import math

FRACTION = 14            # twiddle factors are signed Q1.14
TABLE_LOG = 6            # the table covers half a turn in 32 steps: transforms up to 64 points
HALF_TURN = 1 << (TABLE_LOG - 1)
COS = [round(math.cos(2 * math.pi * k / (1 << TABLE_LOG)) * (1 << FRACTION)) for k in range(HALF_TURN)]
SIN = [round(math.sin(2 * math.pi * k / (1 << TABLE_LOG)) * (1 << FRACTION)) for k in range(HALF_TURN)]
ROUND = 1 << (FRACTION - 1)
# Largest distance between a quantized twiddle factor and the exact one (each component is off by at most half a unit).
TWIDDLE_ERROR = math.sqrt(0.5) / (1 << FRACTION)
ROUNDING = math.sqrt(0.5)   # a rounding of at most 1/2 in both components, as a complex distance


def bit_reverse(value, bits):
    return int(format(value, f'0{bits}b')[::-1], 2)


def limits(width):
    return -(1 << (width - 1)), (1 << (width - 1)) - 1


def fft(samples, logn, width, scale, rounding=ROUND):
    """Return ([(re, im)] in natural order, overflow) exactly as the RTL computes them.

    rounding is the constant added before the product is shifted. Only the search for a frame
    whose product lies exactly between two integers uses another value."""
    low, high = limits(width)
    if len(samples) != 1 << logn or not 1 <= logn <= TABLE_LOG:
        raise ValueError('frame length does not match the transform')
    if any(not (low <= v <= high) for sample in samples for v in sample):
        raise ValueError('sample out of range')
    overflow = False

    def finish(value):
        nonlocal overflow
        if scale:
            value = (value + 1) >> 1          # halve, rounding half up
        if value > high or value < low:
            overflow = True
            return high if value > high else low
        return value

    def transform(points):
        size = len(points)
        if size == 1:
            return points
        even, odd = transform(points[0::2]), transform(points[1::2])
        out = [None] * size
        for k in range(size // 2):
            c, s = COS[k * (1 << TABLE_LOG) // size], SIN[k * (1 << TABLE_LOG) // size]
            (ar, ai), (br, bi) = even[k], odd[k]
            tr = (c * br + s * bi + rounding) >> FRACTION    # b times (cos - j sin), rounded half up
            ti = (c * bi - s * br + rounding) >> FRACTION
            out[k] = (finish(ar + tr), finish(ai + ti))
            out[k + size // 2] = (finish(ar - tr), finish(ai - ti))
        return out

    return transform([tuple(sample) for sample in samples]), overflow


def exact(samples, scale):
    """The transform as complex numbers: sum x[n] exp(-2 pi j k n / N), divided by N when scaled."""
    size = len(samples)
    points = [complex(re, im) for re, im in samples]
    out = []
    for k in range(size):
        total = sum(p * cmath.exp(-2j * cmath.pi * ((k * n) % size) / size) for n, p in enumerate(points))
        out.append(total / size if scale else total)
    return out


def reference(samples, scale):
    return [(round(value.real), round(value.imag)) for value in exact(samples, scale)]


def error_bound(samples, logn, scale):
    """Upper bound on the complex distance between a value the integer transform holds after
    its last stage and the exact value, as long as nothing saturates."""
    largest = max(math.hypot(re, im) for re, im in samples)
    error = 0.0
    for stage in range(1, logn + 1):
        # The first two stages only use the factors 1 and -j. The table holds them exactly, and a
        # product with them needs no rounding.
        twiddle, product = (0.0, 0.0) if stage <= 2 else (TWIDDLE_ERROR, ROUNDING)
        if scale:
            # (a + w b) / 2: a and b carry `error`; the quantized w is off by TWIDDLE_ERROR and at most
            # 1 + TWIDDLE_ERROR long; the product and the halving each round once.
            error = (error + (1 + twiddle) * error + (largest + error) * twiddle + product) / 2 + ROUNDING
        else:
            operand = largest * (1 << (stage - 1)) + error      # values grow by at most 2 per stage
            error = error + (1 + twiddle) * error + operand * twiddle + product
    return error


def tolerance(samples, logn, scale):
    """Largest allowed |fft - reference| of one component: the bound plus the rounding of the reference."""
    return math.ceil(error_bound(samples, logn, scale) + 0.5)


def energy_window(samples, logn, scale):
    """(low, high) for sum |X[k]|**2 of the integer transform, from the input alone.

    Parseval: the exact sum is N * sum |x|**2 (unscaled) or sum |x|**2 / N (scaled). Every output is
    within e of the exact one, so the sum moves by at most 2 e sqrt(N S) + N e**2 (Cauchy-Schwarz).
    """
    size = 1 << logn
    power = sum(re * re + im * im for re, im in samples)
    total = power / size if scale else power * size
    e = error_bound(samples, logn, scale)
    slack = 2 * e * math.sqrt(size * total) + size * e * e
    return max(0, math.floor(total - slack) - 1), math.ceil(total + slack) + 1


def errors(samples, logn, width, scale):
    """Largest component distance between the integer transform and the rounded reference."""
    got, overflow = fft(samples, logn, width, scale)
    if overflow:
        raise ValueError('the frame saturates; the reference does not apply')
    return max(max(abs(g[0] - r[0]), abs(g[1] - r[1])) for g, r in zip(got, reference(samples, scale)))

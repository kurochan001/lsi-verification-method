"""Integer model of the pipelined CORDIC, its real-valued reference and the error bounds.

Three separate things live here, and the regression keeps them apart:
  cordic()     the same integer steps as the RTL. The outputs must match bit for bit.
  reference()  the mathematical result from math.sin/cos/hypot/atan2, rounded to an integer.
  tolerance()  an upper bound on |cordic - reference| derived from the algorithm, not measured.
"""
import math

KF = 17
TURN = 1 << 16          # angle units in one turn
# atan(2**-i) as a fraction of one turn, scaled by 2**32. The RTL holds the same numbers.
ATAN32 = [round(math.atan(2.0 ** -i) / (2 * math.pi) * 2 ** 32) for i in range(20)]


def gain(iterations):
    return math.prod(math.sqrt(1 + 4.0 ** -i) for i in range(iterations))


def gain_inverse(iterations):
    return round(2 ** KF / gain(iterations))


def step(i, guard):
    """Angle step of iteration i in units of 2**-(16+guard) of a turn."""
    zw = 16 + guard
    return (ATAN32[i] + (1 << (31 - zw))) >> (32 - zw)


def signed(value, bits):
    value &= (1 << bits) - 1
    return value - (1 << bits) if value >> (bits - 1) else value


def cordic(mode, x, y, z, width, iterations, guard, trace=None):
    """Return (x_out, y_out, z_out) exactly as the RTL computes them.

    trace, when given, receives the (x, y, z) held after the fold and after every iteration.
    """
    zw, iw = 16 + guard, width + guard + 3
    if not (-(1 << (width - 1)) <= x < 1 << (width - 1) and -(1 << (width - 1)) <= y < 1 << (width - 1) and 0 <= z < TURN):
        raise ValueError('operand out of range')
    xi, yi = x << guard, y << guard
    if mode:
        fold = x < 0
        zi = signed((0x8000 if fold else 0) << guard, zw)
    else:
        fold = bool(((z >> 15) ^ (z >> 14)) & 1)
        zi = signed((z ^ (0x8000 if fold else 0)) << guard, zw)
    if fold:
        xi, yi = -xi, -yi
    if trace is not None:
        trace.append((xi, yi, zi))
    for i in range(iterations):
        up = yi < 0 if mode else zi >= 0
        if up:
            xi, yi, zi = xi - (yi >> i), yi + (xi >> i), zi - step(i, guard)
        else:
            xi, yi, zi = xi + (yi >> i), yi - (xi >> i), zi + step(i, guard)
        zi = signed(zi, zw)
        if not -(1 << (iw - 1)) <= xi < 1 << (iw - 1) or not -(1 << (iw - 1)) <= yi < 1 << (iw - 1):
            raise ValueError('internal overflow')  # the RTL width would wrap here
        if trace is not None:
            trace.append((xi, yi, zi))
    k, half = gain_inverse(iterations), 1 << (KF + guard - 1)
    return ((xi * k + half) >> (KF + guard), (yi * k + half) >> (KF + guard),
            ((zi + (1 << (guard - 1))) >> guard) & (TURN - 1))


def reference(mode, x, y, z):
    """The mathematical result, rounded to the nearest integer (angle modulo one turn)."""
    if mode:
        angle = round(math.atan2(y, x) / (2 * math.pi) * TURN) % TURN if (x or y) else 0
        return round(math.hypot(x, y)), 0, angle
    a = 2 * math.pi * z / TURN
    return round(x * math.cos(a) - y * math.sin(a)), round(x * math.sin(a) + y * math.cos(a)), 0


def residual_bound(i, iterations, guard):
    """Largest |z| after i iterations of a rotation, in units of 2**-(16+guard) of a turn.

    The fold leaves |z| <= a quarter turn. An iteration moves z towards 0 by step(i), so
    |z| becomes ||z| - step(i)|, which is at most max(bound - step(i), step(i)).
    """
    del iterations
    bound = 0x4000 << guard
    for j in range(i):
        bound = max(bound - step(j, guard), step(j, guard))
    return bound


def truncation(iterations):
    """Bound, in internal units, on the length of the error vector that the arithmetic shifts
    add. Iteration j >= 1 drops less than one unit from each component (length < sqrt(2)),
    and the later iterations stretch that by the product of sqrt(1 + 4**-k), k > j."""
    return math.sqrt(2) * sum(math.prod(math.sqrt(1 + 4.0 ** -k) for k in range(j + 1, iterations))
                              for j in range(1, iterations))


def tolerance(mode, x, y, width, iterations, guard):
    """Upper bounds (x, y, angle) on |cordic - reference| in output units, as integers.

    The terms are spelled out in the README. An angle bound of TURN // 2 means that no
    bound smaller than half a turn holds (a vector too short to have a direction).
    """
    del width
    zw = 16 + guard
    radius = math.hypot(x, y)
    a = gain(iterations)
    e_shift = truncation(iterations) / (1 << guard)             # output units, before the gain correction
    k_error = (a * radius + e_shift) * 2.0 ** -(KF + 1)         # K / 2**KF is within 2**-(KF+1) of 1 / gain
    rounding = 0.5 + 0.5                                        # the output and the reference are both rounded
    unit = 2 * math.pi / (1 << zw)                              # one angle unit in radians
    table = iterations * (0.5 + 2.0 ** (zw - 33))               # every step is within half a unit of atan(2**-i)
    if not mode:
        left = residual_bound(iterations, iterations, guard)    # the angle the iterations leave, in internal units
        angle = (left + table) * unit                           # turned angle versus requested angle
        both = radius * angle + e_shift / a + k_error + rounding
        return math.ceil(both), math.ceil(both), math.ceil((left + (1 << (guard - 1))) / (1 << guard))
    # Vectoring: a wrong turn can happen only while |y| is below the shift error, which
    # widens the final angle to the true direction by at most asin(e_shift / radius).
    ratio = e_shift / radius if radius else 1.0
    directed = ratio < 1.0                                      # otherwise the shift error can hide the vector
    psi = min(math.atan(2.0 ** -(iterations - 1)) + math.asin(ratio), math.pi / 2) if directed else math.pi / 2
    magnitude = radius * (1 - math.cos(psi)) + e_shift / a + k_error + rounding
    left = radius * math.sin(psi) + e_shift / a + k_error + rounding
    angle = psi / unit + table                                  # internal angle units
    angle = math.ceil(angle / (1 << guard) + 0.5 + 0.5)         # two roundings to 16 bits
    return math.ceil(magnitude), math.ceil(left), min(angle, TURN // 2) if directed else TURN // 2


def angle_distance(a, b):
    """Distance between two 16-bit angles on the circle."""
    d = (a - b) % TURN
    return min(d, TURN - d)


def errors(mode, x, y, z, width, iterations, guard):
    """(x error, y error, angle error) of the integer model against the reference."""
    got, want = cordic(mode, x, y, z, width, iterations, guard), reference(mode, x, y, z)
    return abs(got[0] - want[0]), abs(got[1] - want[1]), angle_distance(got[2], want[2])

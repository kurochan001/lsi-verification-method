"""Directed numerical boundaries and seeded random inputs for the rational oracle."""
from fractions import Fraction
import random
from reference import accumulate, encode, fp32, pack, power2


def block(code=2, scale=127, count=1):
    return (scale << 128) | pack([code] * count + [0] * (32-count), 4)


def make_vectors(seed, iterations, gradual=False, scale34=False):
    rows = []
    def series(pairs):
        accumulator = 0
        for j, (a, b) in enumerate(pairs):
            accumulator = accumulate(accumulator, a, b, j == 0, gradual)
            rows.append([1, int(j == 0), int(j == len(pairs)-1), a, b, accumulator])
    for a in range(16):
        for b in range(16):
            series([(block(a), block(b))])
    for scale in range(256):
        series([(block(7, scale, 32), block(15 if scale % 2 else 7, 254-scale if scale < 255 else 127, 32))])
    for sa, sb in [(0, 0), (254, 254), (63, 64), (64, 64), (65, 65), (190, 190), (255, 0), (0, 255)]:
        series([(block(1, sa), block(1, sb))])
    # Ascending block order differs from a single final rounding: (2^24 + 1) - 2^24 = 0.
    series([(block(2, 139), block(2, 139)), (block(), block()), (block(10, 139), block(2, 139))])
    # A tiny term must remain available until the addition; a subnormal is not pre-flushed.
    series([(block(2, 64), block(2, 64)), (block(10, 63), block(2, 64))])
    series([(block(7, 254, 32), block(7, 254, 32)), (block(15, 254, 32), block(7, 254, 32)), (block(0, 255), block(0))])
    series([(block(7, 127, 32), block(7, 127, 32)), (block(15, 127, 32), block(7, 127, 32))])
    def encoder(values):
        rows.append([2, 0, 0, pack(values, 32), 0, encode(values, scale34)])
    for midpoint in [Fraction(1,4), Fraction(3,4), Fraction(5,4), Fraction(7,4), Fraction(5,2), Fraction(7,2), Fraction(5)]:
        for sign in [1, -1]:
            bits = fp32(sign * midpoint)
            encoder([0x40800000, bits-1, bits, bits+1] + [0]*28)
    encoder([0]*32)
    encoder([0x80000000, 1, 0x807FFFFF]*10 + [0, 0])
    for position in range(32):
        for special in [0x7FC00001, 0x7F800000, 0xFF800000]:
            values=[0x3F800000]*32;values[position]=special;encoder(values)
    for exponent in [1, 2, 3, 126, 127, 128, 253, 254]:
        encoder([(exponent << 23) | (i << 18) | ((i % 2) << 31) for i in range(32)])
    rng=random.Random(seed)
    for i in range(iterations):
        pairs=[]
        for _ in range(rng.randrange(1,9)):
            a=(rng.randrange(256) << 128) | rng.getrandbits(128)
            b=(rng.randrange(256) << 128) | rng.getrandbits(128)
            pairs.append((a,b))
        series(pairs)
        # Alternating narrow and full exponent distributions, plus arbitrary mantissas.
        encoder([rng.getrandbits(32) if i % 2 else
                 (rng.randrange(80,160) << 23) | rng.getrandbits(23) | (rng.randrange(2) << 31)
                 for _ in range(32)])
        rows.extend([[0,0,0,0,0,0]] * rng.randrange(3))
    return rows


def expected_counts(rows):
    return dict(checks=len(rows), bdp=sum(r[0]==1 and r[2] for r in rows), encoder=sum(r[0]==2 for r in rows))

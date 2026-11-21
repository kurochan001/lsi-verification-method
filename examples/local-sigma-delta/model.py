"""Independent models and SNR arithmetic for the sigma-delta example.

Nothing here is shared with the testbench or the CIC RTL:

* Modulator: the 1st- and 2nd-order loops with a 1-bit quantizer, in Python floats. The input
  is a 16-bit code divided by 2**15 and every coefficient is 1 or 2, so every value is a dyadic
  rational well inside the 53-bit mantissa. The arithmetic is exact, and the bit stream must
  equal the testbench's real-number model bit for bit.
* CIC: STAGES moving sums of RATE samples in Python integers (no integrators, no combs, no
  word length), the same construction as the CIC example uses for its own expectations.
* SNR: a direct DFT of the decimated output written with cmath (no NumPy), the textbook
  in-band noise formula, and a linear prediction that also counts the CIC response and the
  noise it folds into the output band.
"""
import cmath
import math
import random

SCALE = 1 << 15                 # input code / 2**15 is the input in [-1, 1)
CODE_MIN, CODE_MAX = -(1 << 15), (1 << 15) - 1
RATE = 32                       # oversampling ratio = decimation ratio
WINDOW = 256                    # decimated outputs in one SNR measurement
SIGNAL_BIN = 5                  # the test tone completes this many cycles in the window
NOMINAL_AMPLITUDE = 0.5
OVERLOAD_AMPLITUDE = 0.99
IDLE_DC_CODE = 683              # about 1/48 of full scale
PHASE = 0.3

# Envelope of (measured SNR - linear prediction), in dB, over envelope_conditions() below:
# 150 sine inputs per order with amplitudes 0.1 to 0.6 (order 2) or 0.7 (order 1), signal bins
# 3 to 31 and random phases. recorded_envelope() recomputes it; a selftest keeps the two equal.
ENVELOPE = {1: (-0.36, 8.54), 2: (-5.56, 0.89)}
EXTRA_MARGIN_DB = 1.0           # added on both sides of the recorded envelope
# Idle tones with the DC input IDLE_DC_CODE: the largest non-DC bin of the decimated output,
# relative to a full-scale sine. Measured -41.5 dBFS (order 1) and -77.5 dBFS (order 2).
IDLE_TONE_AT_LEAST = {1: -50.0}  # a 1st-order loop is expected to show an in-band tone
IDLE_TONE_AT_MOST = {2: -65.0}   # a 2nd-order loop is expected to keep it small
# Overload: the largest |state of the last integrator| in the measurement window, in units of
# the full-scale input. Up to amplitude 0.9 the 2nd-order state stays below 8.43.
OVERLOAD_STATE = 10.0
FIRST_ORDER_STATE_LIMIT = 2.0   # |s1| < 1 + 1 for any input with |x| < 1


class Modulator:
    """y[n] is the sign of the last integrator (+1 for zero); then the states advance.

    order 1: s1 <- s1 + x - y                      NTF = 1 - z^-1
    order 2: s1 <- s1 + x - y; s2 <- s2 + s1 - 2y  NTF = (1 - z^-1)^2
    """

    def __init__(self, order):
        self.order = order
        self.reset()

    def reset(self):
        self.s1 = 0.0
        self.s2 = 0.0

    def last(self):
        return self.s1 if self.order == 1 else self.s2

    def decide(self):
        return 1.0 if self.last() >= 0.0 else -1.0

    def advance(self, code, y):
        x = code / SCALE
        if self.order == 1:
            self.s1 = self.s1 + x - y
        else:
            s1 = self.s1
            self.s1 = s1 + x - y
            self.s2 = self.s2 + s1 - 2.0 * y


class Cic:
    """STAGES moving sums of RATE accepted samples; every RATE-th sample after a reset gives one
    output. Python integers do not overflow."""

    def __init__(self, stages):
        self.stages = stages
        self.width = output_width(stages)
        self.reset()

    def reset(self):
        self.levels = [[] for _ in range(self.stages + 1)]

    def accept(self, sample):
        self.levels[0].append(sample)
        for level in range(1, self.stages + 1):
            self.levels[level].append(sum(self.levels[level - 1][-RATE:]))
        if len(self.levels[0]) % RATE:
            return None
        value = self.levels[-1][-1]
        if not -(1 << (self.width - 1)) <= value < 1 << (self.width - 1):
            raise ValueError('output width too small for the exact sum')
        return value


def gain(stages):
    return RATE ** stages


def output_width(stages, in_width=2):
    """The width the CIC RTL gives: IN_W + clog2(RATE**STAGES)."""
    return in_width + (gain(stages) - 1).bit_length()


def modulate(codes, order):
    m = Modulator(order)
    bits = []
    for code in codes:
        y = m.decide()
        bits.append(int(y))
        m.advance(code, y)
    return bits


def decimate(bits, stages):
    c = Cic(stages)
    return [v for v in (c.accept(b) for b in bits) if v is not None]


# ---- signals ---------------------------------------------------------------------------------

def settle(stages):
    """Decimated outputs discarded before the window: the moving sums fill in STAGES outputs."""
    return stages + 2


def sine_codes(amplitude, stages, signal_bin=SIGNAL_BIN, phase=PHASE):
    """A coherent tone: signal_bin whole cycles in the window, rounded to the 16-bit code."""
    period = WINDOW * RATE
    return [max(CODE_MIN, min(CODE_MAX, round(amplitude * SCALE * math.sin(2 * math.pi * signal_bin * n / period + phase))))
            for n in range((WINDOW + settle(stages)) * RATE)]


def dc_codes(code, stages):
    return [code] * ((WINDOW + settle(stages)) * RATE)


# ---- spectra -----------------------------------------------------------------------------------

def power_spectrum(samples):
    """|DFT|^2 of bins 0 .. N/2-1, written out (no FFT library)."""
    n = len(samples)
    twiddle = [cmath.exp(-2j * math.pi * k / n) for k in range(n)]
    return [abs(sum(x * twiddle[(k * i) % n] for i, x in enumerate(samples))) ** 2 for k in range(n // 2)]


def snr_db(samples, signal_bin=SIGNAL_BIN):
    """Signal bin against every other bin except DC (so harmonics count as noise)."""
    p = power_spectrum(samples)
    noise = sum(p[1:]) - p[signal_bin]
    if noise <= 0:
        raise ValueError('no noise in the window')
    return 10 * math.log10(p[signal_bin] / noise)


def spur_dbfs(samples, stages):
    """Largest non-DC bin relative to the bin of a full-scale sine at the CIC gain."""
    p = power_spectrum(samples)
    full = (gain(stages) * len(samples) / 2) ** 2
    spur = max(p[1:])
    return -999.0 if spur <= 0 else 10 * math.log10(spur / full)


# ---- predictions -------------------------------------------------------------------------------

def theory_db(order, amplitude, osr=RATE):
    """Textbook in-band SQNR: white quantization noise of power delta^2/12 with delta = 2 (levels
    +-1), shaped by (1 - z^-1)^order and cut by an ideal low-pass at fs / (2 osr):
    N = (delta^2/12) * pi^(2 order) / ((2 order + 1) osr^(2 order + 1)), S = amplitude^2 / 2."""
    noise = (4 / 12) * math.pi ** (2 * order) / ((2 * order + 1) * osr ** (2 * order + 1))
    return 10 * math.log10(amplitude * amplitude / 2 / noise)


def cic_response(f, stages):
    """|H(f)| normalized to 1 at DC, f in cycles per input sample."""
    s = math.sin(math.pi * f)
    if abs(s) < 1e-15:
        return 1.0
    return abs(math.sin(math.pi * f * RATE) / (RATE * s)) ** stages


def linear_db(order, stages, amplitude, signal_bin=SIGNAL_BIN, steps=20000):
    """The same white-noise model, but filtered by the real CIC and decimated: every bit of
    shaped noise that the CIC passes, in band or folded from above, ends up in the output."""
    noise = 0.0
    for i in range(steps):
        f = (i + 0.5) / steps - 0.5
        noise += (4 / 12) * (2 * math.sin(math.pi * f)) ** (2 * order) * cic_response(f, stages) ** 2 / steps
    f0 = signal_bin / (WINDOW * RATE)
    return 10 * math.log10(amplitude * amplitude / 2 * cic_response(f0, stages) ** 2 / noise)


def snr_limits(order, stages, amplitude):
    low, high = ENVELOPE[order]
    centre = linear_db(order, stages, amplitude)
    return centre + low - EXTRA_MARGIN_DB, centre + high + EXTRA_MARGIN_DB


def envelope_conditions(order, count=150, seed=1):
    rng = random.Random(seed * 10 + order)
    amplitudes = [0.1, 0.2, 0.3, 0.4, 0.5, 0.6] + ([0.7] if order == 1 else [])
    return [(rng.choice(amplitudes), rng.choice([3, 5, 7, 11, 13, 17, 19, 23, 29, 31]), rng.random() * 2 * math.pi)
            for _ in range(count)]


def recorded_envelope(order):
    """Recomputes ENVELOPE[order] (rounded outward to 0.01 dB) from the model alone."""
    stages = order + 1
    gaps = []
    for amplitude, signal_bin, phase in envelope_conditions(order):
        codes = sine_codes(amplitude, stages, signal_bin, phase)
        window = decimate(modulate(codes, order), stages)[settle(stages):settle(stages) + WINDOW]
        gaps.append(snr_db(window, signal_bin) - linear_db(order, stages, amplitude, signal_bin))
    return math.floor(min(gaps) * 100) / 100, math.ceil(max(gaps) * 100) / 100

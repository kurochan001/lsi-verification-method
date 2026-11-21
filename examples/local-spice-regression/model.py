"""Decks, corners, waveform measurements and the statistics of the SPICE regression.

Nothing here calls ngspice. The decks are text, the measurements read lists of numbers, and the
analytic values and the binomial bounds come from the standard library only.
The transistor model is a made-up level-1 card for teaching. It is not a process design kit.
"""
import math
import random

# Made-up level-1 cards. The numbers were chosen to give delays of a few tens of picoseconds.
NMOS = dict(vto=0.45, kp=220e-6, lam=0.05)
PMOS = dict(vto=-0.45, kp=90e-6, lam=0.07)
SHARED = 'gamma=0.4 phi=0.7 tox=4n cgso=0.3n cgdo=0.3n cj=1m cjsw=0.2n'
PROCESS = {'ff': dict(dvt=-0.05, kp=1.15), 'tt': dict(dvt=0.0, kp=1.0), 'ss': dict(dvt=0.05, kp=0.85)}
TEMPERATURES = (-40.0, 25.0, 125.0)
SUPPLIES = (1.32, 1.2, 1.08)
CORNERS = {'fast': ('ff', -40.0, 1.32), 'typ': ('tt', 25.0, 1.2), 'slow': ('ss', 125.0, 1.08)}
LOAD = 20e-15          # inverter load
RING_LOAD = 10e-15     # per ring stage
STAGES = 5
EDGE = 50e-12          # input rise and fall time of the inverter test
SETTINGS = dict(reltol=1e-4, method='gear', step=5e-12)
STRICT = dict(reltol=1e-6, method='trap', step=1e-12)


class Mismatch(Exception):
    """A judged difference. The label says which check found it."""
    def __init__(self, label, message):
        super().__init__(message)
        self.label = label


def cards(process='tt', shift=None):
    """The two model cards of one process corner. shift adds per-trial variation."""
    p = PROCESS[process]
    shift = shift or {}
    n_vto = NMOS['vto'] + p['dvt'] + shift.get('n_vto', 0.0)
    p_vto = PMOS['vto'] - p['dvt'] - shift.get('p_vto', 0.0)
    n_kp = NMOS['kp'] * p['kp'] * shift.get('n_kp', 1.0)
    p_kp = PMOS['kp'] * p['kp'] * shift.get('p_kp', 1.0)
    return [f".model nch nmos level=1 vto={n_vto:.9g} kp={n_kp:.9g} lambda={NMOS['lam']} {SHARED}",
            f".model pch pmos level=1 vto={p_vto:.9g} kp={p_kp:.9g} lambda={PMOS['lam']} {SHARED}"]


def options(temp, settings=SETTINGS, extra=''):
    return f".options temp={temp:g} reltol={settings['reltol']:g} method={settings['method']} {extra}".rstrip()


def stage(index, a, b):
    return [f'Mp{index} {b} {a} vdd vdd pch w=2u l=0.18u ad=0.6p as=0.6p pd=2.6u ps=2.6u',
            f'Mn{index} {b} {a} 0 0 nch w=1u l=0.18u ad=0.3p as=0.3p pd=1.6u ps=1.6u']


def rc_deck(resistance, capacitance, settings=SETTINGS):
    """A 1 V step into R-C. The capacitor starts at 0 V, so v(t) = 1 - exp(-t/RC)."""
    tau = resistance * capacitance
    return dict(deck=['rc step', 'Vstep vin 0 DC 1', f'R1 vin vout {resistance:.9g}',
                      f'C1 vout 0 {capacitance:.9g} ic=0',
                      f".options reltol={settings['reltol']:g} abstol=1e-12 method={settings['method']}", '.end'],
                tran=f'tran {tau/200:.9g} {6*tau:.9g} 0 {tau/200:.9g} uic', stop=6 * tau,
                vectors=['time', 'v(vout)'])


def inverter_deck(process, temp, vdd, load=LOAD, settings=SETTINGS, shift=None, extra='', hold_input=False):
    """One inverter driven by one pulse. hold_input keeps the input low, so nothing switches."""
    source = 'Vin in 0 DC 0' if hold_input else f'Vin in 0 pulse(0 {vdd:g} 1n {EDGE:g} {EDGE:g} 2n 6n)'
    return dict(deck=['inverter delay', *cards(process, shift), options(temp, settings, extra),
                      f'Vdd vdd 0 {vdd:g}', source, *stage(0, 'in', 'out'), f'Cl out 0 {load:.9g}', '.end'],
                tran=f"tran {settings['step']:g} 5n 0 {settings['step']:g}", stop=5e-9,
                vectors=['time', 'v(in)', 'v(out)'])


def ring_deck(process, temp, vdd, load=RING_LOAD, settings=SETTINGS, weak_stage=None):
    """A five-stage ring. The supply ramps up and the nodes start at alternating levels."""
    lines = ['ring oscillator', *cards(process), options(temp, settings), f'Vdd vdd 0 pwl(0 0 100p {vdd:g})']
    for i in range(STAGES):
        lines += stage(i, f'n{i}', f'n{(i+1) % STAGES}')
        lines.append(f'C{i} n{(i+1) % STAGES} 0 {load * (4 if weak_stage == i else 1):.9g}')
    lines += ['.ic ' + ' '.join(f'v(n{i})={vdd if i % 2 else 0:g}' for i in range(STAGES)), '.end']
    return dict(deck=lines, tran=f"tran {settings['step']:g} 20n 0 {settings['step']:g} uic", stop=20e-9,
                vectors=['time', 'v(n0)'])


# ---------------------------------------------------------------- measurements from waveforms

def crossings(times, values, level, rising):
    """Times at which the waveform passes the level in one direction, by linear interpolation."""
    found = []
    for i in range(1, len(times)):
        a, b = values[i-1], values[i]
        if (a < level <= b) if rising else (a > level >= b):
            found.append(times[i-1] + (level - a) * (times[i] - times[i-1]) / (b - a))
    return found


def delay(times, source, target, level, source_rising):
    """Time from the first input crossing to the first opposite output crossing after it."""
    start = crossings(times, source, level, source_rising)
    if not start:
        raise Mismatch('SPICE_MEASURE', 'the input never crosses the level')
    after = [t for t in crossings(times, target, level, not source_rising) if t > start[0]]
    if not after:
        raise Mismatch('SPICE_MEASURE', 'the output never crosses the level')
    return after[0] - start[0]


def period(times, values, level, skip=2, count=6):
    """Mean period over several rising crossings, after the start-up cycles."""
    rise = crossings(times, values, level, True)
    if len(rise) < skip + count + 1:
        raise Mismatch('SPICE_MEASURE', f'only {len(rise)} rising crossings')
    return (rise[skip + count] - rise[skip]) / count


def swing_ratio(times, source, target):
    """Output swing over input swing. Undefined when the input does not move: NaN, never a guess."""
    span = max(source) - min(source)
    return (max(target) - min(target)) / span if span > 0 else math.nan


def finite(name, value):
    if not isinstance(value, float) or not math.isfinite(value):
        raise Mismatch('SPICE_NONFINITE', f'{name} is {value!r}')
    return value


# ---------------------------------------------------------------- independent expectations

def rc_reference(tau):
    """Analytic values of the RC step: 50 % delay and 10-90 % rise time."""
    return dict(t50=tau * math.log(2), rise=tau * math.log(9))


def rc_error(times, values, tau):
    """Largest difference from 1 - exp(-t/tau) over all solver points."""
    return max(abs(v - (1 - math.exp(-t / tau))) for t, v in zip(times, values))


def drive_estimate(process, vdd, load):
    """A rough hand estimate of the falling delay: half the swing over the saturation current.

    It ignores the input slope, the parasitic capacitance and the triode region, so it is only good
    to a factor of two. Its use is to catch a wrong unit or a wrong order of magnitude.
    """
    p = PROCESS[process]
    current = 0.5 * NMOS['kp'] * p['kp'] * (1.0 / 0.18) * (vdd - NMOS['vto'] - p['dvt']) ** 2
    return load * (vdd / 2) / current


def in_range(label, name, value, nominal, tolerance):
    finite(name, value)
    if abs(value - nominal) > tolerance * abs(nominal):
        raise Mismatch(label, f'{name}={value:.6g} outside {nominal:.6g} +/- {100*tolerance:g} %')


# ---------------------------------------------------------------- Monte Carlo and its statistics

SIGMA = dict(vto=0.015, kp=0.04, load=0.03)


def draws(seed, trials, stream='run', mean_shift=0.0):
    """Per-trial variation. All randomness is drawn here, in Python, from the seed."""
    rng = random.Random(f'{stream}:{seed}')
    result = []
    for _ in range(trials):
        result.append(dict(n_vto=rng.gauss(mean_shift, SIGMA['vto']), p_vto=rng.gauss(mean_shift, SIGMA['vto']),
                           n_kp=math.exp(rng.gauss(0, SIGMA['kp'])), p_kp=math.exp(rng.gauss(0, SIGMA['kp'])),
                           load=math.exp(rng.gauss(0, SIGMA['load']))))
    return result


def binomial_cdf(k, n, p):
    """P(X <= k) for X ~ Binomial(n, p), summed in log space."""
    if k < 0:
        return 0.0
    if k >= n:
        return 1.0
    if p <= 0:
        return 1.0
    if p >= 1:
        return 0.0
    total = 0.0
    for i in range(k + 1):
        total += math.exp(math.lgamma(n + 1) - math.lgamma(i + 1) - math.lgamma(n - i + 1)
                          + i * math.log(p) + (n - i) * math.log1p(-p))
    return min(1.0, total)


def acceptance(n, p_low, p_high, alpha):
    """Pass counts [lo, hi] that a correct circuit leaves with probability at most alpha per side.

    The reference probability is itself an estimate, so the lower bound uses its lower limit and the
    upper bound its upper limit. That only widens the region.
    """
    lo = 0
    while binomial_cdf(lo, n, p_low) <= alpha:
        lo += 1
    hi = n
    while 1 - binomial_cdf(hi - 1, n, p_high) <= alpha:
        hi -= 1
    return lo, hi


def clopper_pearson(k, n, confidence):
    """Exact two-sided interval for a pass probability, by bisection on the binomial tail."""
    alpha = (1 - confidence) / 2

    def solve(target, upper):
        a, b = 0.0, 1.0
        for _ in range(60):
            m = (a + b) / 2
            value = binomial_cdf(k, n, m) if upper else 1 - binomial_cdf(k - 1, n, m)
            if (value > target) == upper:
                a = m
            else:
                b = m
        return (a + b) / 2
    low = 0.0 if k == 0 else solve(alpha, False)
    high = 1.0 if k == n else solve(alpha, True)
    return low, high

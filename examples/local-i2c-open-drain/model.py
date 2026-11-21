"""Bus loads, the SCL/SDA schedule, the closed-form line and the judgement for the open-drain I2C example.

None of this looks at the RTL:
  * when SCL changes, when the target drives SDA, and when the reading side samples it;
  * the SDA voltage as a chain of RC exponentials, and when it crosses the input thresholds;
  * what the reading side must read, from the line events that ngspice produced.
All values are made up for this teaching example; they are not a product's or a process's.
"""
import math
import random

VDD = 3.3
VIH = 0.7 * VDD            # a rising line is read as 1 once it passes VIH
VIL = 0.3 * VDD            # a falling line is read as 0 once it passes VIL; in between the input keeps its value
RON = 50.0                 # on-resistance of the target's pull-down
T_NS = 10                  # clock period of the reading side (100 MHz)
E0_NS = 25                 # the clock edge that takes the start request and pulls SCL low
THD_NS = 100               # the target changes SDA this long after SCL falls
SWITCH_NS = 0.6            # the 1 ns control ramp turns the switch at 0.6 ns (threshold 0.6 V rising, 0.4 V falling)
GUARD_NS = 2.0             # no line event may come closer than this to a sampling edge
SOLVER = dict(step=2e-9, reltol=1e-4, method='gear')
ALTERNATIVES = (dict(step=1e-9, reltol=1e-5, method='gear'), dict(step=2e-9, reltol=1e-4, method='trap'))
TOL_V = 0.005              # low level: the divider value, within a few solver tolerances


def tol_ns(tau_ns):
    """Allowed difference between an analytic and a solved crossing: 1 ns plus 0.1 % of tau.

    Measured: at most 0.34 ns (strong pull-up, tau 15 ns) and 0.11 ns elsewhere, with a 2 ns step."""
    return 1.0 + 0.001 * tau_ns


def tol_settings_ns(tau_ns):
    """Allowed movement of a crossing when the solver settings change: 0.5 ns plus 0.05 % of tau.

    Measured: at most 0.26 ns (trapezoidal rule, strong pull-up)."""
    return 0.5 + 0.0005 * tau_ns


CONFIGS = {
    'fm400-mid': dict(DIV=125, SAMPLE=62),    # 400 kHz, sampled in the middle of the high phase
    'fm400-late': dict(DIV=125, SAMPLE=112),  # same clock, sampled late in the high phase
    'fm1m': dict(DIV=50, SAMPLE=25),          # 1 MHz, middle of the high phase
}
EDGE_RP = {125: 4700.0, 50: 2200.0}
DATA = 0x5A                # 0 1 0 1 1 0 1 0: three rising transitions, one 1 after a 1


class Mismatch(Exception):
    def __init__(self, label, message):
        super().__init__(message)
        self.label = label


# ---------------------------------------------------------------- the line, in closed form

def low_level(rp):
    return VDD * RON / (RON + rp)


def rise_tau(load):
    return load['rp'] * load['cb'] * 1e9


def fall_tau(load):
    return load['cb'] * load['rp'] * RON / (load['rp'] + RON) * 1e9


def rise_needed(load):
    """ns from the release of a settled low line until it passes VIH."""
    return rise_tau(load) * math.log((VDD - low_level(load['rp'])) / (VDD - VIH))


def window(cfg):
    """ns from the target's release to the sampling edge, for a 1 that follows a 0."""
    return cfg['DIV'] * T_NS - THD_NS + cfg['SAMPLE'] * T_NS


def max_frequency(load, fraction):
    """Highest SCL frequency (Hz) at which a 1 after a 0 is read, sampling at `fraction` of the high phase."""
    return (1 + fraction) / (2 * (rise_needed(load) + THD_NS) * 1e-9)


def edge_load(cfg, ratio):
    """A load with the config's pull-up whose rise needs `ratio` times the config's window."""
    rp = EDGE_RP[cfg['DIV']]
    tau = ratio * window(cfg) / math.log((VDD - low_level(rp)) / (VDD - VIH))
    return dict(rp=rp, cb=round(tau / rp * 1e3, 1) * 1e-12)   # bus capacitance rounded to 0.1 pF


def loads():
    """The fixed loads. Each config's boundary pair is run on every config."""
    found = {'light': dict(rp=1000.0, cb=50e-12), 'heavy': dict(rp=10000.0, cb=400e-12),
             'strong-ok': dict(rp=150.0, cb=100e-12), 'strong-fail': dict(rp=100.0, cb=100e-12)}
    for name, cfg in CONFIGS.items():
        found[f'{name}-inside'] = edge_load(cfg, 0.95)
        found[f'{name}-outside'] = edge_load(cfg, 1.05)
    return found


def schedule(cfg, data):
    """SCL edges, sampling edges, the target's drive (True = pull low) and the end, all in ns."""
    p = cfg['DIV'] * T_NS
    edges = [(E0_NS + n * p, 1 if n % 2 else 0) for n in range(17)] + [(E0_NS + 17 * p, 1)]
    samples = [E0_NS + (2 * k + 1) * p + cfg['SAMPLE'] * T_NS for k in range(8)]
    bits = [(data >> (7 - k)) & 1 for k in range(8)]
    drive, state = [], False
    for k, bit in enumerate(bits):
        want = bit == 0
        if want != state:
            drive.append((E0_NS + 2 * k * p + THD_NS, want))
            state = want
    if state:
        drive.append((E0_NS + 16 * p + THD_NS, False))
    return dict(edges=edges, samples=samples, bits=bits, drive=drive, done=E0_NS + 17 * p, stop=E0_NS + 19 * p,
                end=E0_NS + 21 * p)


def line(load, drive, stop):
    """Digital line events with hysteresis, from the exponential segments between drive changes.

    Returns (events, transitions): events are (t_ns, value, tau_ns); transitions list every segment with
    whether it crossed, so that interrupted rises are visible."""
    vol = low_level(load['rp'])
    v, state, t0, on = VDD, 1, 0.0, False
    events, segments = [], []
    for t1, next_on in [*drive, (stop, None)]:
        length, final = t1 - t0, next_on is None
        if on:
            tau, target = fall_tau(load), vol
            crossing = None
            if state == 1 and v > VIL and vol < VIL:
                crossing = tau * math.log((v - vol) / (VIL - vol))
            if crossing is not None and crossing < length:
                events.append((t0 + crossing, 0, tau))
                state = 0
            segments.append(dict(kind='fall', start=t0, final=final, crossed=crossing is not None and crossing < length))
        else:
            tau, target = rise_tau(load), VDD
            crossing, start_low = None, state == 0
            if state == 0 and v < VIH:
                crossing = tau * math.log((VDD - v) / (VDD - VIH))
            if crossing is not None and crossing < length:
                events.append((t0 + crossing, 1, tau))
                state = 1
            segments.append(dict(kind='rise', start=t0, final=final, start_low=start_low,
                                 crossed=crossing is not None and crossing < length))
        v = target + (v - target) * math.exp(-length / tau)
        t0 = t1
        if next_on is not None:
            on = next_on
    return events, segments


def interrupted(segments):
    """A release that the next pull-down cut off before the line reached VIH."""
    return any(s['kind'] == 'rise' and s['start_low'] and not s['crossed'] and not s['final'] for s in segments)


def sampled(events, samples):
    """The value the reading side must see at each sampling edge. Events too close to an edge are an error."""
    values = []
    for s in samples:
        for t, _v, *_ in events:
            if abs(t - s) < GUARD_NS:
                raise ValueError(f'line event at {t:.3f} ns is within {GUARD_NS} ns of the sampling edge at {s} ns')
        state = 1
        for t, value, *_ in events:
            if t < s:
                state = value
        values.append(state)
    return values


def to_byte(bits):
    return sum(b << (7 - k) for k, b in enumerate(bits))


def outcome(sent, read):
    """correct, slow-rise (a 1 read as 0) or low-too-high (a 0 read as 1)."""
    kinds = set()
    for s, r in zip(sent, read):
        if s == 1 and r == 0:
            kinds.add('slow-rise')
        if s == 0 and r == 1:
            kinds.add('low-too-high')
    return kinds or {'correct'}


def random_case(name, seed):
    """A random load and byte whose closed-form events stay clear of every sampling edge."""
    cfg = CONFIGS[name]
    rng = random.Random(f'{name}/{seed}')
    for _ in range(1000):
        load = dict(rp=round(math.exp(rng.uniform(math.log(1000), math.log(10000)))),
                    cb=round(rng.uniform(50, 400), 1) * 1e-12)
        data = rng.randrange(256)
        plan = schedule(cfg, data)
        events, _ = line(load, plan['drive'], plan['stop'])
        if all(abs(t - s) >= tol_ns(tau) + 5 for t, _v, tau in events for s in plan['samples']):
            return load, data
    raise ValueError('no random load stays clear of the sampling edges')


# ---------------------------------------------------------------- netlist and judgement

def pwl(drive):
    points, level = [(0.0, 0.0)], 0.0
    for t, on in drive:
        begin = t - SWITCH_NS
        points += [(begin, level), (begin + 1.0, 1.0 if on else 0.0)]
        level = 1.0 if on else 0.0
    return ' '.join(f'{t * 1e-9:.12g} {v:g}' for t, v in points)


def deck(template, load, drive, fault=None, solver=SOLVER):
    """Fill the netlist. `fault` breaks one value in the netlist only, for a negative case."""
    if fault == 'release-missing' and (not drive or drive[-1][1]):
        raise ValueError('release-missing needs a drive that ends with a release')
    values = dict(VDD=VDD, RP=load['rp'], CB=load['cb'], VINIT=VDD, RON=RON, PWL=pwl(drive),
                  RELTOL=solver['reltol'], METHOD=solver['method'])
    if fault == 'cb-plus5':
        values['CB'] = load['cb'] * 1.05
    elif fault == 'ron-high':
        values['RON'] = RON * 20
    elif fault == 'no-initial':
        values['VINIT'] = 0.0
    elif fault == 'release-missing':
        values['PWL'] = pwl(drive[:-1])
    elif fault is not None:
        raise ValueError('unknown analog fault')
    text = template
    for key, value in values.items():
        if '@' + key + '@' not in text:
            raise ValueError('netlist template lacks ' + key)
        text = text.replace('@' + key + '@', format(value, '.12g') if isinstance(value, float) else str(value))
    if '@' in text:
        raise ValueError('unfilled netlist placeholder')
    return text


def low_windows(load, drive, stop):
    """Stretches (ns) where the pull-down has been on long enough for the line to have settled."""
    found, settle = [], 30 * fall_tau(load) + 20
    ends = [t for t, _ in drive[1:]] + [stop]
    for (t, on), end in zip(drive, ends):
        if on and end - t > settle + 20:
            found.append((t + settle, end - 1))
    return found


def request(load, plan, solver=SOLVER):
    return dict(stop=plan['stop'] * 1e-9, step=solver['step'], vih=VIH, vil=VIL,
                windows=[[a * 1e-9, b * 1e-9] for a, b in low_windows(load, plan['drive'], plan['stop'])])


def digitise(crossings):
    """Apply the input's hysteresis to the solver's VIH/VIL crossings. Returns (t_ns, value)."""
    events, state = [], 1
    for c in crossings:
        if state == 1 and c['level'] == 'vil' and c['direction'] == 0:
            events.append((c['t'] * 1e9, 0))
            state = 0
        elif state == 0 and c['level'] == 'vih' and c['direction'] == 1:
            events.append((c['t'] * 1e9, 1))
            state = 1
    return events


def _finite(record):
    try:
        values = [record['stop'], record['initial'], *[w[k] for w in record['windows'] for k in ('min', 'max')],
                  *[c['t'] for c in record['crossings']]]
    except (KeyError, TypeError) as exc:
        raise Mismatch('ANALOG_MEASURE', f'a measurement is missing: {exc}') from exc
    if not all(isinstance(v, (int, float)) and math.isfinite(v) for v in values):
        raise Mismatch('ANALOG_MEASURE', 'a measurement is missing or not finite')


def check_analog(load, plan, record):
    """Judge one solved line. Returns (goals, events); raises Mismatch with the first failing label."""
    _finite(record)
    if abs(record['initial'] - VDD) > TOL_V:
        raise Mismatch('ANALOG_INITIAL', f"the line starts at {record['initial']:.4f} V, not released at {VDD} V")
    vol = low_level(load['rp'])
    windows = low_windows(load, plan['drive'], plan['stop'])
    if len(record['windows']) != len(windows):
        raise Mismatch('ANALOG_MEASURE', 'low-level windows differ from the request')
    for w in record['windows']:
        if abs(w['min'] - vol) > TOL_V or abs(w['max'] - vol) > TOL_V:
            raise Mismatch('ANALOG_LOW', f"low level {w['min']:.4f}..{w['max']:.4f} V, expected {vol:.4f} V")
    solved = digitise(record['crossings'])
    analytic, segments = line(load, plan['drive'], plan['stop'])
    if [v for _, v in solved] != [v for _, v, _ in analytic]:
        raise Mismatch('ANALOG_COUNT', f'line events {[v for _, v in solved]} differ from the closed form {[v for _, v, _ in analytic]}')
    worst = 0.0
    for (ts, _), (ta, _, tau) in zip(solved, analytic):
        if abs(ts - ta) > tol_ns(tau):
            raise Mismatch('ANALOG_TIME', f'crossing at {ts:.3f} ns, closed form {ta:.3f} ns (allowed {tol_ns(tau):.2f} ns)')
        worst = max(worst, abs(ts - ta) / tol_ns(tau))
    goals = set()
    if any(v == 1 for _, v in solved):
        goals.add('analog/rise-crossing')
    if any(v == 0 for _, v in solved):
        goals.add('analog/fall-crossing')
    if windows:
        goals.add('analog/low-level')
    if interrupted(segments):
        goals.add('analog/interrupted-rise')
    if vol > VIL and any(on for _, on in plan['drive']):
        goals.add('analog/low-above-vil')
    return goals, solved, worst


def check_settings(reference, other, load):
    a, b = digitise(reference['crossings']), digitise(other['crossings'])
    if [v for _, v in a] != [v for _, v in b]:
        raise Mismatch('ANALOG_SETTINGS', 'the line events depend on the solver settings')
    allowed = tol_settings_ns(max(rise_tau(load), fall_tau(load)))
    shift = max((abs(x - y) for (x, _), (y, _) in zip(a, b)), default=0.0)
    if shift > allowed:
        raise Mismatch('ANALOG_SETTINGS', f'crossings move by {shift:.3f} ns (allowed {allowed:.2f} ns)')
    return shift


def expected_lines(plan, read):
    """The expected-value file the bench reads."""
    lines = [f"EDGES {len(plan['edges'])}"] + [f'{t:.3f} {v}' for t, v in plan['edges']]
    lines += [f"SAMPLES {len(plan['samples'])}"] + [f'{t:.3f} {b}' for t, b in zip(plan['samples'], read)]
    lines += [f"DONE {plan['done']:.3f} {to_byte(read):02x}", f"END {plan['end']:.3f}"]
    return '\n'.join(lines) + '\n'


def event_lines(events):
    return ''.join(f'{t:.3f} {v}\n' for t, v in events)

"""Supply scenarios, analytic expectations and the cycle-level reference for the power-on-reset example.

Three things live here and none of them looks at the RTL:
  * what the detector should do, from the divider ratio, the RC constant and the two thresholds;
  * what the digital side should show at every clock, as closed-form timelines per reset release;
  * which scenes a scenario was built to reach, so that a run cannot pass without reaching them.
"""
import math
import random

T_NS = 4000            # clock period (250 kHz)
SAMPLE_NS = T_NS // 2 - 100   # outputs are compared this long after each rising edge
GUARD_NS = 50          # no detector event is placed closer than this to an edge or a compare point
V_NOMINAL = 1.8
GAIN = 2000.0          # comparator gain, 1/V
R_OUT, C_OUT = 1000.0, 1e-9
EDGE_S = 1e-7          # rise/fall time of an abrupt supply step
SOLVER = dict(step=1e-7, reltol=1e-5, method='gear')

CONFIGS = {
    'tau10-sync2': dict(r1=1e5, r2=1e5, c1=200e-12, vth=0.75, hys=0.10, STAGES=2, WAIT=4, CAL_TIMEOUT=8),
    'tau20-sync3': dict(r1=1e5, r2=1e5, c1=400e-12, vth=0.75, hys=0.16, STAGES=3, WAIT=2, CAL_TIMEOUT=5),
}
DIGITAL = ('STAGES', 'WAIT', 'CAL_TIMEOUT')

# Tolerances, with their reasons (the README repeats them with numbers).
TOL_DIV_V = 0.005      # comparator threshold at the divider node: 2/GAIN = 1 mV plus slope * output delay
TOL_VDD_V = 0.010      # threshold seen at the supply, in addition to the ripple amplitude
TOL_DELAY_S = 2e-7     # two solver steps
TOL_SETTINGS_S = 2e-7  # two solver steps: an event time may move this much when the settings change
MAP_GUARD_S = 5e-7     # dips this close to the analytic boundary are not classified


class Mismatch(Exception):
    def __init__(self, label, message):
        super().__init__(message)
        self.label = label


def analog(cfg):
    """Detector constants derived from the component values."""
    ratio = cfg['r2'] / (cfg['r1'] + cfg['r2'])
    tau = cfg['r1'] * cfg['r2'] / (cfg['r1'] + cfg['r2']) * cfg['c1']
    rise, fall = cfg['vth'] + cfg['hys'] / 2, cfg['vth'] - cfg['hys'] / 2
    return dict(ratio=ratio, tau=tau, tau_out=R_OUT * C_OUT, rise_div=rise, fall_div=fall,
                rise_vdd=rise / ratio, fall_vdd=fall / ratio)


def step_delay(cfg, level=V_NOMINAL):
    """Bounds for the time from an abrupt supply step to the detector event.

    The divider node follows level*ratio*(1-exp(-t/tau)) and reaches the rising threshold at t_div.
    The comparator output is then filtered by tau_out; positive feedback only makes it faster, so the
    event lies between t_div and t_div + tau_out*ln 2.
    """
    a = analog(cfg)
    top = level * a['ratio']
    t_div = a['tau'] * math.log(top / (top - a['rise_div']))
    return t_div - TOL_DELAY_S, t_div + a['tau_out'] * math.log(2) + EDGE_S + TOL_DELAY_S


def dip_boundary(cfg, depth, level=V_NOMINAL):
    """Width of an abrupt dip to `depth` at which the divider node just reaches the falling threshold."""
    a = analog(cfg)
    low, high = depth * a['ratio'], level * a['ratio']
    if low >= a['fall_div']:
        return math.inf
    return a['tau'] * math.log((high - low) / (a['fall_div'] - low))


def minimum_pulse(cfg, level=V_NOMINAL):
    """Shortest low pulse: the node must climb from the falling to the rising threshold again."""
    a = analog(cfg)
    high = level * a['ratio']
    return a['tau'] * math.log((high - a['fall_div']) / (high - a['rise_div']))


def classify_dip(cfg, depth, width):
    """'reset', 'ignored' or None (too close to the analytic boundary to call)."""
    boundary = dip_boundary(cfg, depth)
    if width <= boundary - MAP_GUARD_S:
        return 'ignored'
    if width >= boundary + analog(cfg)['tau_out'] * math.log(2) + MAP_GUARD_S:
        return 'reset'
    return None


# ---------------------------------------------------------------- supply scenarios

def _dips(start, dips):
    """PWL points for nominal supply with abrupt dips; returns points and one window per dip."""
    points, windows = [], []
    for at, depth, width in dips:
        points += [(at, V_NOMINAL), (at + EDGE_S, depth), (at + width, depth), (at + width + EDGE_S, V_NOMINAL)]
        windows.append((at, at + width))
    return points, windows


def _power_on(at=1e-5):
    return [(0.0, 0.0), (at, 0.0), (at + EDGE_S, V_NOMINAL)]


def scenario(name, cfg, seed=0):
    """A supply waveform, what it was built to show, and the per-release input plan."""
    a = analog(cfg)
    tau = a['tau']
    t_clk = T_NS * 1e-9
    base = dict(name=name, ripple=0.0, ripple_hz=20e3, dips=[], classes=[], checks=[], phase=T_NS + 1234, plans=[dict()])
    if name == 'powerup':
        base.update(pwl=_power_on() + [(4e-4, V_NOMINAL)], stop=4e-4, checks=['delay'],
                    plans=[dict(cal=('delay', 2), strap=0x9, clear=('ready', 2))])
    elif name == 'slow-ramp':
        base.update(pwl=[(0.0, 0.0), (5e-3, V_NOMINAL), (6e-3, V_NOMINAL), (11e-3, 0.0)], stop=11e-3, ripple=0.03,
                    checks=['thresholds'], phase=T_NS + 2718, plans=[dict(cal=('delay', 1), strap=0x6)])
    elif name == 'brownout':
        t1 = dip_boundary(cfg, 1.0)
        start = 4e-4
        dips = [(start, 1.5, 1e-4), (start + 4e-4, 1.0, t1 - 1.5e-6), (start + 8e-4, 1.0, t1 + 1.5e-6 + a['tau_out']),
                (start + 12e-4, 0.6, 6 * tau)]
        # The last dip must fall while the calibration of the release after the fourth dip is still waiting.
        high, low = V_NOMINAL * a['ratio'], 0.6 * a['ratio']
        floor = low + (high - low) * math.exp(-dips[3][2] / tau)          # divider node when the fourth dip ends
        good = dips[3][0] + dips[3][2] + tau * math.log((high - floor) / (high - a['rise_div'])) + a['tau_out'] * math.log(2)
        in_cal = good + (cfg['STAGES'] + cfg['WAIT'] + 1 + cfg['CAL_TIMEOUT'] / 2) * t_clk
        dips.append((in_cal - dip_boundary(cfg, 0.6) - a['tau_out'] * math.log(2), 0.6, 6 * tau))
        points, _ = _dips(start, dips)
        stop = dips[-1][0] + 6e-4
        base.update(pwl=_power_on() + points + [(stop, V_NOMINAL)], stop=stop, dips=dips,
                    classes=['ignored-shallow', 'ignored-short', 'reset-shortest', 'reset-long', 'reset-in-cal'],
                    checks=['pulses'], phase=T_NS + 3141,
                    plans=[dict(cal=('delay', 2), strap=0x5, clear=('ready', 2)),
                           dict(cal=('delay', cfg['CAL_TIMEOUT']), strap=0xa, strap_after=0x4),
                           dict(cal=('never',), strap=0x7),
                           dict(cal=('delay', 3), strap=0x3, early_done=True, clear=('release', 0))])
    elif name == 'repower':
        cycle = 8e-4
        pwl = _power_on()
        for index in range(1, 4):
            off = index * cycle
            pwl += [(off, V_NOMINAL), (off + 5e-5, 0.0), (off + 2.5e-4, 0.0), (off + 3e-4, V_NOMINAL)]
        stop = 4 * cycle
        base.update(pwl=pwl + [(stop, V_NOMINAL)], stop=stop, phase=T_NS + 577, checks=['repower'],
                    plans=[dict(cal=('stuck',), strap=0xc, clear=('ready', 3)),
                           dict(cal=('delay', cfg['CAL_TIMEOUT'] + 1), strap=0x1, clear=('release', -1), done_again=True),
                           dict(cal=('never',), strap=0xe),
                           dict(cal=('delay', 1), strap=0x8, clear=('release', 0))])
    elif name == 'dipmap':
        dips, at = [], 4e-4
        depths = (1.5, 1.2, 1.0, 0.6, 0.0) if seed else (1.5, 1.0, 0.0)
        for depth in depths:
            boundary = dip_boundary(cfg, depth)
            widths = (1e-4,) if math.isinf(boundary) else (boundary / 2, boundary - 1e-6, boundary + 2e-6, 3 * boundary)
            for width in widths:
                dips.append((at, depth, width))
                at += 4e-4
        points, _ = _dips(4e-4, dips)
        base.update(pwl=_power_on() + points + [(at, V_NOMINAL)], stop=at, dips=dips, checks=['map'])
    elif name == 'random':
        rng = random.Random(seed * 7919 + len(cfg))
        dips, at = [], 4e-4
        for _ in range(6):
            depth = rng.choice((1.5, 1.2, 1.0, 0.6, 0.0))
            boundary = dip_boundary(cfg, depth)
            width = rng.choice((5e-5, 1e-4)) if math.isinf(boundary) else boundary * rng.choice((0.4, 0.7, 1.6, 3.0, 8.0))
            dips.append((at, depth, width))
            at += width + rng.uniform(3e-4, 5e-4)
        points, _ = _dips(4e-4, dips)
        plans = [dict(cal=rng.choice((('delay', rng.randint(1, cfg['CAL_TIMEOUT'] + 1)), ('never',), ('stuck',))),
                      strap=rng.randrange(16), strap_after=rng.randrange(16), early_done=rng.random() < 0.3,
                      clear=rng.choice((None, ('ready', rng.randint(0, 3)), ('release', rng.randint(-1, 2)))))
                 for _ in range(8)]
        base.update(pwl=_power_on() + points + [(at, V_NOMINAL)], stop=at, dips=dips,
                    checks=['pulses'], phase=T_NS + rng.randrange(T_NS), plans=plans)
    else:
        raise ValueError('unknown scenario ' + name)
    # Each dip is judged in a window that runs until the node has settled again or the next dip starts.
    starts = [at for at, _, _ in base['dips']] + [base['stop']]
    base['windows'] = [(at, min(at + width + 5 * tau, following)) for (at, _, width), following in zip(base['dips'], starts[1:])]
    if any(b <= a for (a, _), (b, _) in zip(base['pwl'], base['pwl'][1:])):
        raise ValueError(name + ': supply points are not in time order')
    return base


def async_pulses(cfg):
    """Detector events written by hand (no SPICE): pulses the analog side cannot make, in every state."""
    phase = T_NS + 2000
    edge = lambda k: phase + k * T_NS
    events, k = [], 3
    def low(start, width):
        events.append((start, 0))
        events.append((start + width, 1))
    events.append((edge(2) + 700, 1))                      # first release
    stages, wait, timeout = (cfg[n] for n in DIGITAL)
    release = 3 + stages                                    # first clock at which the controller runs
    ready = release + wait + 1 + 2                          # with calibration done on its second clock
    k = ready + 3
    low(edge(k) + 600, 2)                                   # 2 ns, between two clocks, while ready
    k += stages + wait + 8
    low(edge(k) - 300, 900)                                 # across one clock, while ready
    k += stages + wait + 8
    low(edge(k) + GUARD_NS, T_NS - 2 * GUARD_NS)            # as wide as fits between two clocks
    k += stages + 2
    low(edge(k) + 1500, 40)                                 # while waiting
    k += stages + wait + 1
    low(edge(k) + 900, 30)                                  # in the clock that loads the straps
    k += stages + wait + 3
    low(edge(k) + 1200, 25)                                 # during calibration
    k += 1
    events.append((edge(k) + 2500, 0))                      # falls again before the release completes
    events.append((edge(k) + 2600, 1))
    k += stages + wait + 1 + timeout + 3                    # this release times out (calibration never done)
    low(edge(k) + 800, 60)                                  # while failed
    k += 1
    low(edge(k) + 300, 10)                                  # two pulses inside one clock period
    low(edge(k) + 2400, 10)
    k += stages + wait + 8
    cycles = k + 6
    plans = [dict(cal=('delay', 2), strap=0xf, clear=('ready', 1))] * 5 + [dict(cal=('never',), strap=0x2)] * 3 + \
            [dict(cal=('never',), strap=0xd)] + [dict(cal=('delay', 1), strap=0xb, clear=('ready', 0))] * 4
    return dict(name='async-pulses', events=events, phase=phase, cycles=cycles, plans=plans)


def deck(template, cfg, spec, fault=None, solver=SOLVER):
    """Fill the netlist template. `fault` deliberately breaks one component for a negative case."""
    values = dict(PWL=' '.join(f'{t:.9g} {v:.6g}' for t, v in spec['pwl']), RIPPLE=spec['ripple'], RIPPLE_HZ=spec['ripple_hz'],
                  R1=cfg['r1'], R2=cfg['r2'], C1=cfg['c1'], GAIN=GAIN, VTH=cfg['vth'], HYS=cfg['hys'],
                  ROUT=R_OUT, COUT=C_OUT, RELTOL=solver['reltol'], METHOD=solver['method'])
    if fault == 'no-hysteresis':
        values['HYS'] = 0.0
    elif fault == 'divider-early':
        values['R2'] = cfg['r2'] * 1.2
    elif fault == 'divider-late':
        values['R2'] = cfg['r2'] * 0.9
    elif fault == 'slow-rc':
        values['C1'] = cfg['c1'] * 2
    elif fault is not None:
        raise ValueError('unknown analog fault')
    text = template
    for key, value in values.items():
        if text.count('@' + key + '@') < 1:
            raise ValueError('netlist template lacks ' + key)
        text = text.replace('@' + key + '@', format(value, '.12g') if isinstance(value, float) else str(value))
    if '@' in text:
        raise ValueError('unfilled netlist placeholder')
    return text


def request(cfg, spec, solver=SOLVER):
    return dict(stop=spec['stop'], step=solver['step'], lookback=5 * analog(cfg)['tau'], windows=[list(w) for w in spec['windows']])


# ---------------------------------------------------------------- analog judgement

def _finite(record):
    try:
        values = [record['stop'], record['initial_det'], record['final_det']]
        for event in record['events']:
            values += [event[k] for k in ('t', 'vdd', 'vdiv', 'vdd_max_before', 'vdd_min_before', 'value')]
        for window in record['windows']:
            values += [window[k] for k in ('det_min', 'det_max', 'vdd_min', 'vdiv_min')]
    except (KeyError, TypeError) as exc:
        raise Mismatch('ANALOG_MEASURE', f'a measurement is missing: {exc}') from exc
    if not all(isinstance(v, (int, float)) and math.isfinite(v) for v in values):
        raise Mismatch('ANALOG_MEASURE', 'a measurement is missing or not finite')
    if not all(e['value'] in (0, 1) for e in record['events']):
        raise Mismatch('ANALOG_MEASURE', 'event value is not 0 or 1')


def check_analog(cfg, spec, record):
    """Judge one solved scenario. Returns the goals it reached; raises Mismatch with the first failing label."""
    a = analog(cfg)
    _finite(record)
    events, goals = record['events'], set()
    values = [e['value'] for e in events]
    if record['initial_det'] >= 0.5 or values != [(i + 1) % 2 for i in range(len(values))]:
        raise Mismatch('ANALOG_MEASURE', 'detector does not start low or its events do not alternate')
    if 'thresholds' in spec['checks'] and len(events) != 2:
        raise Mismatch('ANALOG_CHATTER', f'{len(events)} detector events on one slow ramp up and down, 2 expected')
    for event in events:   # the supply must have reached the rising threshold before the detector reports it
        if event['value'] and event['vdd_max_before'] < a['rise_vdd'] - TOL_VDD_V - spec['ripple']:
            raise Mismatch('CROSS_EARLY', f"power good at {event['t']:.3e} s with the supply below {a['rise_vdd']:.3f} V")
    goals.add('cross/good-after-supply')
    if 'delay' in spec['checks']:
        low, high = step_delay(cfg)
        measured = events[0]['t'] - spec['pwl'][1][0] if events else math.inf
        if not low <= measured <= high:
            raise Mismatch('ANALOG_DELAY', f'step-to-event delay {measured:.3e} s is outside {low:.3e}..{high:.3e} s')
        goals.add('analog/step-delay')
    if 'thresholds' in spec['checks']:
        up, down = events
        slack = TOL_VDD_V + spec['ripple']
        if abs(up['vdd'] - a['rise_vdd']) > slack or abs(down['vdd'] - a['fall_vdd']) > slack:
            raise Mismatch('ANALOG_THRESHOLD', f"supply at the events is {up['vdd']:.4f}/{down['vdd']:.4f} V, "
                           f"expected {a['rise_vdd']:.4f}/{a['fall_vdd']:.4f} V")
        if abs(up['vdiv'] - a['rise_div']) > TOL_DIV_V or abs(down['vdiv'] - a['fall_div']) > TOL_DIV_V:
            raise Mismatch('ANALOG_THRESHOLD', f"divider node at the events is {up['vdiv']:.4f}/{down['vdiv']:.4f} V")
        width = up['vdiv'] - down['vdiv']
        if abs(width - cfg['hys']) > TOL_DIV_V:   # the two thresholds share their offsets, so the width is tighter
            raise Mismatch('ANALOG_HYSTERESIS', f"hysteresis is {width:.4f} V, expected {cfg['hys']:.4f} V")
        goals.update(('analog/no-chatter', 'analog/rise-threshold', 'analog/fall-threshold', 'analog/hysteresis-width'))
    observed = []
    if len(record['windows']) != len(spec['windows']):
        raise Mismatch('ANALOG_MEASURE', 'a dip window was not measured')
    for (start, stop), window in zip(spec['windows'], record['windows']):
        falls = [e for e in events if not e['value'] and start <= e['t'] <= stop]
        if len(falls) > 1 or (falls and window['det_min'] >= 0.5) or (not falls and window['det_max'] < 0.5):
            raise Mismatch('ANALOG_CHATTER', f'dip at {start:.3e} s gives {len(falls)} falling events')
        observed.append('reset' if falls else 'ignored')
    if 'pulses' in spec['checks'] or 'map' in spec['checks']:
        shortest = minimum_pulse(cfg) - TOL_DELAY_S
        lows = [(events[i]['t'], events[i + 1]['t'] - events[i]['t']) for i in range(1, len(events) - 1, 2)]
        if any(width < shortest for _, width in lows):
            raise Mismatch('ANALOG_PULSE', f'a low pulse is shorter than the analytic minimum {shortest:.3e} s')
        goals.add('analog/min-pulse')
        for (_, depth, width), seen in zip(spec['dips'], observed):
            expected = classify_dip(cfg, depth, width)
            if expected is not None and expected != seen:
                raise Mismatch('ANALOG_BROWNOUT', f'dip to {depth} V for {width:.3e} s is {seen}, analytic model says {expected}')
    for label, seen in zip(spec['classes'], observed):
        if seen != label.split('-')[0]:
            raise Mismatch('ANALOG_BROWNOUT', f'the {label} dip was {seen}')
        goals.add('brownout/' + label)
    if 'map' in spec['checks']:
        classes = {classify_dip(cfg, depth, width) for _, depth, width in spec['dips']}
        if not {'reset', 'ignored'} <= classes:
            raise ValueError('dip map does not hold both classes')
        goals.add('analog/boundary-map')
    if 'repower' in spec['checks']:
        if len(events) != 7 or record['final_det'] < 0.5:
            raise Mismatch('ANALOG_CHATTER', f'{len(events)} events for four power-ups and three power-downs')
        goals.add('repower/full-off')
    return goals


def check_settings(reference, other):
    """The same scenario solved with other settings must give the same events within a small time shift."""
    a, b = reference['events'], other['events']
    if [e['value'] for e in a] != [e['value'] for e in b]:
        raise Mismatch('ANALOG_SETTINGS', 'the number or direction of events depends on the solver settings')
    shift = max((abs(x['t'] - y['t']) for x, y in zip(a, b)), default=0.0)
    if not math.isfinite(shift) or shift > TOL_SETTINGS_S:
        raise Mismatch('ANALOG_SETTINGS', f'event times move by {shift:.3e} s when the solver settings change')
    return shift


# ---------------------------------------------------------------- from analog events to the digital side

def to_events(record, phase):
    """Detector events in integer nanoseconds, kept away from clock edges and compare points."""
    events, last = [], -1
    for event in record['events']:
        t = round(event['t'] * 1e9)
        offset = (t - phase) % T_NS
        for point in (0, SAMPLE_NS, T_NS):
            if abs(offset - point) < GUARD_NS:
                t += point + GUARD_NS - offset
                break
        t = max(t, last + 2)
        events.append((t, event['value']))
        last = t
    return events


def check_events(events, phase, cycles):
    last, value = 0, 0
    for t, v in events:
        offset = (t - phase) % T_NS
        if t <= last or v != 1 - value or min(offset, T_NS - offset) < GUARD_NS or abs(offset - SAMPLE_NS) < GUARD_NS:
            raise ValueError('events must alternate, increase and stay clear of edges and compare points')
        last, value = t, v
    if events and (events[0][0] <= phase or events[-1][0] >= phase + cycles * T_NS):
        raise ValueError('events must lie inside the simulated clocks')


def releases(events, phase, cycles, stages):
    """One entry per rise of the detector: the clock at which rst_n rises and the time the release ends.

    rst_n rises at the stages-th clock after the rise, if the detector is still high then. The controller
    takes its first step one clock later, because at the releasing clock it still sees the old rst_n.
    """
    found = []
    for index, (t, value) in enumerate(events):
        if not value:
            continue
        end = events[index + 1][0] if index + 1 < len(events) else math.inf
        first = (t - phase) // T_NS + 1
        rise = first + stages - 1
        found.append(dict(rise=rise if phase + rise * T_NS < end and rise < cycles else None, end=end, start=t))
    return found


def program(events, phase, cycles, cfg, plans):
    """Inputs per clock, placed relative to each release, and the scenes they were placed to make."""
    stages, wait, timeout = (cfg[n] for n in DIGITAL)
    strap, done, clear = [0] * cycles, [0] * cycles, [0] * cycles
    def put(series, k, value=1):
        if 0 <= k < cycles:
            series[k] = value
    live = [r for r in releases(events, phase, cycles, stages) if r['rise'] is not None]
    for index, release in enumerate(live):
        plan = plans[min(index, len(plans) - 1)]
        run = release['rise'] + 1
        load = run + wait - 1                       # the controller shows cfg_load after this clock
        mode = plan.get('cal', ('delay', 1))
        for k in range(run, min(cycles, load + 2)):
            strap[k] = plan.get('strap', 0)
        if 'strap_after' in plan:
            for k in range(load + 2, min(cycles, load + 2 + timeout + 3)):
                strap[k] = plan['strap_after']
        if plan.get('early_done'):
            put(done, run)                            # a pulse while still waiting: must be ignored
        if mode[0] == 'delay':
            put(done, load + 1 + mode[1])
        elif mode[0] == 'stuck':
            for k in range(max(0, run - 2), min(cycles, load + 4)):
                done[k] = 1
        if plan.get('done_again'):
            put(done, load + timeout + 4)             # after the time-out: must not rescue the sequence
        where = plan.get('clear')
        if where:
            anchor = run if where[0] == 'release' else load + 1 + (mode[1] if mode[0] == 'delay' else 1) + 1
            put(clear, anchor + where[1])
    return [list(row) for row in zip(strap, done, clear)]


def expect(events, phase, cycles, cfg, inputs, mutation=None):
    """Outputs at every compare point, from closed-form timelines per release (no state machine)."""
    stages, wait, timeout = (cfg[n] for n in DIGITAL)
    rows = [dict(rst_n=0, cfg_load=0, cal_start=0, ready=0, init_fail=0, por_flag=1, cfg=0) for _ in range(cycles)]
    scenes = set()
    sample = lambda k: phase + k * T_NS + SAMPLE_NS
    for release in releases(events, phase, cycles, stages):
        if release['rise'] is None:
            scenes.add('release/aborted')
            continue
        run = release['rise'] + 1
        load = run + wait - 1
        # calibration is requested from load+1; it is accepted on clocks load+2 .. load+1+timeout
        accept = next((k for k in range(load + 2, min(cycles, load + 2 + timeout)) if inputs[k][1]), None)
        finish = accept if accept is not None else load + 1 + timeout
        cleared = None
        k = release['rise']
        while k < cycles and sample(k) < release['end']:
            row = rows[k]
            row['rst_n'] = 1
            if k >= run:
                if cleared is None and inputs[k][2]:
                    cleared = k
                row['por_flag'] = int(cleared is None)
                row['cfg_load'] = int(k == load)
                if k >= load + 1:
                    row['cfg'] = inputs[load + 1][0]
                    row['cal_start'] = int(k < finish)
                    row['ready'] = int(k >= finish and accept is not None)
                    row['init_fail'] = int(k >= finish and accept is None)
            k += 1
        last = k - 1
        if last >= run and release['end'] != math.inf:
            state = 'ready' if rows[last]['ready'] else 'fail' if rows[last]['init_fail'] else 'cal' if rows[last]['cal_start'] \
                else 'load' if rows[last]['cfg_load'] else 'wait'
            scenes.add('reset/in-' + state)
    return rows, scenes


def pack(row):
    return (row['rst_n'] << 9 | row['cfg_load'] << 8 | row['cal_start'] << 7 | row['ready'] << 6 |
            row['init_fail'] << 5 | row['por_flag'] << 4 | row['cfg'])


def vectors(inputs, rows):
    return ''.join(f'{s:x} {d:x} {c:x} {pack(row):03x}\n' for (s, d, c), row in zip(inputs, rows))


def counts(events, phase, cycles, cfg):
    live = releases(events, phase, cycles, cfg['STAGES'])
    return dict(falls=sum(1 for _, v in events if not v), releases=sum(1 for r in live if r['rise'] is not None))

#!/usr/bin/env python3
"""Netlists for the teaching flip-flop: self-written level-1 model cards, no foundry data."""

VDD = 1.8
LENGTH = 0.18e-6
# Level-1 (Shichman-Hodges) cards written for this example. KP*W/L of the two types is equal
# and the thresholds are symmetric, so an inverter switches at exactly VDD/2.
NMOS = dict(vto=0.45, kp=220e-6, lam=0.05, overlap=0.25e-9)
PMOS = dict(vto=-0.45, kp=110e-6, lam=0.05, overlap=0.25e-9)
WN, WP = 0.5e-6, 1.0e-6          # unit inverter
NODE_CAP = 4e-15                 # lumped wiring and junction capacitance of every inverter output
OPTIONS = dict(reltol=1e-4, abstol=1e-13, vntol=1e-7)
STEP, MAX_STEP = 1e-12, 2e-12

# Events of one measurement, in seconds. The first clock pulse stores the old value;
# the rising edge at CAPTURE is the one that is measured.
FIRST_RISE, FIRST_FALL, CAPTURE, STOP = 1.0e-9, 1.6e-9, 3.0e-9, 4.6e-9

FAULTS = ('weak-output', 'slow-master', 'double-supply', 'stuck-clock')


def models():
    def card(name, kind, p):
        return (f".model {name} {kind} (level=1 vto={p['vto']} kp={p['kp']:.6e} lambda={p['lam']} "
                f"cgso={p['overlap']:.6e} cgdo={p['overlap']:.6e})")
    return [card('nch', 'nmos', NMOS), card('pch', 'pmos', PMOS)]


def ramp(name, node, start, events, slew):
    """A PWL source whose 20-80 % transition time is `slew` and whose 50 % points are `events`."""
    full = slew / 0.6
    points = [(0.0, start)]
    value = start
    for time in events:
        if time - full / 2 <= points[-1][0]:
            raise ValueError('stimulus events overlap')
        points += [(time - full / 2, value), (time + full / 2, VDD - value)]
        value = VDD - value
    return f'V{name} {node} 0 PWL(' + ' '.join(f'{t:.9e} {v:.4f}' for t, v in points) + ')'


def options(settings=None):
    values = dict(OPTIONS, **(settings or {}))
    return '.options ' + ' '.join(f'{k}={v:g}' for k, v in sorted(values.items()) if k in OPTIONS)


def flop(fault=None):
    """Transmission-gate master-slave D flip-flop, rising edge, with a two-stage output buffer."""
    if fault not in (None, *FAULTS):
        raise ValueError('unknown fault')
    out_n, out_p = (1e-6, 2e-6) if fault == 'weak-output' else (2e-6, 4e-6)
    lines = [
        f'.subckt inv a y vdd wn={WN:.3e} wp={WP:.3e}',
        f'Mp y a vdd vdd pch W={{wp}} L={LENGTH:.3e}', f'Mn y a 0 0 nch W={{wn}} L={LENGTH:.3e}',
        f'Cy y 0 {NODE_CAP:.3e}', '.ends',
        '.subckt tg a b en enb vdd',
        f'Mn a en b 0 nch W={WN:.3e} L={LENGTH:.3e}', f'Mp a enb b vdd pch W={WP:.3e} L={LENGTH:.3e}', '.ends',
        'Xc1 clk cb vdd inv', 'Xc2 cb ci vdd inv',
        'Xt1 d m1 cb ci vdd tg', 'Xi1 m1 m2 vdd inv',
        'Xi2 m2 m1f vdd inv wn=0.25u wp=0.5u', 'Xt2 m1f m1 ci cb vdd tg',
        'Xt3 m2 s1 ci cb vdd tg', 'Xi3 s1 s2 vdd inv',
        'Xi4 s2 s1f vdd inv wn=0.25u wp=0.5u', 'Xt4 s1f s1 cb ci vdd tg',
        'Xo1 s2 qb vdd inv wn=1u wp=2u', f'Xo2 qb q vdd inv wn={out_n:.3e} wp={out_p:.3e}',
        f'Cm1 m1 0 {NODE_CAP * (5 if fault == "slow-master" else 1):.3e}', f'Cs1 s1 0 {NODE_CAP:.3e}',
    ]
    return lines


def capture_deck(new, data_time, clock_slew, data_slew, load, settings=None, fault=None, back_time=None):
    """Store !new, then present `new` at data_time and clock it at CAPTURE.

    back_time, when given, returns D to the old value (the hold measurement).
    """
    old = 1 - new
    events = [data_time] + ([back_time] if back_time is not None else [])
    clock = [] if fault == 'stuck-clock' else [FIRST_RISE, FIRST_FALL, CAPTURE]
    lines = ['teaching flip-flop capture', *models(), 'Vdd vdd 0 %.4f' % VDD]
    if fault == 'double-supply':  # two ideal sources on one node: no operating point exists
        lines.append('Vdd2 vdd 0 %.4f' % (VDD - 0.3))
    lines += [ramp('clk', 'clk', 0.0, clock, clock_slew), ramp('d', 'd', old * VDD, events, data_slew),
              *flop(fault), f'Cl q 0 {load:.6e}', options(settings), '.end']
    return lines


def transient(settings=None):
    values = settings or {}
    return f"tran {values.get('step', STEP):.6e} {STOP:.6e} 0 {values.get('max_step', MAX_STEP):.6e}"


def device_deck(kind, vgs, vds):
    """One transistor between ideal sources, for the analytic drain-current check."""
    sign = 1 if kind == 'nmos' else -1
    name, width = ('nch', WN) if kind == 'nmos' else ('pch', WP)
    return ['single transistor', *models(), f'Vg g 0 {sign * vgs:.4f}', f'Vd d 0 {sign * vds:.4f}',
            f'M1 d g 0 0 {name} W={width:.3e} L={LENGTH:.3e}', options(), '.end']


def threshold_deck():
    """An inverter with its output tied to its input settles at its switching threshold."""
    return ['self-biased inverter', *models(), 'Vdd vdd 0 %.4f' % VDD,
            f'Mp x x vdd vdd pch W={WP:.3e} L={LENGTH:.3e}', f'Mn x x 0 0 nch W={WN:.3e} L={LENGTH:.3e}',
            options(), '.end']

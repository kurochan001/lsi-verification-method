#!/usr/bin/env python3
"""Independent expectations for the teaching flip-flop: formulas, the table, and the judgements.

Nothing here runs a circuit simulator. The level-1 equations are written out by hand, the
table is the checked-in record, and every comparison raises a labelled Mismatch.
"""
import json
import math
from pathlib import Path
import re

HERE = Path(__file__).resolve().parent
TABLE = HERE / 'characterized.json'
LIBERTY = HERE / 'ff_measured.lib'

# The same numbers as cells.py, written a second time on purpose: a typo in one copy shows
# up as a failed drain-current check instead of being shared.
VDD = 1.8
LENGTH_UM = 0.18
CARDS = dict(nmos=dict(vto=0.45, kp=220e-6, lam=0.05, width_um=0.5),
             pmos=dict(vto=0.45, kp=110e-6, lam=0.05, width_um=1.0))
OUTPUT_WIDTH_UM = dict(rise=4.0, fall=2.0)   # last inverter: PMOS pulls Q up, NMOS pulls it down

# Tolerances. Times in ps.
DELAY_ABS, DELAY_REL = 0.5, 0.003         # measured CLK->Q against the table
CONSTRAINT_ABS = 2.0                       # setup/hold: two and a half steps of the 0.78 ps search grid
SETTINGS_DELAY, SETTINGS_CONSTRAINT = 1.0, 2.0   # tighter solver settings may move results this far
INTERPOLATION_ABS, INTERPOLATION_REL = 2.0, 0.005  # a point between table entries against bilinear interpolation
CURRENT_REL = 1e-6                         # level-1 drain current against the formula
THRESHOLD_ABS = 1e-6                       # inverter threshold against VDD/2, in volts
OFF_CURRENT = 1e-9                         # a device below its threshold may leak at most this, in amperes
SLOPE_REL = 0.20                           # delay per load capacitance against the hand formula
ESTIMATE_FACTOR = 3.0                      # CLK->Q against the stage-count estimate: order of magnitude only
RESOLUTION = 1.0                           # the search must end with a bracket this narrow
LOOSE_GAP = 2.0                            # the loose criterion must give a setup at least this much smaller


class Mismatch(ValueError):
    def __init__(self, label, message):
        super().__init__(message)
        self.label = label


def fail(label, message):
    raise Mismatch(label, message)


# ---- level-1 equations ------------------------------------------------------------------

def drain_current(kind, vgs, vds, width_um=None):
    """Shichman-Hodges drain current magnitude for magnitudes vgs, vds."""
    card = CARDS[kind]
    beta = card['kp'] * (width_um or card['width_um']) / LENGTH_UM
    over = vgs - card['vto']
    if over <= 0:
        return 0.0
    if vds >= over:
        return 0.5 * beta * over * over * (1 + card['lam'] * vds)
    return beta * (over * vds - vds * vds / 2) * (1 + card['lam'] * vds)


def load_slope(edge):
    """Expected increase of CLK->Q per load capacitance, in ps/fF.

    The last inverter moves Q by VDD/2 against the load. Its current falls from the value at
    Vds = VDD to the value at Vds = VDD/2; the average of the two is used.
    """
    kind = 'pmos' if edge == 'rise' else 'nmos'
    width = OUTPUT_WIDTH_UM[edge]
    current = (drain_current(kind, VDD, VDD, width) + drain_current(kind, VDD, VDD / 2, width)) / 2
    return (VDD / 2) / current * 1e-15 / 1e-12


def stage_estimate():
    """Order-of-magnitude CLK->Q in ps: five unit stages, each moving its node by VDD/2.

    Node capacitance 4 fF plus about 1.5 fF of gate overlap; unit NMOS/PMOS average current.
    """
    capacitance = 5.5e-15
    current = sum((drain_current(k, VDD, VDD) + drain_current(k, VDD, VDD / 2)) / 2 for k in CARDS) / 2
    return 5 * capacitance * (VDD / 2) / current / 1e-12


# ---- the table --------------------------------------------------------------------------

DELAY_TABLES = ('cell_rise', 'cell_fall', 'rise_transition', 'fall_transition')
CHECK_TABLES = ('setup_rise', 'setup_fall', 'hold_rise', 'hold_fall')


def load_table(path=TABLE):
    table = json.loads(Path(path).read_text())
    validate_table(table)
    return table


def validate_table(table):
    if table.get('schema_version') != 1:
        fail('TABLE_FORMAT', 'unsupported table version')
    shapes = dict(delay=(table['clock_slew_ps'], table['load_ff'], DELAY_TABLES),
                  check=(table['data_slew_ps'], table['clock_slew_check_ps'], CHECK_TABLES))
    for rows, columns, names in shapes.values():
        for axis in (rows, columns):
            if len(axis) < 2 or any(b <= a for a, b in zip(axis, axis[1:])):
                fail('TABLE_FORMAT', 'table axes must be increasing with at least two points')
        for name in names:
            values = table.get(name)
            if (not isinstance(values, list) or len(values) != len(rows) or
                    any(not isinstance(r, list) or len(r) != len(columns) for r in values) or
                    not all(isinstance(v, (int, float)) and math.isfinite(v) for r in values for v in r)):
                fail('TABLE_FORMAT', f'table {name} has the wrong shape or a non-finite value')
    return table


def interpolate(rows, columns, values, row, column):
    """Bilinear interpolation inside the table; the point must not lie outside the axes."""
    def bracket(axis, x):
        if not axis[0] <= x <= axis[-1]:
            raise ValueError('point outside the table')
        i = max(j for j in range(len(axis) - 1) if axis[j] <= x)
        return i, (x - axis[i]) / (axis[i + 1] - axis[i])
    i, u = bracket(rows, row)
    j, v = bracket(columns, column)
    return ((1 - u) * (1 - v) * values[i][j] + (1 - u) * v * values[i][j + 1] +
            u * (1 - v) * values[i + 1][j] + u * v * values[i + 1][j + 1])


# ---- judging measurements ---------------------------------------------------------------

def need(results, identity, *fields):
    """A measurement record that exists, did not fail and carries finite numbers."""
    record = results.get(identity)
    if record is None:
        fail('MEAS_MISSING', f'no result for {identity}')
    if record.get('error'):
        missing = 'does not switch' in record['error']
        fail('MEAS_MISSING' if missing else 'SPICE_ERROR', f"{identity}: {record['error']}")
    for field in fields:
        value = record.get(field)
        if value is None:
            fail('MEAS_MISSING', f'{identity} has no {field}')
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            fail('MEAS_INVALID', f'{identity}.{field} is not a finite number')
    return record


def ps(seconds):
    return seconds * 1e12


def check_devices(results):
    worst = 0.0
    for identity, kind, vgs, vds in DEVICE_POINTS:
        measured = abs(need(results, identity, 'current')['current'])
        expected = drain_current(kind, vgs, vds)
        if expected == 0:   # below threshold the level-1 device is off; only leakage (gmin) remains
            if measured > OFF_CURRENT:
                fail('MODEL_CURRENT', f'{identity}: {measured:.3e} A flows below the threshold')
            continue
        error = abs(measured - expected) / expected
        worst = max(worst, error)
        if error > CURRENT_REL:
            fail('MODEL_CURRENT', f'{identity}: {measured:.6e} A, formula {expected:.6e} A')
    threshold = need(results, 'threshold', 'voltage')['voltage']
    if abs(threshold - VDD / 2) > THRESHOLD_ABS:
        fail('MODEL_THRESHOLD', f'inverter threshold {threshold:.6f} V, expected {VDD/2:.6f} V')
    return dict(worst_current_error=worst, threshold=threshold)


DEVICE_POINTS = [('nmos-sat', 'nmos', 1.8, 1.8), ('nmos-lin', 'nmos', 1.8, 0.4), ('nmos-weak', 'nmos', 0.9, 1.8),
                 ('pmos-sat', 'pmos', 1.8, 1.8), ('pmos-lin', 'pmos', 1.8, 0.9), ('pmos-off', 'pmos', 0.3, 1.8)]


def delay_id(edge, slew, load, tag='grid'):
    return f'{tag}/{edge}/s{slew:g}/c{load:g}'


def check_id(kind, edge, data_slew, clock_slew, tag='grid'):
    return f'{tag}/{kind}-{edge}/d{data_slew:g}/k{clock_slew:g}'


def measured_delays(results, table, tag='grid'):
    """CLK->Q delay and output transition for every table entry, in ps."""
    out = {name: [] for name in DELAY_TABLES}
    for slew in table['clock_slew_ps']:
        rows = {name: [] for name in DELAY_TABLES}
        for load in table['load_ff']:
            for edge in ('rise', 'fall'):
                record = need(results, delay_id(edge, slew, load, tag), 'delay', 'transition')
                rows['cell_' + edge].append(ps(record['delay']))
                rows[edge + '_transition'].append(ps(record['transition']))
        for name in DELAY_TABLES:
            out[name].append(rows[name])
    return out


def measured_checks(results, table, tag='grid'):
    out = {name: [] for name in CHECK_TABLES}
    for data in table['data_slew_ps']:
        rows = {name: [] for name in CHECK_TABLES}
        for clock in table['clock_slew_check_ps']:
            for kind in ('setup', 'hold'):
                for edge in ('rise', 'fall'):
                    record = need(results, check_id(kind, edge, data, clock, tag), 'value', 'fails_at')
                    rows[f'{kind}_{edge}'].append(ps(record['value']))
        for name in CHECK_TABLES:
            out[name].append(rows[name])
    return out


def compare_delays(measured, table):
    worst = 0.0
    for name in DELAY_TABLES:
        for got_row, want_row in zip(measured[name], table[name], strict=True):
            for got, want in zip(got_row, want_row, strict=True):
                worst = max(worst, abs(got - want))
                if abs(got - want) > DELAY_ABS + DELAY_REL * abs(want):
                    fail('TABLE_DELAY', f'{name}: measured {got:.2f} ps, table {want:.2f} ps')
    return worst


def compare_checks(measured, table, kind):
    worst = 0.0
    for name in CHECK_TABLES:
        if not name.startswith(kind):
            continue
        for got_row, want_row in zip(measured[name], table[name], strict=True):
            for got, want in zip(got_row, want_row, strict=True):
                worst = max(worst, abs(got - want))
                if abs(got - want) > CONSTRAINT_ABS:
                    fail('TABLE_' + kind.upper(), f'{name}: measured {got:.2f} ps, table {want:.2f} ps')
    return worst


def check_trends(measured):
    """The dependences a constant table cannot show."""
    for name in DELAY_TABLES:
        values = measured[name]
        for row in values:   # more load: slower and a slower edge
            if any(b <= a for a, b in zip(row, row[1:])):
                fail('TREND_LOAD', f'{name} does not grow with the load: {row}')
        if name.startswith('cell_'):
            for column in zip(*values):   # slower clock edge: later Q
                if any(b <= a for a, b in zip(column, column[1:])):
                    fail('TREND_SLEW', f'{name} does not grow with the clock transition: {column}')
    return True


def check_constraint_trends(measured):
    for edge in ('rise', 'fall'):
        setup, hold = measured['setup_' + edge], measured['hold_' + edge]
        for column in zip(*setup):       # slower data edge needs to start earlier
            if any(b <= a for a, b in zip(column, column[1:])):
                fail('TREND_SETUP', f'setup_{edge} does not grow with the data transition: {column}')
        for row in setup:                # slower clock edge closes the master later
            if any(b >= a for a, b in zip(row, row[1:])):
                fail('TREND_SETUP', f'setup_{edge} does not shrink with the clock transition: {row}')
        for row in hold:
            if any(b <= a for a, b in zip(row, row[1:])):
                fail('TREND_HOLD', f'hold_{edge} does not grow with the clock transition: {row}')
    return True


def check_slope(measured, table):
    """Delay per load capacitance against the hand formula for the last inverter."""
    loads = table['load_ff']
    report = {}
    for edge in ('rise', 'fall'):
        expected = load_slope(edge)
        for row in measured['cell_' + edge]:
            slope = (row[-1] - row[0]) / (loads[-1] - loads[0])
            report[edge] = dict(measured=slope, formula=expected)
            if abs(slope - expected) > SLOPE_REL * expected:
                fail('LOAD_SLOPE', f'{edge}: {slope:.4f} ps/fF, formula {expected:.4f} ps/fF')
    return report


def check_estimate(measured):
    estimate = stage_estimate()
    fastest = min(min(row) for name in ('cell_rise', 'cell_fall') for row in measured[name])
    slowest = max(max(row) for name in ('cell_rise', 'cell_fall') for row in measured[name])
    if not estimate / ESTIMATE_FACTOR <= fastest <= estimate * ESTIMATE_FACTOR:
        fail('DELAY_ESTIMATE', f'fastest CLK->Q {fastest:.1f} ps, stage estimate {estimate:.1f} ps')
    return dict(estimate=estimate, fastest=fastest, slowest=slowest)


def check_search(record):
    """The recorded probes must justify the reported boundary."""
    probes = record['probes']
    value, below = ps(record['value']), ps(record['fails_at'])
    verdict = {round(ps(p['value']), 6): p['captured'] for p in probes}
    if not 0 < value - below <= RESOLUTION:
        fail('SEARCH_EVIDENCE', f'bracket {below:.3f}..{value:.3f} ps is wider than {RESOLUTION} ps')
    if verdict.get(round(value, 6)) is not True or verdict.get(round(below, 6)) is not False:
        fail('SEARCH_EVIDENCE', 'the reported bracket was not probed')
    for probe in probes:   # one boundary: everything above the result captures, everything below fails
        if (ps(probe['value']) >= value) != probe['captured']:
            fail('SEARCH_EVIDENCE', f"probe at {ps(probe['value']):.3f} ps contradicts the boundary")
    return len(probes)


def check_sweep(record, boundary):
    """Verdicts over a coarse sweep: a single change from failing to capturing, at the boundary."""
    rows = sorted(record['rows'], key=lambda r: r['value'])
    verdicts = [r['captured'] for r in rows]
    if verdicts != sorted(verdicts) or not verdicts[-1] or verdicts[0]:
        fail('SWEEP_SHAPE', f'verdicts are not fail...capture: {verdicts}')
    last_fail = max(ps(r['value']) for r in rows if not r['captured'])
    first_pass = min(ps(r['value']) for r in rows if r['captured'])
    if not last_fail - CONSTRAINT_ABS <= boundary <= first_pass + CONSTRAINT_ABS:
        fail('SWEEP_SHAPE', f'boundary {boundary:.2f} ps outside the sweep bracket {last_fail:.2f}..{first_pass:.2f} ps')
    return dict(last_fail=last_fail, first_pass=first_pass)


# ---- Liberty text -----------------------------------------------------------------------

def _values(rows, scale):
    return ','.join('"' + ','.join(f'{v * scale:.5f}' for v in row) + '"' for row in rows)


def _axis(values, scale):
    return ','.join(f'{v * scale:.5f}' for v in values)


def liberty(table):
    """The table as a small Liberty library (ns, pF). Written by hand, not by a characterization tool."""
    slew, load = _axis(table['clock_slew_ps'], 1e-3), _axis(table['load_ff'], 1e-3)
    data, clock = _axis(table['data_slew_ps'], 1e-3), _axis(table['clock_slew_check_ps'], 1e-3)

    def delay(name):
        return f'{name}(delays) {{ index_1("{slew}"); index_2("{load}"); values({_values(table[name], 1e-3)}); }}'

    def check(group, name):
        return f'{group}(checks) {{ index_1("{data}"); index_2("{clock}"); values({_values(table[name], 1e-3)}); }}'

    return '\n'.join([
        '/* SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception',
        ' * Teaching library generated from characterized.json. The numbers were measured on a',
        ' * self-written level-1 transistor netlist; they describe no foundry process. */',
        'library(teaching_measured) {',
        ' delay_model : table_lookup;',
        ' time_unit : "1ns"; voltage_unit : "1V"; current_unit : "1mA";',
        ' capacitive_load_unit(1,pf); leakage_power_unit : "1nW";',
        f' nom_process : 1; nom_voltage : {VDD}; nom_temperature : 27;',
        ' input_threshold_pct_rise : 50; input_threshold_pct_fall : 50;',
        ' output_threshold_pct_rise : 50; output_threshold_pct_fall : 50;',
        ' slew_lower_threshold_pct_rise : 20; slew_upper_threshold_pct_rise : 80;',
        ' slew_lower_threshold_pct_fall : 20; slew_upper_threshold_pct_fall : 80;',
        ' lu_table_template(delays) {',
        '  variable_1 : input_net_transition; variable_2 : total_output_net_capacitance;',
        f'  index_1("{slew}"); index_2("{load}");',
        ' }',
        ' lu_table_template(checks) {',
        '  variable_1 : constrained_pin_transition; variable_2 : related_pin_transition;',
        f'  index_1("{data}"); index_2("{clock}");',
        ' }',
        ' cell(DFF) {',
        '  area : 2;',
        '  ff(IQ,IQN) { clocked_on : "CLK"; next_state : "D"; }',
        '  pin(CLK) { direction : input; clock : true; capacitance : 0.002; }',
        '  pin(D) { direction : input; capacitance : 0.002;',
        '   timing() { related_pin : "CLK"; timing_type : setup_rising;',
        '    ' + check('rise_constraint', 'setup_rise'),
        '    ' + check('fall_constraint', 'setup_fall'),
        '   }',
        '   timing() { related_pin : "CLK"; timing_type : hold_rising;',
        '    ' + check('rise_constraint', 'hold_rise'),
        '    ' + check('fall_constraint', 'hold_fall'),
        '   }',
        '  }',
        '  pin(Q) { direction : output; function : "IQ"; max_capacitance : 0.1;',
        '   timing() { related_pin : "CLK"; timing_type : rising_edge; timing_sense : non_unate;',
        '    ' + delay('cell_rise'),
        '    ' + delay('cell_fall'),
        '    ' + delay('rise_transition'),
        '    ' + delay('fall_transition'),
        '   }',
        '  }',
        ' }',
        '}', ''])


def read_flop(text):
    """The DFF tables of a Liberty text, in ns. A reader for these teaching files, not a Liberty parser."""
    start = re.search(r'cell\(DFF\)\s*\{', text)
    if not start:
        raise ValueError('no DFF cell')
    depth, end = 0, None
    for position in range(start.end() - 1, len(text)):
        depth += (text[position] == '{') - (text[position] == '}')
        if depth == 0:
            end = position
            break
    body = text[start.end():end]

    def tables(block):
        found = {}
        for name, values in re.findall(r'(\w+)\(\w+\)\s*\{[^{}]*?values\(([^)]*)\)', block):
            found[name] = [[float(x) for x in row.split(',')] for row in re.findall(r'"([^"]*)"', values)]
        return found

    out = {}
    for block in re.findall(r'timing\(\)\s*\{(.*?)\n\s*\}', body, re.S):
        kind = re.search(r'timing_type\s*:\s*(\w+)', block)
        prefix = {'setup_rising': 'setup', 'hold_rising': 'hold', 'rising_edge': 'delay'}.get(kind and kind[1])
        if prefix:
            out[prefix] = tables(block)
    if set(out) != {'setup', 'hold', 'delay'}:
        raise ValueError('DFF timing groups missing')
    return out


def round_trip(table, text):
    """The Liberty text carries exactly the table (to the printed digits)."""
    flop = read_flop(text)
    pairs = [(flop['delay'][n], table[n]) for n in DELAY_TABLES]
    pairs += [(flop['setup']['rise_constraint'], table['setup_rise']), (flop['setup']['fall_constraint'], table['setup_fall']),
              (flop['hold']['rise_constraint'], table['hold_rise']), (flop['hold']['fall_constraint'], table['hold_fall'])]
    for got, want in pairs:
        if len(got) != len(want) or any(len(a) != len(b) for a, b in zip(got, want)):
            fail('LIBERTY_TABLE', 'Liberty table shape differs from the table')
        if any(abs(a * 1e3 - b) > 0.006 for g, w in zip(got, want) for a, b in zip(g, w)):
            fail('LIBERTY_TABLE', 'Liberty values differ from the table')
    return True


def compare_existing(table, text):
    """An older teaching library against the measured one: order of magnitude and shape only."""
    flop = read_flop(text)

    def spread(rows):
        flat = [v for row in rows for v in row]
        return min(flat), max(flat)

    report = {}
    for label, old, new in (('clk_to_q', flop['delay']['cell_rise'], table['cell_rise']),
                            ('setup', flop['setup']['rise_constraint'], table['setup_rise']),
                            ('hold', flop['hold']['rise_constraint'], table['hold_rise'])):
        old_lo, old_hi = (v * 1e3 for v in spread(old))
        new_lo, new_hi = spread(new)
        report[label] = dict(existing_ps=[old_lo, old_hi], measured_ps=[new_lo, new_hi],
                             existing_is_constant=old_lo == old_hi, existing_covers_measured=old_hi >= new_hi)
    return report

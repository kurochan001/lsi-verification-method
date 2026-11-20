"""Independent rectangular-carrier, piecewise-linear RC and conversion expectations."""
from csv import DictReader
from math import expm1, isfinite
from random import Random

CYCLE_S = 10e-6
RAMP_S = 2e-9
SUPPLY_V = 2.4
VOLTAGE_TOLERANCE = 0.0005
HALF_PERIOD = 8
PERIOD = 2 * HALF_PERIOD
ACQUIRE = 2
CONVERT = 4
LSB_UV = 12500


class Mismatch(ValueError):
    def __init__(self, label, message):
        super().__init__(message)
        self.label = label


def schedule(name, seed, periods):
    """Each tuple holds the two settings for one complete carrier period."""
    if name in ('early', 'late'):
        sample = 1 if name == 'early' else 5
        return [(4, sample)] * periods
    rng = Random(seed)
    return [(2, 1), (6, 5), (4, 3)] + [
        (rng.randrange(2, 7), rng.randrange(1, 6)) for _ in range(periods-3)
    ]


def stimuli(settings):
    yield [0, 0, 0, 0, 0]
    for duty, sample in settings:
        for cycle in range(PERIOD):
            yield [1, 1, int(cycle == 0), duty, sample]


def expected_pwm(settings):
    return [0] + [int(min(phase, PERIOD-phase) < duty)
                  for duty, _ in settings for phase in range(PERIOD)]


def expected_adc(settings, voltages, oracle):
    adc = oracle(8, ACQUIRE, CONVERT, LSB_UV)
    outputs = []
    pwm = expected_pwm(settings)
    for cycle, uv in enumerate(voltages):
        trigger = cycle != 0 and (cycle-1) % PERIOD == settings[(cycle-1)//PERIOD][1]
        fields, _ = adc.step(cycle != 0, trigger, uv, 1)
        outputs.append([cycle, pwm[cycle], int(trigger), 0, *fields])
    return outputs


def read_csv(path, fields, count, convert):
    with path.open(newline='') as stream:
        reader = DictReader(stream)
        if reader.fieldnames != fields:
            raise ValueError(f'Unexpected CSV header in {path.name}')
        rows = []
        for index, row in enumerate(reader):
            if None in row or any(row[field] is None for field in fields):
                raise ValueError(f'Incomplete CSV row {index} in {path.name}')
            values = [convert(row[k]) for k in fields]
            if values[0] != index:
                raise ValueError(f'Nonconsecutive cycle in {path.name}: {values[0]}')
            rows.append(values)
    if len(rows) != count:
        raise ValueError(f'{path.name}: expected {count} rows, got {len(rows)}')
    return rows


DIGITAL_FIELDS = ['cycle', 'pwm', 'trigger', 'cfg_error', 'ready', 'busy', 'overrun', 'valid', 'code']


def check_digital(path, settings, voltages, oracle):
    try:
        actual = read_csv(path, DIGITAL_FIELDS, len(voltages), int)
    except ValueError as exc:
        raise ValueError(f'Invalid four-state trace: {exc}') from exc
    expected = expected_adc(settings, voltages, oracle)
    for got, want in zip(actual, expected):
        if got[1:4] != want[1:4]:
            raise Mismatch('PWM_TRACE', f'cycle {want[0]} expected PWM/event {want[1:4]}, got {got[1:4]}')
        if got[4:] != want[4:]:
            sample_cycle = want[0] - CONVERT
            raise Mismatch('ADC_CODE',
                f'cycle {want[0]} sample_cycle={sample_cycle} expected {want[4:]}, got {got[4:]}')
    return actual


def deck_for(pwm, resistance, capacitance):
    points = [(0.0, 0.0)]
    old = 0
    for cycle, state in enumerate(pwm):
        if old != state:
            points.append((cycle * CYCLE_S, old * SUPPLY_V))
            points.append((cycle * CYCLE_S + RAMP_S, state * SUPPLY_V))
            old = state
    # A continuation per knot keeps the netlist readable and avoids very long lines.
    source = '\n'.join(f'+ {time:.17g} {value:.17g}' for time, value in points)
    return (
        'PWM drives a linear RC\nVdrive drive 0 PWL(\n' + source + '\n+ )\n'
        f'Rplant drive filtered {resistance}\nCplant filtered 0 {capacitance:.17g} ic=0\n'
        '.options reltol=1e-8 abstol=1e-12 method=gear maxord=2\n'
        '.save v(filtered)\n.end\n'
    )


def analytic_voltage(pwm, tau):
    """Evaluate v at each digital edge before its PWM update."""
    voltage = previous = 0.0
    for state in pwm:
        yield voltage
        source = SUPPLY_V * state
        if source != previous:
            ratio = RAMP_S / tau
            alpha = -expm1(-ratio)
            # Exact solution for a linear ramp between the two drive levels.
            voltage += (previous-voltage)*alpha + (source-previous)*(1-alpha/ratio)
            interval = CYCLE_S - RAMP_S
        else:
            interval = CYCLE_S
        voltage += (source-voltage) * -expm1(-interval/tau)
        previous = source


def check_voltage(path, expected, tau):
    trace = read_csv(path, ['cycle', 'time_s', 'voltage_v'], len(expected), float)
    reference = list(analytic_voltage(expected, tau))
    errors = []
    for cycle, ((_, time, voltage), wanted) in enumerate(zip(trace, reference)):
        if not isfinite(voltage) or not isfinite(time) or abs(time-cycle*CYCLE_S) > 1e-12:
            raise ValueError(f'invalid SPICE sample at cycle {cycle}')
        error = abs(voltage-wanted)
        if error > VOLTAGE_TOLERANCE:
            raise Mismatch('ANALOG_RC',
                f'cycle {cycle} expected {wanted:.9f} V, got {voltage:.9f} V, error {error:.6g} V')
        if not -VOLTAGE_TOLERANCE <= voltage <= SUPPLY_V+VOLTAGE_TOLERANCE:
            raise ValueError(f'voltage outside supply range at cycle {cycle}')
        errors.append(error)
    voltages = [row[2] for row in trace]
    deltas = [b-a for a, b in zip(voltages, voltages[1:])]
    if not (max(deltas) > 0.01 and min(deltas) < -0.01):
        raise ValueError('test did not observe both charge and discharge')
    return voltages, reference, max(errors)

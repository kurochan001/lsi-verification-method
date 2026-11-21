#!/usr/bin/env python3
"""Fixed-point biquad: bit-exact arithmetic, overflow and limit-cycle behaviour, and a
frequency-response check with a derived tolerance."""
import importlib.util
import json
from pathlib import Path
import random
import re
import sys
import xml.etree.ElementTree as ET

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('iir_biquad_model', HERE / 'model.py')
M = importlib.util.module_from_spec(spec)
spec.loader.exec_module(M)

NAME = 'local-iir-biquad'
TOP = 'iir_biquad_tb'
CONFIGS = {
    'sat-nearest': dict(FRAC=14, ROUND=M.NEAREST, SAT=1),
    'wrap-nearest': dict(FRAC=14, ROUND=M.NEAREST, SAT=0),
    'sat-floor': dict(FRAC=14, ROUND=M.FLOOR, SAT=1),
    'sat-zero': dict(FRAC=14, ROUND=M.TOWARD_ZERO, SAT=1),
    'coarse': dict(FRAC=6, ROUND=M.NEAREST, SAT=1),
}
ITERATIONS = {'smoke': 80, 'nightly': 600}
SOURCES = [HERE / 'rtl/iir_biquad.sv', HERE / 'tb/iir_biquad_tb.sv']
EXTRA_INPUTS = [HERE / 'model.py']
MUTANTS = 9
# The check that reports each mutant on the fixed scenario. 7 and 8 change nothing in a
# configuration that already wraps or already floors; there they are run as equivalents.
LABELS = {1: 'IIR_DATA', 2: 'IIR_DATA', 3: 'IIR_FLAG', 4: 'IIR_DATA', 5: 'IIR_DATA', 6: 'IIR_CONTROL',
          7: 'IIR_DATA', 8: 'IIR_DATA', 9: 'IIR_DATA'}

# The filter the frequency response is specified for, and the one used to provoke the
# nonlinear effects (poles at radius 0.96: little damping).
LOWPASS = M.design_lowpass(0.1, 0.7071)
RESONANT = M.design_lowpass(0.2, 12)
IMPULSE_AMPLITUDE = 1 << 20
IMPULSE_LENGTH = 128
GRID_POINTS = 64
DESIGN_TOLERANCE = 0.01          # specification of this teaching design: |H - H_design| on the grid
LIMIT_BURST = [1000, -700, 300]
LIMIT_ZEROS, OVERFLOW_ZEROS, TAIL = 300, 520, 64
OVERFLOW_BURST = [4194303, -8388608, -4194304, 0]
LARGE = 1 << 20
# What the integer model shows in the last TAIL samples of the two zero-input windows.
# Pinned: a change of arithmetic that alters the phenomenon must be noticed, not absorbed.
PHENOMENA = {
    'sat-nearest': dict(limit_tail_nonzero=51, osc_tail_large=0),
    'wrap-nearest': dict(limit_tail_nonzero=51, osc_tail_large=64),
    'sat-floor': dict(limit_tail_nonzero=64, osc_tail_large=0),
    'sat-zero': dict(limit_tail_nonzero=0, osc_tail_large=0),
    'coarse': dict(limit_tail_nonzero=51, osc_tail_large=0),
}
# Whether the quantized low-pass meets DESIGN_TOLERANCE. Six fractional bits do not.
DESIGN_MET = {'sat-nearest': True, 'wrap-nearest': True, 'sat-floor': True, 'sat-zero': True, 'coarse': False}
BLOCKED = 0x5a5a5a  # offered while the output is stalled; must never enter the filter
LAST_ARGS = None


def signed24(value):
    return M.wrap(value, 24)


class Oracle:
    """Cycle model of the handshake around the integer filter. One call is one clock."""

    def __init__(self, parameters):
        self.filt = M.Biquad(parameters['FRAC'], parameters['ROUND'], bool(parameters['SAT']))
        self.out = None

    def reset(self):
        self.filt.coefficients = [0, 0, 0, 0, 0]
        self.filt.clear()
        self.out = None

    def step(self, rst, clear, we, addr, data, valid, x, ready, tag):
        if not rst:
            self.reset()
        in_ready = int(not clear and (self.out is None or bool(ready)))
        y, high, low, phase = self.out or (0, 0, 0, 0)
        row = [rst, clear, we, addr, data & 0xffff, valid, x & 0xffffff, ready, phase,
               in_ready, int(self.out is not None), y & 0xffffff, high, low]
        if rst:
            if clear:
                self.filt.clear()
                self.out = None
            elif valid and in_ready:
                self.out = (*self.filt.step(signed24(x)), tag)
            elif self.out is not None and ready:
                self.out = None
            if we and addr < 5:
                self.filt.coefficients[addr] = M.wrap(data, 16)
        return row


class Plan:
    def __init__(self, parameters):
        self.model = Oracle(parameters)
        self.frac = parameters['FRAC']
        self.rows = []

    def cycle(self, rst=1, clear=0, we=0, addr=0, data=0, valid=0, x=0, ready=1, tag=0):
        self.rows.append(self.model.step(rst, clear, we, addr, data, valid, x, ready, tag))

    def load(self, coefficients):
        for addr, value in enumerate(coefficients):
            self.cycle(we=1, addr=addr, data=value)

    def sample(self, x, stall=0, gap=0, tag=0):
        """gap idle clocks, then the sample; then the sink refuses the result for stall clocks
        while another sample is offered and must wait."""
        for _ in range(gap):
            self.cycle()
        self.cycle(valid=1, x=x, tag=tag)
        for _ in range(stall):
            self.cycle(valid=1, x=BLOCKED, ready=0)

    def run(self, samples, tag=0):
        for x in samples:
            self.sample(x, tag=tag)

    def flush(self):
        self.cycle()
        self.cycle()


def fixed(real, frac):
    return M.to_fixed(real, frac)


def boundary_vectors(parameters):
    frac = parameters['FRAC']
    one, half = 1 << frac, 1 << (frac - 1)
    p = Plan(parameters)
    p.cycle(rst=0)
    p.cycle(rst=0)
    # Unity gain: the largest and smallest sample pass exactly, without an overflow flag.
    p.load([one, 0, 0, 0, 0])
    p.sample(0, gap=2)
    p.sample(M.MAX, stall=2)
    p.sample(M.MIN, gap=1, stall=1)
    # One past each end: MAX+1 and MIN-1.
    p.load([one, one, 0, 0, 0])
    p.run([1, M.MAX, -1, M.MIN, 0])
    p.cycle()
    p.cycle(clear=1)
    # Half an LSB either side of zero, and one and a half: the three rounding modes differ here.
    p.load([half, 0, 0, 0, 0])
    p.run([1, -1, 3, -3])
    p.sample(-5, stall=1)
    # Addresses 5 and 7 are not coefficients. Nothing may change, in particular not b1 or a1.
    p.cycle(we=1, addr=5, data=0x7fff)
    p.cycle(we=1, addr=7, data=0x7fff)
    p.run([5, 7])
    p.cycle()
    p.cycle(clear=1)
    # Feedback. Back-to-back samples, a stalled sink with a waiting sample, an idle source.
    resonant = fixed(RESONANT, frac)
    p.load(resonant)
    burst = [100000, -50000, 25000, 0, 0, 0, -3, 0, 0]
    p.run(burst)
    p.sample(1234, stall=3)
    p.run([0, 0, 4321])
    p.sample(0, gap=2)
    # Clear with history present: the same burst must then give the same first outputs.
    p.cycle(clear=1, valid=1, x=123)
    p.run(burst[:6])
    # A coefficient changed while the state is non-zero, once alone and once with a sample.
    p.cycle(we=1, addr=4, data=resonant[4] - 100)
    p.run([0, 0, 777])
    p.cycle(we=1, addr=0, data=resonant[0] + 50, valid=1, x=1000)
    p.run([1000, 0, 0])
    # Reset while a result waits: the result is dropped and the coefficients return to zero.
    p.sample(555, stall=2)
    p.cycle(rst=0, ready=0)
    p.cycle()
    p.run([77, 78])
    p.flush()
    return p.rows


def impulse_vectors(parameters):
    p = Plan(parameters)
    p.cycle(rst=0)
    p.load(fixed(LOWPASS, parameters['FRAC']))
    for n in range(IMPULSE_LENGTH):
        p.sample(IMPULSE_AMPLITUDE if n == 0 else 0, stall=1 if n % 17 == 5 else 0, tag=3)
    p.flush()
    return p.rows


def window_vectors(parameters, burst, zeros, tag):
    p = Plan(parameters)
    p.cycle(rst=0)
    p.load(fixed(RESONANT, parameters['FRAC']))
    p.run(burst)
    p.run([0] * (zeros - TAIL))
    p.run([0] * TAIL, tag=tag)
    p.flush()
    return p.rows


def limit_vectors(parameters):
    return window_vectors(parameters, LIMIT_BURST, LIMIT_ZEROS, 1)


def overflow_vectors(parameters):
    return window_vectors(parameters, OVERFLOW_BURST, OVERFLOW_ZEROS, 2)


def random_vectors(seed, iterations, parameters):
    rng = random.Random(seed)
    frac = parameters['FRAC']
    p = Plan(parameters)
    p.cycle(rst=0)

    def coefficients():
        if rng.random() < 0.5:
            return fixed(M.design_lowpass(rng.uniform(0.02, 0.45), rng.uniform(0.5, 15)), frac)
        span = min(32767, 2 << frac)
        return [rng.randint(-span, span) for _ in range(5)]

    def value():
        kind = rng.randrange(6)
        if kind == 0:
            return rng.choice([M.MAX, M.MIN, M.MAX - 1, M.MIN + 1])
        if kind == 1:
            return rng.randint(-4, 4)
        if kind == 2:
            return 0
        return rng.randint(M.MIN, M.MAX)

    p.load(coefficients())
    for _ in range(iterations):
        event = rng.randrange(40)
        if event == 0:
            p.cycle(clear=1, valid=rng.randrange(2), x=value())
        elif event == 1:
            p.load(coefficients())
        elif event == 2:
            p.cycle(we=1, addr=rng.randrange(8), data=rng.randrange(1 << 16), valid=rng.randrange(2), x=value())
        elif event == 3:
            p.cycle(rst=0, ready=rng.randrange(2))
            p.load(coefficients())
        p.sample(value(), stall=rng.choice([0, 0, 0, 1, 3]), gap=rng.choice([0, 0, 0, 1, 2]))
    p.flush()
    return p.rows


def counts(rows):
    done = [r for r in rows if r[0] and r[10] and r[7]]
    return dict(accepted=sum(bool(r[0] and r[5] and r[9]) for r in rows), completed=len(done),
                overflow_pos=sum(r[12] for r in done), overflow_neg=sum(r[13] for r in done),
                limit_tail_nonzero=sum(r[8] == 1 and r[11] != 0 for r in done),
                osc_tail_large=sum(r[8] == 2 and abs(signed24(r[11])) >= LARGE for r in done))


def phenomena(parameters):
    return dict(limit_tail_nonzero=counts(limit_vectors(parameters))['limit_tail_nonzero'],
                osc_tail_large=counts(overflow_vectors(parameters))['osc_tail_large'])


def equivalent(mutation, parameters):
    """True when the mutant cannot change this configuration."""
    return (mutation == 7 and not parameters['SAT']) or (mutation == 8 and parameters['ROUND'] == M.FLOOR)


def configuration_name(parameters):
    return next(name for name, value in CONFIGS.items() if value == parameters)


def make_cases(args, parameters):
    global LAST_ARGS
    LAST_ARGS = args
    name = configuration_name(parameters)
    seen = phenomena(parameters)
    if seen != PHENOMENA[name]:
        raise ValueError(f'{name}: the model no longer shows the pinned behaviour: {seen}')
    baseline = boundary_vectors(parameters)
    cases = [dict(id='boundaries', vectors=baseline),
             dict(id='impulse', vectors=impulse_vectors(parameters)),
             dict(id='limit-cycle', vectors=limit_vectors(parameters)),
             dict(id='overflow', vectors=overflow_vectors(parameters))]
    for seed in range(args.seed, args.seed + (3 if args.profile == 'nightly' else 1)):
        cases.append(dict(id=f'random-seed{seed}', vectors=random_vectors(seed, args.iterations, parameters)))
    for case in cases:
        case.update(mutation=args.demo_bug, category='functional', expected_failure=None)
    for mutation in range(1, MUTANTS + 1):
        if equivalent(mutation, parameters):
            cases.append(dict(id=f'equivalent-mutation{mutation}', vectors=baseline, mutation=mutation,
                              category='diagnostic', expected_failure=None))
        else:
            cases.append(dict(id=f'detect-mutation{mutation}', vectors=baseline, mutation=mutation,
                              category='mutation', expected_failure=LABELS[mutation]))
    for case in cases:
        case['counts'] = counts(case['vectors'])
    return cases


# ---- frequency response, judged from the simulated impulse response --------------------------

def frequency_report(samples, parameters, design_met=True):
    """samples: the IMPULSE_LENGTH outputs read from the simulation log."""
    frac, rounding = parameters['FRAC'], parameters['ROUND']
    quantized = fixed(LOWPASS, frac)
    real = M.to_real(quantized, frac)
    bound = M.measurement_bound(quantized, frac, rounding, IMPULSE_AMPLITUDE, IMPULSE_LENGTH)
    rows = []
    for omega in M.grid(GRID_POINTS):
        measured = M.dft(samples, omega) / IMPULSE_AMPLITUDE
        rows.append(dict(omega=omega, measured=abs(measured),
                         measurement_error=abs(measured - M.response(real, omega)),
                         design_error=abs(M.response(real, omega) - M.response(LOWPASS, omega)),
                         coefficient_bound=M.coefficient_bound(LOWPASS, quantized, frac, omega)))
    measurement_error = max(r['measurement_error'] for r in rows)
    design_error = max(r['design_error'] for r in rows)
    coefficient_bound = max(r['coefficient_bound'] for r in rows)
    guaranteed = coefficient_bound <= DESIGN_TOLERANCE
    problems = []
    if len(samples) != IMPULSE_LENGTH:
        problems.append('impulse response has the wrong length')
    if measurement_error > bound['total']:
        problems.append('measured response is outside the rounding bound')
    if any(r['design_error'] > r['coefficient_bound'] for r in rows):
        problems.append('coefficient rounding bound violated')
    if guaranteed and design_error > DESIGN_TOLERANCE:
        problems.append('design tolerance violated although the bound guarantees it')
    if (design_error <= DESIGN_TOLERANCE) != design_met:
        problems.append('design tolerance result differs from the pinned expectation')
    return dict(success=not problems, problems=problems, coefficients=quantized,
                measurement_error=measurement_error, measurement_bound=bound,
                design_error=design_error, coefficient_bound=coefficient_bound,
                design_tolerance=DESIGN_TOLERANCE, design_guaranteed=guaranteed,
                design_within_tolerance=design_error <= DESIGN_TOLERANCE, grid=rows)


def impulse_samples(log):
    return [int(v) for v in re.findall(r'^OBS IIR n=\d+ phase=3 y=(-?\d+)$', log, re.M)]


def judge_frequency(out, configurations):
    """Adds one check per configuration to the evidence the shared runner wrote."""
    reports = {name: frequency_report(impulse_samples((out / f'{name}-impulse/simulation.log').read_text(errors='replace')),
                                      parameters, DESIGN_MET[name]) for name, parameters in configurations.items()}
    (out / 'frequency-response.json').write_text(json.dumps(reports, indent=2) + '\n')
    success = all(r['success'] for r in reports.values())
    summary = json.loads((out / 'summary.json').read_text())
    summary['frequency_response'] = {name: dict(success=r['success'], measurement_error=r['measurement_error'],
                                               measurement_bound=r['measurement_bound']['total'],
                                               design_error=r['design_error'],
                                               design_within_tolerance=r['design_within_tolerance'])
                                    for name, r in reports.items()}
    summary['success'] = bool(summary['success'] and success)
    (out / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')
    tree = ET.parse(out / 'junit.xml')
    suite = tree.getroot()
    for old in [n for n in suite.findall('testcase') if n.get('classname') == 'local.' + NAME + '.tolerance']:
        suite.remove(old)  # judging the same evidence again replaces the earlier verdict
    for name, r in reports.items():
        node = ET.SubElement(suite, 'testcase', name=name + '-frequency-response', classname='local.' + NAME + '.tolerance')
        if not r['success']:
            ET.SubElement(node, 'failure', message='; '.join(r['problems'])).text = 'frequency-response.json'
        print(f"Frequency {name}: measured-vs-quantized {r['measurement_error']:.3e} (bound {r['measurement_bound']['total']:.3e}), "
              f"quantized-vs-design {r['design_error']:.3e} (tolerance {DESIGN_TOLERANCE}, "
              f"{'guaranteed' if r['design_guaranteed'] else 'not guaranteed'} by the coefficient bound)")
    suite.set('tests', str(len(suite.findall('testcase'))))
    suite.set('failures', str(len(suite.findall('testcase/failure'))))
    ET.indent(suite)
    tree.write(out / 'junit.xml', encoding='utf-8', xml_declaration=True)
    return success


def main():
    spec = importlib.util.spec_from_file_location('local_runner', HERE.parent / 'local-common/runner.py')
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)
    code = runner.main(sys.modules[__name__])
    if code != 0 or LAST_ARGS is None:
        return code
    names = CONFIGS if LAST_ARGS.configuration == 'all' else {LAST_ARGS.configuration: CONFIGS[LAST_ARGS.configuration]}
    try:
        success = judge_frequency(LAST_ARGS.out.resolve(), names)
    except (OSError, ValueError, KeyError) as exc:
        print('RUNNER_ERROR frequency response: ' + str(exc), file=sys.stderr)
        return 1
    print('Frequency response: ' + ('PASS' if success else 'FAIL'))
    return 0 if success else 1


if __name__ == '__main__':
    sys.exit(main())

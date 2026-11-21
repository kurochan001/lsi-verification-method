#!/usr/bin/env python3
"""Check a SAR ADC three ways: the control logic cycle by cycle, a real-number model of the
capacitor DAC against exact arithmetic, and that model against an ngspice solution of the same
network, including the clock periods at which the model stops being valid."""
import csv
import importlib.util
import json
import math
from pathlib import Path
import shutil
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


M = load('rnm_sar_model', HERE / 'model.py')
COMMON = load('memory_sim', HERE.parent / 'local-memory-common/sim.py')
N = load('ngspice_installation', ROOT / 'tools/ngspice.py')
E = COMMON.E
NAME = 'local-rnm-sar-adc'
TOP = 'sar_adc_tb'
SOURCES = [HERE / 'rtl/sar_logic.sv', HERE / 'tb/sar_cdac_rnm.sv', HERE / 'tb/sar_adc_tb.sv']
CONFIGS = {'b6': 6, 'b8': 8}
MUTANTS = {1: 'SAR_DAC', 2: 'SAR_READY', 3: 'SAR_DAC', 4: 'SAR_DAC', 5: 'SAR_READY',
           6: 'SAR_RESULT', 7: 'SAR_UNKNOWN'}
OPTIONS = dict(reltol=1e-6, steps=50, method='gear')
TIGHT = dict(reltol=1e-8, steps=2000, method='gear')
ANALOG_CASES = ('spice-slow', 'replay-slow', 'spice-mismatch', 'replay-mismatch', 'linearity',
                'settling-analytic', 'settling-sweep', 'spice-options', 'detect-model-weights',
                'detect-settling', 'detect-spice-error')
ANALOG_GOALS = {
    'spice-slow': ['model/vtop-within-tolerance', 'model/codes-agree', 'model/out-of-range-clamp'],
    'replay-slow': ['model/replay-consistent'],
    'linearity': ['linearity/no-missing-ideal', 'linearity/missing-with-mismatch',
                  'linearity/monotonic'],
    'settling-analytic': ['settling/analytic-sample', 'settling/analytic-trial'],
    'settling-sweep': ['settling/predicted-codes', 'settling/minimum-period',
                       'settling/fast-clock-only-in-spice'],
    'spice-options': ['spice/options-insensitive'],
}


def analog_inputs(bits, caps):
    """Inputs solved with ngspice.  The six-bit array takes the whole ramp; the eight-bit one
    takes one point per step and every eighth threshold pair, to keep the run short."""
    if bits <= 6:
        return M.ramp(caps) + M.edges(caps) + M.outside(bits)
    return M.ramp(caps)[::4] + M.edges(caps)[::8] + M.outside(bits)


def sweep_inputs(bits, caps):
    values = M.ramp(caps)
    return values[::max(1, len(values) // 64)]


def read_trace(path):
    with path.open(newline='') as stream:
        return [{k: int(v, 2) if k in ('ready', 'sample', 'busy', 'done', 'cmp') else int(v)
                 for k, v in row.items()} for row in csv.DictReader(stream)]


class Runner:
    def __init__(self, args, evidence, prefix):
        self.args, self.e, self.prefix = args, evidence, prefix
        self.sim = COMMON.Simulator(sys.modules[__name__], args, evidence.out)

    def digital(self, key, bits, timeline, cp_af, seed, mutation=0, expected=None, external=False):
        case = dict(id=key, seed=seed, checks=len(timeline.rows), mutation=mutation,
                    parameters=dict(BITS=bits, CMP_EXT=int(external)), expected_failure=expected,
                    text=timeline.text(cp_af))
        return self.sim.execute(case)

    def solve(self, key, jobs):
        base = self.e.out / key
        base.mkdir(parents=True, exist_ok=True)
        request, answer = base / 'request.json', base / 'solution.json'
        request.write_text(json.dumps(dict(jobs=jobs)))
        command = [sys.executable, str(HERE / 'solve.py'), str(self.prefix), str(request),
                   str(answer)]
        result = E.P.execute(command, base / 'ngspice.log', self.args.timeout, base)
        if result['error'] or result['returncode'] != 0 or not answer.is_file():
            raise M.Mismatch('SPICE_ERROR', 'ngspice run failed; see ' + str(base / 'ngspice.log'))
        return json.loads(answer.read_text())['results']

    def convert(self, key, bits, caps, inputs, period=M.SLOW_S, options=OPTIONS, broken=False):
        job = dict(kind='convert', circuit=M.circuit(bits, caps), options=options, period_s=period,
                   inputs_v=[v * 1e-6 for v in inputs], broken=broken)
        return M.check_solution(self.solve(key, [job])[0], bits, len(inputs))


def configuration(runner, name, bits, seeds):
    e, args = runner.e, runner.args
    caps, cp = M.nominal_caps(bits), M.parasitic(bits)
    weak = M.mismatched_caps(bits)
    hits = set()
    state = {}

    def digital_case(case, timeline, external=False):
        """A run that must pass; returns the trace or None."""
        key = f'{name}/{case}'
        result = runner.digital(key, bits, timeline, cp, args.seed, external=external)
        ok = result['status'] == 'pass'
        e.check(key, ok, dict(status=result['status'], message=result['message'],
                              rows=len(timeline.rows), conversions=len(timeline.conversions)))
        if not ok:
            return None
        hits.update(result['goals'])
        return read_trace(e.out / key / 'trace.csv')

    # 1. Control logic and real-number model against the exact expectation.
    fixed_inputs = M.ramp(caps) + M.edges(caps) + M.outside(bits)
    fixed = M.fixed_timeline(bits, caps, fixed_inputs)
    trace = digital_case('fixed', fixed)
    if trace is not None:
        hits.update(fixed.goals)
        if {code for _, _, code in fixed.conversions} == set(range(1 << bits)):
            hits.add('rnm/every-code')
        state['nominal'] = M.rnm_records(trace, fixed)
    for seed in seeds:
        line = M.random_timeline(bits, caps, seed, 60 if args.profile == 'smoke' else 400)
        key = f'{name}/random-seed{seed}'
        result = runner.digital(key, bits, line, cp, seed)
        e.check(key, result['status'] == 'pass', dict(status=result['status'],
                                                      message=result['message'], rows=len(line.rows)))
    weak_inputs = M.ramp(weak) + M.outside(bits)
    weak_line = M.fixed_timeline(bits, weak, weak_inputs)
    trace = digital_case('mismatch', weak_line)
    if trace is not None:
        state['weak'] = M.rnm_records(trace, weak_line)
    for mutation, label in MUTANTS.items():
        key = f'{name}/detect-mutation{mutation}'
        result = runner.digital(key, bits, fixed, cp, args.seed, mutation=mutation, expected=label)
        e.check(key, result['status'] == 'detected', dict(status=result['status'],
                                                          message=result['message'], expected=label))

    # 2. The same network in ngspice.
    def analog(case, body, expected=None):
        key = f'{name}/{case}'
        try:
            detail = body(key)
            ok = expected is None
            if ok:
                hits.update(ANALOG_GOALS.get(case, []))
            e.check(key, ok, dict(expected=expected, **detail))
        except M.Mismatch as exc:
            print(f'CHECK_FAIL {exc.label} {key}: {exc}', flush=True)
            e.check(key, exc.label == expected, dict(expected=expected, actual=exc.label,
                                                     detail=str(exc)))
        except (OSError, ValueError, KeyError, TypeError) as exc:
            e.check(key, False, dict(expected=expected, error=str(exc)))

    slow_inputs = analog_inputs(bits, caps)
    weak_analog = (M.ramp(weak) if bits <= 6 else M.ramp(weak)[::2]) + M.outside(bits)

    def spice_slow(key):
        solution = runner.convert(key, bits, caps, slow_inputs)
        state['slow'] = solution
        worst = M.compare_models(slow_inputs, solution, state['nominal'], caps)
        clamp = {vin: item['code'] for vin, item in zip(slow_inputs, solution) if vin in M.outside(bits)}
        if sorted(clamp.values()) != [0, (1 << bits) - 1]:
            raise M.Mismatch('MODEL_CODE', f'inputs beyond the rails gave {clamp}')
        return dict(inputs=len(slow_inputs), worst_top_difference_v=worst,
                    tolerance_v=M.VTOP_TOLERANCE_V, period_s=M.SLOW_S)

    def replay(inputs, cap_values, source):
        def body(key):
            solution = state[source]
            line = M.replay_timeline(bits, cap_values, inputs, [item['answers'] for item in solution])
            result = runner.digital(key, bits, line, cp, args.seed, external=True)
            if result['status'] != 'pass':
                raise ValueError(f"replay did not pass: {result['status']}: {result['message']}")
            rows = read_trace(e.out / key / 'trace.csv')
            for (accept, vin, _), item in zip(line.conversions, solution, strict=True):
                if rows[accept + 1 + bits]['result'] != item['code']:
                    raise M.Mismatch('MODEL_CODE', f'replayed logic and ngspice differ at {vin} uV')
            return dict(conversions=len(solution), rows=len(line.rows))
        return body

    def spice_mismatch(key):
        solution = runner.convert(key, bits, weak, weak_analog)
        state['weak-spice'] = solution
        worst = M.compare_models(weak_analog, solution, state['weak'], weak)
        return dict(inputs=len(weak_analog), worst_top_difference_v=worst)

    def linearity(key):
        base = runner.e.out / key
        base.mkdir(parents=True)
        report = {}
        for label, cap_values, inputs, source, records in (
                ('nominal', caps, slow_inputs, 'slow', 'nominal'),
                ('mismatch', weak, weak_analog, 'weak-spice', 'weak')):
            ramp = [v for v in inputs if 0 <= v <= M.VREF_UV]
            index = {v: i for i, v in enumerate(inputs)}
            exact = M.linearity([(v, M.exact_code(v, cap_values)) for v in ramp], bits)
            model = M.linearity([(v, state[records][v]['code']) for v in ramp], bits)
            spice = M.linearity([(v, state[source][index[v]]['code']) for v in ramp], bits)
            if not (exact['missing'] == model['missing'] == spice['missing']) or not (
                    exact['monotonic'] and model['monotonic'] and spice['monotonic']):
                raise M.Mismatch('LINEARITY', f'{label}: exact {exact["missing"]}, model '
                                              f'{model["missing"]}, ngspice {spice["missing"]}')
            report[label] = dict(points=len(ramp), missing=exact['missing'], monotonic=True)
        if report['nominal']['missing'] or not report['mismatch']['missing']:
            raise M.Mismatch('LINEARITY', f'unexpected missing codes: {report}')
        E.P.write_json(base / 'linearity.json', report)
        return report

    total_f, cp_f = sum(caps) * 1e-18, cp * 1e-18
    minimum = M.minimum_period(bits, total_f, cp_f)

    def settling_analytic(key):
        vin = 0.7
        job = dict(kind='waveform', circuit=M.circuit(bits, caps), options=TIGHT,
                   period_s=M.SLOW_S, inputs_v=[vin])
        wave = runner.solve(key, [job])[0]
        sample, trial = wave['sample'], wave['trial']
        values = [*sample['time'], *sample['top'], *trial['time'], *trial['top'], wave['start_top']]
        if len(sample['time']) < 100 or len(trial['time']) < 100 or not all(
                type(v) is float and math.isfinite(v) for v in values):
            raise ValueError('waveform is incomplete or not finite')
        worst_sample = max(abs(v - M.sampling_top(t, vin, total_f, cp_f))
                           for t, v in zip(sample['time'], sample['top'], strict=True))
        final = M.ideal_top(round(vin * 1e6), 1 << (bits - 1), caps, cp)
        tau = M.trial_tau(total_f, cp_f)
        worst_trial = max(abs(v - (final + (wave['start_top'] - final) * math.exp(-t / tau)))
                          for t, v in zip(trial['time'], trial['top'], strict=True))
        if max(worst_sample, worst_trial) > M.ANALYTIC_TOLERANCE_V:
            raise M.Mismatch('SPICE_ANALYTIC', f'sample {worst_sample:.3g} V, trial {worst_trial:.3g} V')
        if max(map(abs, sample['top'])) < 0.05:
            raise ValueError('sampling waveform has no visible transient to compare')
        poles = M.sampling_poles(total_f, cp_f)
        return dict(worst_sample_v=worst_sample, worst_trial_v=worst_trial,
                    tolerance_v=M.ANALYTIC_TOLERANCE_V, sample_poles_per_s=poles[:2],
                    trial_tau_s=tau, points=[len(sample['time']), len(trial['time'])])

    def settling_sweep(key):
        inputs = sweep_inputs(bits, caps)
        factors = M.SWEEP_NIGHTLY if args.profile == 'nightly' else M.SWEEP_SMOKE
        periods = [M.FAST_S, *[f * minimum for f in factors]]
        jobs = [dict(kind='convert', circuit=M.circuit(bits, caps), options=OPTIONS, period_s=p,
                     inputs_v=[v * 1e-6 for v in inputs]) for p in periods]
        solutions = runner.solve(key, jobs)
        table = []
        for period, solution in zip(periods, solutions, strict=True):
            M.check_solution(solution, bits, len(inputs))
            shortfall = M.sampling_shortfall(period, total_f, cp_f)
            wrong = predicted = 0
            for vin, item in zip(inputs, solution):
                wrong += item['code'] != M.exact_code(vin, caps)
                expected = M.predicted_code(vin, caps, shortfall)
                if expected is not None:
                    predicted += 1
                    if item['code'] != expected:
                        raise M.Mismatch('SPICE_ANALYTIC', f'period {period:.3g} s, input {vin} uV: '
                                                           f'ngspice {item["code"]}, formula {expected}')
            table.append(dict(period_s=period, period_over_minimum=period / minimum,
                              shortfall=shortfall, wrong_codes=wrong, predicted=predicted,
                              inputs=len(inputs)))
            if period >= 1.05 * minimum and wrong:
                raise M.Mismatch('MODEL_CODE', f'{wrong} codes differ at {period:.3g} s, above the minimum')
            if predicted < len(inputs) // 2:
                raise ValueError('too few inputs can be predicted to judge the formula')
        state['fast'] = (inputs, solutions[0])
        if table[0]['wrong_codes'] == 0 or not any(
                row['wrong_codes'] for row in table if row['period_over_minimum'] <= 0.75):
            raise ValueError('the short periods did not disturb any code')
        E.P.write_json(e.out / key / 'validity.json', dict(minimum_period_s=minimum, sweep=table))
        return dict(minimum_period_s=minimum, sweep=table)

    def spice_options(key):
        inputs = sweep_inputs(bits, caps)
        variants = [OPTIONS, dict(reltol=1e-4, steps=50, method='gear'),
                    dict(reltol=1e-6, steps=100, method='trap')]
        jobs = [dict(kind='convert', circuit=M.circuit(bits, caps), options=o, period_s=M.SLOW_S,
                     inputs_v=[v * 1e-6 for v in inputs]) for o in variants]
        solutions = [M.check_solution(s, bits, len(inputs)) for s in runner.solve(key, jobs)]
        worst = 0.0
        for other in solutions[1:]:
            for a, b in zip(solutions[0], other, strict=True):
                if a['code'] != b['code']:
                    raise M.Mismatch('SPICE_OPTIONS', 'a solver setting changed a code')
                worst = max(worst, max(abs(x - y) for x, y in zip(a['tops'], b['tops'])))
        if worst > M.VTOP_TOLERANCE_V:
            raise M.Mismatch('SPICE_OPTIONS', f'solver settings move the top plate by {worst:.3g} V')
        return dict(variants=variants, worst_top_difference_v=worst, inputs=len(inputs))

    def detect_model_weights(key):
        # A model that was not given the mismatched array must be told apart from ngspice.
        solution = state['weak-spice']
        inputs = [v for v in weak_analog if v in state['nominal']]
        chosen = [solution[weak_analog.index(v)] for v in inputs]
        M.compare_models(inputs, chosen, state['nominal'], caps)
        return dict(inputs=len(inputs))

    def detect_settling(key):
        # The real-number model has passed at any clock; ngspice at the short period has not.
        inputs, solution = state['fast']
        differing = [vin for vin, item in zip(inputs, solution)
                     if item['code'] != state['nominal'][vin]['code']]
        if differing:
            raise M.Mismatch('ANALOG_SETTLING', f'{len(differing)} of {len(inputs)} codes differ '
                                                f'from the model at {M.FAST_S:.3g} s')
        return dict(inputs=len(inputs))

    def detect_spice_error(key):
        runner.convert(key, bits, caps, slow_inputs[:2], broken=True)
        return {}

    analog('spice-slow', spice_slow)
    analog('replay-slow', replay(slow_inputs, caps, 'slow'))
    analog('spice-mismatch', spice_mismatch)
    analog('replay-mismatch', replay(weak_analog, weak, 'weak-spice'))
    analog('linearity', linearity)
    analog('settling-analytic', settling_analytic)
    analog('settling-sweep', settling_sweep)
    analog('spice-options', spice_options)
    analog('detect-model-weights', detect_model_weights, expected='MODEL_VTOP')
    analog('detect-settling', detect_settling, expected='ANALOG_SETTLING')
    analog('detect-spice-error', detect_spice_error, expected='SPICE_ERROR')
    return hits


def plan_ids(profile, seed):
    seeds = list(range(seed, seed + (3 if profile == 'nightly' else 1)))
    ids = ['toolchain', 'ngspice-installation']
    for name in CONFIGS:
        ids += [f'{name}/fixed', *[f'{name}/random-seed{s}' for s in seeds], f'{name}/mismatch',
                *[f'{name}/detect-mutation{m}' for m in MUTANTS],
                *[f'{name}/{case}' for case in ANALOG_CASES], f'{name}/coverage']
    return ids + ['source-freshness'], seeds


def run(args):
    requirements = HERE / 'requirements.json'
    _, goals = E.C.catalog(requirements)
    ids, seeds = plan_ids(args.profile, args.seed)
    sources = [Path(__file__), Path(M.__file__), Path(COMMON.__file__), Path(N.__file__), N.CONFIG,
               ROOT / N.spec()['patch']['file'], *SOURCES, HERE / 'solve.py', requirements]
    plan = dict(configurations=CONFIGS, mutants=MUTANTS, analog_cases=ANALOG_CASES,
                vref_uv=M.VREF_UV, unit_af=M.UNIT_AF, tau_s=M.TAU_S, ron_ohm=M.RON_OHM,
                slow_period_s=M.SLOW_S, fast_period_s=M.FAST_S, options=OPTIONS, seeds=seeds,
                vtop_tolerance_v=M.VTOP_TOLERANCE_V, analytic_tolerance_v=M.ANALYTIC_TOLERANCE_V)
    e = E.Evidence(NAME, args, sources, plan, ids)
    tools = {n: E.P.execute([getattr(args, n), '-V'], e.out / (n + '-version.log'), args.timeout, e.out)
             for n in ('iverilog', 'vvp')}
    e.check('toolchain', all(not r['error'] and r['returncode'] == 0 for r in tools.values()), tools)
    prefix_log = e.out / 'ngspice-prefix.log'
    probe = E.P.execute([args.ngspice_config, '--prefix'], prefix_log, args.timeout, e.out)
    if probe['error'] or probe['returncode'] != 0:
        raise ValueError('ngspice configuration unavailable; run tools/setup_ngspice.py')
    prefix = Path(prefix_log.read_text().strip()).resolve()
    snapshot = N.snapshot(prefix)
    E.P.write_json(e.out / 'ngspice-source.json', snapshot)
    probe = N.probe(prefix)
    e.check('ngspice-installation', probe['success'], probe)
    runner = Runner(args, e, prefix)
    for name, bits in CONFIGS.items():
        hits = configuration(runner, name, bits, seeds)
        e.check(name + '/coverage', goals <= hits, dict(hit=sorted(hits), missing=sorted(goals - hits)))
    frozen = json.loads((e.out / 'manifest.json').read_text())['source_sha256']
    changed = [name for name, sha in frozen.items() if N.digest(ROOT / name) != sha]
    N.verify(snapshot)
    e.check('source-freshness', not changed, changed)
    return e.finish()


def main():
    parser = E.parser(__doc__, NAME)
    parser.set_defaults(timeout=60)
    parser.add_argument('--waves', action='store_true')
    parser.add_argument('--ngspice-config', default='lsi-ngspice-config')
    args = parser.parse_args()
    E.validate(parser, args)
    config_command = shutil.which(args.ngspice_config)
    if config_command:
        args.ngspice_config = str(Path(config_command).absolute())
    try:
        return run(args)
    except (OSError, ValueError, TypeError, KeyError) as exc:
        print('RUNNER_ERROR', exc, file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())

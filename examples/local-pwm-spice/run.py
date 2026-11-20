#!/usr/bin/env python3
"""Replay sampled ngspice RC voltages into the PWM-driven ADC example."""
import csv
import importlib.util
import json
from pathlib import Path
import shutil
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
ADC = HERE.parent / 'local-adc-conversion'
PWM = HERE.parent / 'local-pwm-adc'


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


MODEL = load('pwm_spice_model', HERE / 'model.py')
ORACLE = load('adc_oracle', ADC / 'model.py').AdcOracle
COMMON = load('memory_sim', HERE.parent / 'local-memory-common/sim.py')
N = load('ngspice_installation', ROOT / 'tools/ngspice.py')
E = COMMON.E
TOP = 'pwm_spice_tb'
SOURCES = [PWM / 'rtl/pwm_adc_trigger.sv', ADC / 'rtl/adc_capture.sv', HERE / 'tb/pwm_spice_tb.sv']
CONFIGS = {'rc47us': 47e-9, 'rc100us': 100e-9}
RESISTANCE = 1000


def digital(sim, settings, vin_uv, key, seed):
    rows = [' '.join(format(value, 'x') for value in [*row, voltage & 0xffffffff])
            for row, voltage in zip(MODEL.stimuli(settings), vin_uv, strict=True)]
    result = sim.execute(dict(id=key, seed=seed, checks=len(rows), parameters={},
                              text='\n'.join(rows)+'\n'))
    if result['status'] != 'pass':
        raise ValueError(f"{key}: {result['status']}: {result['message']}")
    return sim.out / key / 'trace.csv'


def execute(sim, args, prefix, name, capacitance, settings, seed, fault):
    count = 1 + MODEL.PERIOD * len(settings)
    baseline_input = [0] * count
    pwm_file = digital(sim, settings, baseline_input, name+'/pwm', seed)
    pwm = [row[1] for row in MODEL.check_digital(pwm_file, settings, baseline_input, ORACLE)]
    base = sim.out / name
    deck = base / 'plant.cir'
    actual_resistance = RESISTANCE * (2 if fault == 'wrong-rc' else 1)
    deck.write_text(MODEL.deck_for(pwm, actual_resistance, capacitance))
    analog = base / 'ngspice.csv'
    command = [sys.executable, str(HERE/'solve.py'), str(prefix), str(deck), str(count),
               str(MODEL.CYCLE_S), str(analog)]
    solver = E.P.execute(command, base/'ngspice.log', args.timeout, base)
    if solver['error'] or solver['returncode'] != 0:
        raise ValueError('ngspice execution failed; see ngspice.log')
    voltages, reference, error = MODEL.check_voltage(analog, MODEL.expected_pwm(settings),
                                                     RESISTANCE * capacitance)
    measured_uv = [round(v*1e6) for v in voltages]
    drive_uv = [measured_uv[0], *measured_uv[:-1]] if fault == 'early-adc' else measured_uv
    replay_file = digital(sim, settings, drive_uv, name+'/adc', seed)
    replay = MODEL.check_digital(replay_file, settings, measured_uv, ORACLE)
    converted = [(row[0], row[-1]) for row in replay if row[-2]]
    if len(converted) != len(settings):
        raise ValueError(f'expected one conversion per carrier period, got {len(converted)}')

    with (base/'comparison.csv').open('w', newline='') as stream:
        writer = csv.writer(stream)
        writer.writerow(['cycle', 'time_s', 'pwm', 'trigger', 'sample', 'adc_valid', 'adc_code',
                         'ngspice_v', 'analytic_v', 'replay_uv'])
        samples = {cycle - MODEL.CONVERT for cycle, _ in converted}
        for row, voltage, ideal, uv in zip(replay, voltages, reference, drive_uv, strict=True):
            cycle, carrier, trigger = row[:3]
            writer.writerow([cycle, cycle*MODEL.CYCLE_S, carrier, trigger, int(cycle in samples),
                             row[-2], row[-1], voltage, ideal, uv])
    return dict(cycles=count, conversions=len(converted), max_error_v=error,
                last_code=converted[-1][1], last_capture_cycle=converted[-1][0]-MODEL.CONVERT,
                pwm=pwm, goal_hits=['analog/reference', 'analog/charge-discharge',
                                    'adc/one-per-period', 'pwm/trigger'])


def run(args):
    seeds = range(args.seed, args.seed + (3 if args.profile == 'nightly' else 1))
    variants = [('early', args.seed, None), ('late', args.seed, None)]
    variants += [(f'duty-step-{seed}', seed, None) for seed in seeds]
    variants += [('detect-wrong-rc', args.seed, 'wrong-rc'),
                 ('detect-early-adc', args.seed, 'early-adc')]
    requirements = HERE / 'requirements.json'
    _, goals = E.C.catalog(requirements)
    ids = ['toolchain', 'ngspice-installation']
    case_names = [variant[0] for variant in variants]
    ids += [f'{cfg}/{case}' for cfg in CONFIGS for case in [*case_names, 'coverage']]
    ids += ['source-freshness']
    sources = [Path(__file__), Path(MODEL.__file__), Path(COMMON.__file__),
               Path(N.__file__), N.CONFIG, ROOT/N.spec()['patch']['file'], *SOURCES,
               ADC/'model.py', HERE/'solve.py', requirements]
    periods = 24 if args.profile == 'nightly' else 12
    plan = dict(configurations=CONFIGS, resistance_ohm=RESISTANCE, cycle_s=MODEL.CYCLE_S,
                periods=periods, scenarios=[
                    dict(name=name, seed=seed, fault=fault) for name, seed, fault in variants])
    e = E.Evidence('local-pwm-spice', args, sources, plan, ids)
    tools = {n: E.P.execute([getattr(args, n), '-V'], e.out/(n+'-version.log'), args.timeout, e.out)
             for n in ('iverilog', 'vvp')}
    e.check('toolchain', all(not r['error'] and r['returncode']==0 for r in tools.values()), tools)
    prefix_log = e.out / 'ngspice-prefix.log'
    probe = E.P.execute([args.ngspice_config, '--prefix'], prefix_log, args.timeout, e.out)
    if probe['error'] or probe['returncode'] != 0:
        raise ValueError('ngspice configuration unavailable; run tools/setup_ngspice.py')
    prefix = Path(prefix_log.read_text().strip()).resolve()
    snapshot = N.snapshot(prefix)
    E.P.write_json(e.out/'ngspice-source.json', snapshot)
    probe = N.probe(prefix)
    e.check('ngspice-installation', probe['success'], probe)
    sim = COMMON.Simulator(sys.modules[__name__], args, e.out)
    records = {}
    for config, capacitance in CONFIGS.items():
        hits = set()
        for name, seed, fault in variants:
            expected = {'wrong-rc': 'ANALOG_RC', 'early-adc': 'ADC_CODE'}.get(fault)
            key = f'{config}/{name}'
            settings = MODEL.schedule('early' if fault else name, seed, periods)
            try:
                result = execute(sim, args, prefix, key, capacitance, settings, seed, fault)
                records[key] = result
                if not expected:
                    hits.update(result['goal_hits'])
                    if name.startswith('duty-step') and len({d for d, _ in settings}) > 1:
                        hits.add('pwm/duty-step')
                e.check(key, expected is None, dict(case=key, expected=expected, **result))
            except MODEL.Mismatch as exc:
                print(f'CHECK_FAIL {exc.label} {key} seed={seed}: {exc}', flush=True)
                e.check(key, exc.label == expected, dict(expected=expected, actual=exc.label, detail=str(exc)))
            except (OSError, ValueError) as exc:
                e.check(key, False, dict(expected=expected, error=str(exc)))
        early, late = (records.get(f'{config}/{name}') for name in ('early', 'late'))
        phase = {}
        if early and late and early['pwm'] == late['pwm']:
            phase = dict(early_code=early['last_code'], late_code=late['last_code'],
                         early_capture_cycle=early['last_capture_cycle'],
                         late_capture_cycle=late['last_capture_cycle'])
            if (late['last_capture_cycle'] - early['last_capture_cycle'] == 4 and
                    abs(early['last_code'] - late['last_code']) >= 3):
                hits.add('sample/phase-effect')
        e.check(config+'/coverage', goals <= hits, dict(hit=sorted(hits), missing=sorted(goals-hits), phase=phase))
    frozen = json.loads((e.out/'manifest.json').read_text())['source_sha256']
    changed = [name for name, sha in frozen.items() if N.digest(ROOT/name) != sha]
    N.verify(snapshot)
    e.check('source-freshness', not changed, changed)
    return e.finish()


def main():
    parser = E.parser(__doc__, 'local-pwm-spice')
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

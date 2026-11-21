#!/usr/bin/env python3
"""Solve the supply and its detector with ngspice, replay the detector events into the RTL, judge both."""
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import shutil
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


M = load('por_model', HERE / 'model.py')
E = load('por_evidence', HERE.parent / 'local-exploration-common/evidence.py')
N = load('por_ngspice', ROOT / 'tools/ngspice.py')
NAME = 'local-por-sequence'
TOP = 'por_tb'
RTL = [HERE / 'rtl/por_reset_sync.sv', HERE / 'rtl/por_init_ctrl.sv', HERE / 'rtl/por_sequence.sv']
SOURCES = [*RTL, HERE / 'tb/por_tb.sv']
TEMPLATE = HERE / 'por.cir.in'
FIXED = ('powerup', 'slow-ramp', 'brownout', 'repower')
ANALOG_FAULTS = {'no-hysteresis': ('slow-ramp', 'ANALOG_CHATTER'), 'divider-early': ('slow-ramp', 'CROSS_EARLY'),
                 'divider-late': ('slow-ramp', 'ANALOG_THRESHOLD'), 'slow-rc': ('powerup', 'ANALOG_DELAY')}
MUTANTS = {1: ('powerup', 'POR_RELEASE'), 2: ('powerup', 'POR_RELEASE'), 3: ('brownout', 'POR_PARTIAL'),
           4: ('powerup', 'POR_STATE'), 5: ('powerup', 'POR_STATE'), 6: ('brownout', 'POR_ORDER'),
           7: ('repower', 'POR_STATE'), 8: ('brownout', 'POR_STATE'), 9: ('powerup', 'POR_UNKNOWN')}
ALTERNATIVES = (dict(step=5e-8, reltol=1e-5, method='gear'), dict(step=1e-7, reltol=1e-6, method='trap'))
# Scenes each fixed scenario was written to reach; a run that misses one is a broken scenario, not a pass.
SCENES = {'brownout': {'reset/in-ready', 'reset/in-cal'}, 'repower': {'reset/in-ready', 'reset/in-fail'},
          'async-pulses': {'reset/in-ready', 'reset/in-wait', 'reset/in-load', 'reset/in-cal', 'reset/in-fail', 'release/aborted'}}


class Runner:
    def __init__(self, evidence, prefix):
        self.e, self.a, self.prefix = evidence, evidence.args, prefix
        self.builds, self.solved = {}, {}

    def solve(self, key, cfg, spec, fault=None, solver=M.SOLVER):
        """Run ngspice once in its own process; any failure, time-out or missing output is an error."""
        directory = self.e.out / key
        directory.mkdir(parents=True)
        (directory / 'detector.cir').write_text(M.deck(TEMPLATE.read_text(), cfg, spec, fault, solver))
        E.P.write_json(directory / 'request.json', M.request(cfg, spec, solver))
        command = [sys.executable, str(HERE / 'solve.py'), str(self.prefix), str(directory / 'detector.cir'),
                   str(directory / 'request.json'), str(directory / 'measured.json'), str(directory / 'waveform.csv')]
        execution = E.P.execute(command, directory / 'ngspice.log', self.a.timeout, directory)
        log = (directory / 'ngspice.log').read_text(errors='replace')
        if execution['error'] or execution['returncode'] != 0 or not re.search(r'^SPICE_PASS points=\d+ events=\d+$', log, re.M):
            raise ValueError(f"{key}: ngspice did not finish ({execution['error'] or 'see ngspice.log'})")
        return json.loads((directory / 'measured.json').read_text())

    def analog(self, key, cfg, spec, fault=None, expected=None):
        """Solve and judge one scenario. Returns (ok, detail, record, goals)."""
        try:
            record = self.solve(key, cfg, spec, fault)
        except (OSError, ValueError, KeyError) as exc:
            return False, dict(expected=expected, error=str(exc)), None, set()
        detail = dict(expected=expected, points=record['points'], events=[[e['t'], e['value']] for e in record['events']])
        try:
            goals = M.check_analog(cfg, spec, record)
        except M.Mismatch as exc:
            print(f'CHECK_FAIL {exc.label} {key}: {exc}', flush=True)
            return exc.label == expected, dict(detail, label=exc.label, message=str(exc)), record, set()
        return expected is None, dict(detail, goals=sorted(goals)), record, goals

    def simulate(self, key, cfg, events, phase, cycles, plans, mutation=0, expected=None, scenes=()):
        """Replay events into the RTL. Returns (ok, detail, goals)."""
        directory = self.e.out / key
        directory.mkdir(parents=True)
        M.check_events(events, phase, cycles)
        inputs = M.program(events, phase, cycles, cfg, plans)
        rows, reached = M.expect(events, phase, cycles, cfg, inputs)
        if not set(scenes) <= reached:
            raise ValueError(f'{key}: scenario no longer reaches {sorted(set(scenes) - reached)}')
        (directory / 'vectors.txt').write_text(M.vectors(inputs, rows))
        (directory / 'events.txt').write_text(''.join(f'{t} {v}\n' for t, v in events))
        parameters = {**{n: cfg[n] for n in M.DIGITAL}, 'MUTATION': mutation}
        tag = '-'.join(f'{k}{v}' for k, v in sorted(parameters.items()))
        if tag not in self.builds:
            binary = self.e.out / 'build' / (tag + '.vvp')
            binary.parent.mkdir(exist_ok=True)
            command = [self.a.iverilog, '-g2012', '-s', TOP, *[f'-P{TOP}.{k}={v}' for k, v in sorted(parameters.items())],
                       '-o', str(binary), *map(str, SOURCES)]
            self.builds[tag] = binary, E.P.execute(command, binary.with_suffix('.log'), self.a.timeout, self.e.out)
        binary, build = self.builds[tag]
        if build['error'] or build['returncode'] != 0:
            execution = dict(error='build failed', returncode=None)
            (directory / 'simulation.log').write_text('build failed\n')
        else:
            execution = E.P.execute([self.a.vvp, str(binary), '+VECTORS=' + str(directory / 'vectors.txt'),
                                     '+EVENTS=' + str(directory / 'events.txt'), '+WAVE=' + str(directory / 'wave.vcd'),
                                     f'+PHASE={phase}'], directory / 'simulation.log', self.a.timeout, directory)
        log = (directory / 'simulation.log').read_text(errors='replace')
        status, message = E.P.classify(dict(checks=cycles, expected_failure=expected), execution, log)
        counts = M.counts(events, phase, cycles, cfg)
        if status == 'pass':
            found = re.findall(r'^COUNT ([a-z]+)=(\d+)$', log, re.M)
            if len(found) != len(dict(found)) or {k: int(v) for k, v in found} != counts:
                status, message = 'error', 'event or release count differs from the reference'
        if status in ('pass', 'detected') and '$enddefinitions' not in (directory / 'wave.vcd').read_text(errors='replace'):
            status, message = 'error', 'waveform missing'
        goals = set(re.findall(r'^COVER (\S+)$', log, re.M)) if status == 'pass' and not mutation else set()
        detail = dict(status=status, message=message, expected=expected, cycles=cycles, phase_ns=phase, counts=counts,
                      events=len(events), mutation=mutation, goals=sorted(goals), execution=execution)
        E.P.write_json(directory / 'result.json', detail)
        return status == ('detected' if expected else 'pass'), detail, goals


def cycles_for(spec):
    return (round(spec['stop'] * 1e9) - spec['phase']) // M.T_NS - 1


def run(args):
    seeds = list(range(args.seed, args.seed + (3 if args.profile == 'nightly' else 1)))
    scenarios = [*FIXED, *[f'random-{s}' for s in seeds]]
    requirements = HERE / 'requirements.json'
    _, required = E.C.catalog(requirements)
    ids = ['toolchain', 'ngspice-installation']
    for config in M.CONFIGS:
        ids += [f'{config}/spice-{s}' for s in [*scenarios, 'dipmap']]
        ids += [f'{config}/rtl-{s}' for s in [*scenarios, 'async-pulses']]
        ids += [f'{config}/spice-settings']
        ids += [f'{config}/detect-analog-{f}' for f in ANALOG_FAULTS]
        ids += [f'{config}/detect-rtl-{m}' for m in MUTANTS]
        ids += [f'{config}/coverage']
    ids += ['source-freshness']
    sources = [Path(__file__), Path(M.__file__), HERE / 'solve.py', TEMPLATE, requirements, Path(N.__file__), N.CONFIG,
               ROOT / N.spec()['patch']['file'], *SOURCES]
    plan = dict(configurations=M.CONFIGS, scenarios=scenarios, seeds=seeds, clock_ns=M.T_NS, solver=M.SOLVER,
                alternatives=ALTERNATIVES, analog_faults=ANALOG_FAULTS, mutants={str(k): v for k, v in MUTANTS.items()})
    e = E.Evidence(NAME, args, sources, plan, ids)
    tools = {n: E.P.execute([getattr(args, n), '-V'], e.out / (n + '-version.log'), args.timeout, e.out) for n in ('iverilog', 'vvp')}
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
    runner = Runner(e, prefix)
    coverage = {}
    for config, cfg in M.CONFIGS.items():
        hits, replay = set(), {}
        for name in [*scenarios, 'dipmap']:
            kind, seed = ('random', int(name[7:])) if name.startswith('random-') else (name, int(args.profile == 'nightly'))
            spec = M.scenario(kind, cfg, seed)
            ok, detail, record, goals = runner.analog(f'{config}/spice-{name}', cfg, spec)
            e.check(f'{config}/spice-{name}', ok, detail)
            hits |= goals if ok else set()
            if name == 'dipmap':
                continue
            if not ok:
                e.check(f'{config}/rtl-{name}', False, 'the analog side of this scenario did not pass')
                continue
            replay[name] = (M.to_events(record, spec['phase']), spec['phase'], cycles_for(spec), spec['plans'], record, spec)
            events, phase, cycles, plans = replay[name][:4]
            ok, detail, goals = runner.simulate(f'{config}/rtl-{name}', cfg, events, phase, cycles, plans, scenes=SCENES.get(name, ()))
            e.check(f'{config}/rtl-{name}', ok, detail)
            hits |= goals if ok else set()
        pulses = M.async_pulses(cfg)
        ok, detail, goals = runner.simulate(f'{config}/rtl-async-pulses', cfg, pulses['events'], pulses['phase'], pulses['cycles'],
                                            pulses['plans'], scenes=SCENES['async-pulses'])
        e.check(f'{config}/rtl-async-pulses', ok, detail)
        hits |= goals if ok else set()
        # The same scenario with a finer step and with another integration method.
        try:
            reference, spec = replay['brownout'][4:]
            shifts = [M.check_settings(reference, runner.solve(f'{config}/spice-settings/{i}', cfg, spec, None, solver))
                      for i, solver in enumerate(ALTERNATIVES)]
            e.check(f'{config}/spice-settings', True, dict(max_shift_s=shifts, allowed_s=M.TOL_SETTINGS_S))
            hits.add('analog/solver-settings')
        except M.Mismatch as exc:
            print(f'CHECK_FAIL {exc.label} {config}/spice-settings: {exc}', flush=True)
            e.check(f'{config}/spice-settings', False, dict(label=exc.label, message=str(exc)))
        except (OSError, ValueError, KeyError) as exc:
            e.check(f'{config}/spice-settings', False, dict(error=str(exc)))
        for fault, (name, label) in ANALOG_FAULTS.items():
            ok, detail, _, _ = runner.analog(f'{config}/detect-analog-{fault}', cfg, M.scenario(name, cfg), fault, label)
            e.check(f'{config}/detect-analog-{fault}', ok, detail)
        for mutation, (name, label) in MUTANTS.items():
            if name not in replay:
                e.check(f'{config}/detect-rtl-{mutation}', False, 'the scenario for this mutant did not pass its analog side')
                continue
            events, phase, cycles, plans = replay[name][:4]
            ok, detail, _ = runner.simulate(f'{config}/detect-rtl-{mutation}', cfg, events, phase, cycles, plans, mutation, label)
            e.check(f'{config}/detect-rtl-{mutation}', ok, detail)
        coverage[config] = dict(required=sorted(required), hit=sorted(hits), missing=sorted(required - hits),
                                unknown=sorted(hits - required))
        e.check(f'{config}/coverage', not required - hits and not hits - required, coverage[config])
    E.P.write_json(e.out / 'coverage.json', coverage)
    E.P.write_json(e.out / 'builds.json', {k: dict(binary=str(v[0]), **v[1]) for k, v in runner.builds.items()})
    frozen = json.loads((e.out / 'manifest.json').read_text())['source_sha256']
    changed = [name for name, sha in frozen.items() if hashlib.sha256((ROOT / name).read_bytes()).hexdigest() != sha]
    try:
        N.verify(snapshot)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        changed.append(str(exc))
    e.check('source-freshness', not changed, changed)
    return e.finish()


def main():
    parser = E.parser(__doc__, NAME)
    parser.add_argument('--ngspice-config', default='lsi-ngspice-config')
    args = parser.parse_args()
    E.validate(parser, args)
    if args.seed > 2**30:
        parser.error('seed must be at most 2**30')
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

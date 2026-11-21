#!/usr/bin/env python3
"""Solve the SDA line with ngspice for each bus load, replay its threshold crossings into the reading side, judge both."""
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


M = load('i2c_od_model', HERE / 'model.py')
E = load('i2c_od_evidence', HERE.parent / 'local-exploration-common/evidence.py')
N = load('i2c_od_ngspice', ROOT / 'tools/ngspice.py')
NAME = 'local-i2c-open-drain'
TOP = 'i2c_od_tb'
RTL = [HERE / 'rtl/i2c_rx_master.sv']
SOURCES = [*RTL, HERE / 'tb/i2c_od_tb.sv']
TEMPLATE = HERE / 'sda.cir.in'
GROUPS = {'div125': 'fm400-mid', 'div50': 'fm1m'}          # the SCL clock decides the line; SAMPLE does not
SETTINGS_LOAD = {'div125': 'fm400-mid-outside', 'div50': 'fm1m-outside'}
ANALOG_FAULTS = {'no-initial': 'ANALOG_INITIAL', 'ron-high': 'ANALOG_LOW', 'release-missing': 'ANALOG_COUNT', 'cb-plus5': 'ANALOG_TIME'}
FAULT_LOAD = 'fm400-mid-inside'
MUTANTS = {1: 'I2C_SAMPLE', 2: 'I2C_BIT', 3: 'I2C_SCL', 4: 'I2C_PHASE', 5: 'I2C_COUNT', 6: 'I2C_SCL'}
MUTANT_CASE = ('fm400-mid', 'light')
RESCUE = ('fm400-late', 'fm400-mid-outside')                # a later sampling point reads what the middle one misses


def group_of(cfg):
    return next(g for g, name in GROUPS.items() if M.CONFIGS[name]['DIV'] == cfg['DIV'])


class Runner:
    def __init__(self, evidence, prefix):
        self.e, self.a, self.prefix = evidence, evidence.args, prefix
        self.builds = {}

    def solve(self, key, load, plan, fault=None, solver=M.SOLVER):
        """Run ngspice once in its own process; any failure, time-out or missing output is an error."""
        directory = self.e.out / key
        directory.mkdir(parents=True)
        (directory / 'sda.cir').write_text(M.deck(TEMPLATE.read_text(), load, plan['drive'], fault, solver))
        E.P.write_json(directory / 'request.json', M.request(load, plan, solver))
        command = [sys.executable, str(HERE / 'solve.py'), str(self.prefix), str(directory / 'sda.cir'),
                   str(directory / 'request.json'), str(directory / 'measured.json'), str(directory / 'waveform.csv')]
        execution = E.P.execute(command, directory / 'ngspice.log', self.a.timeout, directory)
        log = (directory / 'ngspice.log').read_text(errors='replace')
        if execution['error'] or execution['returncode'] != 0 or not re.search(r'^SPICE_PASS points=\d+ crossings=\d+$', log, re.M):
            raise ValueError(f"{key}: ngspice did not finish ({execution['error'] or 'see ngspice.log'})")
        return json.loads((directory / 'measured.json').read_text())

    def analog(self, key, load, plan, fault=None, expected=None):
        """Solve and judge one line. Returns (ok, detail, record, goals, events)."""
        try:
            record = self.solve(key, load, plan, fault)
        except (OSError, ValueError, KeyError) as exc:
            return False, dict(expected=expected, error=str(exc)), None, set(), None
        detail = dict(expected=expected, rp=load['rp'], cb=load['cb'], points=record['points'])
        try:
            goals, events, worst = M.check_analog(load, plan, record)
        except M.Mismatch as exc:
            print(f'CHECK_FAIL {exc.label} {key}: {exc}', flush=True)
            return exc.label == expected, dict(detail, label=exc.label, message=str(exc)), record, set(), None
        detail.update(events=[[round(t, 3), v] for t, v in events], worst_fraction_of_tolerance=round(worst, 4), goals=sorted(goals))
        return expected is None, detail, record, goals, events

    def simulate(self, key, cfg, plan, events, read, mutation=0, expected=None):
        """Replay the line events into the bench. Returns (ok, detail)."""
        directory = self.e.out / key
        directory.mkdir(parents=True)
        (directory / 'events.txt').write_text(M.event_lines(events))
        (directory / 'expected.txt').write_text(M.expected_lines(plan, read))
        parameters = {'DIV': cfg['DIV'], 'SAMPLE': cfg['SAMPLE'], 'MUTATION': mutation}
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
            execution = E.P.execute([self.a.vvp, str(binary), '+EVENTS=' + str(directory / 'events.txt'),
                                     '+EXPECT=' + str(directory / 'expected.txt'), '+WAVE=' + str(directory / 'wave.vcd')],
                                    directory / 'simulation.log', self.a.timeout, directory)
        log = (directory / 'simulation.log').read_text(errors='replace')
        checks = len(plan['edges']) + len(plan['samples']) + 1
        status, message = E.P.classify(dict(checks=checks, expected_failure=expected), execution, log)
        if status in ('pass', 'detected') and '$enddefinitions' not in (directory / 'wave.vcd').read_text(errors='replace'):
            status, message = 'error', 'waveform missing'
        detail = dict(status=status, message=message, expected=expected, mutation=mutation, sent=f"{M.to_byte(plan['bits']):02x}",
                      read=f'{M.to_byte(read):02x}', events=len(events), execution=execution)
        E.P.write_json(directory / 'result.json', detail)
        return status == ('detected' if expected else 'pass'), detail


def read_case(cfg, load, plan, events):
    """The byte the reading side must show, from the solved line, and the same from the closed form."""
    read = M.sampled(events, plan['samples'])
    analytic, _ = M.line(load, plan['drive'], plan['stop'])
    if M.sampled(analytic, plan['samples']) != read:
        raise M.Mismatch('ANALOG_BOUNDARY', 'the closed form and the solved line give different sampled bits')
    return read


def run(args):
    seeds = list(range(args.seed, args.seed + (3 if args.profile == 'nightly' else 1)))
    loads = M.loads()
    requirements = HERE / 'requirements.json'
    _, required = E.C.catalog(requirements)
    ids = ['toolchain', 'ngspice-installation']
    ids += [f'spice-{g}-{n}' for g in GROUPS for n in loads]
    ids += [f'spice-{c}-random-{s}' for c in M.CONFIGS for s in seeds]
    ids += [f'rtl-{c}-{n}' for c in M.CONFIGS for n in [*loads, *[f'random-{s}' for s in seeds]]]
    ids += [f'spice-settings-{g}' for g in GROUPS]
    ids += [f'detect-analog-{f}' for f in ANALOG_FAULTS] + [f'detect-rtl-{m}' for m in MUTANTS]
    ids += ['coverage', 'source-freshness']
    sources = [Path(__file__), Path(M.__file__), HERE / 'solve.py', TEMPLATE, requirements, Path(N.__file__), N.CONFIG,
               ROOT / N.spec()['patch']['file'], *SOURCES]
    plan = dict(configurations=M.CONFIGS, loads=loads, data=f'{M.DATA:02x}', seeds=seeds, solver=M.SOLVER,
                alternatives=M.ALTERNATIVES, analog_faults=ANALOG_FAULTS, mutants={str(k): v for k, v in MUTANTS.items()},
                thresholds=dict(vdd=M.VDD, vih=M.VIH, vil=M.VIL, ron=M.RON))
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
    hits, solved, reads = set(), {}, {}
    # The line depends on the SCL clock only, so each clock is solved once per load.
    for group, name in GROUPS.items():
        plan_g = M.schedule(M.CONFIGS[name], M.DATA)
        for load_name, ld in loads.items():
            ok, detail, record, goals, events = runner.analog(f'spice-{group}-{load_name}', ld, plan_g)
            e.check(f'spice-{group}-{load_name}', ok, detail)
            if ok:
                hits |= goals
                solved[group, load_name] = record, events
    cases = {}
    for config, cfg in M.CONFIGS.items():
        group, plan_c = group_of(cfg), M.schedule(cfg, M.DATA)
        for load_name, ld in loads.items():
            cases[config, load_name] = cfg, ld, plan_c, solved.get((group, load_name), (None, None))[1]
        for seed in seeds:
            ld, data = M.random_case(config, seed)
            plan_r = M.schedule(cfg, data)
            ok, detail, _, goals, events = runner.analog(f'spice-{config}-random-{seed}', ld, plan_r)
            e.check(f'spice-{config}-random-{seed}', ok, dict(detail, data=f'{data:02x}'))
            hits |= goals if ok else set()
            cases[config, f'random-{seed}'] = cfg, ld, plan_r, events if ok else None
    for (config, load_name), (cfg, ld, plan_c, events) in cases.items():
        key = f'rtl-{config}-{load_name}'
        if events is None:
            e.check(key, False, 'the analog side of this case did not pass')
            continue
        try:
            read = read_case(cfg, ld, plan_c, events)
        except (M.Mismatch, ValueError) as exc:
            print(f"CHECK_FAIL {getattr(exc, 'label', 'PLAN')} {key}: {exc}", flush=True)
            e.check(key, False, dict(error=str(exc)))
            continue
        kinds = M.outcome(plan_c['bits'], read)
        ok, detail = runner.simulate(key, cfg, plan_c, events, read)
        ratio = M.rise_needed(ld) / M.window(cfg)
        e.check(key, ok, dict(detail, outcome=sorted(kinds), rise_over_window=round(ratio, 4)))
        if not ok:
            continue
        reads[config, load_name] = kinds
        hits |= {f'outcome/{k}' for k in kinds}
        if kinds != {'correct'}:
            hits.add('rtl/misread-predicted')
        if 0.9 <= ratio < 1 and kinds == {'correct'}:
            hits.add('boundary/just-inside')
        if 1 < ratio <= 1.1 and 'slow-rise' in kinds:
            hits.add('boundary/just-outside')
    if reads.get(RESCUE) == {'correct'} and 'slow-rise' in reads.get(('fm400-mid', RESCUE[1]), set()):
        hits.add('sample/later-rescues')
    for group, name in GROUPS.items():
        key, load_name = f'spice-settings-{group}', SETTINGS_LOAD[group]
        try:
            reference = solved[group, load_name][0]
            ld, plan_g = loads[load_name], M.schedule(M.CONFIGS[name], M.DATA)
            shifts = [M.check_settings(reference, runner.solve(f'{key}/{i}', ld, plan_g, None, solver), ld)
                      for i, solver in enumerate(M.ALTERNATIVES)]
            e.check(key, True, dict(shift_ns=shifts))
            hits.add('analog/solver-settings')
        except M.Mismatch as exc:
            print(f'CHECK_FAIL {exc.label} {key}: {exc}', flush=True)
            e.check(key, False, dict(label=exc.label, message=str(exc)))
        except (OSError, ValueError, KeyError) as exc:
            e.check(key, False, dict(error=str(exc)))
    plan_f = M.schedule(M.CONFIGS['fm400-mid'], M.DATA)
    detected = 0
    for fault, label in ANALOG_FAULTS.items():
        ok, detail, _, _, _ = runner.analog(f'detect-analog-{fault}', loads[FAULT_LOAD], plan_f, fault, label)
        e.check(f'detect-analog-{fault}', ok, detail)
        detected += ok
    if detected == len(ANALOG_FAULTS):
        hits.add('negative/analog-faults')
    config, load_name = MUTANT_CASE
    cfg, ld, plan_m, events = cases[config, load_name]
    detected = 0
    for mutation, label in MUTANTS.items():
        key = f'detect-rtl-{mutation}'
        if events is None:
            e.check(key, False, 'the analog side of the mutant case did not pass')
            continue
        ok, detail = runner.simulate(key, cfg, plan_m, events, M.sampled(events, plan_m['samples']), mutation, label)
        e.check(key, ok, detail)
        detected += ok
    if detected == len(MUTANTS):
        hits.add('negative/rtl-mutants')
    coverage = dict(required=sorted(required), hit=sorted(hits), missing=sorted(required - hits), unknown=sorted(hits - required))
    E.P.write_json(e.out / 'coverage.json', coverage)
    e.check('coverage', not required - hits and not hits - required, coverage)
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

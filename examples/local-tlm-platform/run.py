#!/usr/bin/env python3
"""One C driver on a TLM-2.0 virtual platform and on the peripheral RTL, both held to a contract model."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import random
import shutil
import signal
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


E = load('tlm_platform_evidence', HERE.parent / 'local-exploration-common/evidence.py')
M = load('tlm_platform_model', HERE / 'model.py')
SC = load('tlm_platform_systemc', ROOT / 'tools/systemc.py')
P = E.P

NAME = 'local-tlm-platform'
CONFIGS = {'wait0': 0, 'wait2': 2}
RTL = [HERE / 'rtl/irq_timer.sv', HERE / 'rtl/periph_sram.sv', HERE / 'rtl/periph_sys.sv']
DRIVER = [HERE / 'c/app.c', HERE / 'c/app.h']
HARNESS = HERE / 'tb/rtl_harness.cpp'
PLATFORM = HERE / 'tlm/platform.cpp'
REQUIREMENTS = HERE / 'requirements.json'
INPUTS = [Path(__file__), HERE / 'model.py', REQUIREMENTS, *RTL, *DRIVER, HARNESS, PLATFORM,
          ROOT / 'tools/systemc.py', ROOT / 'tools/environment.json']
# RTL mutation: (scenario that shows it, first category that differs from the model)
RTL_MUTATIONS = {1: ('race', 'PLAT_ACCESS'), 2: ('basic', 'PLAT_EVENT'), 3: ('basic', 'PLAT_MEMORY'),
                 4: ('basic', 'PLAT_ACCESS'), 5: ('basic', 'PLAT_ACCESS'), 6: ('basic', 'PLAT_ACCESS'),
                 7: ('basic', 'PLAT_MEMORY')}
TLM_MUTATIONS = {1: 'clear-wins', 2: 'ignore-enable'}
NEGATIVE_GOALS = {'negative/rtl-mutations', 'negative/tlm-model', 'negative/race-only-in-rtl'}
WAIT_GOALS = {'bus/wait-state'}


def scenarios(profile, seed):
    found = {'basic': dict(irqs=8, load=150, seed=0x1234, race=0),
             'race': dict(irqs=8, load=90, seed=0x5678, race=1)}
    for value in range(seed, seed + (3 if profile == 'nightly' else 1)):
        rng = random.Random(value)
        found[f'random-seed{value}'] = dict(irqs=rng.randint(1, 16), load=rng.randint(70, 400),
                                            seed=rng.randrange(2 ** 32), race=rng.randint(0, 1))
    return found


def timing(config, wait):
    """Driver timing knobs and a hard cycle limit; none of them changes the expected result."""
    load = config['load']
    return dict(lead=2 + wait, wait_limit=4 * (load + 1),
                cycle_limit=6000 + 4 * (config['irqs'] + 2) * (load + 2) * (1 + wait))


def plan(profile, seed):
    names = list(scenarios(profile, seed))
    ids = ['toolchain', 'build']
    for cfg in CONFIGS:
        ids += [f'tlm-{cfg}/{n}' for n in names] + [f'rtl-{cfg}/{n}' for n in names] + [f'rtl-{cfg}/coverage']
    ids += [f'rtl-wait0/mutation{m}' for m in RTL_MUTATIONS]
    ids += ['rtl-wait0/race-fault-on-basic', 'tlm-wait0/clear-wins-invisible', 'tlm-wait0/fault-ie',
            'requirements', 'source-freshness']
    return ids


def tlm_headers(home):
    include = Path(home) / 'include'
    files = [include / 'tlm.h', *[p for d in ('tlm', 'tlm_core', 'tlm_utils') for p in sorted((include / d).rglob('*')) if p.is_file()]]
    if len(files) < 20 or not (include / 'tlm_utils/simple_target_socket.h').is_file():
        raise ValueError('TLM-2.0 headers missing from the SystemC installation')
    return {str(p.relative_to(home)): hashlib.sha256(p.read_bytes()).hexdigest() for p in files}


def observe(record):
    """Goals the RTL actually showed in one run."""
    hits = set(record['covers']) & {'race/clear-set', 'bus/wait-state', 'timer/period'}
    access = record['access']
    if all(('R', hole, 0, 1) in access for hole in M.HOLES):
        hits.add('bus/unmapped-error')
    status = [d for op, a, d, e in access if (op, a, e) == ('R', M.STATUS, 0)]
    if 3 in status:
        hits.add('status/overrun')
        if ('irq_level_masked', 0) in record['notes']:
            hits.add('irq/masked-level')
        expired = [d for op, a, d, e in access if (op, a) == ('R', M.EXPIRED)]
        if expired and expired[0] == 1:
            hits.add('timer/reenable-reset')
    if status[1:2] == [2]:
        hits.add('status/w1c-partial')
    if any(name == 'irq' for name, _ in record['notes']):
        hits.add('irq/handled')
    if all(v is not None for v in record['memory']):
        hits.add('memory/readback')
    return hits


class Run:
    def __init__(self, args):
        self.a = args
        names = plan(args.profile, args.seed)
        self.scenarios = scenarios(args.profile, args.seed)
        self.e = E.Evidence(NAME, args, INPUTS, dict(configurations=CONFIGS, scenarios=self.scenarios,
                                                     rtl_mutations={str(k): v for k, v in RTL_MUTATIONS.items()},
                                                     tlm_mutations={str(k): v for k, v in TLM_MUTATIONS.items()}), names)
        self.out = self.e.out
        self.records = {}

    def execute(self, command, log, timeout=None):
        return P.execute([str(c) for c in command], log, self.a.timeout if timeout is None else timeout, self.out)

    def toolchain(self):
        probe = self.execute([self.a.systemc_config, '--prefix'], self.out / 'systemc-prefix.log')
        try:
            if probe['error'] or probe['returncode'] != 0:
                raise ValueError('SystemC prefix unavailable')
            self.home = Path((self.out / 'systemc-prefix.log').read_text().strip())
            self.systemc = dict(core=SC.snapshot(self.home), tlm_sha256=tlm_headers(self.home))
        except (OSError, ValueError) as exc:
            return self.e.check('toolchain', False, dict(error=str(exc), probe=probe))
        # The repository runner re-verifies systemc-source.json, so it holds exactly the core snapshot.
        P.write_json(self.out / 'systemc-source.json', self.systemc['core'])
        P.write_json(self.out / 'tlm-headers.json', self.systemc['tlm_sha256'])
        versions = {name: self.execute(command, self.out / f'{name}-version.log') for name, command in
                    (('cc', [self.a.cc, '--version']), ('cxx', [self.a.cxx, '--version']),
                     ('verilator', [self.a.verilator, '--version']), ('systemc', [self.a.systemc_config, '--version']))}
        P.write_json(self.out / 'tools.json', versions)
        good = (all(not v['error'] and v['returncode'] == 0 for v in versions.values()) and
                (self.out / 'systemc-version.log').read_text().strip() == 'SystemC 2.3.4')
        return self.e.check('toolchain', good, dict(versions=versions, tlm_headers=len(self.systemc['tlm_sha256'])))

    def build(self):
        build = self.out / 'build'
        build.mkdir()
        driver = build / 'app.o'
        cc = self.execute([self.a.cc, '-std=c11', '-Wall', '-Wextra', '-Werror', '-I' + str(HERE / 'c'), '-c', HERE / 'c/app.c',
                           '-o', driver], build / 'driver-build.log', self.a.build_timeout)
        jobs = {}
        for m in (0, *TLM_MUTATIONS):
            binary = build / f'tlm-m{m}'
            jobs[f'tlm-m{m}'] = (binary, [self.a.cxx, '-std=gnu++17', f'-DTLM_MUTATION={m}', '-I' + str(HERE / 'c'),
                                          '-I' + str(self.home / 'include'), PLATFORM, driver, self.home / 'lib/libsystemc.a',
                                          '-pthread', '-o', binary])
        for wait, mutation in [(0, 0), (2, 0), *[(0, m) for m in RTL_MUTATIONS]]:
            obj = build / f'rtl-w{wait}-m{mutation}'
            jobs[f'rtl-w{wait}-m{mutation}'] = (obj / 'Vperiph_sys', [
                self.a.verilator, '--cc', '--exe', '--build', '-j', '2', '--trace', '-Wno-fatal', '--x-initial', 'unique',
                '--x-assign', 'unique', '--top-module', 'periph_sys',
                f'-GWAIT={wait}', f'-GMUTATION={mutation}', '--Mdir', obj, '-CFLAGS', '-I' + str(HERE / 'c'),
                '-LDFLAGS', driver, *RTL, HARNESS])
        results = {}
        if not cc['error'] and cc['returncode'] == 0:
            with ThreadPoolExecutor(max_workers=self.a.jobs) as pool:
                futures = {name: pool.submit(self.execute, command, build / f'{name}.log', self.a.build_timeout)
                           for name, (_, command) in jobs.items()}
                results = {name: future.result() for name, future in futures.items()}
        self.binaries = {name: binary for name, (binary, _) in jobs.items()
                         if name in results and not results[name]['error'] and results[name]['returncode'] == 0 and binary.is_file()}
        P.write_json(build / 'builds.json', dict(driver=cc, builds=results))
        return self.e.check('build', len(self.binaries) == len(jobs), dict(driver=cc['returncode'], built=sorted(self.binaries),
                                                                            missing=sorted(set(jobs) - set(self.binaries))))

    def simulate(self, side, binary_name, name, config, wait):
        d = self.out / 'runs' / side / name
        d.mkdir(parents=True)
        t = timing(config, wait)
        binary = self.binaries.get(binary_name)
        if binary is None:
            return dict(status='error', message='binary not built')
        arguments = [config['irqs'], config['load'], config['seed'], config['race'], t['lead'], t['wait_limit'], t['cycle_limit']]
        if side.startswith('rtl'):
            arguments.append(d / 'wave.vcd')
        execution = self.execute([binary, *arguments], d / 'simulation.log')
        log = (d / 'simulation.log').read_text(errors='replace')
        record = dict(side=side, binary=binary_name, config=config, timing=t, execution=execution)
        try:
            parsed = M.parse(log)
        except ValueError as exc:
            parsed = None
            record.update(status='error', message=str(exc))
        if parsed is not None:
            record['parsed'] = dict(parsed, covers=sorted(parsed['covers']))
            if execution['error']:
                record.update(status='error', message=execution['error'])
            elif parsed['fails']:
                record.update(status='failed', message='harness: ' + ','.join(parsed['fails']))
            elif execution['returncode'] != 0 or not parsed['complete']:
                record.update(status='error', message='incomplete run or nonzero exit')
            elif side.startswith('rtl') and not self.wave(d):
                record.update(status='error', message='waveform missing')
            else:
                diffs = M.differences(parsed, M.expected(config))
                record.update(status='complete', differences=[dict(category=c, detail=x) for c, x in diffs])
        P.write_json(d / 'result.json', record)
        record['parsed_object'] = parsed
        return record

    @staticmethod
    def wave(d):
        wave = d / 'wave.vcd'
        return wave.is_file() and '$enddefinitions' in wave.read_text(errors='replace')

    def functional(self):
        hits = {cfg: set() for cfg in CONFIGS}
        for cfg, wait in CONFIGS.items():
            for name, config in self.scenarios.items():
                tlm = self.simulate(f'tlm-{cfg}', 'tlm-m0', name, config, wait)
                ok = tlm['status'] == 'complete' and not tlm['differences']
                self.e.check(f'tlm-{cfg}/{name}', ok, self.summary(tlm))
                self.records[f'tlm-{cfg}/{name}'] = tlm
                rtl = self.simulate(f'rtl-{cfg}', f'rtl-w{wait}-m0', name, config, wait)
                ok = rtl['status'] == 'complete' and not rtl['differences']
                versus = None
                if ok:
                    if tlm['status'] == 'complete':
                        versus = M.differences(rtl['parsed_object'], M.masked(tlm['parsed_object']))
                        ok = not versus
                    else:
                        ok, versus = False, 'TLM run did not complete'
                if ok and name == 'race':
                    ok = 'race/clear-set' in rtl['parsed_object']['covers']
                if ok:
                    hits[cfg] |= observe(rtl['parsed_object'])
                self.e.check(f'rtl-{cfg}/{name}', ok, dict(self.summary(rtl), versus_tlm=versus))
                self.records[f'rtl-{cfg}/{name}'] = rtl
        _, goals = E.C.catalog(REQUIREMENTS)
        functional = goals - NEGATIVE_GOALS
        for cfg, wait in CONFIGS.items():
            required = functional - (WAIT_GOALS if wait == 0 else set())
            self.e.check(f'rtl-{cfg}/coverage', required <= hits[cfg],
                         dict(required=sorted(required), hit=sorted(hits[cfg] & required), missing=sorted(required - hits[cfg])))
        return set().union(*hits.values())

    def negatives(self):
        credited = set()
        detected = []
        for m, (name, label) in RTL_MUTATIONS.items():
            r = self.simulate('rtl-wait0-mutations', f'rtl-w0-m{m}', f'mutation{m}', self.scenarios[name], 0)
            first = r['differences'][0]['category'] if r['status'] == 'complete' and r['differences'] else None
            ok = first == label
            detected.append(ok)
            self.e.check(f'rtl-wait0/mutation{m}', ok, dict(self.summary(r), expected_failure=label, observed_first=first))
        if all(detected):
            credited.add('negative/rtl-mutations')
        r = self.simulate('rtl-wait0-mutations', 'rtl-w0-m1', 'race-fault-on-basic', self.scenarios['basic'], 0)
        quiet_rtl = r['status'] == 'complete' and not r['differences']
        self.e.check('rtl-wait0/race-fault-on-basic', quiet_rtl, dict(self.summary(r), meaning='mutation 1 is invisible without the race'))
        r = self.simulate('tlm-wait0-mutations', 'tlm-m1', 'clear-wins-invisible', self.scenarios['race'], 0)
        reference = self.records.get('tlm-wait0/race')
        quiet_tlm = (r['status'] == 'complete' and not r['differences'] and reference is not None and
                     reference['status'] == 'complete' and r['parsed_object']['access'] == reference['parsed_object']['access'])
        self.e.check('tlm-wait0/clear-wins-invisible', quiet_tlm,
                     dict(self.summary(r), meaning='the TLM model never lands an acknowledge on an expiry'))
        if quiet_rtl and quiet_tlm and detected[0]:
            credited.add('negative/race-only-in-rtl')
        r = self.simulate('tlm-wait0-mutations', 'tlm-m2', 'fault-ie', self.scenarios['basic'], 0)
        first = r['differences'][0]['category'] if r['status'] == 'complete' and r['differences'] else None
        if self.e.check('tlm-wait0/fault-ie', first == 'PLAT_EVENT', dict(self.summary(r), expected_failure='PLAT_EVENT', observed_first=first)):
            credited.add('negative/tlm-model')
        return credited

    @staticmethod
    def summary(r):
        return {k: v for k, v in r.items() if k not in ('parsed', 'parsed_object')}

    def finish(self, hits):
        _, goals = E.C.catalog(REQUIREMENTS)
        self.e.check('requirements', goals <= hits, dict(goals=len(goals), hit=sorted(goals & hits), missing=sorted(goals - hits)))
        changed = [str(p) for p in INPUTS if hashlib.sha256(p.read_bytes()).hexdigest() !=
                   json.loads((self.out / 'manifest.json').read_text())['source_sha256'].get(str(p.relative_to(ROOT)))]
        try:
            SC.verify(self.systemc['core'])
            if tlm_headers(self.home) != self.systemc['tlm_sha256']:
                changed.append('TLM headers changed')
        except (OSError, ValueError) as exc:
            changed.append(str(exc))
        self.e.check('source-freshness', not changed, changed)
        return self.e.finish()


def run(args):
    r = Run(args)
    if not r.toolchain() or not r.build():
        return r.e.finish()
    hits = r.functional()
    hits |= r.negatives()
    return r.finish(hits)


def main():
    p = E.parser(__doc__, NAME)
    p.add_argument('--verilator', default='verilator')
    p.add_argument('--cc', default='cc')
    p.add_argument('--cxx', default='c++')
    p.add_argument('--systemc-config', default='lsi-systemc-config')
    p.add_argument('--jobs', type=int, default=4)
    p.add_argument('--build-timeout', type=float, default=300)
    args = p.parse_args()
    E.validate(p, args)
    if args.jobs < 1 or not math.isfinite(args.build_timeout) or args.build_timeout <= 0 or args.seed > 2 ** 31:
        p.error('positive jobs, finite build timeout and a 31-bit seed required')
    args.cxx = shutil.which(args.cxx) or args.cxx
    args.systemc_config = shutil.which(args.systemc_config) or args.systemc_config
    previous = signal.signal(signal.SIGTERM, P.interrupted)
    try:
        return run(args)
    except P.RunInterrupted as exc:
        return 128 + exc.signum
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print('RUNNER_ERROR', exc, file=sys.stderr)
        return 1
    finally:
        signal.signal(signal.SIGTERM, previous)


if __name__ == '__main__':
    sys.exit(main())

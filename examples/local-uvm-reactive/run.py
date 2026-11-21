#!/usr/bin/env python3
"""Native UVM reactive (responder) agent: memory model, driver callbacks and a factory override."""
from collections import Counter
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import re
import sys
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
spec = importlib.util.spec_from_file_location('reactive_evidence', HERE.parent / 'local-exploration-common/evidence.py')
E = importlib.util.module_from_spec(spec)
spec.loader.exec_module(E)
HARNESS = HERE.parent / 'local-uvm-random/sim_main.cpp'
SOURCES = [HERE / 'tb/rx_if.sv', HERE / 'tb/rx_pkg.sv', HERE / 'rtl/req_master.sv', HERE / 'tb/top.sv']
_, GOALS = E.C.catalog(HERE / 'requirements.json')
RETRIES, TIMEOUT = 2, 8
TESTS = {'base': 'rx_base_test', 'error': 'rx_error_test'}
COVERS = {'cp_' + s for s in ('stall', 'ok', 'error_rsp', 'retry_ok', 'exhausted', 'timeout', 'boundary', 'early', 'idle_rsp', 'reset_busy')}
REQUIRED_COVERS = {'base': COVERS, 'error': {'cp_ok', 'cp_error_rsp', 'cp_exhausted'}}
MUTANTS = {1: 'RX_HOLD', 2: 'RX_RETRY', 3: 'RX_RETRY', 4: 'RX_TIMEOUT', 5: 'RX_SPURIOUS', 6: 'RX_DATA', 7: 'RX_REQUEST', 8: 'RX_SPURIOUS', 9: 'RX_DRAIN'}
DIAGNOSTICS = [('scoreboard-off', 'base', 'RX_DRAIN', dict(CHECKER_OFF=2)), ('done-monitor-off', 'base', 'RX_ORDER', dict(CHECKER_OFF=1)),
               ('memory-model-fault', 'base', 'RX_MEMORY', dict(MEMORY_FAULT=1)), ('callbacks-off', 'base', 'RX_GOALS', dict(CALLBACKS_OFF=1)),
               ('factory-override-off', 'error', 'RX_FACTORY', dict(NO_OVERRIDE=1))]
ITEM_FIELDS = ('stall', 'delay', 'err', 'drop', 'early', 'dup', 'aborted')
# Commands issued outside the random part: (write, address, data).
PLAIN = [(0, 0x21, 0), (1, 0x21, 0x5c), (0, 0x21, 0), (1, 0x22, 0xa7), (0, 0x22, 0)]
DIRECTED = [(0, 0x21, 0), (1, 0x30, 0x11), (1, 0x31, 0x22), (0, 0x30, 0), (0, 0x31, 0), (1, 0x30, 0xee), (0, 0x30, 0), (1, 0x32, 0x33),
            (0, 0x32, 0), (0, 0x21, 0), (0, 0x22, 0), (1, 0x33, 0x44), (0, 0x33, 0), (0, 0x21, 0), (0, 0x21, 0)]
FACTORY_DIRECTED = [(1, 0x10, 0x3c), (1, 0xc5, 0x99), (0, 0xc5, 0), (0, 0x10, 0)]
# The responses of the directed part of the base test, one row per attempt. Fields left out are 0.
DIRECTED_ITEMS = [dict(stall=3, delay=7), dict(err=1), {}, dict(err=1), dict(err=1), {}, {}, {}, dict(err=1), dict(err=1), dict(err=1), {},
                  dict(drop=1), {}, dict(early=1, stall=2), dict(dup=1), dict(err=1, dup=1), {}, {}, dict(delay=7, aborted=1), {}]


def planned_commands(test, seed, count):
    """The command list a seed must produce: directed commands and the generator of the random part."""
    state = seed & 0xffffffff

    def draw():
        nonlocal state
        state = (state * 1664525 + 1013904223) & 0xffffffff
        return (state >> 31, (((state >> 24) & 3) << 6) | ((state >> 16) & 3), (state >> 8) & 255)
    if test == 'base':
        return [c + (0,) for c in PLAIN + DIRECTED] + [draw() + (1,) for _ in range(count + 6)]
    return [c + (0,) for c in FACTORY_DIRECTED] + [draw() + (1,) for _ in range(count)]


def parse(log):
    def rows(prefix, names):
        pattern = '^' + prefix + ''.join(r' %s=(\w+)' % n for n in names) + '$'
        found = re.findall(pattern, log, re.M)
        if len(found) != sum(line.startswith(prefix + ' ') for line in log.splitlines()):
            raise ValueError('malformed ' + prefix + ' line')
        return [dict(zip(names, (v if n in ('type', 'name') else int(v) for n, v in zip(names, row)))) for row in found]
    issued = rows('RX_ISSUED', ('n', 'random', 'write', 'addr', 'wdata'))
    items = rows('RX_ITEM', ('n', 'type', 'write', 'addr') + ITEM_FIELDS)
    observed = rows('RX_OBS', ('kind', 'cycle', 'level', 'write', 'addr', 'wdata', 'rdata', 'err', 'timeout', 'tries'))
    phases = rows('RX_PHASE', ('name', 'items'))
    if [r['n'] for r in issued] != list(range(1, len(issued) + 1)) or [r['n'] for r in items] != list(range(1, len(items) + 1)):
        raise ValueError('issued commands or response items are not numbered in order')
    if any(a['cycle'] > b['cycle'] for a, b in zip(observed, observed[1:])):
        raise ValueError('observations are not in time order')
    return issued, items, observed, phases


def check_items(test, items, phases):
    """The injected fields must be what the scenario of each phase allows."""
    names = [p['name'] for p in phases]
    expected = ['plain', 'directed', 'random', 'quiet', 'deleted', 'end'] if test == 'base' else ['directed', 'random', 'end']
    bounds = [p['items'] for p in phases]
    if names != expected or bounds != sorted(bounds) or bounds[-1] != len(items):
        raise ValueError('phase markers differ')
    part = {name: items[a:b] for name, a, b in zip(names, bounds, bounds[1:])}
    kind = 'rx_rsp_item' if test == 'base' else 'rx_err_item'
    if any(t['type'] != kind for t in items):
        raise ValueError('response item type differs from the factory setting')
    if any(t['stall'] not in range(4) or t['delay'] not in range(TIMEOUT) or (t['early'] and t['stall'] < 2) or (t['drop'] and t['dup']) for t in items):
        raise ValueError('response item outside the driver limits')

    def quiet(t, *fields):
        return not any(t[f] for f in fields)
    if test == 'base':
        if [{f: t[f] for f in ITEM_FIELDS} for t in part['directed']] != [{f: row.get(f, 0) for f in ITEM_FIELDS} for row in DIRECTED_ITEMS]:
            raise ValueError('directed responses differ from the plan')
        if not all(quiet(t, *ITEM_FIELDS) for t in part['plain'] + part['deleted']) or len(part['plain']) != 5 or len(part['deleted']) != 2:
            raise ValueError('a response without callbacks was shaped')
        if not all(quiet(t, 'err', 'drop', 'early', 'dup', 'aborted') for t in part['quiet']) or len(part['quiet']) != 4:
            raise ValueError('a disabled callback shaped a response')
        if any(t['aborted'] for t in part['random']):
            raise ValueError('unexpected aborted response')
    else:
        if any(t['err'] != int(t['addr'] >= 0xc0) or not quiet(t, 'drop', 'early', 'dup', 'aborted') for t in items):
            raise ValueError('error item does not follow the address rule')
        if not all(quiet(t, 'stall', 'delay') for t in part['directed']):
            raise ValueError('a response without callbacks was shaped')
    return part


def ledger(log, test, seed, count):
    """Independent model: from the issued commands and the injected response fields, predict every
    observation with its cycle relation, the memory contents and the final counters."""
    issued, items, observed, phases = parse(log)
    plan = planned_commands(test, seed, count)
    if [(r['write'], r['addr'], r['wdata'], r['random']) for r in issued] != plan:
        raise ValueError('issued commands differ from the seed')
    part = check_items(test, items, phases)
    stream = iter(observed)
    queue = iter(items)
    memory = {}
    stale = set()
    goals = set()
    counts = Counter()
    previous = None

    def take(kind, **fields):
        obs = next(stream, None)
        if obs is None or obs['kind'] != kind or any(obs[k] != v for k, v in fields.items()):
            raise ValueError(f'observation differs: expected kind {kind} {fields}, got {obs}')
        return obs

    def spurious(addr, cycle=None):
        obs = take(2, err=0, rdata=~addr & 255)
        if cycle is not None and obs['cycle'] != cycle:
            raise ValueError('duplicate response is not on the next edge')
        counts['spurious'] += 1
        return obs
    take(0, level=1)
    for write, addr, wdata, _ in plan:
        command = take(4, write=write, addr=addr, wdata=wdata)
        counts['commands'] += 1
        tries = 0
        start = command['cycle']
        penalty = 0
        outcome = None
        while outcome is None:
            item = next(queue, None)
            if item is None or (item['write'], item['addr']) != (write, addr):
                raise ValueError('response item does not belong to the command')
            tries += 1
            counts['attempts'] += 1
            if item['early']:
                early = spurious(addr)
            accept = take(3, write=write, addr=addr, wdata=wdata)
            if accept['cycle'] != start + 2 + item['stall'] + penalty or (item['early'] and not start + 2 <= early['cycle'] < accept['cycle']):
                raise ValueError('acceptance edge differs from the stall')
            if item['aborted']:
                take(0, level=0)
                take(0, level=1)
                counts['cancelled'] += 1
                outcome = 'cancelled'
            elif item['drop']:
                done = take(1, err=1, timeout=1, rdata=0, tries=tries)
                if done['cycle'] != accept['cycle'] + TIMEOUT + 1:
                    raise ValueError('timeout edge differs')
                counts['timeouts'] += 1
                outcome = 'timeout'
            else:
                rdata = 0 if write else memory.get(addr, ~addr & 255)
                response = take(2, err=item['err'], rdata=rdata)
                if response['cycle'] != accept['cycle'] + 1 + item['delay']:
                    raise ValueError('response edge differs from the delay')
                counts['errors'] += item['err']
                final = not item['err'] or tries == RETRIES + 1
                if final:
                    done = take(1, err=item['err'], timeout=0, rdata=rdata, tries=tries)
                    if done['cycle'] != response['cycle'] + 1:
                        raise ValueError('completion edge differs')
                    outcome = 'error' if item['err'] else 'ok'
                if item['dup']:
                    spurious(addr, response['cycle'] + 1)
                start, penalty = response['cycle'], item['dup']
            if item['stall']:
                goals.add('callback/stall')
            if item['delay'] == TIMEOUT - 1 and outcome == 'ok':
                goals.add('callback/delay-boundary')
        counts['completed'] += outcome != 'cancelled'
        if outcome == 'ok':
            if write:
                memory[addr] = wdata
                stale.discard(addr)
            else:
                goals.add('respond/read-after-write' if addr in memory else 'respond/read-default')
                if addr in stale:
                    goals.add('retry/write-not-committed')
            if tries > 1:
                counts['retried_ok'] += 1
                goals.add('retry/once' if tries == 2 else 'retry/twice')
            if previous == 'timeout':
                goals.add('timeout/recovery')
            if previous == 'cancelled':
                goals.add('reset/recovery')
        elif write:
            stale.add(addr)
        if outcome == 'error':
            counts['exhausted'] += 1
        previous = outcome
    if next(stream, None) is not None or next(queue, None) is not None:
        raise ValueError('observations or response items left over')
    names = ('commands', 'completed', 'cancelled', 'attempts', 'errors', 'timeouts', 'spurious', 'exhausted', 'retried_ok')
    line = 'RX_COMPLETE ' + ' '.join(f'{n}={counts[n]}' for n in names) + f' items={len(items)}\n'
    if log.count(line) != 1 or log.count('RX_COMPLETE') != 1:
        raise ValueError('UVM scoreboard counters and the independent ledger differ')
    goals.add('respond/one-item-per-request')
    if test == 'base':
        goals.add('factory/base-type')
        for name, field in (('callback/error', 'err'), ('callback/drop', 'drop'), ('violation/early', 'early'), ('violation/duplicate', 'dup')):
            if any(t[field] for t in items):
                goals.add(name)
        if any(t[f] for t in part['random'] for f in ('err', 'drop', 'early', 'dup')):
            goals.add('callback/disable')
        if any(t['stall'] or t['delay'] for t in part['quiet'] + part['random']):
            goals.add('callback/delete')
        if counts['exhausted']:
            goals.add('retry/exhausted')
        if counts['timeouts']:
            goals.add('timeout/expired')
        if counts['cancelled'] == 1:
            goals.add('reset/cancel')
    else:
        goals.add('factory/error-type')
        if counts['exhausted'] and any(not t['err'] for t in items):
            goals.add('factory/error-region')
    return dict({n: counts[n] for n in names}, items=len(items), ok=counts['completed'] - counts['timeouts'] - counts['exhausted']), goals


def native(path, log, test, counts):
    observed = {}
    for line in path.read_text().splitlines():
        if not line or line.startswith('#'):
            continue
        m = re.fullmatch(r"C '([^']*)' (\d+)", line)
        if not m:
            raise ValueError('malformed native coverage')
        meta = dict(p.split('\x02', 1) for p in m[1].split('\x01') if p)
        if meta.get('t') != 'user':
            continue
        name = meta.get('o')
        if name not in COVERS or name in observed or meta.get('h') != 'TOP.top.' + name or Path(meta.get('f', '')).resolve() != (HERE / 'tb/top.sv').resolve():
            raise ValueError('native cover identity differs')
        observed[name] = int(m[2])
    logged = Counter(re.findall(r'^RX_COVER (\w+)$', log, re.M))
    if observed.keys() != COVERS or set(logged) - COVERS or any(logged[k] != n for k, n in observed.items()):
        raise ValueError('SVA covers missing or action/DB counts differ')
    if any(observed[k] <= 0 for k in REQUIRED_COVERS[test]):
        raise ValueError('required SVA cover not hit')
    exact = dict(cp_ok=counts['ok'], cp_error_rsp=counts['errors'], cp_retry_ok=counts['retried_ok'], cp_exhausted=counts['exhausted'],
                 cp_timeout=counts['timeouts'], cp_reset_busy=counts['cancelled'])
    if any(observed[k] != v for k, v in exact.items()):
        raise ValueError('native covers and the independent ledger differ')
    return observed


def evaluate(case, execution, log):
    status, message = E.P.classify(case, execution, log)
    if case['expected_failure']:
        return status == 'detected', message, {}, set()
    if status != 'pass':
        return False, message, {}, set()
    if log.count('Accellera:1800.2:UVM:2020.3.2') != 1:
        return False, 'unexpected UVM library', {}, set()
    if sorted(re.findall(r'^UVM_WARNING .*?\[([^]]+)\]', log, re.M)) != ['NO_DPI_USED', 'NO_VISIT_CHECK']:
        return False, 'unexpected warnings', {}, set()
    for name, value in (('WARNING', '2'), ('ERROR', '0'), ('FATAL', '0')):
        if re.findall(r'^UVM_' + name + r'\s*:\s*(\d+)\s*$', log, re.M) != [value]:
            return False, 'UVM summary differs', {}, set()
    try:
        counts, goals = ledger(log, case['test'], case['seed'], case['commands'])
        return True, 'independent ledger completed', counts, goals
    except ValueError as exc:
        return False, str(exc), {}, set()


def issued_total(test, commands):
    return len(planned_commands(test, 0, commands))


def run(a):
    commands = 400 if a.profile == 'nightly' else 40
    seeds = list(range(a.seed, a.seed + (3 if a.profile == 'nightly' else 1)))
    checks = ['build', *[f'{t}/seed{s}' for s in seeds for t in TESTS], *[f'mutation{m}' for m in MUTANTS], *[d[0] for d in DIAGNOSTICS],
              'coverage', 'goals', 'source-freshness']
    plan = dict(retries=RETRIES, timeout=TIMEOUT, random_commands=commands, seeds=seeds, tests=TESTS, goals=sorted(GOALS),
                native_covers=sorted(COVERS), mutants=MUTANTS, diagnostics=[d[0] for d in DIAGNOSTICS])
    e = E.Evidence('local-uvm-reactive', a, [Path(__file__), HERE / 'requirements.json', HARNESS, *SOURCES], plan, checks)
    home = a.uvm_home.resolve()
    E.P.write_json(e.out / 'uvm-source.json', dict(root=str(home), source_sha256={
        str(p.relative_to(home)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted((home / 'src').rglob('*')) if p.is_file()}))
    version = E.P.execute([a.verilator, '--version'], e.out / 'verilator-version.log', a.timeout, e.out)
    E.P.write_json(e.out / 'tools.json', dict(verilator=version))
    command = [a.verilator, '--cc', '--exe', '--build', '--timing', '--trace', '--coverage-user', '--assert', '-Wno-fatal', '-j', str(a.jobs),
               '--top-module', 'top', '--Mdir', str(e.out / 'build'), '-I' + str(home / 'src'), '+define+UVM_NO_DPI',
               str(home / 'src/uvm_pkg.sv'), *map(str, SOURCES), str(HARNESS)]
    build = E.P.execute(command, e.out / 'build.log', a.build_timeout, e.out)
    built = not build['error'] and build['returncode'] == 0 and not version['error'] and version['returncode'] == 0
    e.check('build', built, build)
    records = []

    def execute(name, test, seed, mutation=0, label=None, **flags):
        d = e.out / name
        d.mkdir(parents=True)
        case = dict(id=name, test=test, seed=seed, commands=commands, checks=issued_total(test, commands), expected_failure=label)
        cmd = [str(e.out / 'build/Vtop'), '+TEST=' + TESTS[test], f'+SEED={seed}', f'+COMMANDS={commands}', f'+MUTATION={mutation}',
               f'+SVA_OFF={int(a.sva_off)}', '+WAVE=' + str(d / 'trace.vcd'), *[f'+{k}={v}' for k, v in flags.items()]]
        if built:
            r = E.P.execute(cmd, d / 'simulation.log', a.timeout, d)
        else:
            r = dict(error='build failed', returncode=None)
            (d / 'simulation.log').write_text('build failed\n')
        log = (d / 'simulation.log').read_text(errors='replace')
        ok, message, counts, goals = evaluate(case, r, log)
        covers = {}
        try:
            if ok and label is None:
                covers = native(d / 'coverage.dat', log, test, counts)
            if ok and (not (d / 'trace.vcd').is_file() or '$enddefinitions' not in (d / 'trace.vcd').read_text()):
                raise ValueError('waveform missing')
        except (OSError, ValueError, KeyError) as exc:
            ok = False
            message = str(exc)
        record = dict(case, mutation=mutation, flags=flags, success=ok, message=message, ledger=counts, goals=sorted(goals) if ok else [], native=covers, execution=r)
        records.append(record)
        E.P.write_json(d / 'result.json', record)
        e.check(name, ok, record)
    for seed in seeds:
        for test in TESTS:
            execute(f'{test}/seed{seed}', test, seed, a.demo_bug if test == 'base' else 0)
    for mutation, label in MUTANTS.items():
        execute(f'mutation{mutation}', 'base', seeds[0], mutation, label)
    for name, test, label, flags in DIAGNOSTICS:
        execute(name, test, seeds[0], label=label, **flags)
    normal = [r for r in records if r['expected_failure'] is None]
    e.check('coverage', len(normal) == 2 * len(seeds) and all(r['success'] and r['native'].keys() == COVERS for r in normal),
            dict(runs=len(normal), covers=sorted(COVERS)))
    hit = set().union(*[set(r['goals']) for r in normal])
    e.check('goals', all(r['success'] for r in normal) and hit == GOALS, dict(required=sorted(GOALS), missing=sorted(GOALS - hit), unknown=sorted(hit - GOALS)))
    E.P.write_json(e.out / 'executions.json', records)
    manifest = json.loads((e.out / 'manifest.json').read_text())['source_sha256']
    changed = [n for n, h in manifest.items() if not (ROOT / n).is_file() or hashlib.sha256((ROOT / n).read_bytes()).hexdigest() != h]
    e.check('source-freshness', not changed, changed)
    return e.finish()


def main():
    p = E.parser(__doc__, 'local-uvm-reactive')
    p.add_argument('--uvm-home', type=Path, required=True)
    p.add_argument('--verilator', default='verilator')
    p.add_argument('--jobs', type=int, default=2)
    p.add_argument('--build-timeout', type=float, default=600)
    p.add_argument('--demo-bug', type=int, choices=range(10), default=0)
    p.add_argument('--sva-off', action='store_true')
    a = p.parse_args()
    E.validate(p, a)
    if not (a.uvm_home / 'src/uvm_pkg.sv').is_file() or not 1 <= a.jobs <= 8 or not math.isfinite(a.build_timeout) or a.build_timeout <= 0 or a.seed > 2**31 - 4:
        p.error('prepared UVM, valid jobs/seed and finite build limit required')
    try:
        return run(a)
    except (OSError, ValueError, KeyError, TypeError, RuntimeError) as exc:
        print('UVM_REACTIVE_ERROR', exc, file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())

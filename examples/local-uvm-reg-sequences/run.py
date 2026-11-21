#!/usr/bin/env python3
"""UVM built-in register and memory sequences, exclusions, RAL coverage and what they miss."""
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import re
import sys
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


E = load('reg_sequences_evidence', HERE.parent / 'local-exploration-common/evidence.py')
M = load('reg_sequences_model', HERE / 'model.py')
SOURCES = [HERE / 'tb/regbus_if.sv', HERE / 'tb/reg_seq_pkg.sv', HERE / 'rtl/reg_bank.sv', HERE / 'tb/top.sv']
_, GOALS = E.C.catalog(HERE / 'requirements.json')
BINS = {'zero', 'ones', 'other'}
BASE_WARNINGS = ['NO_DPI_USED', 'NO_VISIT_CHECK']
# Mutation -> label of the check that is planned to find it in the full flow.
MUTANTS = {1: 'REG_RESET', 2: 'REG_BITBASH', 3: 'REG_BITBASH', 4: 'MEM_WALK', 5: 'REG_MIRROR',
           6: 'REG_ALIAS', 7: 'REG_W1C', 8: 'MEM_WALK', 9: 'MEM_ALIAS'}
# Mutations that the built-in sequences alone are planned to miss.
BUILTIN_MISSES = (5, 6, 7, 9)


def case(identity, seed, iterations, label=None, mutation=0, plus=(), warnings=(), report=None, coverage=True, **model):
    plan = M.expected_counts(iterations, **model)
    return dict(id=identity, seed=seed, iterations=iterations, expected_failure=label, mutation=mutation,
                plusargs=[f'+MUTATION={mutation}', f'+SEED={seed}', f'+ITERATIONS={iterations}', *plus],
                warnings=sorted([*BASE_WARNINGS, *warnings]), library_report=report, coverage=coverage,
                model=model, totals=M.totals(plan), checks=sum(M.totals(plan)[k] for k in ('reads', 'writes')))


def cases(profile, seed):
    iterations = 4 if profile == 'smoke' else 16
    seeds = list(range(seed, seed + (1 if profile == 'smoke' else 3)))
    out = [case(f'seed{s}', s, iterations) for s in seeds]
    out += [case(f'mutation{m}', seed, iterations, label, m) for m, label in MUTANTS.items()]
    out += [case(f'builtin-only-mutation{m}', seed, iterations, None, m, ['+BUILTIN_ONLY=1'], builtin_only=True) for m in BUILTIN_MISSES]
    out += [
        # A volatile register declared as stable: the reset check reports a false failure.
        case('status-nonvolatile', seed, iterations, 'REG_RESET', plus=['+STATUS_NONVOLATILE=1'], status_volatile=False),
        case('status-nonvolatile-excluded', seed, iterations, plus=['+STATUS_NONVOLATILE=1', '+EXCLUDE_STATUS=1'], status_volatile=False, excluded=['status']),
        # Hardware events while a W1C register is bashed: a false failure unless it is excluded.
        case('events-during-bash', seed, iterations, 'REG_BITBASH', plus=['+EVENTS_DURING_BASH=1', '+BUILTIN_ONLY=1'], builtin_only=True),
        case('events-during-bash-excluded', seed, iterations, plus=['+EVENTS_DURING_BASH=1', '+EXCLUDE_IRQ=1', '+BUILTIN_ONLY=1'], builtin_only=True, bit_bash_excluded=['irq']),
        # Excluding a register that did not need it hides a defect from the built-in sequences.
        case('over-exclusion-mutation2', seed, iterations, None, 2, ['+EXCLUDE_SCRATCH=1', '+BUILTIN_ONLY=1'], builtin_only=True, excluded=['scratch']),
        # Backdoor variants of the access sequence.
        case('backdoor-none', seed, iterations, plus=['+BACKDOOR=0'], warnings=['uvm_reg_access_seq'] * 2, backdoor=False),
        case('backdoor-hdl-path', seed, iterations, 'REG_ACCESS', plus=['+BACKDOOR=2'], report='UVM_HDL_READ'),
        case('backdoor-crossed', seed, iterations, 'REG_ACCESS', plus=['+BACKDOOR=3'], report='RegModel'),
        case('coverage-off', seed, iterations, plus=['+COVERAGE_OFF=1'], coverage=False),
    ]
    return seeds, iterations, out


def native_bins(path):
    """Hit counts of the covergroup bins in the Verilator coverage database."""
    found = {}
    for line in path.read_text(errors='replace').splitlines():
        m = re.fullmatch(r"C '([^']*)' (\d+)", line)
        if not m:
            continue
        meta = dict(p.split('\x02', 1) for p in m[1].split('\x01') if '\x02' in p)
        if meta.get('t') != 'covergroup':
            continue
        name = meta.get('bin')
        if name not in BINS or name in found or 'value_classes' not in meta.get('h', '') or Path(meta.get('f', '')).name != 'reg_seq_pkg.sv':
            raise ValueError('covergroup bin identity differs')
        found[name] = int(m[2])
    if found.keys() != BINS:
        raise ValueError('covergroup bins missing from the coverage database')
    return found


def evaluate(c, execution, log):
    """Return (ok, message, details) for one finished simulation."""
    status, message = E.P.classify(c, execution, log)
    reports = re.findall(r'^LIBRARY_REPORT id=(\S+) ', log, re.M)
    if c['expected_failure']:
        if status != 'detected':
            return False, message, {}
        if c['library_report'] and reports != [c['library_report']]:
            return False, 'library report differs: ' + ','.join(reports), {}
        return True, message, dict(library_report=reports)
    if status != 'pass':
        return False, message, {}
    if log.count('Accellera:1800.2:UVM:2020.3.2') != 1:
        return False, 'unexpected UVM library version', {}
    if sorted(re.findall(r'^UVM_WARNING .*?\[([^]]+)\]', log, re.M)) != c['warnings']:
        return False, 'unexpected/missing UVM warnings', {}
    for severity, count in (('WARNING', len(c['warnings'])), ('ERROR', 0), ('FATAL', 0)):
        if re.findall(r'^UVM_' + severity + r'\s*:\s*(\d+)\s*$', log, re.M) != [str(count)]:
            return False, 'UVM report summary differs', {}
    pairs = re.findall(r'^COUNT ([a-z_]+)=(\d+)$', log, re.M)
    if len(pairs) != len(dict(pairs)) or {k: int(v) for k, v in pairs} != c['totals']:
        return False, 'completion counts differ', {}
    try:
        replayed = M.replay(log)
    except ValueError as exc:
        return False, 'reference model: ' + str(exc), {}
    plan = M.expected_counts(c['iterations'], **c['model'])
    observed = {k: v for k, v in replayed['stages'].items() if v or k in plan}
    if observed != plan:
        differing = sorted(k for k in set(plan) | set(observed) if plan.get(k) != observed.get(k))
        return False, 'access counts differ from the plan in ' + ','.join(differing), {}
    outside = sorted({int(v, 16) for v in re.findall(r'^RAL_SAMPLE_OUTSIDE offset=([0-9a-f]+)$', log, re.M)})
    if any(v != M.MEMORY_BASE + 4 * M.MEMORY_WORDS for v in outside):
        return False, 'address coverage sampled an unexpected offset', {}
    covers = sorted(set(re.findall(r'^COVER (\S+)$', log, re.M)))
    # Value classes of the other registers are sampled too; they are recorded but not required.
    if any(g not in GOALS and not g.startswith('ral/value/') for g in covers):
        return False, 'unknown coverage goal reported', {}
    ral = [g for g in covers if g.startswith('ral/')]
    if not c['coverage'] and ral:
        return False, 'register coverage sampled although it was not enabled', {}
    return True, message, dict(covers=covers, events=replayed['events'], sampled_outside=outside,
                               accesses={stage: sum(v.values()) for stage, v in plan.items()})


def run(a):
    seeds, iterations, plan = cases(a.profile, a.seed)
    checks = ['build', *[c['id'] for c in plan], 'coverage', 'source-freshness']
    e = E.Evidence('local-uvm-reg-sequences', a, [Path(__file__), HERE / 'model.py', HERE / 'requirements.json', *SOURCES],
                   dict(seeds=seeds, iterations=iterations, goals=sorted(GOALS), mutants=MUTANTS, builtin_misses=list(BUILTIN_MISSES),
                        cases=[dict(id=c['id'], expected_failure=c['expected_failure'], plusargs=c['plusargs'], checks=c['checks']) for c in plan]), checks)
    home = a.uvm_home.resolve()
    E.P.write_json(e.out / 'uvm-source.json', dict(root=str(home), source_sha256={str(p.relative_to(home)): hashlib.sha256(p.read_bytes()).hexdigest()
                                                                               for p in sorted((home / 'src').rglob('*')) if p.is_file()}))
    version = E.P.execute([a.verilator, '--version'], e.out / 'verilator-version.log', a.timeout, e.out)
    E.P.write_json(e.out / 'tools.json', dict(verilator=version))
    build_dir = e.out / 'build'
    command = [a.verilator, '--binary', '--timing', '--trace', '--assert', '--coverage-user', '-Wno-fatal', '-j', str(a.jobs), '--top-module', 'top',
               '--Mdir', str(build_dir), '-I' + str(home / 'src'), '-I' + str(HERE / 'tb'), '+define+UVM_NO_DPI', str(home / 'src/uvm_pkg.sv'), *map(str, SOURCES)]
    build = E.P.execute(command, e.out / 'build.log', a.build_timeout, e.out)
    E.P.write_json(e.out / 'build.json', build)
    built = not build['error'] and build['returncode'] == 0 and not version['error'] and version['returncode'] == 0 and (build_dir / 'Vtop').is_file()
    e.check('build', built, build['error'] or build['returncode'])
    records = []
    hits = set()
    for c in plan:
        d = e.out / c['id']
        d.mkdir()
        if built:
            execution = E.P.execute([str(build_dir / 'Vtop'), *c['plusargs'], '+WAVE=' + str(d / 'wave.vcd')], d / 'simulation.log', a.timeout, d)
        else:
            execution = dict(error='build failed', returncode=None, seconds=0)
            (d / 'simulation.log').write_text('build failed\n')
        log = (d / 'simulation.log').read_text(errors='replace')
        ok, message, details = evaluate(c, execution, log)
        try:
            if ok and (not (d / 'wave.vcd').is_file() or '$enddefinitions' not in (d / 'wave.vcd').read_text(errors='replace')):
                raise ValueError('waveform missing')
            if ok and not c['expected_failure']:
                bins = native_bins(d / 'coverage.dat')
                details['covergroup_bins'] = bins
                # Complete runs must hit every bin; a run without coverage must hit none.
                if (c['id'].startswith('seed') and not all(bins.values())) or (not c['coverage'] and any(bins.values())):
                    raise ValueError('covergroup hits do not match the coverage setting')
        except (OSError, ValueError) as exc:
            ok, message = False, str(exc)
        # Only complete, unmodified runs count toward the coverage goals.
        if ok and c['id'].startswith('seed'):
            hits.update(details['covers'])
        record = dict(c, success=ok, message=message, details=details, execution=execution)
        records.append(record)
        E.P.write_json(d / 'result.json', record)
        e.check(c['id'], ok, message)
    normal = [r for r in records if r['id'].startswith('seed')]
    e.check('coverage', len(normal) == len(seeds) and all(r['success'] for r in normal) and GOALS <= hits, dict(required=sorted(GOALS), missing=sorted(GOALS - hits)))
    E.P.write_json(e.out / 'executions.json', records)
    manifest = json.loads((e.out / 'manifest.json').read_text())['source_sha256']
    changed = [n for n, h in manifest.items() if not (ROOT / n).is_file() or hashlib.sha256((ROOT / n).read_bytes()).hexdigest() != h]
    e.check('source-freshness', not changed, changed)
    return e.finish()


def main():
    p = E.parser(__doc__, 'local-uvm-reg-sequences')
    p.add_argument('--uvm-home', type=Path, required=True)
    p.add_argument('--verilator', default='verilator')
    p.add_argument('--jobs', type=int, default=4)
    p.add_argument('--build-timeout', type=float, default=600)
    a = p.parse_args()
    E.validate(p, a)
    if not (a.uvm_home / 'src/uvm_pkg.sv').is_file() or not 1 <= a.jobs <= 32 or not math.isfinite(a.build_timeout) or a.build_timeout <= 0 or a.seed > 2**31 - 4:
        p.error('prepared UVM 2020-3.2 (--uvm-home with src/uvm_pkg.sv), valid jobs/seed and finite build limit required')
    try:
        return run(a)
    except (OSError, ValueError, KeyError, TypeError, RuntimeError) as exc:
        print('REG_SEQUENCES_ERROR', exc, file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())

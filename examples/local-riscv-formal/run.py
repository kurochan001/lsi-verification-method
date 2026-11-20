#!/usr/bin/env python3
"""Bounded checks on a retirement interface in the style of RVFI: results, memory accesses, register consistency and the pc chain of the RV32I core, with its mutants."""
from concurrent.futures import ThreadPoolExecutor
import importlib.util
import json
from pathlib import Path
import shutil
import sys
from types import SimpleNamespace

HERE = Path(__file__).resolve().parent
EXAMPLES = HERE.parent


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


E = load('riscv_formal_evidence', EXAMPLES / 'local-exploration-common/evidence.py')
F = load('riscv_formal_runner', EXAMPLES / 'local-formal-common/runner.py')
P = E.P
NAME = 'local-riscv-formal'
TOP = 'rvfi_formal'
HARNESS = HERE / 'rvfi_formal.sv'
RTL = [EXAMPLES / 'local-riscv-decoder/rtl/rv32i_decoder.sv', EXAMPLES / 'local-riscv-pmp/rtl/pmp.sv',
       EXAMPLES / 'local-riscv-iss/rtl/rv32i_core.sv']
SOURCES = [*RTL, HARNESS]
REQUIREMENTS = HERE / 'requirements.json'
CONFIGS = {'none': 0, 'static': 1, 'dynamic': 2}     # PREDICT of the core
# Assertions of each group of the harness (parameter CHECK is the sum of the selected groups).
GROUPS = {1: {'ap_rd_addr', 'ap_rd_value'}, 2: {'ap_bus', 'ap_load', 'ap_store', 'ap_mem_addr'},
          4: {'ap_reg_rs1', 'ap_reg_rs2'}, 8: {'ap_halt', 'ap_pc_first', 'ap_pc_chain'}}
COVERS = {'cp_lui', 'cp_auipc', 'cp_jal', 'cp_jalr', 'cp_taken', 'cp_not_taken', 'cp_load', 'cp_store', 'cp_opimm',
          'cp_op', 'cp_forward1', 'cp_forward2', 'cp_load_use', 'cp_wait', 'cp_reg_read', 'cp_halt'}
CLASSES = {1: 'link', 2: 'add', 3: 'logic', 4: 'shift', 5: 'compare'}
# The first instruction retires in step 6. The pc chain and the register check run DEPTH steps;
# the result and memory checks, whose data paths cost far more to search, run VALUE_DEPTH steps:
# four retirements, enough for forwarding over one, two and three instructions, a load followed
# by its use, and a flush (see README).
DEPTH = 11
VALUE_DEPTH = 10
COVER_DEPTH = 16
# Mutants of the core, the configuration and check that show each, and the assertion expected to
# fail. None: the mutant changes no retired result, so the same checks must still pass.
MUTANTS = {
    1: ('none', dict(CHECK=1, CLASS=2), 'ap_rd_value'),
    2: ('none', dict(CHECK=1, CLASS=2), 'ap_rd_value'),
    3: ('none', dict(CHECK=8), 'ap_pc_chain'),
    4: ('none', dict(CHECK=1, CLASS=2, NO_WAIT=0, SIMPLE=1), 'ap_rd_value'),
    5: ('static', dict(CHECK=8), 'ap_pc_chain'),
    6: ('static', dict(CHECK=8), None),
    7: ('static', dict(CHECK=8), None),
    8: ('static', dict(CHECK=8), 'ap_pc_chain'),
    9: ('none', dict(CHECK=2), 'ap_load'),
    10: ('none', dict(CHECK=2), 'ap_store'),
    11: ('none', dict(CHECK=2), 'ap_load'),
    12: ('none', dict(CHECK=1, CLASS=2), 'ap_rd_value'),
}


def task(name, configuration, mode='bmc', expect='PASS', depth=DEPTH, category='normal', failure=None, mutation=0, **parameters):
    values = dict(PREDICT=CONFIGS[configuration], MUTATION=mutation, CHECK=15, CLASS=0, SIMPLE=0, NO_WAIT=1, LOCK_RESET=0)
    values.update(parameters)
    return dict(id=name, configuration=configuration, mode=mode, expect=expect, depth=depth, category=category,
                failure=failure, parameters=values)


def plan(profile, demo_bug=0):
    """Nightly adds the result and memory checks under both predictors, and one more step to the pc and register checks."""
    tasks = []
    more = 1 if profile == 'nightly' else 0
    deep, value = DEPTH + more, VALUE_DEPTH   # one more step of the value checks took over ten minutes
    for configuration in CONFIGS:
        tasks.append(task(f'{configuration}-pc-chain', configuration, depth=deep, mutation=demo_bug, CHECK=8))
        tasks.append(task(f'{configuration}-register-consistency', configuration, depth=deep, mutation=demo_bug, CHECK=4))
        if configuration == 'none' or profile == 'nightly':
            tasks.append(task(f'{configuration}-memory-access', configuration, depth=value, mutation=demo_bug, CHECK=2))
            for number, label in CLASSES.items():
                tasks.append(task(f'{configuration}-result-{label}', configuration, depth=value, mutation=demo_bug, CHECK=1, CLASS=number))
    tasks.append(task('none-waits-result-add', 'none', depth=value, mutation=demo_bug, CHECK=1, CLASS=2, NO_WAIT=0, SIMPLE=1))
    tasks.append(task('none-waits-pc-chain', 'none', depth=deep, mutation=demo_bug, CHECK=8, NO_WAIT=0, SIMPLE=1))
    tasks.append(task('none-scenario-cover', 'none', mode='cover', depth=COVER_DEPTH, NO_WAIT=0))
    for number, (configuration, parameters, failure) in MUTANTS.items():
        if failure:
            tasks.append(task(f'{configuration}-detect-mutation{number}', configuration, expect='FAIL', category='mutation',
                              failure=failure, mutation=number, **parameters))
        else:
            tasks.append(task(f'{configuration}-invisible-mutation{number}', configuration, category='diagnostic',
                              mutation=number, **parameters))
    tasks.append(task('none-overconstrained', 'none', mode='cover', expect='FAIL', depth=COVER_DEPTH, category='diagnostic', LOCK_RESET=1))
    if len({t['id'] for t in tasks}) != len(tasks):
        raise ValueError('duplicate task id')
    return tasks


def enabled(case):
    """The assertions a task compiles and can fail: those of the groups its CHECK selects."""
    return set().union(*(names for bit, names in GROUPS.items() if case['parameters']['CHECK'] & bit))


def properties(parameters, case):
    """What the compiled model must contain. The cover goal on memory waits needs waits."""
    covers = COVERS if case['parameters']['NO_WAIT'] == 0 else COVERS - {'cp_wait'}
    return {'assert': enabled(case), 'assume': {'as_legal'}, 'cover': covers}


def sby_text(case, timeout):
    settings = ''.join(f'chparam -set {key} {value} {TOP}\n' for key, value in case['parameters'].items())
    names = ' '.join(path.name for path in SOURCES)
    return (f"[options]\nmode {case['mode']}\ndepth {case['depth']}\ntimeout {max(1, int(timeout) - 5)}\n\n"
            f"[engines]\nsmtbmc z3\n\n[script]\nread -formal -sv {names}\n{settings}prep -top {TOP}\nopt_clean\nopt_expr\n"
            f"write_json ../model/inventory.json\nasync2sync\nmemory_map\nopt -full\n\n[files]\n" +
            '\n'.join(path.name for path in SOURCES) + '\n')


def run_task(args, out, case):
    directory = out / case['id']
    directory.mkdir()
    for source in SOURCES:
        shutil.copy2(source, directory / source.name)
    (directory / 'task.sby').write_text(sby_text(case, args.formal_timeout))
    execution = P.execute([args.sby, '--yosys', args.yosys, '--smtbmc', args.smtbmc, '--witness', args.witness, 'task.sby'],
                          directory / 'console.log', args.formal_timeout, directory)
    work = directory / 'task'
    status_file = work / 'status'
    status = status_file.read_text().split()[0] if status_file.exists() and status_file.read_text().strip() else 'MISSING'
    log = (work / 'logfile.txt').read_text(errors='replace') if (work / 'logfile.txt').exists() else ''
    wanted = properties(None, case)
    traces, inventory = [], None
    try:
        traces = F.witnessed_traces(work / 'engine_0', out)
        if status in ('PASS', 'FAIL') and not execution['error']:
            inventory = F.inventory(work / 'model/inventory.json', SimpleNamespace(TOP=TOP, properties=properties), {}, case)
        outcome, message = judge(case, execution, status, log, traces, wanted)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        outcome, message = 'error', 'invalid evidence: ' + str(exc)
    reached = sorted(F.observed(log)[0])
    record = dict(id=case['id'], configuration=case['configuration'], category=case['category'], mode=case['mode'],
                  depth=case['depth'], parameters=case['parameters'], outcome=outcome, message=message, formal_status=status,
                  inventory=inventory, traces=traces, reached=reached, **execution)
    P.write_json(directory / 'result.json', record)
    return record


def judge(case, execution, status, log, traces, wanted):
    """The common verdict, with one addition: a diagnostic cover run must reach nothing at all."""
    if case['category'] == 'diagnostic' and case['mode'] == 'cover':
        if execution['error']:
            return 'error', execution['error']
        reached, unreached, failed = F.observed(log)
        if status == 'FAIL' and execution['returncode'] == 2 and not reached and unreached == set(wanted['cover']) and not failed:
            return 'detected', 'a core held in reset reaches none of the goals'
        return 'error', 'the over-constrained run did not end with every goal unreached'
    return F.judge(case, execution, status, log, traces, wanted)


def audit_requirements(catalog, tasks, records):
    """Every goal names a planned task; a requirement holds when all its tasks ended as planned."""
    by_id = {record['id']: record for record in records}
    planned = {t['id'] for t in tasks}
    rows, unknown = [], []
    for requirement in catalog['requirements']:
        goals = [g for g in requirement['goals'] if not g.startswith('nightly:')]
        goals += [g.split(':', 1)[1] for g in requirement['goals'] if g.startswith('nightly:') and g.split(':', 1)[1] in planned]
        unknown += [g for g in goals if g not in planned]
        rows.append(dict(id=requirement['id'], goals=goals,
                         passed=bool(goals) and all(by_id.get(g, {}).get('outcome') in ('pass', 'detected') for g in goals)))
    return rows, unknown


def main():
    parser = E.parser(__doc__, NAME)
    parser.add_argument('--demo-bug', type=int, choices=range(len(MUTANTS) + 1), default=0)
    parser.add_argument('--jobs', type=int, default=4)
    parser.add_argument('--formal-timeout', type=float, default=900)
    for name, default in (('sby', 'yowasp-sby'), ('yosys', 'yowasp-yosys'), ('smtbmc', 'yowasp-yosys-smtbmc'), ('witness', 'yowasp-yosys-witness')):
        parser.add_argument('--' + name, default=default)
    args = parser.parse_args()
    E.validate(parser, args)
    if not 1 <= args.jobs <= 16 or args.formal_timeout <= 10:
        parser.error('1..16 jobs and a formal timeout above 10 seconds required')
    try:
        tasks = plan(args.profile, args.demo_bug)
        catalog = json.loads(REQUIREMENTS.read_text())
        ids = ['toolchain', *[t['id'] for t in tasks], 'cover-goals', 'requirements', 'inputs-unchanged']
        evidence = E.Evidence(NAME, args, [Path(__file__), Path(F.__file__), REQUIREMENTS, *SOURCES],
                              dict(tasks=tasks, depth=DEPTH, value_depth=VALUE_DEPTH, cover_depth=COVER_DEPTH), ids)
        out = evidence.out
        tools = {}
        for name, command in (('yosys', [args.yosys, '-V']), ('sby', [args.sby, '--version']), ('z3', ['z3', '--version'])):
            log = out / (name + '-version.log')
            tools[name] = dict(P.execute(command, log, args.timeout, out), output=log.read_text(errors='replace').strip())
        P.write_json(out / 'tools.json', tools)
        evidence.check('toolchain', all(not t['error'] and t['returncode'] == 0 and t['output'] for t in tools.values()),
                       {name: t['output'] for name, t in tools.items()})
        with ThreadPoolExecutor(max_workers=args.jobs) as pool:
            records = list(pool.map(lambda case: run_task(args, out, case), tasks))
        for record in records:
            evidence.check(record['id'], record['outcome'] in ('pass', 'detected'),
                           dict(outcome=record['outcome'], message=record['message'], seconds=round(record['seconds'], 1)))
        cover = next(r for r in records if r['id'] == 'none-scenario-cover')
        credited = set(cover['reached']) if cover['outcome'] == 'pass' else set()
        P.write_json(out / 'coverage.json', dict(required=sorted(COVERS), hit=sorted(credited), missing=sorted(COVERS - credited)))
        evidence.check('cover-goals', credited == COVERS, sorted(COVERS - credited))
        rows, unknown = audit_requirements(catalog, tasks, records)
        P.write_json(out / 'requirements.json', dict(revision=catalog['revision'], requirements=rows, unknown_goals=unknown))
        evidence.check('requirements', not unknown and all(row['passed'] for row in rows),
                       dict(unknown=unknown, failed=[row['id'] for row in rows if not row['passed']]))
        frozen = json.loads((out / 'manifest.json').read_text())['source_sha256']
        changed = [name for name, digest in frozen.items()
                   if not (E.ROOT / name).is_file() or E.hashlib.sha256((E.ROOT / name).read_bytes()).hexdigest() != digest]
        evidence.check('inputs-unchanged', not changed, changed)
        return evidence.finish()
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print('RUNNER_ERROR', exc, file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())

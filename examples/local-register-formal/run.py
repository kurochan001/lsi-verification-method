#!/usr/bin/env python3
"""Generate formal properties per field attribute from SystemRDL, check the generator against hand-written tables, and prove two register blocks with their mutants."""
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


E = load('register_formal_evidence', EXAMPLES / 'local-exploration-common/evidence.py')
F = load('register_formal_runner', EXAMPLES / 'local-formal-common/runner.py')
P = E.P
NAME = 'local-register-formal'
GENERATOR = HERE / 'generate_properties.py'
BINDINGS = HERE / 'bindings.json'
REQUIREMENTS = HERE / 'requirements.json'
SPEC = EXAMPLES / 'local-register-spec'
SPEC_INPUTS = [SPEC / 'generate.py', SPEC / 'registers.rdl', SPEC / 'contract.json']
WIDE_RTL = HERE / 'rtl/reg_block.sv'
TABLES = {name: HERE / f'expected/{name}.json' for name in ('spec', 'wide')}
INPUTS = [GENERATOR, BINDINGS, REQUIREMENTS, HERE / 'registers.rdl', WIDE_RTL, *TABLES.values(), *SPEC_INPUTS]
PROVE_DEPTH = 6
COVER_DEPTH = 16
# Mutants of each block and the assertion that must fail. The block of local-register-spec
# carries mutants 1 to 3 in its generated RTL; reg_block.sv carries 1 to 8.
MUTANTS = {
    'spec': {1: 'ap_cfg_value_reset', 2: 'ap_cfg_value_write', 3: 'ap_pending_value_event'},
    'wide': {1: 'ap_ctrl_mode_reset', 2: 'ap_ctrl_mode_write', 3: 'ap_ctrl_rev_const', 4: 'ap_status_err_w1c',
             5: 'ap_ctrl_reserved', 6: 'ap_unmapped_error', 7: 'ap_status_done_event', 8: 'ap_status_done_read'},
}
# Generator errors (generate_properties.py --demo-bug), tried on the wide map. Each entry:
# whether the proof of the correct block still passes, the assertions one of which fails
# when it does not, and a mutant that escapes the weakened properties.
GENERATOR_BUGS = {
    1: dict(proof='PASS', escape=5),
    2: dict(proof='FAIL', failures=['ap_status_done_hold', 'ap_status_err_hold', 'ap_status_done_write', 'ap_status_err_write']),
    3: dict(proof='FAIL', failures=['ap_ctrl_mode_reset', 'ap_ctrl_rev_reset', 'ap_ctrl_rev_const', 'ap_id_value_reset', 'ap_id_value_const']),
    4: dict(proof='PASS'),
    5: dict(proof='PASS', escape=5),
}


def variants(profile):
    """The property sets to generate: (key, configuration, demo bug, idle assumption)."""
    rows = [('spec', 'spec', 0, False), ('wide', 'wide', 0, False), ('spec-idle', 'spec', 0, True), ('wide-idle', 'wide', 0, True),
            ('spec-bug5', 'spec', 5, False)]
    rows += [(f'wide-bug{bug}', 'wide', bug, False) for bug in GENERATOR_BUGS]
    return rows


def task(name, block, variant, mode='prove', expect='PASS', category='normal', failures=(), mutation=0, wait=0):
    parameters = dict(MUTATION=mutation)
    if block == 'spec':
        parameters['WAIT_CYCLES'] = wait
    return dict(id=name, block=block, variant=variant, mode=mode, expect=expect, category=category,
                failures=list(failures), parameters=parameters, depth=COVER_DEPTH if mode == 'cover' else PROVE_DEPTH)


def plan(profile, demo_bug=0):
    """Nightly repeats the proofs of the generated block with two wait cycles in every transfer."""
    tasks = []
    blocks = [('spec', 'spec', 0), ('wide', 'wide', 0)]
    if profile == 'nightly':
        blocks.append(('spec-wait2', 'spec', 2))
    for prefix, block, wait in blocks:
        tasks.append(task(f'{prefix}-prove', block, block, mutation=demo_bug, wait=wait))
        tasks.append(task(f'{prefix}-cover', block, block, mode='cover', wait=wait))
        for number, failure in MUTANTS[block].items():
            tasks.append(task(f'{prefix}-detect-mutation{number}', block, block, expect='FAIL', category='mutation',
                              failures=[failure], mutation=number, wait=wait))
    for block in ('spec', 'wide'):
        tasks.append(task(f'{block}-overconstrained', block, block + '-idle', mode='cover', expect='FAIL', category='diagnostic'))
    for bug, row in GENERATOR_BUGS.items():
        variant = f'wide-bug{bug}'
        if row['proof'] == 'PASS':
            tasks.append(task(f'generator-bug{bug}-proof-still-passes', 'wide', variant, category='diagnostic'))
        else:
            tasks.append(task(f'generator-bug{bug}-proof-fails', 'wide', variant, expect='FAIL', category='counterexample',
                              failures=row['failures']))
        if 'escape' in row:
            tasks.append(task(f"generator-bug{bug}-mutation{row['escape']}-escapes", 'wide', variant, category='diagnostic',
                              mutation=row['escape']))
    if len({t['id'] for t in tasks}) != len(tasks):
        raise ValueError('duplicate task id')
    return tasks


def flatten(table):
    """A generated property table in the shape of the hand-written one."""
    def value(v):
        return hex(v) if isinstance(v, int) else v
    return dict(asserts={a['name']: [a['kind'], a['address'], a['lsb'], a['width'], value(a['value'])] for a in table['asserts']},
                covers=sorted(table['covers']), assumes=sorted(table['assumes']))


def expected_table(name):
    table = json.loads(TABLES[name].read_text())
    return dict(asserts=table['asserts'], covers=sorted(table['covers']), assumes=sorted(table['assumes']))


def differences(generated, expected):
    rows = []
    for name in sorted(set(generated['asserts']) | set(expected['asserts'])):
        if generated['asserts'].get(name) != expected['asserts'].get(name):
            rows.append(dict(name=name, generated=generated['asserts'].get(name), expected=expected['asserts'].get(name)))
    for kind in ('covers', 'assumes'):
        if generated[kind] != expected[kind]:
            rows.append(dict(name=kind, generated=generated[kind], expected=expected[kind]))
    return rows


def same_contract(model, contract):
    """The fields read here against the hand-written contract of local-register-spec."""
    mine = sorted((r['name'], r['address'], f['width'], f['reset'], f['access']) for r in model for f in r['fields'])
    theirs = sorted((r['name'], r['address'], r['width'], r['reset'], r['access']) for r in contract)
    return all(len(r['fields']) == 1 and r['fields'][0]['lsb'] == 0 for r in model) and mine == theirs


def formal_source(source):
    """Yosys reads neither bind nor a hierarchical reference, so the generated properties go into
    a copy of the module, in front of its last endmodule. The tracked RTL is not touched."""
    text = source.read_text()
    index = text.rfind('endmodule')
    if index < 0 or text.count('endmodule') != 1:
        raise ValueError('one module per register file expected')
    return text[:index] + '`include "properties.svh"\n' + text[index:]


def sby_text(case, module, timeout):
    settings = ''.join(f'chparam -set {key} {value} {module}\n' for key, value in case['parameters'].items())
    return (f"[options]\nmode {case['mode']}\ndepth {case['depth']}\ntimeout {max(1, int(timeout) - 5)}\n\n"
            f"[engines]\nsmtbmc z3\n\n[script]\nread -formal -sv dut.sv\n{settings}prep -top {module}\n"
            f"write_json ../model/inventory.json\n\n[files]\ndut.sv\nproperties.svh\n")


def judge(case, execution, status, log, traces, wanted):
    """The common verdict, with two additions. A planned failure may name several assertions, any of
    which confirms it. With no transfer ever started, only the goals that need none (a hardware
    event setting a bit) may still be reached."""
    if case['category'] == 'diagnostic' and case['mode'] == 'cover':
        if execution['error']:
            return 'error', execution['error']
        reached, unreached, failed = F.observed(log)
        free = {name for name in wanted['cover'] if name.endswith('_event')}
        if status == 'FAIL' and execution['returncode'] == 2 and reached == free and unreached == set(wanted['cover']) - free and not failed:
            return 'detected', 'without a transfer only the event goals are reached'
        return 'error', 'the idle environment did not leave exactly the transfer goals unreached'
    if not case['failures']:
        return F.judge(dict(case, failure=None), execution, status, log, traces, wanted)
    verdict = ('error', 'no candidate')
    for failure in case['failures']:
        verdict = F.judge(dict(case, failure=failure), execution, status, log, traces, wanted)
        if verdict[0] == 'detected':
            break
    return verdict


def run_task(args, out, case, context):
    directory = out / case['id']
    directory.mkdir()
    module = context['modules'][case['block']]
    (directory / 'dut.sv').write_text(formal_source(context['rtl'][case['block']]))
    shutil.copy2(out / 'generated' / case['variant'] / 'properties.svh', directory / 'properties.svh')
    (directory / 'task.sby').write_text(sby_text(case, module, args.formal_timeout))
    execution = P.execute([args.sby, '--yosys', args.yosys, '--smtbmc', args.smtbmc, '--witness', args.witness, 'task.sby'],
                          directory / 'console.log', args.formal_timeout, directory)
    work = directory / 'task'
    status_file = work / 'status'
    status = status_file.read_text().split()[0] if status_file.exists() and status_file.read_text().strip() else 'MISSING'
    log = (work / 'logfile.txt').read_text(errors='replace') if (work / 'logfile.txt').exists() else ''
    table = context['wanted'][case['variant']]
    wanted = {'assert': set(table['asserts']), 'assume': set(table['assumes']), 'cover': set(table['covers'])}
    traces, inventory = [], None
    try:
        traces = F.witnessed_traces(work / 'engine_0', out)
        if status in ('PASS', 'FAIL') and not execution['error']:
            inventory = F.inventory(work / 'model/inventory.json', SimpleNamespace(TOP=module, properties=lambda p, c: wanted), {}, case)
        outcome, message = judge(case, execution, status, log, traces, wanted)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        outcome, message = 'error', 'invalid evidence: ' + str(exc)
    record = dict(id=case['id'], block=case['block'], variant=case['variant'], category=case['category'], mode=case['mode'],
                  depth=case['depth'], parameters=case['parameters'], outcome=outcome, message=message, formal_status=status,
                  inventory=inventory, traces=traces, reached=sorted(F.observed(log)[0]), failed=sorted(F.observed(log)[2]), **execution)
    P.write_json(directory / 'result.json', record)
    return record


def audit_requirements(catalog, planned, passed):
    """Every goal names a planned check; a requirement holds when all its checks passed."""
    rows, unknown = [], []
    for requirement in catalog['requirements']:
        goals = [g for g in requirement['goals'] if not g.startswith('nightly:')]
        goals += [g.split(':', 1)[1] for g in requirement['goals'] if g.startswith('nightly:') and g.split(':', 1)[1] in planned]
        unknown += [g for g in goals if g not in planned]
        rows.append(dict(id=requirement['id'], goals=goals, passed=bool(goals) and all(g in passed for g in goals)))
    return rows, unknown


def check_ids(tasks, kinds):
    ids = ['toolchain', 'generate-rtl', *[f'generate-{key}' for key, *_ in kinds], 'spec-contract', 'spec-table', 'wide-table']
    ids += [f'generator-bug{bug}-table-rejects' for bug in GENERATOR_BUGS]
    ids += ['generator-bug5-invisible-on-spec', *[t['id'] for t in tasks], 'cover-goals', 'requirements', 'inputs-unchanged']
    return ids


def main():
    parser = E.parser(__doc__, NAME)
    parser.add_argument('--demo-bug', type=int, choices=range(max(len(m) for m in MUTANTS.values()) + 1), default=0,
                        help='run the normal proofs on a mutant (the spec block has mutants 1 to 3 only)')
    parser.add_argument('--jobs', type=int, default=4)
    parser.add_argument('--formal-timeout', type=float, default=300)
    parser.add_argument('--rdl-python', default=sys.executable, help='Python with systemrdl-compiler, for the two generators')
    for name, default in (('sby', 'yowasp-sby'), ('yosys', 'yowasp-yosys'), ('smtbmc', 'yowasp-yosys-smtbmc'), ('witness', 'yowasp-yosys-witness')):
        parser.add_argument('--' + name, default=default)
    args = parser.parse_args()
    E.validate(parser, args)
    if not 1 <= args.jobs <= 16 or args.formal_timeout <= 10:
        parser.error('1..16 jobs and a formal timeout above 10 seconds required')
    try:
        tasks = plan(args.profile, args.demo_bug)
        kinds = variants(args.profile)
        catalog = json.loads(REQUIREMENTS.read_text())
        bindings = json.loads(BINDINGS.read_text())
        ids = check_ids(tasks, kinds)
        evidence = E.Evidence(NAME, args, [Path(__file__), Path(F.__file__), *INPUTS],
                              dict(tasks=tasks, variants=[list(k) for k in kinds], prove_depth=PROVE_DEPTH, cover_depth=COVER_DEPTH), ids)
        out = evidence.out
        tools = {}
        for name, command in (('yosys', [args.yosys, '-V']), ('sby', [args.sby, '--version']), ('z3', ['z3', '--version']),
                              ('systemrdl', [args.rdl_python, '-c', 'import importlib.metadata as m; print(m.version("systemrdl-compiler"))'])):
            log = out / (name + '-version.log')
            tools[name] = dict(P.execute(command, log, args.timeout, out), output=log.read_text(errors='replace').strip())
        P.write_json(out / 'tools.json', tools)
        ready = evidence.check('toolchain', all(not t['error'] and t['returncode'] == 0 and t['output'] for t in tools.values()),
                               {name: t['output'] for name, t in tools.items()})
        generated = out / 'generated'
        generated.mkdir()
        rtl = P.execute([args.rdl_python, str(SPEC / 'generate.py'), str(SPEC / 'registers.rdl'), '--out', str(generated / 'spec-rtl')],
                        out / 'generate-rtl.log', args.timeout, out) if ready else dict(error='toolchain missing', returncode=None)
        ready = evidence.check('generate-rtl', not rtl['error'] and rtl['returncode'] == 0 and (generated / 'spec-rtl/rdl_regs.sv').is_file(), rtl) and ready
        tables = {}
        for key, configuration, bug, idle in kinds:
            source = (HERE / bindings[configuration]['source']).resolve()
            command = [args.rdl_python, str(GENERATOR), str(source), '--bindings', str(BINDINGS), '--configuration', configuration,
                       '--out', str(generated / key), '--demo-bug', str(bug), *(['--idle'] if idle else [])]
            run = P.execute(command, out / f'generate-{key}.log', args.timeout, out) if ready else dict(error='not started', returncode=None)
            done = not run['error'] and run['returncode'] == 0 and (generated / key / 'properties.svh').is_file()
            if done:
                tables[key] = flatten(json.loads((generated / key / 'properties.json').read_text()))
            evidence.check(f'generate-{key}', done, run)
        if len(tables) != len(kinds):
            return evidence.finish()
        expected = {name: expected_table(name) for name in TABLES}
        model = json.loads((generated / 'spec/model.json').read_text())
        evidence.check('spec-contract', same_contract(model, json.loads((SPEC / 'contract.json').read_text())), model)
        for name in TABLES:
            rows = differences(tables[name], expected[name])
            evidence.check(f'{name}-table', not rows, rows)
        report = {}
        for bug in GENERATOR_BUGS:
            rows = differences(tables[f'wide-bug{bug}'], expected['wide'])
            report[bug] = rows
            evidence.check(f'generator-bug{bug}-table-rejects', bool(rows), rows[:4])
        P.write_json(out / 'generator-bugs.json', report)
        evidence.check('generator-bug5-invisible-on-spec', not differences(tables['spec-bug5'], expected['spec']),
                       'one field per register from bit 0: this error changes nothing, so the simple map cannot show it')
        # Normal tasks must compile exactly the hand-written names; the variants compile what they generated.
        wanted = dict(tables)
        wanted.update(expected)
        for key in ('spec-idle', 'wide-idle'):
            base = expected[key.split('-')[0]]
            wanted[key] = dict(base, assumes=sorted([*base['assumes'], 'as_idle']))
        context = dict(wanted=wanted, modules={name: bindings[name]['module'] for name in bindings},
                       rtl=dict(spec=generated / 'spec-rtl/rdl_regs.sv', wide=WIDE_RTL))
        with ThreadPoolExecutor(max_workers=args.jobs) as pool:
            records = list(pool.map(lambda case: run_task(args, out, case, context), tasks))
        for record in records:
            evidence.check(record['id'], record['outcome'] in ('pass', 'detected'),
                           dict(outcome=record['outcome'], message=record['message'], seconds=round(record['seconds'], 1)))
        coverage = {}
        for record in records:
            if record['mode'] == 'cover' and record['category'] == 'normal':
                required = set(expected[record['block']]['covers'])
                hit = set(record['reached']) if record['outcome'] == 'pass' else set()
                coverage[record['id']] = dict(required=sorted(required), hit=sorted(hit & required), missing=sorted(required - hit))
        P.write_json(out / 'coverage.json', coverage)
        evidence.check('cover-goals', bool(coverage) and not any(row['missing'] for row in coverage.values()),
                       {name: row['missing'] for name, row in coverage.items()})
        passed = {r['id'] for r in evidence.results if r['status'] == 'pass'}
        rows, unknown = audit_requirements(catalog, set(ids), passed)
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

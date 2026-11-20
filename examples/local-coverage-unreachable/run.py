#!/usr/bin/env python3
"""Classify unhit code coverage points with formal cover and induction, and audit the exclusion ledger."""
from concurrent.futures import ThreadPoolExecutor
import copy
import fnmatch
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import re
import shutil
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
NAME = 'local-coverage-unreachable'
spec = importlib.util.spec_from_file_location('unreachable_code_coverage', HERE.parent / 'local-code-coverage/run.py')
C = importlib.util.module_from_spec(spec)
spec.loader.exec_module(C)
E, P = C.E, C.E.P
ITEMS = HERE / 'items.json'
LEDGER = HERE / 'exclusions.json'
REQUIREMENTS = HERE / 'requirements.json'
GUARDED = HERE / 'rtl/guarded_unit.sv'
HARNESS = C.HERE / 'sim_main.cpp'
PLAN = C.HERE / 'coverage-plan.json'
MEASURED_KINDS = ('line', 'branch', 'fsm_state', 'fsm_arc')   # expr and toggle points are not classified here
CONFIGURATION = 'width8'
CLASSES = ('reachable', 'unreachable', 'conditional', 'unclassified', 'invalid')
EXCLUDABLE = ('unreachable', 'conditional')
ENGINE = 'smtbmc z3'


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def text_sha256(text):
    return hashlib.sha256(text.encode()).hexdigest()


def load_items(path=ITEMS):
    """The item table: targets, assumptions, helpers and one pinned class per item."""
    data = json.loads(Path(path).read_text())
    if data.get('schema_version') != 1 or type(data.get('revision')) is not int:
        raise ValueError('ITEMS: unsupported version')
    ids = [item['id'] for item in data['items']]
    if not ids or len(set(ids)) != len(ids) or any(not re.fullmatch(r'[a-z0-9-]+', name) for name in ids):
        raise ValueError('ITEMS: empty, duplicate or malformed item id')
    for item in data['items']:
        target = data['targets'][item['target']]
        if (item['expected'] not in CLASSES or not item['expression'].strip() or not 2 <= item['depth'] <= 40 or
                set(item['assumptions']) - data['assumptions'].keys() or set(item['helpers']) - data['helpers'].keys() or
                any(data['assumptions'][name]['implicit'] for name in item['assumptions'])):
            raise ValueError('ITEMS: invalid item ' + item['id'])
        if (item['category'] == 'measured') != bool(target['measured']) or ('point' in item) != (item['category'] == 'measured'):
            raise ValueError('ITEMS: only items of the measured target carry a coverage point: ' + item['id'])
    for name, assumption in data['assumptions'].items():
        if not assumption['source'].strip() or not re.search(r'\b%s:assume\(' % re.escape(name), assumption['statement']):
            raise ValueError('ITEMS: assumption without source or label: ' + name)
    return data


def implicit_assumptions(data):
    return sorted(name for name, assumption in data['assumptions'].items() if assumption['implicit'])


def harness(source, data, checks, assumptions):
    """The RTL with assumptions and checks placed before its last endmodule. The checked-in file is not changed."""
    position = source.rindex('endmodule')
    lines = [' // Added by run.py for this task.', ' reg f_past=1\'b0;', ' always @(posedge clk)begin', '  f_past<=1\'b1;']
    lines += ['  ' + data['assumptions'][name]['statement'] for name in assumptions]
    lines.append('  if(f_past)begin')
    for flavor, name, expression in checks:
        body = f'cover({expression})' if flavor == 'cover' else f'assert(!({expression}))' if flavor == 'never' else f'assert({expression})'
        lines.append(f'   {name}:{body};')
    lines += ['  end', ' end', 'endmodule', '']
    return source[:position] + '\n'.join(lines)


def make_task(data, name, target, mode, depth, checks, assumptions):
    """One SBY task. `checks` are (flavor, label, expression) with flavor cover, never or helper."""
    if mode not in ('cover', 'prove', 'bmc') or not checks or len({label for _, label, _ in checks}) != len(checks):
        raise ValueError('TASK: invalid task ' + name)
    assumptions = sorted(set(implicit_assumptions(data)) | set(assumptions))
    return dict(id=name, target=target, mode=mode, depth=depth, checks=[list(check) for check in checks], assumptions=assumptions,
                covers=sorted(label for flavor, label, _ in checks if flavor == 'cover'),
                asserts=sorted(label for flavor, label, _ in checks if flavor != 'cover'))


def item_tasks(data, item, cross=False):
    """Cover first; a proof only when the item is not expected to be reached, or as the nightly cross-check."""
    helpers = [('helper', name, data['helpers'][name]) for name in item['helpers']]
    common = (item['target'], )
    tasks = {'cover': make_task(data, 'cover-' + item['id'], *common, 'cover', item['depth'], [('cover', 'target', item['expression'])], item['assumptions'])}
    if item['expected'] != 'reachable' or cross:
        tasks['prove'] = make_task(data, 'prove-' + item['id'], *common, 'prove', item['depth'],
                                   [('never', 'target', item['expression']), *helpers], item['assumptions'])
    return tasks


def goal_task(data, target, assumption):
    goals = data['targets'][target]['goals']
    return make_task(data, 'goals-' + assumption, target, 'cover', data['targets'][target]['goal_depth'],
                     [('cover', name, expression) for name, expression in sorted(goals.items())], [assumption])


def plan_tasks(data, profile):
    """Every SBY task of the run, by id, and the check ids in a fixed order."""
    tasks, checks = {}, ['tools', 'measured-build', 'measured-baseline', 'measured-inventory']
    for item in data['items']:
        cross = profile == 'nightly' and item['expected'] == 'reachable' and item['category'] != 'diagnostic'
        for task in item_tasks(data, item, cross).values():
            tasks[task['id']] = task
        checks.append('classify-' + item['id'])
        if item['category'] == 'measured' and item['expected'] == 'reachable':
            checks.append('replay-' + item['id'])
        if cross:
            checks.append('cross-' + item['id'])
    checks.append('measured-closure')
    for item in data['items']:
        for assumption in item['assumptions']:
            task = goal_task(data, item['target'], assumption)
            if task['id'] not in tasks:
                tasks[task['id']] = task
                checks.append(task['id'])
    shallow = next(item for item in data['items'] if item['id'] == 'gu-stall-shallow')
    tasks['bmc-gu-stall-shallow'] = make_task(data, 'bmc-gu-stall-shallow', shallow['target'], 'bmc', shallow['depth'],
                                              [('never', 'target', shallow['expression'])], shallow['assumptions'])
    checks += ['bounded-pass-is-not-proof', 'ledger-accepted', *('ledger-reject-' + name for name in TAMPERINGS), 'source-identity', 'requirements']
    return tasks, checks


def sby_text(task, top, source_name, parameters, timeout):
    setup = ''.join(f'chparam -set {key} {value} {top}\n' for key, value in parameters.items())
    return (f"[options]\nmode {task['mode']}\ndepth {task['depth']}\ntimeout {max(1, int(timeout) - 5)}\n\n[engines]\n{ENGINE}\n\n"
            f"[script]\nread -formal -sv {source_name}\n{setup}prep -top {top}\nopt_clean\nwrite_json ../model/inventory.json\n"
            f"memory_map\nopt -full\n\n[files]\n{source_name}\n")


def compiled_inventory(path):
    """Labels of the assert, assume and cover statements that the tool compiled."""
    found = {'assert': [], 'assume': [], 'cover': []}
    for module in json.loads(path.read_text())['modules'].values():
        for name, cell in module.get('cells', {}).items():
            if cell['type'] == '$check' and cell['parameters']['FLAVOR'] in found:
                found[cell['parameters']['FLAVOR']].append(name.rsplit('.', 1)[-1])
    return {key: sorted(value) for key, value in found.items()}


def read_log(log):
    def names(pattern):
        return sorted({name.rsplit('.', 1)[-1] for name in re.findall(pattern, log)})
    return dict(reached=names(r'Reached cover statement in step \d+ at [\w.$]+: ([\w.]+)'),
                unreached=names(r'Unreached cover statement at [\w.$]+: ([\w.]+)'),
                failed=names(r'engine_0(?:\.basecase)?: ##[\s\d:]+Assert failed in [\w.$]+: ([\w.]+)'),
                induction='successful proof by k-induction' in log,
                basecase_passed=bool(re.search(r'returned pass for basecase', log)),
                induction_failed=bool(re.search(r'returned FAIL for induction', log)),
                bounded_passed=bool(re.search(r'engine_0: ##[\s\d:]+Status: passed', log)))


def outcome(task, record):
    """What one finished task shows. Tool errors, time-outs and incomplete evidence are `error`, never a finding."""
    if record['error']:
        return 'error', record['error']
    status, code, log = record['formal_status'], record['returncode'], record['log']
    if record['inventory'] != dict(**{'assert': task['asserts']}, assume=task['assumptions'], cover=task['covers']):
        return 'error', 'compiled assertions, assumptions or covers differ from the task'
    if task['mode'] == 'cover':
        if status == 'PASS' and code == 0 and log['reached'] == task['covers'] and not log['unreached'] and record['traces']:
            return 'reached', 'every cover reached with a trace'
        if status == 'FAIL' and code == 2 and log['unreached'] and sorted(log['reached'] + log['unreached']) == task['covers']:
            return 'unreached', 'not reached within %d steps: %s' % (task['depth'], ', '.join(log['unreached']))
        return 'error', 'incomplete cover evidence'
    if task['mode'] == 'prove':
        if status == 'PASS' and code == 0 and log['induction'] and not log['failed']:
            return 'proved', 'proved by k-induction'
        if status == 'UNKNOWN' and code == 4 and log['basecase_passed'] and log['induction_failed']:
            return 'inconclusive', 'holds for %d steps, induction did not finish' % task['depth']
        if status == 'FAIL' and code == 2 and 'target' in log['failed'] and record['traces']:
            return 'refuted', 'counterexample from reset'
        return 'error', 'incomplete proof evidence'
    if status == 'PASS' and code == 0 and log['bounded_passed'] and not log['failed']:
        return 'bounded-pass', 'holds for %d steps only' % task['depth']
    if status == 'FAIL' and code == 2 and 'target' in log['failed'] and record['traces']:
        return 'refuted', 'counterexample from reset'
    return 'error', 'incomplete bounded evidence'


def classify(cover, prove=None, contract_assumptions=(), goals_kept=None):
    """The class of an item from the outcomes of its tasks. Only a trace or a finished induction decides."""
    if cover == 'reached':
        return 'error' if prove == 'proved' else 'reachable'
    if cover != 'unreached' or prove in ('error', 'refuted'):
        return 'error'
    if prove != 'proved':                      # no proof, a bounded pass or an unfinished induction
        return 'unclassified'
    if not contract_assumptions:
        return 'unreachable'
    if goals_kept is None:
        return 'error'
    return 'conditional' if goals_kept else 'invalid'


def decode_witness(path):
    """Input values per step from a Yosys witness file."""
    witness = json.loads(Path(path).read_text())
    if witness.get('format') != 'Yosys Witness Trace' or not witness.get('steps'):
        raise ValueError('WITNESS: not a witness trace')
    steps = []
    for index, step in enumerate(witness['steps']):
        bits, position, row = step['bits'][::-1], 0, {}
        for signal in witness['signals']:
            if signal['init_only'] and index:
                continue
            chunk = bits[position:position + signal['width']]
            position += signal['width']
            if len(chunk) != signal['width']:
                raise ValueError('WITNESS: step shorter than its signals')
            if not signal['init_only'] and len(signal['path']) == 1:
                name = signal['path'][0].lstrip('\\')
                value = int(chunk[::-1].replace('x', '0').replace('?', '0'), 2) << signal['offset']
                row[name] = row.get(name, 0) | value
        if position != len(bits):
            raise ValueError('WITNESS: step longer than its signals')
        steps.append(row)
    return steps


def replay_rows(steps, width=8):
    """Simulation vectors with independent expected values, from the inputs of a cover trace."""
    plan = C.Plan(width)
    for step in steps:
        request = (step['operation'], step['a'], step['b'], step['enable'], step['authorized']) if step['req_valid'] else None
        plan.cycle(rst=step['rst_n'], req=request, ready=step['resp_ready'])
    for _ in range(3):
        plan.cycle()
    return plan.rows


def match_points(zero_ids, items):
    """Tie each unhit point to exactly one item. Returns {item id: point id}."""
    mapping = {}
    for item in items:
        found = [identity for identity in zero_ids
                 if all(json.loads(identity).get(key) == value for key, value in item['point'].items())]
        if len(found) != 1:
            raise ValueError('MEASURED: %s matches %d unhit points' % (item['id'], len(found)))
        mapping[item['id']] = found[0]
    if len(set(mapping.values())) != len(mapping) or set(mapping.values()) != set(zero_ids):
        raise ValueError('MEASURED: unhit points and items are not one to one')
    return mapping


def tool_versions(directory, args):
    """Versions that the ledger pins. YoWASP ships SBY inside the Yosys package, so SBY has no version of its own."""
    logs = {}
    for name, command in (('yosys', [args.yosys, '-V']), ('sby', [args.sby, '--version']), ('z3', ['z3', '--version']),
                          ('verilator', [args.verilator, '--version'])):
        execution = P.execute(command, directory / (name + '-version.log'), args.timeout, directory)
        logs[name] = dict(execution, output=(directory / (name + '-version.log')).read_text(errors='replace').strip())
    def version(name, pattern):
        match = re.search(pattern, logs[name]['output'])
        return match.group(1) if match and not logs[name]['error'] and logs[name]['returncode'] == 0 else None
    return dict(yosys=version('yosys', r'Yosys (\d[\w.+-]*)'), z3=version('z3', r'Z3 version (\d[\w.]*)'),
                verilator=version('verilator', r'Verilator (\d[\w.]*)')), logs


def audit(ledger, data, fresh, source_hashes, versions):
    """Problems of the exclusion ledger against the proofs of this run. An empty list accepts the ledger."""
    problems = []
    if ledger.get('schema_version') != 1 or not isinstance(ledger.get('exclusions'), list) or not ledger['exclusions']:
        return ['LEDGER_FORMAT']
    if any(ledger.get('tools', {}).get(name) != versions.get(name) or not versions.get(name) for name in ('yosys', 'z3')):
        problems.append('LEDGER_TOOL_VERSION')
    items = {item['id']: item for item in data['items']}
    seen = set()
    for entry in ledger['exclusions']:
        name = entry.get('item')
        if name not in items or name in seen:
            problems.append('LEDGER_UNKNOWN_ITEM')
            continue
        seen.add(name)
        item, result = items[name], fresh.get(name, {})
        if entry.get('source_sha256') != source_hashes[item['target']]:
            problems.append('LEDGER_STALE_SOURCE')
        if entry.get('expression_sha256') != text_sha256(item['expression']):
            problems.append('LEDGER_STALE_EXPRESSION')
        if not all(str(entry.get(key, '')).strip() for key in ('reason', 'reviewed', 'expires')):
            problems.append('LEDGER_NO_REVIEW')
        proof = entry.get('proof')
        if not isinstance(proof, dict) or not proof.get('task'):
            problems.append('LEDGER_NO_PROOF')
            continue
        cls = result.get('class')
        if cls == 'reachable':
            problems.append('LEDGER_REACHABLE')
        elif cls == 'invalid':
            problems.append('LEDGER_OVERCONSTRAINED')
        elif proof.get('mode') != 'prove' or cls == 'unclassified':
            problems.append('LEDGER_BOUNDED_ONLY')
        elif cls not in EXCLUDABLE or proof.get('task') != result.get('proof_task') or proof.get('engine') != ENGINE:
            problems.append('LEDGER_NO_PROOF')
        if 'assumptions' not in entry or sorted(entry['assumptions']) != result.get('assumptions'):
            problems.append('LEDGER_ASSUMPTIONS')
        if sorted(entry.get('helpers', [])) != result.get('helpers'):
            problems.append('LEDGER_HELPERS')
        if item['category'] == 'measured' and entry.get('point_id') != result.get('point_id'):
            problems.append('LEDGER_POINT')
    return sorted(set(problems))


def tamper_no_proof(ledger):
    del ledger['exclusions'][0]['proof']


def tamper_stale_source(ledger):
    ledger['exclusions'][0]['source_sha256'] = '0' * 64


def tamper_missing_assumption(ledger):
    entry = next(e for e in ledger['exclusions'] if e['item'] == 'gu-test')
    entry['assumptions'] = [name for name in entry['assumptions'] if name != 'as_functional_mode']


def _added(ledger, data, name, mode='prove'):
    item = next(i for i in data['items'] if i['id'] == name)
    entry = copy.deepcopy(next(e for e in ledger['exclusions'] if e['item'] == 'gu-guard'))
    entry.update(item=name, expression_sha256=text_sha256(item['expression']), helpers=sorted(item['helpers']),
                 assumptions=sorted(set(implicit_assumptions(data)) | set(item['assumptions'])),
                 proof=dict(task=('prove-' if mode == 'prove' else 'bmc-') + name, mode=mode, engine=ENGINE, depth=item['depth']))
    ledger['exclusions'].append(entry)


TAMPERINGS = {
    'no-proof': (tamper_no_proof, 'LEDGER_NO_PROOF'),
    'stale-source': (tamper_stale_source, 'LEDGER_STALE_SOURCE'),
    'missing-assumption': (tamper_missing_assumption, 'LEDGER_ASSUMPTIONS'),
    'reachable': (lambda ledger, data: _added(ledger, data, 'gu-deny'), 'LEDGER_REACHABLE'),
    'bounded-only': (lambda ledger, data: _added(ledger, data, 'gu-stall-shallow', 'bmc'), 'LEDGER_BOUNDED_ONLY'),
    'overconstrained': (lambda ledger, data: _added(ledger, data, 'gu-deny-overconstrained'), 'LEDGER_OVERCONSTRAINED'),
}


def tampered(ledger, data, name):
    changed = copy.deepcopy(ledger)
    function = TAMPERINGS[name][0]
    function(changed, data) if function.__code__.co_argcount == 2 else function(changed)
    return changed


def requirement_coverage(requirements, check_ids, passed, profile):
    """Each goal names planned checks; every planned check belongs to a requirement."""
    rows, owned = [], set()
    for requirement in requirements['requirements']:
        matched = sorted({name for goal in requirement['goals'] for name in check_ids if fnmatch.fnmatchcase(name, goal)})
        empty = [goal for goal in requirement['goals'] if not any(fnmatch.fnmatchcase(name, goal) for name in check_ids)]
        skipped = requirement.get('nightly_only') and profile != 'nightly'
        if empty and not skipped:
            raise ValueError('REQUIREMENTS: goal without a planned check: ' + ', '.join(empty))
        owned.update(matched)
        rows.append(dict(id=requirement['id'], checks=matched, applicable=not skipped,
                         passed=bool(matched) and all(name in passed for name in matched) if not skipped else None))
    orphans = sorted(set(check_ids) - owned - {'requirements'})
    if orphans:
        raise ValueError('REQUIREMENTS: check without a requirement: ' + ', '.join(orphans))
    return rows


def run_task(args, data, task, out):
    """Run one SBY task in its own directory and collect what the tool left."""
    target = data['targets'][task['target']]
    source = ROOT / target['source']
    directory = out / 'tasks' / task['id']
    directory.mkdir(parents=True)
    (directory / source.name).write_text(harness(source.read_text(), data, [tuple(check) for check in task['checks']], task['assumptions']))
    (directory / 'task.sby').write_text(sby_text(task, target['top'], source.name, target['parameters'], args.formal_timeout))
    execution = P.execute([args.sby, '--yosys', args.yosys, '--smtbmc', args.smtbmc, '--witness', args.witness, 'task.sby'],
                          directory / 'console.log', args.formal_timeout, directory)
    work = directory / 'task'
    status = (work / 'status').read_text().split()[0] if (work / 'status').is_file() and (work / 'status').read_text().strip() else 'MISSING'
    log = (work / 'logfile.txt').read_text(errors='replace') if (work / 'logfile.txt').is_file() else ''
    record = dict(id=task['id'], formal_status=status, log=read_log(log), traces=[], inventory=None, **execution)
    try:
        for trace in sorted((work / 'engine_0').glob('*.vcd')):
            if trace.name.startswith('trace_induct'):       # starts from an arbitrary state: kept, not counted
                continue
            witness = trace.with_suffix('.yw')
            if '$enddefinitions' not in trace.read_text(errors='replace') or not witness.is_file() or not witness.stat().st_size:
                raise ValueError('trace without its witness')
            record['traces'].append(str(trace.relative_to(out)))
        if status in ('PASS', 'FAIL', 'UNKNOWN') and not execution['error']:
            record['inventory'] = compiled_inventory(work / 'model/inventory.json')
    except (OSError, ValueError, KeyError, TypeError) as exc:
        record['error'] = record['error'] or 'invalid evidence: ' + str(exc)
    record['outcome'], record['message'] = outcome(task, record)
    P.write_json(directory / 'result.json', dict(record, task=task))
    return record


def run(args):
    data = load_items()
    ledger = json.loads(args.ledger.read_text())
    requirements = json.loads(REQUIREMENTS.read_text())
    code_plan = json.loads(PLAN.read_text())
    contract = code_plan['configurations'][CONFIGURATION]
    tasks, check_ids = plan_tasks(data, args.profile)
    requirement_coverage(requirements, check_ids, set(), args.profile)       # reject an orphan before anything runs
    inputs = [Path(__file__), Path(C.__file__), ITEMS, args.ledger.resolve(), REQUIREMENTS, PLAN, HARNESS, C.RTL, GUARDED]
    e = E.Evidence(NAME, args, inputs, dict(items=data['items'], tasks=list(tasks.values()), measured_kinds=MEASURED_KINDS,
                                            configuration=CONFIGURATION), check_ids)
    out = e.out
    source_hashes = {name: sha256(ROOT / target['source']) for name, target in data['targets'].items()}
    versions, version_logs = tool_versions(out, args)
    P.write_json(out / 'tools.json', dict(versions=versions, logs=version_logs))
    e.check('tools', all(versions.values()) and not version_logs['sby']['error'] and version_logs['sby']['returncode'] == 0, versions)

    # 1. Measure the base test of the code coverage example and list its unhit points.
    width = C.CONFIGS[CONFIGURATION]
    build = out / 'verilator-build'
    command = [args.verilator, '--cc', '--exe', '--build', '--trace', '-j', str(args.jobs), '--top-module', 'command_unit', '--Mdir', str(build),
               f'-GWIDTH={width}', '-GMUTATION=0', *C.FLAGS, str(C.RTL), str(HARNESS)]
    built = P.execute(command, out / 'verilator-build.log', args.build_timeout, out)
    built_ok = not built['error'] and built['returncode'] == 0 and sha256(C.RTL) == code_plan['rtl_sha256']
    e.check('measured-build', built_ok, built)

    def simulate(name, rows):
        directory = out / name
        directory.mkdir()
        vectors, wave = directory / 'vectors.txt', directory / 'wave.vcd'
        vectors.write_text(''.join(' '.join(format(value, 'x') for value in row) + '\n' for row in rows))
        if not built_ok:
            raise ValueError('MEASURED: build failed')
        execution = P.execute([str(build / 'Vcommand_unit'), str(vectors), str(wave)], directory / 'simulation.log', args.timeout, directory)
        C.check_simulation(execution, (directory / 'simulation.log').read_text(errors='replace'), rows, wave)
        points = C.read_native(directory / 'coverage.dat')
        C.validate_inventory(points, contract)
        return points

    baseline, zero, mapping = None, [], {}
    try:
        baseline = simulate('measured-baseline', C.vectors(width))
        report = C.report(baseline, contract)
        zero = sorted(point['id'] for kind in MEASURED_KINDS for point in report[kind]['zero_points'])
        outside = {kind: report[kind]['total'] - report[kind]['hit'] for kind in sorted(C.KINDS - set(MEASURED_KINDS))}
        e.check('measured-baseline', bool(zero), dict(unhit=len(zero), not_classified_here=outside))
    except (OSError, ValueError, KeyError, TypeError) as exc:
        e.check('measured-baseline', False, str(exc))
    measured_items = [item for item in data['items'] if item['category'] == 'measured']
    try:
        mapping = match_points(zero, measured_items)
        e.check('measured-inventory', True, mapping)
    except (ValueError, KeyError, TypeError) as exc:
        e.check('measured-inventory', False, str(exc))

    # 2. Run every formal task.
    with ThreadPoolExecutor(max_workers=args.jobs) as pool:
        records = dict(zip(tasks, pool.map(lambda task: run_task(args, data, task, out), tasks.values())))
    P.write_json(out / 'tasks.json', records)

    # 3. Required behaviour under each assumption that is not the reset.
    goals_kept = {}
    for name, record in records.items():
        if not name.startswith('goals-'):
            continue
        assumption = name.removeprefix('goals-')
        blocked = record['log']['unreached'] if record['outcome'] == 'unreached' else []
        goals_kept[assumption] = record['outcome'] == 'reached'
        expected = sorted(data['assumptions'][assumption]['blocks'])
        e.check(name, record['outcome'] in ('reached', 'unreached') and blocked == expected,
                dict(outcome=record['outcome'], blocked=blocked, expected_blocked=expected, message=record['message']))

    # 4. Classify the items and replay the cover traces of the measured unit.
    fresh, replayed = {}, []
    for item in data['items']:
        cover = records['cover-' + item['id']]
        steps = None
        prove = records.get('prove-' + item['id'])
        cross = prove is not None and item['expected'] == 'reachable'
        kept = all(goals_kept.get(name) for name in item['assumptions']) if item['assumptions'] else None
        cls = classify(cover['outcome'], None if cross or prove is None else prove['outcome'], item['assumptions'], kept)
        fresh[item['id']] = dict({'class': cls}, expected=item['expected'], cover=cover['outcome'], prove=prove['outcome'] if prove else None,
                                 proof_task=prove['id'] if prove and not cross else None,
                                 assumptions=(prove or cover)['inventory']['assume'] if (prove or cover)['inventory'] else None,
                                 helpers=sorted(set((prove['inventory'] or {}).get('assert', [])) - {'target'}) if prove else [],
                                 point_id=mapping.get(item['id']), trace=cover['traces'][0] if cover['outcome'] == 'reached' else None)
        if cover['outcome'] == 'reached':
            try:
                steps = decode_witness((out / cover['traces'][0]).with_suffix('.yw'))
                P.write_json(out / 'tasks' / cover['id'] / 'reach-inputs.json', steps)
                fresh[item['id']]['reach_steps'] = len(steps)
            except (OSError, ValueError, KeyError, TypeError) as exc:
                fresh[item['id']]['class'] = cls = 'error'
                fresh[item['id']]['witness_error'] = str(exc)
        e.check('classify-' + item['id'], cls == item['expected'],
                dict(fresh[item['id']], cover_message=cover['message'], prove_message=prove['message'] if prove else None))
        if 'replay-' + item['id'] in check_ids:
            try:
                if steps is None:
                    raise ValueError('REPLAY: no cover trace to replay')
                rows = replay_rows(steps, width)
                points = simulate('replay-' + item['id'], rows)
                hits = points[mapping[item['id']]]['count']
                replayed.append(points)
                e.check('replay-' + item['id'], hits > 0, dict(hits=hits, rows=len(rows)))
            except (OSError, ValueError, KeyError, TypeError) as exc:
                e.check('replay-' + item['id'], False, str(exc))
        if 'cross-' + item['id'] in check_ids:
            e.check('cross-' + item['id'], prove['outcome'] == 'refuted', prove['message'])
    P.write_json(out / 'classification.json', dict(items=fresh, counts={name: sum(r['class'] == name for r in fresh.values()) for name in (*CLASSES, 'error')}))

    # 5. What is still unhit after the replays must be exactly what the ledger excludes.
    try:
        expected_replays = sum(name.startswith('replay-') for name in check_ids)
        if baseline is None or len(replayed) != expected_replays:
            raise ValueError('MEASURED: baseline or replay missing')
        merged = C.merge_counts([baseline, *replayed])
        left = {identity for identity, count in merged.items() if count == 0 and json.loads(identity)['t'] in MEASURED_KINDS}
        excluded = {entry.get('point_id') for entry in ledger['exclusions'] if entry.get('point_id')}
        e.check('measured-closure', left == excluded == set(contract['not_required']),
                dict(left=sorted(left), excluded=sorted(excluded), code_coverage_plan=sorted(contract['not_required'])))
    except (ValueError, KeyError, TypeError) as exc:
        e.check('measured-closure', False, str(exc))

    # 6. A bounded pass exists for the shallow item and still leaves it unclassified.
    bounded = records['bmc-gu-stall-shallow']
    e.check('bounded-pass-is-not-proof', bounded['outcome'] == 'bounded-pass' and fresh['gu-stall-shallow']['class'] == 'unclassified' and
            fresh['gu-stall']['class'] == 'reachable', dict(bmc=bounded['message'], shallow=fresh['gu-stall-shallow']['class'], deep=fresh['gu-stall']['class']))

    # 7. The ledger, and six ledgers that must be rejected.
    problems = audit(ledger, data, fresh, source_hashes, versions)
    excludable = {name for name, result in fresh.items() if result['class'] in EXCLUDABLE}
    e.check('ledger-accepted', not problems and {entry['item'] for entry in ledger['exclusions']} == excludable, problems or sorted(excludable))
    for name, (_, code) in TAMPERINGS.items():
        try:
            found = audit(tampered(ledger, data, name), data, fresh, source_hashes, versions)
        except (KeyError, TypeError, StopIteration) as exc:      # the checked-in ledger is already unusable
            found = ['LEDGER_FORMAT: ' + repr(exc)]
        e.check('ledger-reject-' + name, not problems and code in found, found)
    P.write_json(out / 'ledger-audit.json', dict(problems=problems, tools=versions, source_sha256=source_hashes))

    try:
        C.check_sources(out / 'manifest.json')
        e.check('source-identity', True, 'source hashes unchanged')
    except (OSError, ValueError, KeyError, TypeError) as exc:
        e.check('source-identity', False, str(exc))
    passed = {result['id'] for result in e.results if result['status'] == 'pass'}
    coverage = requirement_coverage(requirements, check_ids, passed, args.profile)
    P.write_json(out / 'coverage.json', coverage)
    P.write_json(out / 'requirements.json', requirements)
    e.check('requirements', all(row['passed'] for row in coverage if row['applicable']), [row['id'] for row in coverage if row['applicable'] and not row['passed']])
    return e.finish()


def main():
    parser = E.parser(__doc__, NAME)
    parser.add_argument('--verilator', default='verilator')
    for name, default in (('sby', 'yowasp-sby'), ('yosys', 'yowasp-yosys'), ('smtbmc', 'yowasp-yosys-smtbmc'), ('witness', 'yowasp-yosys-witness')):
        parser.add_argument('--' + name, default=default)
    parser.add_argument('--jobs', type=int, default=4)
    parser.add_argument('--ledger', type=Path, default=LEDGER, help='exclusion ledger to audit; another file shows a rejection')
    parser.add_argument('--build-timeout', type=float, default=180)
    parser.add_argument('--formal-timeout', type=float, default=120)
    args = parser.parse_args()
    E.validate(parser, args)
    if args.jobs < 1 or any(not math.isfinite(value) or value <= 0 for value in (args.build_timeout, args.formal_timeout)):
        parser.error('positive jobs and finite positive timeouts required')
    args.verilator = C.resolve_tool(args.verilator)
    try:
        return run(args)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print('RUNNER_ERROR', exc, file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())

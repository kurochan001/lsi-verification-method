#!/usr/bin/env python3
"""List and classify clock and reset domain crossings from Yosys netlists, and check them against a ledger."""
import importlib.util
import json
from pathlib import Path
import re
import shutil
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
NAME = 'local-cdc-structural'


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


E = load('cdc_evidence', HERE.parent / 'local-exploration-common/evidence.py')
C = load('cdc_check', HERE / 'cdc_check.py')
G = load('cdc_generator', HERE / 'generator.py')
P = E.P
TARGETS, LEDGER, WAIVERS, REQUIREMENTS = (HERE / name for name in
                                          ('targets.json', 'ledger.json', 'waivers.json', 'requirements.json'))
SEEDS = {'smoke': 1, 'nightly': 3}
BLOCKS = {'smoke': 12, 'nightly': 40}
GROUPS = {'cdc-handshake': 'ledger/cdc-handshake', 'async-fifo': 'ledger/async-fifo', 'irq-cdc': 'ledger/irq-cdc'}
BROKEN = 'module cdc_broken (input wire clk, input wire d, output reg q);\n    always @(posedge clk) q <= d\nendmodule\n'


def read_json(path):
    data = json.loads(path.read_text())
    if data.get('schema_version') != 1 or type(data.get('revision')) is not int or data['revision'] < 1:
        raise ValueError(f'unsupported schema_version or invalid revision: {path.name}')
    return data


def load_targets(path=TARGETS):
    targets = read_json(path)['targets']
    ids = [target['id'] for target in targets]
    if not targets or len(set(ids)) != len(ids):
        raise ValueError('empty or duplicate target list')
    for target in targets:
        if target['kind'] not in ('positive', 'negative', 'existing') or \
                (target['kind'] == 'negative') != (target.get('rule') in C.RULES):
            raise ValueError(f"invalid kind or rule: {target['id']}")
    return targets


def goals_catalog(path=REQUIREMENTS):
    data = read_json(path)
    goals = [goal for item in data['requirements'] for goal in item['goals']]
    if not goals or len(set(goals)) != len(goals):
        raise ValueError('empty or duplicate goals')
    return data, set(goals)


def summarize(report):
    """The part of a report that the ledger states."""
    return dict(
        flops=report['flops'], asynchronous_reset_flops=report['asynchronous_reset_flops'],
        synchronizers=report['synchronizers'],
        unsynchronized=[dict(source=c['source'], sink=c['sink'], paths=c['paths'])
                        for c in report['crossings'] if c['kind'] == 'unsynchronized'],
        findings={C.finding_key(f): f['bits'] for f in report['findings']})


def synthesize(args, directory, source_text, source_name, top, parameters):
    """Run Yosys on one source. Returns the netlist, or None with the reason."""
    directory.mkdir(parents=True)
    (directory / source_name).write_text(source_text)
    script = C.synthesis_script(source_name, top, parameters, 'netlist.json')
    (directory / 'synthesis.ys').write_text(script.replace('; ', '\n') + '\n')
    execution = P.execute([args.yosys, '-q', '-l', 'synthesis.log', '-p', script], directory / 'yosys-console.log',
                          args.timeout, directory)
    P.write_json(directory / 'synthesis.json', execution)
    if execution['error'] or execution['returncode'] != 0:
        return None, execution['error'] or f"yosys exit {execution['returncode']}"
    try:
        return json.loads((directory / 'netlist.json').read_text()), None
    except (OSError, ValueError) as exc:
        return None, f'unreadable netlist: {exc}'


def judge(target, report, entry, waivers, hashes):
    """Compare one report with its ledger entry and its waivers. Returns (ok, detail)."""
    problems = []
    observed = summarize(report)
    for field, value in observed.items():
        if entry.get(field) != value:
            problems.append(f'{field} differs from the ledger')
    excused, remaining, errors = C.apply_waivers(target['id'], report['findings'], waivers, hashes)
    problems += errors
    still_open = sorted(C.finding_key(f) for f in remaining)
    if still_open != sorted(entry.get('open', [])):
        problems.append('open findings differ from the ledger: ' + ', '.join(still_open or ['none']))
    if target['kind'] == 'negative':
        rules = {f['rule'] for f in remaining}
        if rules != {target['rule']}:
            problems.append(f"negative example must report {target['rule']} alone, got {sorted(rules) or 'nothing'}")
    elif remaining:
        problems.append('findings without a waiver')
    return not problems, dict(problems=problems, observed=observed, open=still_open,
                              excused=[dict(finding=C.finding_key(f), waiver=f['waiver'], disposition=f['disposition'])
                                       for f in excused])


def plan_ids(targets, seeds):
    ids = ['tool-version'] + [f"target-{t['id']}" for t in targets]
    ids += [f"checker-without-{t['rule']}" for t in targets if t['kind'] == 'negative']
    ids += ['waiver-expired', 'waiver-unused', 'waiver-without-reason', 'waiver-ledger-complete',
            'undeclared-port', 'undeclared-clock', 'build-failure']
    ids += [f'random-seed{seed}' for seed in seeds]
    return ids + ['requirements-and-coverage']


def run(args):
    targets = load_targets()
    ledger = read_json(LEDGER)['targets']
    waivers = read_json(WAIVERS)['waivers']
    requirements, required = goals_catalog()
    seeds = list(range(args.seed, args.seed + SEEDS[args.profile]))
    blocks = args.blocks or BLOCKS[args.profile]
    sources = sorted({ROOT / t['source'] for t in targets})
    inputs = [Path(__file__), HERE / 'cdc_check.py', HERE / 'generator.py', TARGETS, LEDGER, WAIVERS, REQUIREMENTS, *sources]
    evidence = E.Evidence(NAME, args, inputs, dict(targets=[t['id'] for t in targets], seeds=seeds, blocks=blocks,
                                                   rules=list(C.RULES)), plan_ids(targets, seeds))
    out = evidence.out
    hashes = {str(path.relative_to(ROOT)): C.sha256(path) for path in sources}
    hit = {}
    demo = [C.RULES[args.demo_bug - 1]] if args.demo_bug else []   # a checker that lost one rule

    def credit(ok, *goals):
        if ok:
            for goal in goals:
                hit.setdefault(goal, []).append(evidence.results[-1]['id'])

    version = P.execute([args.yosys, '-V'], out / 'yosys-version.log', args.timeout, out)
    text = (out / 'yosys-version.log').read_text(errors='replace').strip()
    evidence.check('tool-version', not version['error'] and version['returncode'] == 0 and 'Yosys' in text, text)

    reports, netlists = {}, {}
    for target in targets:
        name = target['id']
        source = ROOT / target['source']
        data, problem = synthesize(args, out / name, source.read_text(), source.name, target['top'], target['parameters'])
        if data is None:
            evidence.check(f'target-{name}', False, problem)
            continue
        try:
            report = C.analyze(data, target['top'], target, disabled=demo)
        except C.Unsupported as exc:
            evidence.check(f'target-{name}', False, f'unsupported: {exc}')
            continue
        netlists[name], reports[name] = data, report
        if name not in ledger:
            evidence.check(f'target-{name}', False, 'no ledger entry')
            continue
        ok, detail = judge(target, report, ledger[name], waivers, hashes)
        P.write_json(out / name / 'report.json', dict(target=target, report=report, **detail))
        evidence.check(f'target-{name}', ok, detail['problems'] or
                       f"{sum(report['flops'].values())} flops, {len(report['crossings'])} crossings, "
                       f"{len(report['findings'])} findings, {len(detail['excused'])} excused")
        goals = [('domain/single-clock', 'domain/two-clocks', 'domain/three-clocks')[len(target['clocks']) - 1]]
        if report['asynchronous_reset_flops']:
            goals.append('domain/asynchronous-reset')
        goals += [f'sync/{word}-stages' for word, count in (('two', 2), ('three', 3))
                  if any(s['stages'] == count for s in report['synchronizers'])]
        if target['kind'] == 'negative':
            goals.append('rule/' + target['rule'])
        if target['kind'] == 'positive':
            goals += ['sync/clean-design', 'sync/reset-synchronizer']
        goals += [goal for prefix, goal in GROUPS.items() if name.startswith(prefix)]
        goals += ['waiver/' + row['disposition'] for row in detail['excused']]
        credit(ok, *goals)

    # The checker with one rule switched off must be noticed by that rule's negative example.
    noticed = []
    for target in targets:
        if target['kind'] != 'negative':
            continue
        name, rule = target['id'], target['rule']
        check = f'checker-without-{rule}'
        if name not in reports:
            evidence.check(check, False, 'the negative example was not analysed')
            continue
        weakened = C.analyze(netlists[name], target['top'], target, disabled=[rule])
        ok, detail = judge(target, weakened, ledger[name], waivers, hashes)
        missed = not any(f['rule'] == rule for f in weakened['findings'])
        complete = C.analyze(netlists[name], target['top'], target)
        intact = judge(target, complete, ledger[name], waivers, hashes)[0]
        noticed.append(evidence.check(check, intact and missed and not ok,
                                      dict(with_all_rules=intact, finding_gone=missed, problems=detail['problems'])))
    credit(len(noticed) == len(C.RULES) and all(noticed), 'checker/rule-off-noticed')

    # Waivers: a stale hash, a finding that does not exist, a missing reason.
    reference = next((t for t in targets if t['id'] in reports and any(t['id'] in w['targets'] for w in waivers)), None)
    if reference is None:
        for check in ('waiver-expired', 'waiver-unused', 'waiver-without-reason'):
            evidence.check(check, False, 'no analysed target has a waiver')
    else:
        name, report = reference['id'], reports[reference['id']]
        own = [w for w in waivers if name in w['targets']]
        baseline = judge(reference, report, ledger[name], waivers, hashes)[0]

        def rejected(changed, word):
            ok, detail = judge(reference, report, ledger[name], changed, hashes)
            return baseline and not ok and any(word in problem for problem in detail['problems']), detail['problems']
        stale = dict(hashes, **{path: '0' * 64 for path in own[0]['expires']['source_sha256']})
        ok, detail = judge(reference, report, ledger[name], waivers, stale)
        good = baseline and not ok and any('expired' in p for p in detail['problems'])
        credit(evidence.check('waiver-expired', good, detail['problems']), 'waiver/expired-rejected')
        extra = [dict(own[0], id='W-UNUSED', findings=['NO_SYNC nothing->nowhere'])]
        good, detail = rejected(waivers + extra, 'does not have')
        credit(evidence.check('waiver-unused', good, detail), 'waiver/unused-rejected')
        blank = [dict(w, reason='  ') if w is own[0] else w for w in waivers]
        good, detail = rejected(blank, 'lacks reason')
        credit(evidence.check('waiver-without-reason', good, detail), 'waiver/incomplete-rejected')
    known = {t['id'] for t in targets}
    stray = sorted(t for w in waivers for t in w.get('targets', []) if t not in known)
    listed = [w.get('id') for w in waivers]
    evidence.check('waiver-ledger-complete', not stray and len(set(listed)) == len(listed) and
                   set(ledger) == known, dict(unknown_targets=stray, ledger_only=sorted(set(ledger) - known),
                                              targets_only=sorted(known - set(ledger))))

    # What the checker cannot read must be an error.
    reference = next((t for t in targets if t['id'] in netlists and t.get('inputs')), None)
    if reference is None:
        evidence.check('undeclared-port', False, 'no analysed target')
        evidence.check('undeclared-clock', False, 'no analysed target')
    else:
        data = netlists[reference['id']]
        for check, goal, changed in (
                ('undeclared-port', 'checker/undeclared-port',
                 dict(reference, inputs=dict(list(reference['inputs'].items())[1:]))),
                ('undeclared-clock', 'checker/undeclared-clock', dict(reference, clocks=reference['clocks'][1:]))):
            try:
                C.analyze(data, reference['top'], changed)
                credit(evidence.check(check, False, 'the analysis accepted an incomplete description'), goal)
            except C.Unsupported as exc:
                credit(evidence.check(check, True, str(exc)), goal)
    data, problem = synthesize(args, out / 'build-failure', BROKEN, 'cdc_broken.sv', 'cdc_broken', {})
    credit(evidence.check('build-failure', data is None and problem is not None and 'timeout' not in str(problem),
                          problem or 'the broken source was accepted'), 'checker/build-failure')

    # Random designs whose findings are known from how they were built.
    for seed in seeds:
        generated = G.generate(seed, blocks)
        check = f'random-seed{seed}'
        P.write_json(out / f'{check}-expected.json', dict(kinds=generated['kinds'], target=generated['target'],
                                                         expected=generated['expected']))
        data, problem = synthesize(args, out / check, generated['source'], 'cdc_random.sv', generated['target']['top'], {})
        if data is None:
            evidence.check(check, False, problem)
            continue
        try:
            report = C.analyze(data, generated['target']['top'], generated['target'], disabled=demo)
        except C.Unsupported as exc:
            evidence.check(check, False, f'unsupported: {exc}')
            continue
        observed = dict(flops=report['flops'], asynchronous_reset_flops=report['asynchronous_reset_flops'],
                        synchronizers=[{k: s[k] for k in ('source', 'sink', 'bits', 'stages')}
                                       for s in report['synchronizers']],
                        findings=report['findings'])
        P.write_json(out / check / 'report.json', report)
        differing = [field for field in observed if observed[field] != generated['expected'][field]]
        ok = evidence.check(check, not differing, differing or
                            f"{blocks} blocks, {len(report['findings'])} findings as constructed")
        goals = ['domain/three-clocks']
        if set(generated['kinds']) == set(G.KINDS):
            goals.append('random/all-patterns')
        if re.search(r'^    always @\(posedge \w+\) g\d+ <= \{g\d+\[[\d:]+\], ~s\d+\};$', generated['source'], re.M):
            goals.append('random/inverted-path')
        credit(ok, *goals)

    missing = sorted(required - hit.keys())
    coverage = dict(success=not missing, required=len(required), hit=len(required & hit.keys()), missing=missing,
                    hits={goal: hit[goal] for goal in sorted(hit)},
                    requirements=[dict(item, passed=set(item['goals']) <= hit.keys()) for item in requirements['requirements']])
    P.write_json(out / 'coverage.json', coverage)
    P.write_json(out / 'crossings.json', {name: summarize(report) for name, report in reports.items()})
    evidence.check('requirements-and-coverage', not missing and not (hit.keys() - required), missing)
    print(f"Coverage: {coverage['hit']}/{coverage['required']}")
    return evidence.finish()


def main():
    parser = E.parser(__doc__, NAME)
    parser.add_argument('--yosys', default='yowasp-yosys')
    parser.add_argument('--demo-bug', type=int, choices=range(len(C.RULES) + 1), default=0,
                        help='switch off rule N of the checker in the normal analysis; the run must then fail')
    parser.add_argument('--blocks', type=int, help='pattern blocks of each random design; default 12 (smoke), 40 (nightly)')
    args = parser.parse_args()
    E.validate(parser, args)
    if args.blocks is not None and not len(G.KINDS) <= args.blocks <= 200:
        parser.error(f'--blocks must be {len(G.KINDS)}..200')
    try:
        return run(args)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print('RUNNER_ERROR ' + str(exc), file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())

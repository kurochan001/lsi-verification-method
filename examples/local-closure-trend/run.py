#!/usr/bin/env python3
"""Build a closure trend table from a fixed regression history and recount every number."""
import copy
import importlib.util
import json
import math
from pathlib import Path
import random
import re
import sys

HERE = Path(__file__).resolve().parent
DATA = HERE / 'data'


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


E = load('closure_trend_evidence', HERE.parent / 'local-exploration-common/evidence.py')
T = load('closure_trend_generator', HERE / 'trend.py')
C = load('closure_trend_recount', HERE / 'recount.py')

ROW_FIELDS = T.COLUMNS[4:]
SUMMARY_FIELDS = ('defects_found', 'environment_issues', 'flaky', 'denominator_changes', 'escapes', 'verdict')
# Each deliberate counting error and the first number the independent recount must disagree with.
MUTANTS = {
    1: ('a time limit read as a pass', 'passed@c02'),
    2: ('a reopened defect counted again as new', 'new_defects@c07'),
    3: ('a fix counted one campaign late', 'open@c03'),
    4: ('environment trouble counted as a defect', 'new_defects@c03'),
    5: ('coverage of failed runs credited', 'functional@c01'),
    6: ('a new denominator left unreported', 'denominator_changes'),
    7: ('a different seed treated as the same plan', 'flaky@c09'),
    8: ('escapes left out of the report', 'escapes'),
    9: ('open defects ignored by the closure check', 'verdict'),
}
# Each broken input, the edit that makes it, and the label the report must refuse it with.
REJECTS = {
    'missing-result': lambda h: h['campaigns'][2]['summary']['results'].pop(),
    'duplicate-job': lambda h: h['campaigns'][4]['summary']['results'].__setitem__(1, copy.deepcopy(h['campaigns'][4]['summary']['results'][0])),
    'out-of-order': lambda h: h['campaigns'][6].__setitem__('date', '2026-09-30'),
    'unknown-campaign': lambda h: h['issues']['issues'][0]['events'].append(['reopened', 'c99']),
    'event-order': lambda h: h['issues']['issues'][0]['events'].insert(0, ['closed', 'c01']),
    'coverage-range': lambda h: h['campaigns'][0]['coverage']['ip-fifo']['functional'].__setitem__(0, 21),
    'coverage-job': lambda h: h['campaigns'][1]['coverage'].__setitem__('ip-spi', dict(functional=[1, 2])),
}


def first_difference(a, b):
    """The first field, in table order, where two trends disagree; None if they agree."""
    if len(a['rows']) != len(b['rows']):
        return 'rows'
    for field in ROW_FIELDS:
        for x, y in zip(a['rows'], b['rows']):
            if x[field] != y[field]:
                return f"{field}@{x['campaign']}"
    for field in SUMMARY_FIELDS:
        if a['summary'][field] != b['summary'][field]:
            return field
    return None


def parse_markdown(text):
    """Read the trend table back from the Markdown a reviewer sees."""
    lines = [l for l in text.splitlines() if l.startswith('| ')]
    header, separator, body = lines[0], lines[1], lines[2:]
    if set(separator.replace('|', '').split()) != {'---'}:
        raise ValueError('table separator differs')
    if len(header.split('|')) - 2 != len(T.COLUMNS):
        raise ValueError('table header differs')
    rows = []
    for line in body:
        cells = [c.strip() for c in line.strip('|').split('|')]
        row = {}
        for key, cell in zip(T.COLUMNS, cells):
            if key in ('functional', 'code'):
                m = re.fullmatch(r'(\d+)/(\d+)', cell)
                row[key] = [int(m[1]), int(m[2])]
            elif key in ('campaign', 'date', 'commit'):
                row[key] = cell
            else:
                row[key] = int(cell)
        rows.append(row)
    return rows


def hand_counts(trend, expected):
    rows, s = trend['rows'], trend['summary']
    observed = {field: [r[field] for r in rows] for field in ('passed', 'failed', 'incomplete', 'new_defects', 'reopened',
                                                               'closed', 'open', 'environment', 'coverage_excluded', 'flaky')}
    observed.update(campaigns=[r['campaign'] for r in rows], functional_first=rows[0]['functional'],
                    functional_last=rows[-1]['functional'], flaky_jobs=s['flaky'], denominator_changes=s['denominator_changes'],
                    defects_found=s['defects_found'], environment_issues=s['environment_issues'],
                    escapes=[e['id'] for e in s['escapes']], verdict=s['verdict'])
    return {k: dict(expected=v, observed=observed[k]) for k, v in expected.items()
            if k not in ('schema_version', 'note') and observed[k] != v}


def random_history(rng):
    """A consistent invented history, to compare the generator and the recount on cases nobody wrote by hand."""
    jobs = [f'job-{i}' for i in range(rng.randint(2, 6))]
    campaigns, commit, seed = [], 0, 100
    totals = {(j, m): rng.randint(5, 40) for j in jobs for m in T.METRICS}
    for i in range(rng.randint(4, 12)):
        step = rng.random()
        if i == 0 or step < 0.6:
            commit += 1
            seed += 1
        elif step < 0.8:
            seed += 1  # same commit, another stimulus
        results, coverage = [], {}
        for j in jobs:
            roll = rng.random()
            if roll < 0.08:
                results.append(dict(id=j, success=False, started=rng.random() < 0.5,
                                    message=rng.choice(['job timeout after 60 s', 'not started: missing tool']), junit=None))
                continue
            ok = roll > 0.3
            results.append(dict(id=j, success=ok, started=True, message='checker failure' if not ok else 'planned execution valid', junit=10))
            if rng.random() < 0.1:
                totals[(j, 'functional')] += rng.randint(1, 4)
            if rng.random() < 0.05 and totals[(j, 'code')] > 5:
                totals[(j, 'code')] -= rng.randint(1, 3)  # lines removed: a denominator may also shrink
            coverage[j] = {m: [rng.randint(0, totals[(j, m)]), totals[(j, m)]] for m in T.METRICS}
        campaigns.append(dict(schema_version=1, campaign=f'r{i:02d}', date=f'2026-11-{i + 1:02d}', commit=f'c{commit}',
                              profile='nightly', seed=seed, summary=dict(planned=len(results), results=results), coverage=coverage))
    names = [c['campaign'] for c in campaigns]
    issues = []
    for k in range(rng.randint(0, 8)):
        kind = rng.choice(['rtl', 'rtl', 'testbench', 'environment'])
        at = rng.randrange(len(names))
        events = [['found', names[at]]]
        state = 'open'
        while at < len(names) - 1 and rng.random() < 0.7:
            at = rng.randrange(at, len(names))
            events.append(['closed' if state == 'open' else 'reopened', names[at]])
            state = 'closed' if state == 'open' else 'open'
        issue = dict(id=f'X-{k}', kind=kind, events=events)
        if rng.random() < 0.3:
            issue['flaky_job'] = rng.choice(jobs)
        issues.append(issue)
    escapes = [dict(id=f'E-{k}', kind='rtl', phase='integration', last_campaign=names[-1], category='stimulus',
                    missed_check='invented') for k in range(rng.randint(0, 2))]
    criteria = dict(schema_version=1, stable_campaigns=rng.randint(1, 3), max_open=rng.randint(0, 1),
                    functional_complete=rng.random() < 0.5, flaky_resolved=rng.random() < 0.5)
    return dict(index=dict(schema_version=1, campaigns=names), campaigns=campaigns,
                issues=dict(schema_version=1, issues=issues, escapes=escapes), criteria=criteria)


def recount_memory(history):
    return C.count(history['index']['campaigns'], {c['campaign']: c for c in history['campaigns']},
                   history['issues'], history['criteria'])


def run(a):
    randoms = 12 if a.profile == 'nightly' else 3
    requirements = json.loads((HERE / 'requirements.json').read_text(encoding='utf-8'))
    ids = (['inventory', 'trend-table', 'recount', 'markdown-roundtrip', 'hand-counts']
           + [f'reject-{name}' for name in REJECTS] + [f'mutation{m}' for m in MUTANTS]
           + [f'random-{i:02d}' for i in range(1, randoms + 1)] + ['requirements'])
    inputs = [Path(__file__), HERE / 'trend.py', HERE / 'recount.py', HERE / 'expected.json', HERE / 'requirements.json',
              *T.inputs(DATA)]
    e = E.Evidence('local-closure-trend', a, inputs,
                   dict(data='invented history of 11 campaigns in the shape of run_regression summaries',
                        mutants={m: d for m, (d, _) in MUTANTS.items()}, rejects=sorted(REJECTS), random_histories=randoms), ids)
    history = T.load(DATA)
    try:
        order = T.validate(history)
        e.check('inventory', True, dict(campaigns=order, issues=len(history['issues']['issues']),
                                        escapes=len(history['issues']['escapes'])))
    except T.InputError as exc:
        e.check('inventory', False, str(exc))
        return e.finish()
    trend = T.build(history)
    markdown = T.render_markdown(trend)
    E.P.write_json(e.out / 'trend.json', trend)
    (e.out / 'trend.md').write_text(markdown, encoding='utf-8')
    e.check('trend-table', len(trend['rows']) == len(order), dict(rows=len(trend['rows']), summary=trend['summary']))
    independent = C.recount(DATA)
    E.P.write_json(e.out / 'recount.json', independent)
    difference = first_difference(trend, independent)
    e.check('recount', difference is None, dict(first_difference=difference))
    try:
        parsed = parse_markdown((e.out / 'trend.md').read_text(encoding='utf-8'))
        e.check('markdown-roundtrip', parsed == trend['rows'], dict(rows=len(parsed)))
    except (ValueError, TypeError, IndexError) as exc:
        e.check('markdown-roundtrip', False, str(exc))
    differences = hand_counts(trend, json.loads((HERE / 'expected.json').read_text(encoding='utf-8')))
    e.check('hand-counts', not differences, differences)
    for name, edit in REJECTS.items():
        broken = copy.deepcopy(history)
        edit(broken)
        try:
            T.build(broken)
            e.check(f'reject-{name}', False, 'the broken input was accepted')
        except T.InputError as exc:
            e.check(f'reject-{name}', str(exc).startswith(f'CT_INPUT {name}:'), str(exc))
    for m, (description, label) in MUTANTS.items():
        observed = first_difference(T.build(history, mutation=m), independent)
        e.check(f'mutation{m}', observed == label, dict(description=description, expected=label, observed=observed))
    rng = random.Random(a.seed)
    for i in range(1, randoms + 1):
        sample = random_history(rng)
        try:
            T.validate(sample)
            difference = first_difference(T.build(sample), recount_memory(sample))
            e.check(f'random-{i:02d}', difference is None,
                    dict(campaigns=len(sample['campaigns']), issues=len(sample['issues']['issues']), first_difference=difference))
        except T.InputError as exc:
            e.check(f'random-{i:02d}', False, 'generated history refused: ' + str(exc))
    done = {r['id']: r['status'] for r in e.results}
    missing = sorted({g for r in requirements['requirements'] for g in r['goals']} - {k for k, v in done.items() if v == 'pass'})
    e.check('requirements', requirements['schema_version'] == 1 and not missing,
            dict(requirements=len(requirements['requirements']), missing=missing))
    return e.finish()


def main():
    p = E.parser(__doc__, 'local-closure-trend')
    a = p.parse_args()
    E.validate(p, a)
    if not math.isfinite(a.timeout) or a.seed > 2 ** 31 - 1:
        p.error('valid seed and time limit required')
    try:
        return run(a)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print('RUNNER_ERROR', exc, file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())

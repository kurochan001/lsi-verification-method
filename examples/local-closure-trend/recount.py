"""Recount every number of the trend table without the generator's code.

Written separately from trend.py on purpose: open defects come from a running sum of +1/-1
events, outcomes from a regular expression, flakiness from the set of verdicts seen per plan,
coverage from the set of passing jobs, and denominator changes from the sequence of totals.
"""
from collections import defaultdict
import json
from pathlib import Path
import re

NOT_A_VERDICT = re.compile(r'^(job timeout|command timeout|not started)')


def recount(directory):
    directory = Path(directory)
    index = json.loads((directory / 'index.json').read_text(encoding='utf-8'))
    order = index['campaigns']
    runs = {name: json.loads((directory / 'campaigns' / f'{name}.json').read_text(encoding='utf-8')) for name in order}
    tracker = json.loads((directory / 'issues.json').read_text(encoding='utf-8'))
    criteria = json.loads((directory / 'criteria.json').read_text(encoding='utf-8'))
    return count(order, runs, tracker, criteria)


def verdict_of(result):
    if result['started'] is not True or NOT_A_VERDICT.match(result['message']):
        return 'incomplete'
    return {True: 'pass', False: 'fail'}[result['success']]


def count(order, runs, tracker, criteria):
    defects = [i for i in tracker['issues'] if i['kind'] != 'environment']
    delta = defaultdict(int)
    tally = defaultdict(lambda: defaultdict(int))
    for issue in defects:
        for kind, campaign in issue['events']:
            delta[campaign] += 1 if kind in ('found', 'reopened') else -1
            tally[campaign][kind] += 1
    environment = defaultdict(int)
    for issue in tracker['issues']:
        if issue['kind'] == 'environment':
            environment[issue['events'][0][1]] += 1
    seen_verdicts = defaultdict(set)
    flagged = {}
    totals = defaultdict(list)
    rows = []
    running = 0
    for name in order:
        run = runs[name]
        verdicts = {r['id']: verdict_of(r) for r in run['summary']['results']}
        running += delta[name]
        passing = {job for job, v in verdicts.items() if v == 'pass'}
        functional = [sum(run['coverage'][j]['functional'][0] for j in passing if j in run['coverage']),
                      sum(run['coverage'][j]['functional'][1] for j in passing if j in run['coverage'])]
        code = [sum(run['coverage'][j]['code'][0] for j in passing if j in run['coverage']),
                sum(run['coverage'][j]['code'][1] for j in passing if j in run['coverage'])]
        for job, metrics in run['coverage'].items():
            for metric, pair in metrics.items():
                totals[(job, metric)].append((name, pair[1]))
        plan = (run['commit'], run['seed'], run['profile'])
        for job, v in verdicts.items():
            if v != 'incomplete':
                seen_verdicts[(plan, job)].add(v)
                if len(seen_verdicts[(plan, job)]) == 2 and job not in flagged:
                    flagged[job] = name
        rows.append(dict(campaign=name, date=run['date'], commit=run['commit'], seed=run['seed'],
                         planned=len(verdicts),
                         passed=list(verdicts.values()).count('pass'),
                         failed=list(verdicts.values()).count('fail'),
                         incomplete=list(verdicts.values()).count('incomplete'),
                         new_defects=tally[name]['found'], reopened=tally[name]['reopened'],
                         closed=tally[name]['closed'], open=running, environment=environment[name],
                         functional=functional, code=code,
                         coverage_excluded=len(verdicts) - len(passing & set(run['coverage'])),
                         flaky=len(flagged)))
    changes = []
    for (job, metric), sequence in totals.items():
        for (_, before), (campaign, after) in zip(sequence, sequence[1:]):
            if before != after:
                changes.append(dict(campaign=campaign, job=job, metric=metric, before=before, after=after))
    changes.sort(key=lambda d: (order.index(d['campaign']), d['job'], d['metric']))
    escapes = [dict(id=e['id'], kind=e['kind'], phase=e['phase'], last_campaign=e['last_campaign'],
                    category=e['category'], missed_check=e['missed_check']) for e in tracker['escapes']]
    summary = dict(campaigns=len(rows), defects_found=sum(tally[n]['found'] for n in order),
                   environment_issues=sum(environment.values()),
                   flaky=[dict(job=job, first=first) for job, first in sorted(flagged.items())],
                   denominator_changes=changes, escapes=escapes)
    unmet = []
    window = rows[-criteria['stable_campaigns']:]
    if len(window) != criteria['stable_campaigns'] or sum(r['failed'] + r['incomplete'] for r in window):
        unmet.append('unstable-recent-campaigns')
    if rows[-1]['open'] > criteria['max_open']:
        unmet.append('open-defects')
    if criteria['functional_complete'] and (rows[-1]['coverage_excluded'] > 0 or rows[-1]['functional'][0] < rows[-1]['functional'][1]):
        unmet.append('functional-coverage-incomplete')
    if criteria['flaky_resolved']:
        fixed = set()
        for issue in tracker['issues']:
            if 'flaky_job' in issue and issue['events'][-1][0] == 'closed':
                fixed.add(issue['flaky_job'])
        if set(flagged) - fixed:
            unmet.append('unresolved-flaky-jobs')
    summary['verdict'] = dict(ready=not unmet, reasons=unmet)
    return dict(rows=rows, summary=summary)

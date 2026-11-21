"""Build a closure trend table from a fixed, ordered regression history.

The table is the thing a review reads. Every number in it is recounted independently by
recount.py, and the runner compares the two. MUTATION selects a deliberate counting error
(0 is the correct generator); each one is a mistake that is easy to make in a real report.
"""
import json
from pathlib import Path

DEFECT_KINDS = ('rtl', 'testbench')
KINDS = DEFECT_KINDS + ('environment',)
METRICS = ('functional', 'code')
EVENTS = ('found', 'closed', 'reopened')
INCOMPLETE_PREFIXES = ('job timeout', 'command timeout', 'not started')
COLUMNS = ('campaign', 'date', 'commit', 'seed', 'planned', 'passed', 'failed', 'incomplete',
           'new_defects', 'reopened', 'closed', 'open', 'environment', 'functional', 'code',
           'coverage_excluded', 'flaky')


class InputError(ValueError):
    """An input the report must refuse; the message starts with a stable label."""


def refuse(label, detail):
    raise InputError(f'CT_INPUT {label}: {detail}')


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def load(directory):
    directory = Path(directory)
    index = read_json(directory / 'index.json')
    campaigns = [read_json(directory / 'campaigns' / f'{name}.json') for name in index['campaigns']]
    issues = read_json(directory / 'issues.json')
    return dict(index=index, campaigns=campaigns, issues=issues, criteria=read_json(directory / 'criteria.json'))


def inputs(directory):
    directory = Path(directory)
    index = read_json(directory / 'index.json')
    return [directory / 'index.json', directory / 'issues.json', directory / 'criteria.json',
            *[directory / 'campaigns' / f'{name}.json' for name in index['campaigns']]]


def outcome(result):
    """pass, fail or incomplete. A time limit or a job that never started is not a verdict."""
    if not result['started'] or result['message'].startswith(INCOMPLETE_PREFIXES):
        return 'incomplete'
    return 'pass' if result['success'] else 'fail'


def validate(history):
    """Refuse histories whose counts would be meaningless. Returns the campaign IDs in order."""
    index, campaigns, issues = history['index'], history['campaigns'], history['issues']
    for name, record in [('index', index), ('issues', issues), ('criteria', history['criteria']),
                         *[(c.get('campaign', '?'), c) for c in campaigns]]:
        if record.get('schema_version') != 1:
            refuse('schema', f'{name} is not schema_version 1')
    order = [c['campaign'] for c in campaigns]
    if order != index['campaigns'] or len(set(order)) != len(order):
        refuse('campaign-inventory', 'campaign files differ from the index or repeat')
    dates = [c['date'] for c in campaigns]
    if dates != sorted(dates):
        refuse('out-of-order', 'campaign dates decrease in the index order')
    jobs_seen = set()
    for c in campaigns:
        summary = c['summary']
        results = summary['results']
        if type(summary['planned']) is not int or summary['planned'] != len(results):
            refuse('missing-result', f"{c['campaign']} plans {summary['planned']} jobs but records {len(results)}")
        ids = [r['id'] for r in results]
        if len(set(ids)) != len(ids):
            refuse('duplicate-job', f"{c['campaign']} records a job twice")
        for r in results:
            if not (isinstance(r['id'], str) and type(r['success']) is bool and type(r['started']) is bool
                    and isinstance(r['message'], str)):
                refuse('result-shape', f"{c['campaign']} {r.get('id')}")
            if r['success'] and not r['started']:
                refuse('result-shape', f"{c['campaign']} {r['id']} passed without starting")
        jobs_seen.update(ids)
        for job, metrics in c['coverage'].items():
            if job not in ids:
                refuse('coverage-job', f"{c['campaign']} has coverage for unplanned job {job}")
            for metric, pair in metrics.items():
                if metric not in METRICS:
                    refuse('coverage-metric', f'{metric} is not one of {METRICS}')
                hit, total = pair
                if type(hit) is not int or type(total) is not int or total <= 0 or not 0 <= hit <= total:
                    refuse('coverage-range', f"{c['campaign']} {job} {metric} {pair}")
    position = {name: i for i, name in enumerate(order)}
    seen = set()
    for issue in issues['issues']:
        if issue['id'] in seen or issue['kind'] not in KINDS:
            refuse('issue-shape', issue['id'])
        seen.add(issue['id'])
        state, last = None, -1
        for kind, campaign in issue['events']:
            if campaign not in position:
                refuse('unknown-campaign', f"{issue['id']} refers to {campaign}")
            if kind not in EVENTS or position[campaign] < last:
                refuse('event-order', f"{issue['id']} {kind} at {campaign}")
            allowed = {None: 'found', 'open': 'closed', 'closed': 'reopened'}
            if allowed[state] != kind:
                refuse('event-order', f"{issue['id']} cannot be {kind} while {state or 'unknown'}")
            state, last = ('open' if kind in ('found', 'reopened') else 'closed'), position[campaign]
        if 'flaky_job' in issue and issue['flaky_job'] not in jobs_seen:
            refuse('issue-shape', f"{issue['id']} names an unknown flaky job")
    for escape in issues['escapes']:
        if escape['id'] in seen or escape['kind'] not in DEFECT_KINDS or escape['last_campaign'] not in position:
            refuse('escape-shape', escape['id'])
        seen.add(escape['id'])
    return order


def build(history, mutation=0):
    validate(history)
    campaigns, issues = history['campaigns'], history['issues']
    events = {}
    for issue in issues['issues']:
        for kind, campaign in issue['events']:
            events.setdefault(campaign, []).append((issue, kind))
    open_now, rows, flaky, totals, changes, earlier = set(), [], {}, {}, [], []
    for c in campaigns:
        results = c['summary']['results']
        outcomes = {r['id']: outcome(r) for r in results}
        if mutation == 1:  # a time limit read as a pass
            outcomes = {job: 'pass' if o == 'incomplete' else o for job, o in outcomes.items()}
        new = reopened = closed = environment = 0
        deferred = []
        for issue, kind in events.get(c['campaign'], []):
            defect = issue['kind'] in DEFECT_KINDS or mutation == 4  # 4: environment trouble counted as a defect
            if not defect:
                environment += kind == 'found'
                continue
            if kind == 'found':
                new += 1
                open_now.add(issue['id'])
            elif kind == 'reopened':
                reopened += 1
                new += mutation == 2  # 2: a reopened defect counted again as new
                open_now.add(issue['id'])
            else:
                closed += 1
                if mutation == 3:  # 3: the fix only counts in the next campaign
                    deferred.append(issue['id'])
                else:
                    open_now.discard(issue['id'])
        open_count = len(open_now)
        for name in deferred:
            open_now.discard(name)
        sums = {metric: [0, 0] for metric in METRICS}
        excluded = 0
        for r in results:
            metrics = c['coverage'].get(r['id'])
            for metric, (hit, total) in (metrics or {}).items():
                key = (r['id'], metric)
                if key in totals and totals[key] != total and mutation != 6:  # 6: a new denominator goes unreported
                    changes.append(dict(campaign=c['campaign'], job=r['id'], metric=metric, before=totals[key], after=total))
                totals[key] = total
            credited = metrics is not None and (outcomes[r['id']] == 'pass' or mutation == 5)  # 5: failed runs credited
            if credited:
                for metric, (hit, total) in metrics.items():
                    sums[metric][0] += hit
                    sums[metric][1] += total
            else:
                excluded += 1
        plan = (c['commit'], c['profile']) if mutation == 7 else (c['commit'], c['seed'], c['profile'])  # 7: seed ignored
        for previous_plan, previous_outcomes in earlier:
            if previous_plan != plan:
                continue
            for job, o in outcomes.items():
                before = previous_outcomes.get(job)
                if {o, before} == {'pass', 'fail'}:
                    flaky.setdefault(job, c['campaign'])
        earlier.append((plan, outcomes))
        rows.append(dict(campaign=c['campaign'], date=c['date'], commit=c['commit'], seed=c['seed'],
                         planned=len(results),
                         passed=sum(o == 'pass' for o in outcomes.values()),
                         failed=sum(o == 'fail' for o in outcomes.values()),
                         incomplete=sum(o == 'incomplete' for o in outcomes.values()),
                         new_defects=new, reopened=reopened, closed=closed, open=open_count,
                         environment=environment, functional=sums['functional'], code=sums['code'],
                         coverage_excluded=excluded, flaky=len(flaky)))
    position = {c['campaign']: i for i, c in enumerate(campaigns)}
    changes.sort(key=lambda d: (position[d['campaign']], d['job'], d['metric']))
    escapes = [] if mutation == 8 else [  # 8: escapes left out of the report
        {k: e[k] for k in ('id', 'kind', 'phase', 'last_campaign', 'category', 'missed_check')} for e in issues['escapes']]
    summary = dict(campaigns=len(rows),
                   defects_found=sum(r['new_defects'] for r in rows),
                   environment_issues=sum(r['environment'] for r in rows),
                   flaky=[dict(job=job, first=first) for job, first in sorted(flaky.items())],
                   denominator_changes=changes, escapes=escapes)
    summary['verdict'] = verdict(rows, summary, issues, history['criteria'], mutation)
    return dict(rows=rows, summary=summary)


def verdict(rows, summary, issues, criteria, mutation=0):
    """Closure is a decision for people; this only lists the criteria that are not met."""
    reasons = []
    recent = rows[-criteria['stable_campaigns']:]
    if len(recent) < criteria['stable_campaigns'] or any(r['failed'] or r['incomplete'] for r in recent):
        reasons.append('unstable-recent-campaigns')
    if rows[-1]['open'] > criteria['max_open'] and mutation != 9:  # 9: open defects ignored
        reasons.append('open-defects')
    last = rows[-1]
    if criteria['functional_complete'] and (last['coverage_excluded'] or last['functional'][0] != last['functional'][1]):
        reasons.append('functional-coverage-incomplete')
    if criteria['flaky_resolved']:
        closed = {i.get('flaky_job') for i in issues['issues'] if i['events'][-1][0] == 'closed'}
        if any(f['job'] not in closed for f in summary['flaky']):
            reasons.append('unresolved-flaky-jobs')
    return dict(ready=not reasons, reasons=reasons)


def render_markdown(trend):
    head = ['実行', '日付', 'コミット', 'seed', '予定', '合格', '不合格', '未完了', '新規', '再発', '解決', '未解決',
            '環境', '機能カバレッジ', 'コードカバレッジ', '未計上', '揺れ']
    lines = ['# 収束の傾向', '', '| ' + ' | '.join(head) + ' |', '|' + ' --- |' * len(head)]
    for r in trend['rows']:
        cells = [r[k] if k not in ('functional', 'code') else f'{r[k][0]}/{r[k][1]}' for k in COLUMNS]
        lines.append('| ' + ' | '.join(str(x) for x in cells) + ' |')
    s = trend['summary']
    lines += ['', '## 揺れたジョブ', '']
    lines += [f"- {f['job']}（最初は{f['first']}）" for f in s['flaky']] or ['- なし']
    lines += ['', '## 分母の変更', '']
    lines += [f"- {d['campaign']} {d['job']} {d['metric']}：{d['before']}→{d['after']}" for d in s['denominator_changes']] or ['- なし']
    lines += ['', '## 流出', '']
    lines += [f"- {e['id']}（{e['phase']}、最後の実行は{e['last_campaign']}）：{e['missed_check']}" for e in s['escapes']] or ['- なし']
    lines += ['', '## 収束の判定', '', '- 満たしていない基準：' + ('、'.join(s['verdict']['reasons']) or 'なし'), '']
    return '\n'.join(lines)

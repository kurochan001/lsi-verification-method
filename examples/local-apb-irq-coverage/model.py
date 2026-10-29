"""Project plans and correlate observed APB edges without sampling driver intent as a hit."""
from itertools import combinations, product
import json
from pathlib import Path

FACTORS = ('pending', 'mask', 'clear', 'event')
FIELDS = ('rst', 'sel', 'enable', 'write', 'address', 'data', 'event', 'ready', 'error',
          'pre_config', 'pre_pending', 'post_config', 'post_pending', 'irq')
WIDTHS = (1, 1, 1, 1, 8, 32, 4, 1, 1, 32, 4, 32, 4, 1)
GROUPS = ('pairwise', 'priority', 'temporal', 'legacy')


def load_model(path):
    model = json.loads(Path(path).read_text())
    expected = dict(schema_version=1, bits=[0, 1, 2, 3], binary_factors=list(FACTORS),
                    pairwise_strength=2, priority_pending=1, event_offsets=[-1, 0, 1],
                    wait_configurations=[0, 1, 3])
    if any(model.get(k) != v for k, v in expected.items()):
        raise ValueError('unsupported interaction model definition')
    if type(model.get('revision')) is not int or model['revision'] < 1:
        raise ValueError('invalid model revision')
    extra = model.get('extra_goals', {})
    if not isinstance(extra, dict) or set(extra) - set(GROUPS):
        raise ValueError('unknown extra-goal group')
    for group, goals in extra.items():
        if (not isinstance(goals, list) or len(goals) != len(set(goals)) or
                any(not isinstance(g, str) or not g.startswith(group + '/') for g in goals)):
            raise ValueError('invalid extra goals')
    return model


def required_groups(model, legacy):
    groups = {g: set() for g in GROUPS}
    for bit in model['bits']:
        for a, b in combinations(FACTORS, 2):
            for x, y in product((0, 1), repeat=2):
                groups['pairwise'].add(f'pairwise/bit{bit}/{a}{x}/{b}{y}')
        for mask, clear, event in product((0, 1), repeat=3):
            groups['priority'].add(f'priority/bit{bit}/mask{mask}/clear{clear}/event{event}')
        for pending, mask, offset in product((0, 1), (0, 1), (-1, 0, 1)):
            groups['temporal'].add(f'temporal/bit{bit}/pending{pending}/mask{mask}/offset{offset}')
    groups['legacy'] = {'legacy/' + g for g in legacy}
    for group, goals in model.get('extra_goals', {}).items():
        groups[group].update(goals)
    return groups


def project_vectors(vectors, wait):
    """Independent specification-based planning model, never used as observed evidence."""
    config = pending = elapsed = 0
    records = []
    for cycle, row in enumerate(vectors, 1):
        rst, sel, enable, write, address, data, event = row
        ready = int(bool(rst and sel and enable and elapsed >= wait))
        invalid = address not in (0, 4, 8) or (write and address == 4)
        record = dict(zip(FIELDS[:7], row), cycle=cycle, ready=ready,
                      error=int(bool(ready and invalid)), pre_config=config,
                      pre_pending=pending, checked=False)
        if not rst:
            config = pending = elapsed = 0
        else:
            if ready and write and not invalid and address == 0:
                config = data
            for bit in range(4):
                if ready and write and address == 8 and data & (1 << bit):
                    pending &= ~(1 << bit)
                if event & (1 << bit):
                    pending |= 1 << bit
            if sel and not enable:
                elapsed = 0
            elif sel and enable:
                elapsed += 1
        record.update(post_config=config, post_pending=pending,
                      irq=int(bool(config & pending & 15)))
        records.append(record)
    return records


def clear_transfer(record):
    return (record['rst'] and record['sel'] and record['enable'] and record['ready']
            and not record['error'] and record['write'] and record['address'] == 8)


def collect(records):
    """Distinct goals -> the actual cycle(s) establishing the same scenario's condition."""
    hits = {}

    def hit(goal, cycles):
        hits.setdefault(goal, []).append(cycles)

    for i, r in enumerate(records):
        if not clear_transfer(r):
            continue
        for bit in range(4):
            values = dict(pending=(r['pre_pending'] >> bit) & 1,
                          mask=(r['pre_config'] >> bit) & 1,
                          clear=(r['data'] >> bit) & 1, event=(r['event'] >> bit) & 1)
            hit(f"full4/bit{bit}/pending{values['pending']}/mask{values['mask']}/clear{values['clear']}/event{values['event']}", [r['cycle']])
            for a, b in combinations(FACTORS, 2):
                hit(f'pairwise/bit{bit}/{a}{values[a]}/{b}{values[b]}', [r['cycle']])
            if values['pending']:
                hit(f"priority/bit{bit}/mask{values['mask']}/clear{values['clear']}/event{values['event']}",
                    [r['cycle']])
            if not values['clear'] or i == 0 or i + 1 == len(records):
                continue
            window = records[i-1:i+2]
            if not all(w['rst'] for w in window):
                continue
            mask = values['mask']
            if any(((w[key] >> bit) & 1) != mask for w in window
                   for key in ('pre_config', 'post_config')):
                continue
            if any(clear_transfer(w) and w['data'] & (1 << bit)
                   for w in (window[0], window[2])):
                continue
            offsets = [j - 1 for j, w in enumerate(window) if w['event'] & (1 << bit)]
            if len(offsets) != 1:
                continue
            initial = (window[0]['pre_pending'] >> bit) & 1
            goal = f'temporal/bit{bit}/pending{initial}/mask{mask}/offset{offsets[0]}'
            hit(goal, [w['cycle'] for w in window])
    return hits


def read_trace(path, vectors, complete):
    """Strict prefix for a failed run; all rows and verdicts are required on success."""
    rows = []
    for line in Path(path).read_text().splitlines():
        words = line.split()
        if words[:1] == ['OBS'] and len(words) == 16:
            cycle = int(words[1])
            if cycle != len(rows) + 1 or cycle > len(vectors) or (rows and not rows[-1]['checked']):
                raise ValueError('non-contiguous observation or unfinished earlier cycle')
            values = [int(word, 16) for word in words[2:]]
            if any(v < 0 or v >= (1 << width) for v, width in zip(values, WIDTHS)):
                raise ValueError('out-of-range observation')
            if values[:7] != vectors[cycle-1]:
                raise ValueError('observed stimulus differs from saved vectors')
            row = dict(zip(FIELDS, values), cycle=cycle, checked=False)
            if rows and (row['pre_config'], row['pre_pending']) != (
                    rows[-1]['post_config'], rows[-1]['post_pending']):
                raise ValueError('pre/post state continuity differs')
            rows.append(row)
        elif words[:1] == ['OK'] and len(words) == 2:
            if not rows or int(words[1]) != rows[-1]['cycle'] or rows[-1]['checked']:
                raise ValueError('duplicate or unmatched checker verdict')
            rows[-1]['checked'] = True
        else:
            raise ValueError('malformed observation or checker verdict')
    if not rows or (complete and (len(rows) != len(vectors) or not rows[-1]['checked'])):
        raise ValueError('missing observations or checker completion')
    return rows

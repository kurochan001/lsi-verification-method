"""Independent expectations: property semantics over a trace, hand-checked traces, queue model."""
import random

PATTERNS = ('hold', 'onehot', 'within', 'nodup', 'pipe', 'order', 'cross')
SEL = {name: index + 1 for index, name in enumerate(PATTERNS)}
KINDS = ('pass', 'violation', 'vacuous')
LEN = 48
WITHIN_N, PIPE_LAT, CROSS_N = 3, 2, 3


def idle(ea=1, eb=1):
    return dict(ea=ea, eb=eb, rst=1, v0=0, v1=0, d0=0, d1=0)


def blank(cross=False):
    """Row 0 holds the checkers in reset. For the two-clock pattern clk_b ticks on even rows only."""
    rows = [idle(1, 1 if not cross or r % 2 == 0 else 0) for r in range(LEN)]
    rows[0]['rst'] = 0
    return rows


def put(rows, tick, **fields):
    rows[tick].update(fields)


def encode(rows):
    """One 13-bit hexadecimal word per row, in the layout of tb/trace_harness.sv."""
    return ''.join(format(r['ea'] << 12 | r['eb'] << 11 | r['rst'] << 10 | r['v0'] << 9 | r['v1'] << 8 |
                          r['d0'] << 4 | r['d1'], '04x') + '\n' for r in rows)


def fixed_traces():
    """Three hand-written traces per pattern. The expected results are in expected.json."""
    t = {}
    r = blank(); put(r, 2, v0=1, d0=5); put(r, 3, v0=1, d0=5); put(r, 4, v0=1, v1=1, d0=5); put(r, 6, v0=1, v1=1, d0=9)
    t['hold', 'pass'] = r
    r = blank(); put(r, 2, v0=1, d0=5); put(r, 3, v0=1, d0=6)
    t['hold', 'violation'] = r
    r = blank(); put(r, 2, v0=1, v1=1, d0=5); put(r, 3, v0=1, v1=1, d0=6)
    t['hold', 'vacuous'] = r

    r = blank(); put(r, 2, v0=1, d0=1); put(r, 3, v0=1, d0=8); put(r, 4, d0=3)
    t['onehot', 'pass'] = r
    r = blank(); put(r, 2, v0=1, d0=4); put(r, 3, v0=1, d0=6); put(r, 4, v0=1, d0=0)
    t['onehot', 'violation'] = r
    r = blank(); put(r, 2, d0=0); put(r, 3, d0=3)
    t['onehot', 'vacuous'] = r

    r = blank(); put(r, 2, v0=1); put(r, 3, v1=1); put(r, 5, v0=1); put(r, 8, v1=1); put(r, 10, v0=1); put(r, 11, v0=1); put(r, 13, v1=1)
    t['within', 'pass'] = r
    r = blank(); put(r, 2, v0=1); put(r, 6, v1=1); put(r, 8, v0=1, v1=1)
    t['within', 'violation'] = r
    r = blank(); put(r, 3, v1=1); put(r, 5, v1=1)
    t['within', 'vacuous'] = r

    r = blank(); put(r, 2, v0=1, d0=1); put(r, 3, v0=1, d0=2); put(r, 5, v1=1, d1=1); put(r, 6, v0=1, d0=1); put(r, 7, v1=1, d1=2); put(r, 8, v1=1, d1=1)
    t['nodup', 'pass'] = r
    r = blank(); put(r, 2, v0=1, d0=1); put(r, 4, v0=1, d0=1); put(r, 6, v0=1, d0=1, v1=1, d1=1); put(r, 8, v1=1, d1=1)
    t['nodup', 'violation'] = r
    r = blank(); put(r, 3, v1=1, d1=1)
    t['nodup', 'vacuous'] = r

    r = blank(); put(r, 2, v0=1, d0=5); put(r, 3, v0=1, d0=7); put(r, 4, v1=1, d1=5); put(r, 5, v1=1, d1=7)
    t['pipe', 'pass'] = r
    r = blank(); put(r, 2, v0=1, d0=5); put(r, 4, v1=1, d1=6); put(r, 6, v0=1, d0=3)
    t['pipe', 'violation'] = r
    r = blank(); put(r, 4, v1=1, d1=5)
    t['pipe', 'vacuous'] = r

    r = blank(); put(r, 2, v0=1, d0=1); put(r, 3, v0=1, d0=2); put(r, 5, v1=1, d1=1); put(r, 6, v1=1, d1=2); put(r, 7, v0=1, d0=3); put(r, 9, v1=1, d1=3)
    t['order', 'pass'] = r
    r = blank(); put(r, 2, v0=1, d0=1); put(r, 3, v0=1, d0=2); put(r, 5, v1=1, d1=2); put(r, 6, v1=1, d1=1); put(r, 7, v0=1, d0=4); put(r, 8, v0=1, d0=5); put(r, 9, v1=1, d1=5)
    t['order', 'violation'] = r
    t['order', 'vacuous'] = blank()

    r = blank(True); put(r, 3, v0=1); put(r, 8, v1=1); put(r, 10, v0=1); put(r, 14, v1=1)
    t['cross', 'pass'] = r
    r = blank(True); put(r, 3, v0=1); put(r, 10, v1=1); put(r, 11, v0=1)
    t['cross', 'violation'] = r
    r = blank(True); put(r, 6, v1=1)
    t['cross', 'vacuous'] = r
    return t


def evaluate(pattern, rows):
    """Failure ticks and antecedent ticks of one pattern, written from the property definitions."""
    fails, hits = [], []
    if pattern == 'hold':
        for t, r in enumerate(rows):
            if not r['rst']:
                continue
            p = rows[t - 1]
            if t and p['rst'] and p['v0'] and not p['v1'] and not (r['v0'] and r['d0'] == p['d0']):
                fails.append(t)
            if r['v0'] and not r['v1']:
                hits.append(t)
    elif pattern == 'onehot':
        for t, r in enumerate(rows):
            if r['rst'] and r['v0']:
                hits.append(t)
                if bin(r['d0']).count('1') != 1:
                    fails.append(t)
    elif pattern == 'within':
        for t, r in enumerate(rows):
            if r['rst'] and r['v0']:
                hits.append(t)
                window = rows[t + 1:t + 1 + WITHIN_N]
                if len(window) == WITHIN_N and not any(w['v1'] for w in window):
                    fails.append(t + WITHIN_N)
        fails = sorted(set(fails))
    elif pattern == 'nodup':
        opened = set()
        for t, r in enumerate(rows):
            if not r['rst']:
                opened.clear()
                continue
            tag, dtag = r['d0'] & 3, r['d1'] & 3
            if r['v0']:
                hits.append(t)
                if tag in opened:
                    fails.append(t)
            if r['v1']:
                opened.discard(dtag)
            if r['v0']:
                opened.add(tag)
    elif pattern == 'pipe':
        for t, r in enumerate(rows):
            if r['rst'] and r['v0']:
                hits.append(t)
                if t + PIPE_LAT < len(rows):
                    q = rows[t + PIPE_LAT]
                    if not (q['v1'] and q['d1'] == r['d0']):
                        fails.append(t + PIPE_LAT)
    elif pattern == 'order':
        queue = []                      # [payload, followed]
        for t, r in enumerate(rows):
            if not r['rst']:
                queue.clear()
                continue
            follow = bool(r['v0']) and not any(entry[1] for entry in queue)
            if r['v1'] and queue:
                payload, followed = queue.pop(0)
                if followed and payload != r['d1']:
                    fails.append(t)
            if r['v0']:
                queue.append([r['d0'], follow])
                if follow:
                    hits.append(t)
    elif pattern == 'cross':
        sent = seen = pending = False
        edges = 0
        for t, r in enumerate(rows):
            if not r['rst']:
                sent = seen = pending = False
                continue
            if r['eb']:
                fresh = sent != seen
                if pending and not r['v1'] and (fresh or edges == CROSS_N - 1):
                    fails.append(t)
                if fresh:
                    hits.append(t)
                    seen, pending, edges = sent, True, 1
                elif pending:
                    pending = not r['v1']
                    edges += 1
            if r['ea'] and r['v0']:
                sent = not sent
    else:
        raise ValueError(pattern)
    return fails, hits


def random_trace(pattern, seed, faults):
    """Random traffic. Without faults every row obeys the property; with faults some rows break it."""
    rng = random.Random(f'{pattern}-{seed}-{faults}')
    rows = blank(pattern == 'cross')
    keep = (lambda p: rng.random() < p) if faults else (lambda p: True)
    if pattern == 'order':
        queue, used = [], 0
        for t in range(1, LEN):
            push = len(queue) < 6 and rng.random() < 0.5
            pop = bool(queue) and rng.random() < 0.45
            head = queue[0] if queue else 0
            if pop:
                queue.pop(0)
                if not keep(0.85):
                    head ^= 1 << rng.randrange(4)
            if push:
                used = (used * 5 + 3) & 15
                queue.append(used)
            put(rows, t, v0=int(push), v1=int(pop), d0=used if push else 0, d1=head if pop else 0)
        return rows
    if pattern == 'cross':
        busy = limit = 0
        for t in range(1, LEN):
            accept = busy == 0 and rng.random() < 0.3
            note = 0
            if busy:
                busy += rows[t]['eb']
                if rows[t]['eb'] and busy >= limit:
                    note, busy = 1, 0
            if accept:
                busy, limit = 1, rng.choice((3, 4)) if keep(0.7) else 5
            put(rows, t, v0=int(accept), v1=note)
        return rows
    opened, age = set(), 0
    for t in range(1, LEN):
        if pattern == 'hold':
            p = rows[t - 1]
            if p['v0'] and not p['v1'] and keep(0.9):
                put(rows, t, v0=1, v1=rng.randrange(2), d0=p['d0'])
            else:
                put(rows, t, v0=rng.randrange(2), v1=rng.randrange(2), d0=rng.randrange(16))
        elif pattern == 'onehot':
            put(rows, t, v0=int(rng.random() < 0.7), d0=1 << rng.randrange(4) if keep(0.9) else rng.randrange(16))
        elif pattern == 'within':
            # age counts the cycles since the oldest unanswered request.
            ack = keep(0.7) if age >= WITHIN_N else rng.random() < 0.3
            req = rng.random() < 0.25
            put(rows, t, v0=int(req), v1=int(ack))
            age = (0 if ack else age + 1 if age else 0) or int(req)
        elif pattern == 'nodup':
            free = [i for i in range(4) if i not in opened]
            start = rng.random() < 0.4 and (bool(free) or faults)
            done = rng.random() < 0.4 and (bool(opened) or faults)
            tag = rng.choice(free) if free and keep(0.9) else rng.randrange(4)
            dtag = rng.choice(sorted(opened)) if opened and keep(0.9) else rng.randrange(4)
            put(rows, t, v0=int(start), v1=int(done), d0=tag, d1=dtag)
            if done:
                opened.discard(dtag)
            if start:
                opened.add(tag)
        elif pattern == 'pipe':
            put(rows, t, v0=int(rng.random() < 0.4), d0=rng.randrange(16))
            if t >= PIPE_LAT and rows[t - PIPE_LAT]['v0'] and rows[t - PIPE_LAT]['rst'] and keep(0.9):
                put(rows, t, v1=1, d1=rows[t - PIPE_LAT]['d0'])
            else:
                put(rows, t, v1=rng.randrange(2), d1=rng.randrange(16))
    return rows


class Queue:
    """Cycle model of rtl/tagged_queue.sv, written from its specification."""
    def __init__(self, lat=1):
        self.lat, self.items, self.wait, self.inside = lat, [], 0, set()

    def step(self, in_valid, in_id, in_data, out_ready):
        in_ready = len(self.items) < 4 and in_id not in self.inside
        out_valid = bool(self.items) and self.wait == 0
        out_id, out_data = self.items[0] if self.items else (0, 0)
        take, give = bool(in_valid) and in_ready, out_valid and bool(out_ready)
        new_head = (take and (not self.items or (give and len(self.items) == 1))) or (give and len(self.items) > 1)
        if give:
            self.inside.discard(self.items.pop(0)[0])
        if take:
            self.items.append((in_id, in_data))
            self.inside.add(in_id)
        self.wait = self.lat if new_head else max(0, self.wait - 1)
        return int(in_ready), int(out_valid), out_id, out_data


def queue_stimulus(seed, cycles):
    """Input rows (in_valid, in_id, in_data, out_ready, evt): seed None is the fixed scenario."""
    if seed is None:
        rows = [(1, i & 3, 0x10 + i, 0, i % 5 == 0) for i in range(8)]             # fill, refuse when full
        rows += [(0, 0, 0, 1, 0)] * 10                                             # drain
        rows += [(1, 2, 0x40 + i, 1, 1) for i in range(8)]                          # same identifier: wait for exit
        rows += [(1, i & 3, 0x60 + i, i % 3 != 0, i % 2) for i in range(16)]        # mixed
        rows += [(0, 0, 0, 1, 0)] * 12
        return rows
    rng = random.Random(seed)
    rows, stall = [], 0
    for _ in range(cycles):
        if stall == 0 and rng.random() < 0.08:
            stall = rng.randrange(2, 9)
        ready = 0 if stall else int(rng.random() < 0.7)
        stall = max(0, stall - 1)
        rows.append((int(rng.random() < 0.7), rng.randrange(4), rng.randrange(256), ready, int(rng.random() < 0.4)))
    return rows + [(0, 0, 0, 1, 0)] * 12


def queue_vectors(rows, lat=1):
    """Append the expected in_ready, out_valid, out_id and out_data to every stimulus row."""
    model, lines = Queue(lat), []
    for in_valid, in_id, in_data, out_ready, evt in rows:
        in_ready, out_valid, out_id, out_data = model.step(in_valid, in_id, in_data, out_ready)
        word = (in_valid << 24 | in_id << 22 | in_data << 14 | out_ready << 13 | int(evt) << 12 |
                in_ready << 11 | out_valid << 10 | out_id << 8 | out_data)
        lines.append(format(word, '07x'))
    return lines

"""Reference for the renaming example: instructions executed one after another, without renaming.

The model knows the instructions in flight in program order and the committed value of each
logical register. It knows nothing of physical registers, pointers or the free list. A row is
one operation of the bench: op, a, b, c, d, e.
"""
import random

RESET, ALLOC, DONE, FLUSH, COMMIT, READ, BOTH = range(7)
NONE, RETIRE, TRAP = range(3)
# Flags of a row; the bench reports the goal of each flag once the checks of the row have passed.
F_IGNORED, F_CANCEL, F_NOTHING, F_SAME_DST, F_YOUNGER, F_REUSE, F_INFLIGHT = (1 << n for n in range(7))


class Model:
    def __init__(self, lregs, pregs, rob):
        self.lregs = lregs
        # An instruction needs a place in the buffer and a spare physical register.
        self.capacity = min(rob, pregs - lregs)
        self.rows = []
        self.next_id = 0
        self.counts = dict(steps=0, allocs=0, retires=0, traps=0, flushes=0)
        self.reset()

    def row(self, *values):
        self.rows.append(list(values) + [0] * (6 - len(values)))

    def reset(self):
        flags = F_INFLIGHT if getattr(self, 'flight', None) else 0
        self.state = [0] * self.lregs
        self.flight = []       # in program order: dict(id, dst, value, done, exc)
        self.gone = set()      # cancelled or retired; their place has not been given out again
        self.flushed = False
        self.row(RESET, 0, 0, 0, 0, flags)

    def room(self):
        return len(self.flight) < self.capacity

    def alloc(self, dst):
        """An instruction that writes dst; refused when there is no room. Returns its id or None."""
        ident, ready = self.next_id, self.room()
        flags = F_REUSE if ready and self.flushed else 0
        self.row(ALLOC, ident, dst, int(ready), 0, flags)
        if not ready:
            return None
        self.next_id += 1
        self.flight.append(dict(id=ident, dst=dst, value=None, done=False, exc=False))
        self.gone.clear()      # places and registers may now be reused
        self.flushed = False
        self.counts['allocs'] += 1
        return ident

    def find(self, ident):
        return next((i for i in self.flight if i['id'] == ident), None)

    def done(self, ident, value, exc=False):
        """Completion. A second one, or one for an instruction that is gone, changes nothing."""
        item = self.find(ident)
        if item is None and ident not in self.gone:
            raise ValueError('the place of this instruction may belong to another one by now')
        ignored = item is None or item['done']
        self.row(DONE, ident, value, int(exc), 0, F_IGNORED if ignored else 0)
        if not ignored:
            item.update(value=value, done=True, exc=exc)

    def flush(self, ident):
        """Cancel everything younger than ident, which stays."""
        position = next(n for n, i in enumerate(self.flight) if i['id'] == ident)
        kept, cancelled = self.flight[:position + 1], self.flight[position + 1:]
        flags = F_CANCEL if cancelled else F_NOTHING
        if any(c['dst'] == k['dst'] for c in cancelled for k in kept):
            flags |= F_SAME_DST
        self.row(FLUSH, ident, len(kept), 0, 0, flags)
        self.flight = kept
        self.gone.update(c['id'] for c in cancelled)
        self.flushed = self.flushed or bool(cancelled)
        self.counts['flushes'] += 1

    def _commit(self):
        """What the head does when commit is enabled: kind, id, dst, value, flags."""
        if not self.flight or not self.flight[0]['done']:
            return NONE, 0, 0, 0, 0
        head = self.flight[0]
        if head['exc']:
            flags = F_YOUNGER if len(self.flight) > 1 else 0
            self.gone.update(i['id'] for i in self.flight)
            self.flight = []
            self.flushed = True
            self.counts['traps'] += 1
            return TRAP, head['id'], head['dst'], 0, flags
        self.flight.pop(0)
        self.gone.add(head['id'])
        self.state[head['dst']] = head['value']
        self.counts['retires'] += 1
        return RETIRE, head['id'], head['dst'], head['value'], 0

    def commit(self):
        kind, ident, dst, value, flags = self._commit()
        self.row(COMMIT, kind, dst, value, ident, flags)
        return kind

    def commit_and_alloc(self, dst):
        """Both in one cycle. The room is the one before the retirement."""
        ident, ready = self.next_id, self.room()
        kind, head, head_dst, value, _ = self._commit()
        if kind != RETIRE:
            raise ValueError('only a retirement is combined with an allocation')
        self.row(BOTH, ident, dst, int(ready), head | head_dst << 12, value)
        if ready:
            self.next_id += 1
            self.flight.append(dict(id=ident, dst=dst, value=None, done=False, exc=False))
            self.gone.clear()
            self.flushed = False
            self.counts['allocs'] += 1
            return ident
        return None

    def read_all(self):
        for register, value in enumerate(self.state):
            self.row(READ, register, value)

    def finish(self):
        self.read_all()
        self.counts['steps'] = len(self.rows)
        return self.rows, self.counts


def boundary(lregs, pregs, rob):
    """The fixed scenario. Each mutant first goes wrong at the step named beside it."""
    m = Model(lregs, pregs, rob)
    m.read_all()
    a = m.alloc(1)
    m.done(a, 0x11)
    m.commit()                       # mutant 2: frees the committed register
    m.read_all()
    b = m.alloc(2)
    m.commit()                       # the head has not completed
    c = m.alloc(2)                   # the same logical register again
    m.flush(b)                       # mutants 1 and 3: undoing c; mutant 5: b is cancelled too
    m.done(b, 0x22)
    m.commit()
    m.read_all()
    first = m.alloc(3)               # a register and a place are reused
    while m.room():
        m.alloc(len(m.flight) % lregs)
    m.alloc(0)                       # mutant 4: no room
    youngest = m.flight[-1]['id']
    m.done(first, 0x33)
    m.done(first, 0x44)              # ignored: already complete
    m.flush(youngest)                # nothing is younger
    m.commit_and_alloc(1)            # refused: the room of this cycle is the one before the retirement
    second = m.flight[0]['id']
    m.done(second, 0x55)
    m.commit()
    third = m.flight[0]['id']
    m.done(third, 0x66)
    m.commit_and_alloc(2)            # accepted in the cycle of a retirement
    m.read_all()
    while len(m.flight) < 2:
        m.alloc(3)
    trapped, lost = m.flight[0]['id'], m.flight[1]['id']
    m.done(lost, 0x77)
    m.done(trapped, 0x88, exc=True)
    m.commit()                       # mutant 6: the exception is retired
    m.done(lost, 0x99)               # ignored: cancelled by the exception
    m.read_all()
    m.commit()                       # the buffer is empty
    alone = m.alloc(0)
    m.done(alone, 0xaa, exc=True)
    m.commit()                       # an exception with nothing younger
    m.alloc(1)
    after = m.alloc(0)
    m.done(after, 0xbb)
    m.reset()                        # with instructions in flight
    m.read_all()
    again = m.alloc(3)
    m.done(again, 0xcc)
    m.commit()
    return m.finish()


def random_rows(lregs, pregs, rob, seed, operations):
    rng = random.Random(seed)
    m = Model(lregs, pregs, rob)
    value = lambda: rng.choice((0, 0xff, rng.randrange(256)))
    while len(m.rows) < operations:
        roll = rng.random()
        pending = [i for i in m.flight if not i['done']]
        if roll < 0.30:
            m.alloc(rng.randrange(lregs))
        elif roll < 0.55 and pending:
            m.done(rng.choice(pending)['id'], value(), exc=rng.random() < 0.12)
        elif roll < 0.60 and (m.gone or len(pending) < len(m.flight)):
            done = [i['id'] for i in m.flight if i['done']]
            m.done(rng.choice(sorted(m.gone) + done), value())      # ignored
        elif roll < 0.70 and m.flight:
            m.flush(rng.choice(m.flight)['id'])
        elif roll < 0.74 and m.flight and m.flight[0]['done'] and not m.flight[0]['exc']:
            m.commit_and_alloc(rng.randrange(lregs))
        elif roll < 0.93:
            if m.commit() != NONE and rng.random() < 0.5:
                m.read_all()
        elif roll < 0.95:
            m.reset()
        else:
            m.read_all()
    return m.finish()

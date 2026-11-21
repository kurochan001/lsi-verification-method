"""Reference for the buffer manager: Python lists, no pointers.

The free list is a first-in first-out list of buffer numbers, every queue is a list, and the
held buffers are a set. The model knows nothing of the next-pointer table. A row is one cycle
of the bench:

  op, enq_v, enq_q, deq_v, deq_q, rel_v, rel_id,
  expected enq_ready, enq_id, deq_ready, deq_id, rel_ready,
  expected free count, counts of queues 0..3 after the cycle, flags.

The expected ready values are those for the inputs of the row, also when the valid is 0, and an
expected id is checked only when its ready is 1.
"""
import random

RESET, CYCLE = 0, 1
COLUMNS = 18
GOALS = ['enq/accepted', 'enq/refused-full', 'deq/accepted', 'deq/refused-empty',
         'release/accepted', 'release/twice', 'release/queued', 'same/one', 'same/many',
         'free/swap-one', 'free/refill-empty', 'cycle/three', 'cycle/idle', 'held/all',
         'queue/last', 'enq/reuse', 'reset/busy']
FLAG = {goal: 1 << n for n, goal in enumerate(GOALS)}


class Model:
    def __init__(self, nb, nq):
        self.nb, self.nq = nb, nq
        self.rows = []
        self.counts = dict(steps=0, enqs=0, deqs=0, releases=0, refused=0, resets=0)
        self.free = list(range(nb))
        self.queues = [[] for _ in range(nq)]
        self.held = set()
        self.released = set()
        self.reset()

    def place(self, buffer):
        if buffer in self.free:
            return 'free'
        if buffer in self.held:
            return 'held'
        return next(f'queue{q}' for q, items in enumerate(self.queues) if buffer in items)

    def _tail(self):
        return [len(self.free)] + [len(q) for q in self.queues] + [0] * (4 - self.nq)

    def reset(self):
        busy = len(self.free) != self.nb
        self.free = list(range(self.nb))
        self.queues = [[] for _ in range(self.nq)]
        self.held = set()
        self.released = set()
        self.counts['resets'] += 1
        flags = FLAG['reset/busy'] if busy else 0
        self.rows.append([RESET] + [0] * 11 + self._tail() + [flags])

    def cycle(self, enq=None, deq=None, rel=None, enq_q=0, deq_q=0, rel_id=0):
        """One cycle. enq, deq: queue numbers or None; rel: buffer number or None.
        enq_q, deq_q, rel_id are what the idle inputs show when the operation is not requested."""
        enq_v, deq_v, rel_v = enq is not None, deq is not None, rel is not None
        enq_q = enq if enq_v else enq_q
        deq_q = deq if deq_v else deq_q
        rel_id = rel if rel_v else rel_id
        enq_ready = len(self.free) > 0
        enq_id = self.free[0] if enq_ready else 0
        deq_ready = len(self.queues[deq_q]) > 0
        deq_id = self.queues[deq_q][0] if deq_ready else 0
        rel_ready = rel_id in self.held
        enq_fire, deq_fire, rel_fire = enq_v and enq_ready, deq_v and deq_ready, rel_v and rel_ready
        flags = 0
        if enq_v:
            flags |= FLAG['enq/accepted'] if enq_ready else FLAG['enq/refused-full']
        if deq_v:
            flags |= FLAG['deq/accepted'] if deq_ready else FLAG['deq/refused-empty']
        if rel_v:
            if rel_ready:
                flags |= FLAG['release/accepted']
            else:
                flags |= FLAG['release/twice'] if rel_id in self.free else FLAG['release/queued']
        if enq_fire and deq_fire and enq_q == deq_q:
            flags |= FLAG['same/one'] if len(self.queues[enq_q]) == 1 else FLAG['same/many']
        if enq_fire and rel_fire and len(self.free) == 1:
            flags |= FLAG['free/swap-one']
        if rel_fire and not self.free:
            flags |= FLAG['free/refill-empty']
        if enq_fire and deq_fire and rel_fire and enq_q != deq_q:
            flags |= FLAG['cycle/three']
        if not (enq_v or deq_v or rel_v):
            flags |= FLAG['cycle/idle']
        if enq_fire and enq_q == self.nq - 1:
            flags |= FLAG['queue/last']
        if enq_fire and enq_id in self.released:
            flags |= FLAG['enq/reuse']
        # All operations see the state at the start of the cycle.
        if enq_fire:
            self.free.pop(0)
            self.counts['enqs'] += 1
        if deq_fire:
            self.held.add(self.queues[deq_q].pop(0))
            self.counts['deqs'] += 1
        if enq_fire:
            self.queues[enq_q].append(enq_id)
        if rel_fire:
            self.held.remove(rel_id)
            self.free.append(rel_id)
            self.released.add(rel_id)
            self.counts['releases'] += 1
        elif rel_v:
            self.counts['refused'] += 1
        if len(self.held) == self.nb:
            flags |= FLAG['held/all']
        self.rows.append([CYCLE, int(enq_v), enq_q, int(deq_v), deq_q, int(rel_v), rel_id,
                          int(enq_ready), enq_id, int(deq_ready), deq_id, int(rel_ready)] + self._tail() + [flags])
        return (enq_id if enq_fire else None), (deq_id if deq_fire else None), rel_fire

    def finish(self):
        self.counts['steps'] = len(self.rows)
        return self.rows, self.counts


def boundary(nb, nq):
    """The fixed scenario. The comment beside a step names the mutant that first goes wrong there."""
    m = Model(nb, nq)
    m.cycle()                                   # nothing requested; readies still checked
    m.cycle(deq=0)                              # mutant 5: a dequeue from an empty queue
    m.cycle(enq=0)                              # queue 0 = [0]
    m.cycle(enq=1)                              # queue 1 = [1]
    m.cycle(enq=0)                              # mutant 3: queue 0 = [0, 2], the old tail is linked
    _, first, _ = m.cycle(deq=0)                # buffer 0 is held
    m.cycle(rel=first)                          # mutant 1: the released buffer joins the free list
    m.cycle(rel=first)                          # mutant 2: released twice, refused
    m.cycle(rel=1)                              # refused: buffer 1 is in queue 1
    m.cycle(rel=m.free[0])                      # refused: a free buffer
    m.cycle(enq=1, deq=1)                       # mutant 4: queue 1 has one buffer; out and in at once
    m.cycle(enq=0)
    m.cycle(enq=nq - 1)                         # the last queue; the next free buffer is not the one after the tail
    m.cycle(enq=0, deq=0)                       # queue 0 has two: out and in at once, the tail is linked
    # Take every free buffer, then refuse one more enqueue (mutant 6).
    q = 0
    while m.free:
        m.cycle(enq=q)
        q = (q + 1) % nq
    m.cycle(enq=0)                              # mutant 6: the free list is empty
    # Hold two buffers, release one into the empty free list, then swap with the other.
    _, a, _ = m.cycle(deq=0)
    _, b, _ = m.cycle(deq=1)
    m.cycle(rel=a)                              # the free list was empty
    m.cycle(enq=2 % nq, rel=b)                  # mutant 7: one free buffer leaves while another joins
    _, h, _ = m.cycle(deq=0)
    m.cycle(enq=0, deq=1, rel=h)                # three at once, on different queues
    # Hold every buffer, then give them all back.
    while m.free:
        m.cycle(enq=0)
    while any(m.queues):
        for q in range(nq):
            if m.queues[q]:
                m.cycle(deq=q)
    m.cycle()
    for buffer in sorted(m.held):
        m.cycle(rel=buffer)
    for q in range(nq):                         # reuse of released buffers
        m.cycle(enq=q)
    _, c, _ = m.cycle(deq=0)
    m.reset()                                   # with buffers in queues and held
    m.cycle(rel=c)                              # refused: a reset gives every buffer back
    m.cycle(enq=0)
    m.cycle(deq=0)
    return m.finish()


def random_rows(nb, nq, seed, operations):
    rng = random.Random(seed)
    m = Model(nb, nq)
    while len(m.rows) < operations:
        if rng.random() < 0.01:
            m.reset()
            continue
        enq = rng.randrange(nq) if rng.random() < 0.45 else None
        deq = rng.randrange(nq) if rng.random() < 0.40 else None
        rel = None
        if rng.random() < 0.40:
            roll = rng.random()
            if roll < 0.75 and m.held:
                rel = rng.choice(sorted(m.held))
            else:
                rel = rng.randrange(nb)
        m.cycle(enq, deq, rel, enq_q=rng.randrange(nq), deq_q=rng.randrange(nq), rel_id=rng.randrange(nb))
    return m.finish()

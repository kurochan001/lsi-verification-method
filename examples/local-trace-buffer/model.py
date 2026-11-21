"""Reference for the trace buffer and the frame monitor, written from the specification.

The trace buffer is a list of every sample since arm; at the end of a capture the window is the
last min(written, DEPTH) of them. No ring, no pointers. The frame monitor counts data bytes
since the last flag.
"""
FLAG = 0x7e
MAXLEN = 4


class FrameMonitor:
    """error is a one-clock pulse after a data byte that makes the frame longer than MAXLEN.
    old=True is the revision that failed in the field: a flag right after a flag counts as data."""

    def __init__(self, old=False):
        self.old = old
        self.reset()
        self.error = 0

    def reset(self):
        self.length, self.last_flag = 0, False

    def edge(self, rst_n, valid, data):
        self.error = 0
        if not rst_n:
            self.reset()
            return
        if not valid:
            return
        flag = data == FLAG
        if flag and not (self.old and self.last_flag):
            self.length = 0
        else:
            if not flag and self.length >= MAXLEN:
                self.error = 1
            self.length = min(self.length + 1, 7)
        self.last_flag = flag


class TraceModel:
    def __init__(self, depth):
        self.depth = depth
        self.reset()

    def reset(self):
        self.phase = 'idle'
        self.history, self.window, self.kept = [], [], 0
        self.post = self.sel = self.value = self.mask = 0
        self.rd = (0, 0, 0, 0)

    @property
    def busy(self):
        return int(self.phase in ('capture', 'post'))

    @property
    def done(self):
        return int(self.phase == 'done')

    def finish(self):
        self.phase = 'done'
        kept = min(len(self.history), self.depth)
        self.window = self.history[-kept:]
        self.trigger_at = self.trigger_index - (len(self.history) - kept)
        self.position = 0

    def edge(self, rst_n, arm, post, sel, value, mask, sample, ext, rd_req):
        rd = (0, 0, 0, 0)
        if not rst_n:
            self.reset()
        elif arm:
            self.phase, self.history, self.kept = 'capture', [], 0
            self.post, self.sel, self.value, self.mask = post, sel, value, mask
        elif self.busy:
            self.history.append(sample)
            self.kept = min(self.kept + 1, self.depth)
            hit = ext if self.sel else (sample & self.mask) == (self.value & self.mask)
            if self.phase == 'capture' and hit:
                self.trigger_index = len(self.history) - 1
                if self.post == 0:
                    self.finish()
                else:
                    self.phase, self.remaining = 'post', self.post
            elif self.phase == 'post':
                self.remaining -= 1
                if self.remaining == 0:
                    self.finish()
        elif self.done and rd_req and self.position < len(self.window):
            p = self.position
            rd = (1, self.window[p], int(p == self.trigger_at), int(p == len(self.window) - 1))
            self.position += 1
        self.rd = rd


class Bench:
    """Rows: [check, rst_n, arm, post, sel, value, mask, valid, data, rd_req,
    dut_error, busy, done, kept, rd_valid, rd_data, rd_trig, rd_last] (outputs before the edge)."""

    def __init__(self, depth, old=False):
        self.depth = depth
        self.trace, self.monitor = TraceModel(depth), FrameMonitor(old)
        self.rows, self.known = [], False

    def cycle(self, rst_n=1, arm=0, post=0, sel=0, value=0, mask=0, valid=0, data=0, rd_req=0):
        t, m = self.trace, self.monitor
        error = m.error
        sample = (valid << 8) | data
        self.rows.append([int(self.known), rst_n, arm, post, sel, value, mask, valid, data, rd_req,
                          error, t.busy, t.done, t.kept, *t.rd])
        if not rst_n:
            self.known = True
        if self.known:
            t.edge(rst_n, arm, post, sel, value, mask, sample, error, rd_req)
            m.edge(rst_n, valid, data)

    # Helpers.
    def reset(self, cycles=1):
        for _ in range(cycles):
            self.cycle(rst_n=0)

    def idle(self, cycles=1):
        for _ in range(cycles):
            self.cycle()

    def arm(self, post, sel=0, value=0, mask=0):
        self.cycle(arm=1, post=post, sel=sel, value=value, mask=mask)

    def stream(self, samples):
        """samples: list of (valid, data)."""
        for valid, data in samples:
            self.cycle(valid=valid, data=data)

    def read(self, count):
        for _ in range(count):
            self.cycle(rd_req=1)
        self.idle(1)                           # the last answer appears a clock later

    def readout(self):
        """What the board dump of the last finished capture contains: (sample, trigger) pairs."""
        return [(row[15], row[16]) for row in self.rows if row[14]]


def frames(rng, count, idle=0.2, double_flag=0.15):
    """Legal traffic: frames of 1..MAXLEN bytes between flags, idle clocks and, now and then, two
    flags in a row followed by a short frame (at most MAXLEN-1 bytes)."""
    out = []
    for _ in range(count):
        doubled = rng.random() < double_flag
        out.append((1, FLAG))
        if doubled:
            out.append((1, FLAG))
        for _ in range(rng.randrange(1, MAXLEN if doubled else MAXLEN + 1)):
            if rng.random() < idle:
                out.append((0, rng.randrange(256)))
            out.append((1, rng.choice([d for d in range(256) if d != FLAG])))
    return out


def field_stream():
    """The traffic of the field failure: legal frames, then two flags followed by a frame of
    exactly MAXLEN bytes (legal, but the old revision calls it too long), then more frames."""
    import random
    rng = random.Random(20261121)
    burst = [(1, FLAG), (1, FLAG), (1, 0x10), (0, 0x99), (1, 0x20), (1, 0x30), (1, 0x40)]
    return frames(rng, 40) + burst + frames(rng, 6) + [(1, FLAG)]

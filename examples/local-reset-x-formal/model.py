"""Reference for reset_x_unit, and the rows the testbench applies.

The reference keeps "unknown" as None. It never guesses: a register without a reset is unknown
until something defined was written to it, and an output is compared only where the
specification gives it a value.

Row: op, rst, in_valid, in_data, cfg_we, cfg_step2, then what is expected after the clock edge:
ready, out_valid, out_data, odd, count, err, known stage-valid mask, stage-valid bits, flush counter.
op POWER (first row only) gives the registers values before the first clock edge: flush counter,
step, valid bits, data (the same in every stage), counter, error flag, and the name of the pattern.
Without it, simulation starts from X.
"""
import random

CYCLE, POWER = 0, 1


class Model:
    def __init__(self, width, stages):
        self.width, self.stages, self.flush = width, stages, stages - 1
        self.init = None            # no reset seen yet
        self.v = [None] * stages
        self.d = [None] * stages
        self.step = self.count = self.err = None
        self.rows = []
        self.counts = dict(outputs=0, resets=0, refused=0)

    @property
    def ready(self):
        return self.init == self.flush

    def outputs(self):
        valid = bool(self.v[-1]) and self.ready
        data = self.d[-1] if valid else 0
        if valid and data is None:
            raise ValueError('a valid output without defined data')
        odd = valid and bin(data).count('1') % 2 == 1
        mask = sum(1 << k for k, bit in enumerate(self.v) if bit is not None)
        bits = sum(1 << k for k, bit in enumerate(self.v) if bit)
        return [int(self.ready), int(valid), data, int(odd), self.count, self.err, mask, bits, self.init]

    def cycle(self, rst=0, in_valid=0, in_data=0, cfg_we=0, cfg_step2=0):
        if self.init is None and not rst:
            raise ValueError('the first cycle must be a reset')
        if not 0 <= in_data < 1 << self.width:
            raise ValueError('data out of range')
        ready = self.ready
        valid = bool(self.v[-1]) and ready
        accept = bool(in_valid) and ready
        # Stage k takes the data of the stage before it when that one is valid. If that valid
        # bit is unknown, the data becomes unknown as well.
        d = list(self.d)
        for k in range(1, self.stages):
            if self.v[k - 1] is None:
                d[k] = None
            elif self.v[k - 1]:
                d[k] = self.d[k - 1]
        if accept:
            d[0] = in_data
        v = [accept and not rst] + self.v[:-1]
        if rst:
            self.init, self.step, self.count, self.err = 0, 0, 0, 0
            self.counts['resets'] += 1
        else:
            if valid:
                self.count = (self.count + (2 if self.step else 1)) % 16
            if in_valid and not ready:
                self.err = 1
                self.counts['refused'] += 1
            if cfg_we:
                self.step = int(bool(cfg_step2))
            self.init = min(self.init + 1, self.flush)
        self.v, self.d = v, d
        self.counts['outputs'] += bool(self.v[-1]) and self.ready
        self.rows.append([CYCLE, int(rst), int(in_valid), in_data, int(cfg_we), int(cfg_step2)] + self.outputs())
        return self.rows[-1]


ZEROS, ONES, MIXED = 0, 1, 2


def power_row(width, stages, power):
    """Register values at power-up. MIXED has the flush counter at 0 with the flags set."""
    ones = lambda bits: (1 << bits) - 1
    counter_bits = (stages - 1).bit_length()
    values = {ZEROS: [0, 0, 0, 0, 0, 0],
              ONES: [ones(counter_bits), 1, ones(stages), ones(width), 15, 1],
              MIXED: [0, 1, 0b101 & ones(stages), 0xA5 & ones(width), 5, 1]}[power]
    return [POWER] + values + [power] + [0] * 7


def start(width, stages, power):
    """A model and its first row. power: None (start from X), ZEROS, ONES or MIXED."""
    m = Model(width, stages)
    if power is not None:
        m.rows.append(power_row(width, stages, power))
    return m


def boundary(width, stages, power=None):
    """A fixed sequence that reaches every goal of requirements.json except the other power-up values."""
    m = start(width, stages, power)
    top = (1 << width) - 1
    m.cycle(rst=1)                                # one-cycle reset from power-up
    m.cycle(in_valid=1, in_data=1)                # offered during the flush: refused, error
    for _ in range(stages):
        m.cycle()                                 # error stays; ready rises; data still unknown
    m.cycle(in_valid=1, in_data=top)              # the first item after the first reset
    for _ in range(stages + 1):
        m.cycle()
    m.cycle(rst=1)                                # clears the error
    m.cycle(rst=1)
    m.cycle(rst=1)                                # a long reset
    for _ in range(stages - 1):
        m.cycle()
    for data in (1, top, 2, 0):                   # back to back; odd and even parity
        m.cycle(in_valid=1, in_data=data)
    for _ in range(stages + 1):
        m.cycle()
    m.cycle(cfg_we=1, cfg_step2=1)
    for data in range(9):                         # step 2 wraps the counter
        m.cycle(in_valid=1, in_data=data & top)
    for _ in range(stages + 1):
        m.cycle()
    m.cycle(cfg_we=1, cfg_step2=0)
    m.cycle(in_valid=1, in_data=3)
    m.cycle(in_valid=1, in_data=top)
    m.cycle(rst=1)                                # reset with data in flight
    for _ in range(stages + 2):
        m.cycle(in_valid=0)
    m.cycle(in_valid=1, in_data=top)
    for _ in range(stages + 1):
        m.cycle()
    return m.rows, m.counts


def random_rows(width, stages, seed, count):
    rng = random.Random(f'{seed}:{width}:{stages}')
    m = start(width, stages, rng.choice((None, ZEROS, ONES, MIXED)))
    m.cycle(rst=1)
    for _ in range(count):
        m.cycle(rst=rng.random() < 0.04, in_valid=rng.random() < 0.6, in_data=rng.randrange(1 << width),
                cfg_we=rng.random() < 0.1, cfg_step2=rng.randrange(2))
    return m.rows, m.counts

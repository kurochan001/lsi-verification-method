"""Calculate ADC observations with absolute deadlines and quantization thresholds."""
from bisect import bisect_right
from random import Random


class AdcOracle:
    def __init__(self, bits, acquire, convert, lsb_uv):
        self.acquire = acquire
        self.convert = convert
        self.thresholds = range(lsb_uv, (1 << bits) * lsb_uv, lsb_uv)
        self.tick = 0
        self.sample_at = self.complete_at = None
        self.sampled = self.code = 0
        self.valid = False

    def ready(self, reset_n):
        return bool(reset_n and self.sample_at is None and not self.valid)

    def step(self, reset_n, start, voltage, result_ready):
        ready = self.ready(reset_n)
        goals = 0
        overrun = False
        if not reset_n:
            if self.sample_at is not None or self.valid:
                goals |= 1 << 7
            self.sample_at = self.complete_at = None
            self.valid = False
            self.code = self.sampled = 0
        else:
            overrun = bool(start and not ready)
            if self.valid and not result_ready:
                goals |= 1 << 6
            if self.valid and result_ready:
                self.valid = False
            if ready and start:
                self.sample_at = self.tick + self.acquire
                self.complete_at = self.sample_at + self.convert
                goals |= 1 << 0
            if self.tick == self.sample_at:
                self.sampled = bisect_right(self.thresholds, voltage)
                goals |= 1 << 1
                if voltage < 0:
                    goals |= 1 << 2
                if voltage >= self.thresholds.stop:
                    goals |= 1 << 3
                if abs(voltage - self.thresholds.start) <= 1:
                    goals |= 1 << 4
            if self.tick == self.complete_at:
                self.code = self.sampled
                self.valid = True
                self.sample_at = self.complete_at = None
            if overrun:
                goals |= 1 << 5
        self.tick += 1
        return [int(ready), int(self.sample_at is not None), int(overrun),
                int(self.valid), self.code], goals


def vectors(parameters, seed, iterations):
    model = AdcOracle(parameters['BITS'], parameters['ACQUIRE'],
                      parameters['CONVERT'], parameters['LSB_UV'])
    rows = []

    def step(reset_n=1, start=0, voltage=0, ready=1):
        outputs, goals = model.step(reset_n, start, voltage, ready)
        rows.append([reset_n, start, voltage & 0xffffffff, ready, *outputs, goals])

    def conversion(voltage, hold=False):
        # The voltage at start, sample capture and completion is intentionally different.
        step(start=1, voltage=12345)
        for _ in range(model.acquire - 1):
            step(voltage=78912)
        step(voltage=voltage)
        for tick in range(model.convert):
            step(start=int(tick == 0 and hold), voltage=123, ready=int(not hold))
        if hold:
            step(ready=0)
            step(start=1, ready=0)
        step()

    step(reset_n=0)
    for boundary in range((1 << parameters['BITS']) + 1):
        for delta in (-1, 0, 1):
            conversion(boundary * parameters['LSB_UV'] + delta, hold=(boundary == 1))
    # Reset in acquisition, conversion and result hold.
    step(start=1)
    step(reset_n=0)
    step(start=1)
    for _ in range(model.acquire):
        step(voltage=54321)
    step(reset_n=0)
    conversion(22222)
    step(start=1)
    for _ in range(model.acquire + model.convert):
        step(voltage=87000, ready=0)
    step(reset_n=0)
    for _ in range(model.acquire + model.convert + 2):
        step()
    conversion(98765, hold=True)

    rng = Random(seed)
    for _ in range(iterations):
        step(int(rng.randrange(31) != 0), int(rng.randrange(4) == 0),
             rng.randrange(-1000, 303001), rng.randrange(2))
    for _ in range(model.acquire + model.convert + 2):
        step()
    return rows

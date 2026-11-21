"""Reference model and window specification of the token bucket.

The model uses Python integers, so it has no adder widths and cannot overflow. The window
specification is a separate check over a whole trace: it does not look at the level at all.
"""


class Bucket:
    """One clock edge per step, in the order of the specification in rtl/token_bucket.sv."""

    def __init__(self, frac):
        self.cost, self.tokens = 1 << frac, None

    def cap(self, depth):
        return depth * self.cost

    def step(self, rst_n, req, depth, rate):
        cap = self.cap(depth)
        if not rst_n:
            self.tokens = cap
            return 0, self.tokens, dict(cap=cap, avail=None)
        if self.tokens is None:
            raise ValueError('the bucket must be reset before its first request')
        total = self.tokens + rate
        avail = min(total, cap)
        grant = int(bool(req) and avail >= self.cost)
        self.tokens = avail - (self.cost if grant else 0)
        return grant, self.tokens, dict(cap=cap, avail=avail, total=total, saturated=total > cap)


def window_bound(cost, caps, rates, start, end):
    """Largest number of grants the specification allows in cycles start..end (inclusive).

    The first cycle can deliver at most a full bucket (its refill is lost to the saturation);
    every later cycle adds at most its own refill. Grants are whole tokens.
    """
    return (caps[start] + sum(rates[start + 1:end + 1])) // cost


def window_slack(cost, rows):
    """Smallest (bound - grants) over every window without a reset, and one window reaching it.

    rows: (rst_n, grant, cap, rate) per cycle. Returns (slack, (start, end)) or (None, None) when
    the trace has no cycle out of reset. Quadratic in the trace length.
    """
    best, where = None, None
    n = len(rows)
    for start in range(n):
        if not rows[start][0]:
            continue
        grants = 0
        units = rows[start][2]                       # the first cycle: at most a full bucket
        for end in range(start, n):
            rst_n, grant, cap, rate = rows[end]
            if not rst_n:
                break
            if end > start:
                units += rate
            grants += grant
            slack = units // cost - grants
            if best is None or slack < best:
                best, where = slack, (start, end)
    return best, where


def loose_bound(cost, depth, rate, length):
    """The textbook bound depth + rate * length, for a window with one constant setting."""
    return depth + (rate * length) // cost

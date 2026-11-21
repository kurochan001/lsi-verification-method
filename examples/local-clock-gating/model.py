"""Event schedule and expected counts for the clock gate, the clock switch and the odd divider.

Nothing here follows the registers of the RTL. The expected values come from the edge
times of the source clocks and from the rules of the contract:

- gate: a clock pulse appears whole at the output if, and only if, the enable is 1 at its rising edge;
- switch: with both clocks running, a change completes within 1.5 periods of each clock, and
  while one clock is selected the output has exactly the rising edges of that clock;
- divider: after reset the output rises on the first rising edge and then on every DIV-th one.

All times are in picoseconds. Clock edges lie on multiples of 1000 ps; every input change is
placed off that grid, so no input ever changes together with a clock edge.
"""
import random

SIGNALS = dict(EN=0, SEL=1, RUN_A=2, RUN_B=3, SW_RST=4, DIV_RST=5,
               CHECK_GATE=8, CHECK_ACTIVE=9, WINDOW_OPEN=10, WINDOW_CLOSE=11, CHECK_DIV=12,
               CHECK_RELEASE=13)
INPUTS = {0, 1, 2, 3, 4, 5}
GRID = 1000


def nudge(time, offset=300):
    """The next time after `time` that lies `offset` past a multiple of the grid."""
    return time - time % GRID + GRID + offset


def value_at(changes, time):
    """Value of a signal recorded as (time, value) changes, at `time`."""
    value = changes[0][1]
    for at, new in changes:
        if at > time:
            break
        value = new
    return value


def free_rises(half, start, end):
    """Rising edges in (start, end] of a clock that starts low and toggles every `half`."""
    first = (start - half) // (2 * half) + 1
    last = (end - half) // (2 * half)
    return max(0, last - first + 1)


class StoppableClock:
    """A clock that toggles on its grid only while it is running, as the bench generates it."""

    def __init__(self, half):
        self.half = half
        self.running = [(0, 1)]

    def set_running(self, time, value):
        self.running.append((time, value))

    def edges(self, end):
        level, result = 0, []
        for tick in range(self.half, end + 1, self.half):
            if value_at(self.running, tick):
                level ^= 1
                result.append((tick, level))
        return result

    def rises(self, start, end):
        return sum(level and start < tick for tick, level in self.edges(end))

    def level(self, time):
        edges = self.edges(time)
        return edges[-1][1] if edges else 0

    def next_rise(self, time, horizon=40):
        """The first rising edge after `time`, if the clock keeps its present run state."""
        for tick, level in self.edges(time + horizon * self.half):
            if level and tick > time:
                return tick
        return None


class Scenario:
    def __init__(self, parameters):
        self.period = dict(a=parameters['PERIOD_A'], b=parameters['PERIOD_B'])
        self.div = parameters['DIV']
        if self.div % 2 == 0 or self.div < 3 or any(p % (2 * GRID) for p in self.period.values()):
            raise ValueError('odd DIV of 3 or more and periods on a 2000 ps grid required')
        self.half = {name: period // 2 for name, period in self.period.items()}
        self.clock = {name: StoppableClock(half) for name, half in self.half.items()}
        self.events, self.enable = [], [(0, 0)]
        self.selected, self.windows = 'a', 0
        start = nudge(2 * max(self.period.values()))
        # One cursor per circuit: the three circuits are exercised at the same time.
        self.gate_at = self.switch_at = self.divider_at = start
        self.divider_release, self.divider_total = None, 0
        self.switch_trigger = None
        self.add(start, 'SW_RST', 1)
        self.check_active(start + 3 * self.half['a'], 'a')
        self.release_divider(start)

    # ---- bookkeeping ----
    def add(self, time, signal, value):
        if SIGNALS[signal] in INPUTS and time % GRID == 0:
            raise ValueError('an input may not change on the clock grid')
        self.events.append((time, len(self.events), SIGNALS[signal], value))
        return time

    # ---- clock gate ----
    def gate_expected(self, time):
        half = self.half['a']
        return sum(value_at(self.enable, rise) for rise in range(half, time + 1, 2 * half))

    def set_enable(self, time, value):
        self.enable.append((time, value))
        self.gate_at = max(self.gate_at, self.add(time, 'EN', value))

    def check_gate(self, time):
        self.gate_at = max(self.gate_at, self.add(time, 'CHECK_GATE', self.gate_expected(time)))

    def gate_rise(self, after):
        """A rising edge of the free-running clock, at least two periods after `after`."""
        half = self.half['a']
        return (after // (2 * half) + 3) * 2 * half + half

    # ---- clock switch ----
    def check_active(self, time, clock):
        value = dict(a=1, b=2).get(clock, 0)
        self.switch_at = self.add(nudge(time), 'CHECK_ACTIVE', value)

    def window(self, clock, periods=4):
        """Count the output edges over a few periods; `clock` is the selected one, or None."""
        opened = self.add(self.switch_at + GRID, 'WINDOW_OPEN', 0)
        closed = opened + periods * max(self.period.values())
        expected = self.clock[clock].rises(opened, closed) if clock else 0
        self.switch_at = self.add(closed, 'WINDOW_CLOSE', expected)
        self.windows += 1

    def other(self):
        return 'b' if self.selected == 'a' else 'a'

    def bound(self):
        return 3 * (self.half['a'] + self.half['b'])

    def switch(self, time=None):
        """Select the other clock while both run."""
        new = self.other()
        time = self.add(time or self.switch_at + 2 * GRID, 'SEL', int(new == 'b'))
        self.check_active(time + self.bound(), new)
        self.selected = new
        self.window(new)

    def glitch_time(self):
        """A select time, shortly after a rising edge of the selected clock, at which a plain
        multiplexer cuts the pulse short and a switch without break-before-make overlaps."""
        old, new = self.selected, self.other()
        time = self.switch_at
        for _ in range(200):
            rise = self.clock[old].next_rise(time)
            select = rise + 1500
            arrival = self.clock[new].next_rise(select)
            if (self.clock[new].level(select) == 0 and
                    arrival + self.half[new] < rise + 3 * self.half[old]):
                return select
            time = rise
        raise ValueError('no select time found for the glitch scenario')

    def switch_to_stopped_target(self, stop_delay=2 * GRID):
        """The target clock is stopped: the old clock is released and the output stays low."""
        old, new = self.selected, self.other()
        stopped = self.add(self.switch_at + stop_delay, 'RUN_' + new.upper(), 0)
        self.clock[new].set_running(stopped, 0)
        selected = self.add(stopped + 2 * GRID, 'SEL', int(new == 'b'))
        self.check_active(selected + 3 * self.half[old], None)
        self.window(None)
        resumed = self.add(self.switch_at + 2 * GRID, 'RUN_' + new.upper(), 1)
        self.clock[new].set_running(resumed, 1)
        self.check_active(resumed + 4 * self.half[new], new)
        self.selected = new
        self.window(new)

    def switch_from_stopped_clock(self, stop_delay=2 * GRID):
        """The selected clock is stopped: the switch cannot complete until it is reset."""
        old, new = self.selected, self.other()
        stopped = self.add(self.switch_at + stop_delay, 'RUN_' + old.upper(), 0)
        self.clock[old].set_running(stopped, 0)
        selected = self.add(stopped + 2 * GRID, 'SEL', int(new == 'b'))
        self.check_active(selected + self.bound(), old)
        self.window(old)
        asserted = self.add(self.switch_at + 2 * GRID, 'SW_RST', 0)
        released = self.add(asserted + 3 * GRID, 'SW_RST', 1)
        self.check_active(released + 3 * self.half[new], new)
        self.selected = new
        self.window(new)
        resumed = self.add(self.switch_at + 2 * GRID, 'RUN_' + old.upper(), 1)
        self.clock[old].set_running(resumed, 1)
        self.switch_at = resumed

    # ---- odd divider ----
    def divider_expected(self, time):
        rises = free_rises(self.half['a'], self.divider_release, time)
        return -(-rises // self.div)

    def release_divider(self, time):
        self.divider_release = self.add(time, 'DIV_RST', 1)
        self.divider_at = time

    def check_divider(self, time):
        self.divider_at = self.add(time, 'CHECK_DIV', self.divider_expected(time))

    def reset_with_b_selected(self):
        """Reset and release while clk_b stays selected, both clocks running. After the release
        clk_a must never be enabled: the reset state requests neither clock. The reset is applied
        while clk_b is low, so no pulse is cut, and released while clk_a is high, so the first edge
        of clk_a afterwards is a falling one that would enable clk_a from a wrong reset value."""
        if self.selected != 'b':
            raise ValueError('clk_b must be the selected clock')
        low = self.clock['b'].next_rise(self.switch_at) + self.half['b']
        asserted = self.add(low + 300, 'SW_RST', 0)
        rise = self.clock['a'].next_rise(asserted + 2 * GRID)
        released = self.add(rise + 300, 'SW_RST', 1)
        sample = rise + self.half['a'] + 300
        taken = self.clock['b'].next_rise(released)
        self.switch_at = self.add(sample, 'CHECK_RELEASE', 2 if taken + self.half['b'] < sample else 0)
        self.check_active(released + self.bound(), 'b')
        self.window('b')

    def reset_divider(self, time, low=2 * GRID):
        self.divider_total += self.divider_expected(time)
        self.add(time, 'DIV_RST', 0)
        self.release_divider(time + low)

    # ---- result ----
    def rows(self):
        end = nudge(max(self.gate_at, self.switch_at, self.divider_at) + 3 * self.period['a'])
        if value_at(self.enable, end):
            self.set_enable(end, 0)
            end = nudge(end + 3 * self.period['a'])
        self.check_gate(end)
        self.check_divider(end + GRID)
        ordered = sorted(self.events)
        rows, previous = [], 0
        for time, _, signal, value in ordered:
            rows.append([time - previous, signal, value])
            previous = time
        counts = dict(steps=len(rows), gate_pulses=self.gate_expected(end), switch_windows=self.windows,
                      divider_pulses=self.divider_total + self.divider_expected(end + GRID))
        return rows, counts


def gate_boundaries(s):
    period, half = s.period['a'], s.half['a']
    rise = s.gate_rise(s.gate_at)
    s.set_enable(rise - 2100, 1)                  # in the low phase: the next pulse passes
    s.check_gate(rise + 3 * period + 2600)
    s.set_enable(rise + 4 * period + 1500, 0)     # in the high phase: this pulse still passes whole
    s.check_gate(rise + 7 * period + 2600)
    s.check_gate(rise + 9 * period + 2600)        # nothing while disabled
    s.set_enable(rise + 10 * period + 100, 1)     # just after a rising edge: too late for this pulse
    s.set_enable(rise + 11 * period - 100, 0)     # just before the next one: no pulse at all
    s.check_gate(rise + 11 * period + 2600)
    s.set_enable(rise + 12 * period - 100, 1)     # just before a rising edge
    s.set_enable(rise + 12 * period + half + 100, 0)   # just after the falling edge: one pulse
    s.check_gate(rise + 13 * period + 2600)
    s.set_enable(rise + 14 * period + half - 100, 1)   # just before a falling edge
    s.set_enable(rise + 16 * period + 100, 0)
    s.check_gate(rise + 18 * period + 2600)


def switch_boundaries(s):
    s.window('a')
    s.switch_trigger = s.glitch_time()
    s.switch(s.switch_trigger)                    # a to b, select while the output is high
    s.switch()                                    # b to a
    s.switch_to_stopped_target()                  # a to b, b stopped
    s.switch_from_stopped_clock()                 # b stopped, back to a through reset
    s.switch()                                    # a to b again after the recovery
    s.switch_from_stopped_clock(stop_delay=2 * GRID + s.half['b'])  # stop b at its other level
    s.switch_to_stopped_target(stop_delay=2 * GRID + s.half['b'])
    s.reset_with_b_selected()                     # reset released with b still selected


def divider_boundaries(s):
    period = s.period['a']
    s.check_divider(nudge(s.divider_at + 7 * s.div * period))
    # Reset in the middle of a high phase, then start again.
    first = (s.divider_at // (s.div * period) + 2) * s.div * period
    s.reset_divider(nudge(first + period, 700))
    s.check_divider(nudge(s.divider_at + 5 * s.div * period))


def vectors(parameters, seed, operations):
    """Rows of delay, signal and value. The fixed scenario comes first; `operations` random ones follow."""
    s = Scenario(parameters)
    gate_boundaries(s)
    switch_boundaries(s)
    divider_boundaries(s)
    rng = random.Random(seed)
    period = s.period['a']
    for _ in range(operations):
        roll = rng.random()
        if roll < 0.5:
            at = s.gate_at + rng.randrange(1, 4 * period // 100) * 100
            at += 100 if at % GRID == 0 else 0
            s.set_enable(at, 1 - value_at(s.enable, at))
            if rng.random() < 0.6:
                s.check_gate(nudge(at + rng.randrange(1, 5) * period, rng.choice((100, 300, 600, 900))))
        elif roll < 0.75:
            s.switch(nudge(s.switch_at + rng.randrange(0, 4) * GRID, rng.randrange(1, 10) * 100))
        elif roll < 0.82:
            s.switch_to_stopped_target(stop_delay=rng.randrange(2, 20) * GRID)
        elif roll < 0.88:
            s.switch_from_stopped_clock(stop_delay=rng.randrange(2, 20) * GRID)
        elif roll < 0.95:
            s.check_divider(nudge(s.divider_at + rng.randrange(1, 4 * s.div) * period, rng.randrange(1, 10) * 100))
        else:
            s.reset_divider(nudge(s.divider_at + rng.randrange(1, 3 * s.div) * period, rng.randrange(1, 10) * 100))
    return s.rows()

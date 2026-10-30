"""Cycle stimulus: expected RX captures come from transmitted frames, never DUT probes."""
import random

DIVISOR = 8


class Timeline:
    def __init__(self, wait, parity):
        self.wait, self.parity, self.rows, self.cursor = wait, parity, [], 0
        self.reset()

    def ensure(self, length):
        while len(self.rows) < length:
            # reset, APB select/enable/write/address/data, RX line, planned capture/data/PE/FE
            self.rows.append([1, 0, 0, 0, 0, 0, 1, 0, 0, 0, 0])

    def idle(self, clocks=4):
        self.cursor += clocks
        self.ensure(self.cursor)

    def reset(self):
        self.ensure(self.cursor + 2)
        for i in range(self.cursor, self.cursor + 2):
            self.rows[i] = [0, 0, 0, 0, 0, 0, 1, 0, 0, 0, 0]
        self.cursor += 2
        self.idle(4)

    def bus_at(self, start, address, write=0, data=0):
        end = start + self.wait + 1
        self.ensure(end + 1)
        for i in range(start, end + 1):
            if self.rows[i][1]:
                raise ValueError("overlapping APB stimulus")
            self.rows[i][1:6] = [1, int(i != start), write, address, data]
        return end

    def bus(self, address, write=0, data=0):
        end = self.bus_at(self.cursor, address, write, data)
        self.cursor = end + 1
        return end

    def rx_at(self, start, value, kind=0):
        # kind 0=normal, 1=wrong parity, 2=low stop.
        parity = (value.bit_count() % 2) ^ int(self.parity == 2)
        bits = [0] + [(value >> b) & 1 for b in range(8)]
        if self.parity:
            bits += [parity ^ int(kind == 1)]
        bits += [int(kind != 2)]
        end = start + len(bits) * DIVISOR + 2 * DIVISOR + 4
        self.ensure(end)
        for b, level in enumerate(bits):
            for i in range(start + b * DIVISOR, start + (b + 1) * DIVISOR):
                self.rows[i][6] = level
        if kind == 2:
            # Keep the line low past the bad stop bit; it must not start a new frame.
            for i in range(start + len(bits) * DIVISOR, start + (len(bits) + 2) * DIVISOR):
                self.rows[i][6] = 0
        # 2-FF input synchronization, start qualification, then data/parity/stop.
        # UART rx_valid is registered; the wrapper captures it one edge later.
        event = start + 3 + DIVISOR // 2 + (9 + int(self.parity != 0)) * DIVISOR
        self.rows[event][7:] = [1, value, int(kind == 1 and self.parity != 0), int(kind == 2)]
        return event, end

    def source(self, bit, value):
        if bit == 0:
            accepted = self.bus_at(self.cursor, 8, 1, value)
            event = accepted + (10 + int(self.parity != 0)) * DIVISOR + 1
            end = event + 4
            self.ensure(end)
            return event, end
        return self.rx_at(self.cursor, value, {1: 0, 2: 1, 3: 2}[bit])

    def duplex(self, tx, rx, kind=0, busy=1):
        accepted = self.bus(8, 1, tx)
        _, end = self.rx_at(accepted + 1, rx, kind)
        if busy:
            self.bus(8, 1, tx ^ 255)
        self.bus(4)
        self.cursor = max(self.cursor, end)
        self.bus(12)
        self.bus(16)
        self.idle()

    def abort(self):
        self.bus(0, 1, 15)
        # An active interrupt and a partially transmitted/received frame coexist.
        _, end = self.rx_at(self.cursor, 0x69, 2)
        self.cursor = end
        accepted = self.bus(8, 1, 0x5a)
        self.rx_at(accepted + 1, 0xa5)
        self.cursor = accepted + 4 * DIVISOR
        self.rows = self.rows[:self.cursor]  # reset cancels the planned RX completion
        self.reset()
        self.idle((12 * DIVISOR))
        self.bus(0, 1, 15)
        self.duplex(0x96, 0x69)

    def finish(self):
        self.idle(2 * DIVISOR)
        return self.rows[:self.cursor]


def boundary_vectors(wait, parity):
    t = Timeline(wait, parity)
    t.bus(20)
    for address, write in ((12, 0), (8, 0), (4, 1), (20, 1), (12, 1), (1, 1), (24, 1)):
        t.bus(address, write, 0xffffffff)
    t.bus(0, 1, 0xfffffff0)
    t.bus(0)
    t.bus(0, 1, 15)
    patterns = [0, 255, 85, 1, 128]
    for i, value in enumerate(patterns):
        t.duplex(value, patterns[(i + 1) % len(patterns)])
        t.bus(16, 1, 15)
    # Each source is produced by an actual TX completion or RX waveform.
    for bit in (0, 1, 2, 3):
        if bit == 2 and not parity:
            continue
        for mask in (0, 1):
            for clear in (0, 1):
                for new in (0, 1):
                    t.reset()
                    _, end = t.source(bit, 0x96)
                    t.cursor = end
                    t.bus(0, 1, (1 << bit) if mask else 0)
                    t.bus(16)
                    if new:
                        event, end = t.source(bit, 0x69)
                        t.bus_at(event - wait - 1, 16, 1, (1 << bit) if clear else 0)
                        t.cursor = end
                    else:
                        t.bus(16, 1, (1 << bit) if clear else 0)
                    t.bus(16)
    # Masked event -> unmask -> remask -> acknowledge.
    t.reset()
    _, end = t.rx_at(t.cursor, 0x3c)
    t.cursor = end
    for mask in (2, 0, 15):
        t.bus(0, 1, mask)
    t.bus(16, 1, 15)
    # Two IRQ sources: partial clear must leave the other source active.
    _, end = t.rx_at(t.cursor, 0xc3, 2)
    t.cursor = end
    t.bus(4)  # STATUS reports the framing error of the last receive.
    t.bus(16, 1, 2)
    t.bus(16, 1, 8)
    if parity:
        _, end = t.rx_at(t.cursor, 0x5a, 1)
        t.cursor = end
        t.bus(4)  # A later parity-error frame replaces both STATUS error flags.
    # New receive during SETUP, wait, or an erroneous completion.
    for phase in ('setup', 'wait', 'error'):
        if phase == 'wait' and not wait:
            continue
        event, end = t.rx_at(t.cursor, 0x55)
        start = event if phase == 'setup' else event - 1 if phase == 'wait' else event - wait - 1
        t.bus_at(start, 1 if phase == 'error' else 4)
        t.cursor = end
    # A mask update coincides with an actual receive event.
    for old, new in ((0, 2), (2, 0)):
        t.bus(0, 1, old)
        event, end = t.rx_at(t.cursor, 0x80)
        t.bus_at(event - wait - 1, 0, 1, new)
        t.cursor = end
    # Consume the old snapshot on the same edge that the new byte arrives.
    event, end = t.rx_at(t.cursor, 0x01)
    t.bus_at(event - wait - 1, 12)
    t.cursor = end
    t.bus(12)
    t.abort()
    return t.finish()


def random_vectors(wait, parity, seed, operations):
    rng = random.Random(seed)
    t = Timeline(wait, parity)
    for _ in range(operations):
        t.bus(0, 1, rng.randrange(16))
        kind = rng.choice([0, 0, 2] + ([1] if parity else []))
        op = rng.randrange(6)
        if op == 0:
            t.duplex(rng.randrange(256), rng.randrange(256), kind, rng.randrange(2))
        elif op in (1, 2):
            event, end = t.rx_at(t.cursor, rng.randrange(256), kind)
            t.bus_at(event - wait - 1, rng.choice((0, 4, 12, 16, 20, 1, 24)), rng.randrange(2), rng.getrandbits(32))
            t.cursor = end
            if rng.randrange(2):
                t.bus(12)
        elif op == 3:
            _, end = t.source(0, rng.randrange(256))
            t.cursor = end
        elif op == 4:
            t.abort()
        else:
            t.bus(rng.choice((0, 4, 8, 12, 16, 20, 1, 24)), rng.randrange(2), rng.getrandbits(32))
            # A random TX write may have succeeded. Wait out its complete frame.
            t.idle(12 * DIVISOR)
        t.bus(16, 1, rng.randrange(16))
        t.idle(rng.randrange(3) * DIVISOR + 2)
    t.bus(16)
    t.bus(4)
    return t.finish()


def expected_metrics(rows, wait, parity):
    metrics = dict(tx_completed=0, rx_captured=0, rx_reads=0, apb_completed=0, apb_errors=0)
    remaining, available, elapsed = 0, False, 0
    for rst, sel, enable, write, address, data, rxd, receive, value, pe, fe in rows:
        if not rst:
            remaining, available, elapsed = 0, False, 0
            continue
        ready = remaining == 0
        accepted = sel and enable and elapsed >= wait
        invalid = (address not in (0, 4, 8, 12, 16, 20) or
                   (write and address in (4, 12, 20)) or
                   (address == 8 and (not write or not ready)) or
                   (address == 12 and not write and not available))
        if remaining:
            remaining -= 1
            if not remaining:
                metrics['tx_completed'] += 1
        if accepted:
            metrics['apb_completed'] += 1
            metrics['apb_errors'] += int(invalid)
            if not invalid:
                if address == 8 and write:
                    remaining = (10 + int(parity != 0)) * DIVISOR
                if address == 12 and not write:
                    available = False
                    metrics['rx_reads'] += 1
        if receive:
            available = True
            metrics['rx_captured'] += 1
        if sel and not enable:
            elapsed = 0
        elif sel and enable:
            elapsed += 1
    return metrics

"""Bit-level reference of three CAN 2.0A nodes on one wired-AND bus.

Every node advances one nominal bit at a time: it puts a level on the bus, the bus is the AND of
all levels, and each node then samples its own view of the bus. There is no clock, no time quantum
and no resynchronisation here; the RTL has to arrive at the same bits with three unequal clocks.
"""
REC, DOM = 1, 0
ACTIVE, PASSIVE, OVERLOAD = 0, 1, 2
KIND = dict(bit=1, stuff=2, crc=3, form=4, ack=5, overload=6)
BUS_DOM, RX_DOM, RX_REC = 0, 1, 2       # injections: force the bus, or one node's view of it
POLY = 0x4599


def crc15(bits):
    """The CRC register after the destuffed bits from SOF to the end of the data field."""
    crc = 0
    for bit in bits:
        feedback = bit ^ (crc >> 14)
        crc = (crc << 1) & 0x7FFF
        if feedback:
            crc ^= POLY
    return crc


def crc15_division(bits):
    """The same value by polynomial long division of the message followed by 15 zeros."""
    work = list(bits) + [0] * 15
    divisor = [1] + [(POLY >> k) & 1 for k in range(14, -1, -1)]
    for i in range(len(bits)):
        if work[i]:
            for k, d in enumerate(divisor):
                work[i + k] ^= d
    value = 0
    for bit in work[len(bits):]:
        value = value * 2 + bit
    return value


def payload_bytes(rtr, dlc):
    return 0 if rtr else min(dlc, 8)


def frame_bits(identifier, rtr, dlc, data):
    """Destuffed bits from SOF to the last CRC bit. data holds the first byte in bits 63..56."""
    if not (0 <= identifier < 2048 and rtr in (0, 1) and 0 <= dlc < 16 and 0 <= data < 1 << 64):
        raise ValueError('invalid frame')
    count = payload_bytes(rtr, dlc)
    if data & ((1 << (64 - 8 * count)) - 1):
        raise ValueError('data beyond the length')
    bits = [DOM] + [(identifier >> k) & 1 for k in range(10, -1, -1)] + [rtr, DOM, DOM]
    bits += [(dlc >> k) & 1 for k in range(3, -1, -1)]
    bits += [(data >> (63 - k)) & 1 for k in range(8 * count)]
    crc = crc15(bits)
    return bits + [(crc >> k) & 1 for k in range(14, -1, -1)]


def stuffed(bits):
    """Insert the complement after every five equal bits, counting inserted bits as well."""
    out, value, length = [], None, 0
    for bit in bits:
        out.append(bit)
        value, length = (value, length + 1) if bit == value else (bit, 1)
        if length == 5:
            out.append(1 - bit)
            value, length = 1 - bit, 1
    return out


def wire_bits(identifier, rtr, dlc, data, ack=True):
    """One undisturbed frame as it appears on the bus, from SOF to the last EOF bit."""
    return stuffed(frame_bits(identifier, rtr, dlc, data)) + [REC, DOM if ack else REC, REC] + [REC] * 7


class Node:
    def __init__(self, index):
        self.index, self.queue, self.events, self.online = index, [], [], True
        self.reset()

    def reset(self):
        self.tec = self.rec = 0
        self.state, self.count = 'integ', 0
        self.role_tx = self.was_tx = False
        self.sent = REC

    @property
    def passive(self):
        return self.tec >= 128 or self.rec >= 128

    @property
    def mode(self):
        return 2 if self.state == 'off' else int(self.passive)

    def quiet(self):
        return not self.online or (self.state == 'idle' and not self.queue)

    # -- what the node puts on the bus in this bit ------------------------------------------
    def tx(self):
        out = REC
        if not self.online:
            pass
        elif self.state == 'idle':
            out = DOM if self.queue else REC
        elif self.state == 'body' and self.role_tx:
            out = 1 - self.run_value if self.run_length == 5 else self.txbits[len(self.bits)]
        elif self.state == 'tail' and self.role_tx:
            out = 1 - self.run_value
        elif self.state == 'ack' and not self.role_tx and self.crc_ok:
            out = DOM
        elif self.state == 'flag' and self.flag != PASSIVE:
            out = DOM
        self.sent = out
        return out

    # -- helpers ----------------------------------------------------------------------------
    def start_frame(self, transmitter):
        self.state, self.bits, self.run_value, self.run_length = 'body', [DOM], DOM, 1
        self.role_tx = self.was_tx = transmitter
        self.length, self.crc_ok = None, False
        if transmitter:
            self.txbits = frame_bits(*self.queue[0])

    def bump(self, amount):
        """Add to the counter of the present role and leave the bus when the transmit count allows no more."""
        if self.role_tx:
            self.tec += amount
            if self.tec >= 256:
                self.state, self.count, self.sequences = 'off', 0, 0
                return True
        else:
            self.rec = min(255, self.rec + amount)
        return False

    def error(self, kind, count=True):
        self.events.append(('err', KIND[kind]))
        was_passive = self.passive            # the flag follows the state before this error
        self.ack_hold = kind == 'ack' and self.role_tx and was_passive
        if count and not self.ack_hold and self.bump(8 if self.role_tx else 1):
            return
        self.state, self.flag, self.count, self.equal = 'flag', PASSIVE if was_passive else ACTIVE, 0, 0

    def overload(self):
        self.events.append(('err', KIND['overload']))
        self.state, self.flag, self.count = 'flag', OVERLOAD, 0

    # -- one sampled bit --------------------------------------------------------------------
    def sample(self, value):
        if not self.online:
            return
        getattr(self, 'in_' + self.state)(value)

    def in_integ(self, value):
        self.count = self.count + 1 if value == REC else 0
        if self.count == 11:
            self.state = 'idle'

    def in_off(self, value):
        self.count = self.count + 1 if value == REC else 0
        if self.count == 11:
            self.count, self.sequences = 0, self.sequences + 1
            if self.sequences == 128:
                self.tec = self.rec = 0
                self.state, self.role_tx, self.was_tx = 'idle', False, False

    def in_idle(self, value):
        if value == DOM:
            self.start_frame(bool(self.queue))
        elif self.sent == DOM:
            self.role_tx = self.was_tx = True
            self.error('bit')

    def in_body(self, value):
        index, stuff = len(self.bits), self.run_length == 5
        if self.role_tx and value != self.sent:
            if self.sent == DOM:
                return self.error('bit')
            if stuff:
                # A recessive stuff bit overwritten while the identifier is still being sent.
                return self.error('stuff', count=False) if index <= 12 else self.error('bit')
            if not 1 <= index <= 12:
                return self.error('bit')
            self.role_tx = self.was_tx = False        # arbitration lost: go on as a receiver
            self.events.append(('lost', index))
        if stuff:
            if value == self.run_value:
                return self.error('stuff')
            self.run_value, self.run_length = value, 1
            return None
        self.bits.append(value)
        self.run_value, self.run_length = (value, self.run_length + 1) if value == self.run_value else (value, 1)
        if len(self.bits) == 19:
            rtr, dlc = self.bits[12], int(''.join(map(str, self.bits[15:19])), 2)
            self.length = 34 + 8 * payload_bytes(rtr, dlc)
        if len(self.bits) == self.length:
            body, tail = self.bits[:-15], self.bits[-15:]
            self.crc_ok = crc15(body) == int(''.join(map(str, tail)), 2)
            self.state = 'tail' if self.run_length == 5 else 'crcdel'
        return None

    def in_tail(self, value):
        if self.role_tx and value != self.sent:
            return self.error('bit')
        if value == self.run_value:
            return self.error('stuff')
        self.state = 'crcdel'
        return None

    def in_crcdel(self, value):
        if value == DOM:
            return self.error('form')
        self.state = 'ack'
        return None

    def in_ack(self, value):
        if self.role_tx:
            if value == REC:
                return self.error('ack')
        elif self.sent == DOM and value == REC:
            return self.error('bit')
        elif self.crc_ok and value == DOM:
            self.rec = 127 if self.rec > 127 else max(0, self.rec - 1)
        self.state = 'ackdel'
        return None

    def in_ackdel(self, value):
        if value == DOM:
            return self.error('form')
        if not self.role_tx and not self.crc_ok:
            return self.error('crc')
        self.state, self.count = 'eof', 0
        return None

    def in_eof(self, value):
        self.count += 1
        if value == DOM:
            return self.overload() if not self.role_tx and self.count == 7 else self.error('form')
        if not self.role_tx and self.count == 6:
            bits = self.bits
            rtr, dlc = bits[12], int(''.join(map(str, bits[15:19])), 2)
            data = 0
            for k, bit in enumerate(bits[19:19 + 8 * payload_bytes(rtr, dlc)]):
                data |= bit << (63 - k)
            self.events.append(('rx', int(''.join(map(str, bits[1:12])), 2), rtr, dlc, data))
        if self.count == 7:
            if self.role_tx:
                self.events.append(('done',))
                self.tec = max(0, self.tec - 1)
                self.queue.pop(0)
            self.state, self.count = 'ifs', 0
        return None

    def in_ifs(self, value):
        self.count += 1
        if value == DOM:
            if self.count < 3:
                return self.overload()
            suspended = self.passive and self.was_tx
            return self.start_frame(bool(self.queue) and not suspended)
        if self.count == 3:
            self.state, self.count = ('susp', 0) if self.passive and self.was_tx else ('idle', 0)
        return None

    def in_susp(self, value):
        self.count += 1
        if value == DOM:
            return self.start_frame(False)
        if self.count == 8:
            self.state = 'idle'
        return None

    def in_flag(self, value):
        if self.flag == PASSIVE:
            if value == DOM and self.ack_hold:
                self.ack_hold = False
                if self.bump(8):
                    return
            self.equal = self.equal + 1 if self.count and value == self.previous else 1
            self.previous, self.count = value, self.count + 1
            if self.equal == 6:
                self.state, self.first = 'wait', True
            return
        if value == REC:                       # the flag itself is disturbed
            self.events.append(('err', KIND['bit']))
            self.count = 0
            self.bump(8)
            return
        self.count += 1
        if self.count == 6:
            self.state, self.first = 'wait', True

    def in_wait(self, value):
        if value == DOM:
            if self.first and not self.role_tx and self.flag != OVERLOAD:
                self.bump(8)
            self.first = False
        else:
            self.state, self.count = 'delim', 1

    def in_delim(self, value):
        if value == DOM:
            return self.overload() if self.count == 7 else self.error('form')
        self.count += 1
        if self.count == 8:
            self.state, self.count = 'ifs', 0
        return None


class Bus:
    def __init__(self, nodes=3):
        self.nodes = [Node(index) for index in range(nodes)]
        self.time, self.levels, self.injections = 0, [], {}

    def inject(self, time, kind, node=0, length=1):
        for offset in range(length):
            self.injections.setdefault(time + offset, []).append((kind, node))

    def step(self):
        level = min(node.tx() for node in self.nodes)
        views = [level] * len(self.nodes)
        for kind, node in self.injections.get(self.time, []):
            if kind == BUS_DOM:
                level, views = DOM, [DOM] * len(self.nodes)
        for kind, node in self.injections.get(self.time, []):
            if kind != BUS_DOM:
                views[node] = DOM if kind == RX_DOM else REC
        for node, view in zip(self.nodes, views):
            node.sample(view)
        self.levels.append(level)
        self.time += 1

    def quiet(self):
        return all(node.quiet() for node in self.nodes)


def runs(levels):
    """Run lengths from the first dominant bit, without the recessive tail."""
    if DOM not in levels:
        return []
    out, start = [], levels.index(DOM)
    for level in levels[start:]:
        if out and out[-1][0] == level:
            out[-1][1] += 1
        else:
            out.append([level, 1])
    if out[-1][0] == REC:
        out.pop()
    return [tuple(run) for run in out]

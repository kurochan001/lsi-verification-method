"""Reference for the sensor packet receiver: header ECC, payload CRC, packets and the receiver.

The header code and the CRC are written differently from the RTL on purpose. The RTL uses
parity masks, a syndrome and a bit-serial CRC; here the code is built from codeword positions,
decoded by searching for the single flip that yields a codeword, and the CRC is table driven.
The packet layer works on a buffer of the bytes of one packet instead of a byte state machine.
The lane layer (per-lane queues merged round robin) follows the same structure as the RTL,
because the clock in which each byte is delivered is part of the expected output.
"""
from collections import deque

SYNC = 0xb8
DEPTH = 4
T_FS, T_FE, T_LS, T_LE, T_ROW = 0x00, 0x01, 0x02, 0x03, 0x2a
LONG = 0x20
ERR_HEADER, ERR_CRC, ERR_SEQUENCE, ERR_COUNT, ERR_TRUNCATED, ERR_LANE = (1 << n for n in range(6))
# Data bits sit at the codeword positions that are not powers of two, in increasing order.
POSITIONS = [p for p in range(1, 30) if p & (p - 1)]


def ecc_encode(value):
    """Six check bits of a 24-bit header: five Hamming parities and one parity over everything."""
    if not 0 <= value < 1 << 24:
        raise ValueError('24-bit header required')
    word = {position: value >> index & 1 for index, position in enumerate(POSITIONS)}
    for j in range(5):
        word[1 << j] = sum(bit for position, bit in word.items() if position >> j & 1) & 1
    checks = sum(word[1 << j] << j for j in range(5))
    return checks | (sum(word.values()) & 1) << 5


def header_decode(b0, b1, b2, ecc):
    """(value, corrected) or None. Exactly one flipped bit is repaired; anything else is refused."""
    if ecc >> 6:
        return None
    value = b0 | b1 << 8 | b2 << 16
    if ecc_encode(value) == ecc:
        return value, False
    repaired = [value ^ 1 << bit for bit in range(24) if ecc_encode(value ^ 1 << bit) == ecc]
    repaired += [value for bit in range(6) if ecc_encode(value) == ecc ^ 1 << bit]
    return (repaired[0], True) if len(repaired) == 1 else None


def _crc_table():
    table = []
    for byte in range(256):
        value = byte
        for _ in range(8):
            value = value >> 1 ^ 0x8408 if value & 1 else value >> 1
        table.append(value)
    return table


CRC_TABLE = _crc_table()


def crc16(data):
    """Reflected x^16 + x^12 + x^5 + 1, start value 0xffff, no final inversion."""
    value = 0xffff
    for byte in data:
        value = value >> 8 ^ CRC_TABLE[(value ^ byte) & 0xff]
    return value


def header(kind, count):
    value = kind | (count & 0xffff) << 8
    return [kind, count & 0xff, count >> 8 & 0xff, ecc_encode(value)]


def short_packet(kind, number):
    return header(kind, number)


def long_packet(kind, payload, count=None, crc=None):
    crc = crc16(payload) if crc is None else crc
    return header(kind, len(payload) if count is None else count) + list(payload) + [crc & 0xff, crc >> 8]


def frame_packets(number, lines):
    """Packets of one well-formed frame; lines is a list of pixel rows."""
    packets = [short_packet(T_FS, number)]
    for index, pixels in enumerate(lines):
        packets += [short_packet(T_LS, index), long_packet(T_ROW, pixels), short_packet(T_LE, index)]
    return packets + [short_packet(T_FE, number)]


def blank():
    return dict(pix_valid=0, pix_data=0, pix_first=0, pix_last=0, row_done=0, row_ok=0, frame_start=0,
                frame_end=0, frame_clean=0, evt_num=0, hdr_fix=0, pkt_ignored=0, err=0)


class Receiver:
    """One call of edge() is one clock; it returns what the outputs show after that clock."""

    def __init__(self, lanes, max_line):
        self.lanes, self.max_line = lanes, max_line
        self.reset()

    def reset(self):
        self.clear_lanes()
        self.drop = False
        self.buffer = []
        self.emit = False
        self.in_frame = self.in_line = self.row_seen = self.dirty = False
        self.width = None
        self.frame_no = self.line_cnt = 0

    def clear_lanes(self):
        self.queue = [deque() for _ in range(self.lanes)]
        self.synced = [False] * self.lanes
        self.ended = [False] * self.lanes
        self.turn = 0

    def edge(self, rst_n, active, valid, data):
        event = blank()
        if not rst_n:
            self.reset()
            return event
        if self.drop:                       # everything is discarded until every lane is quiet
            self.clear_lanes()
            self.buffer = []
            self.drop = any(active)
            return event
        running = all(self.synced)
        lane = self.turn
        deliver = running and bool(self.queue[lane])
        strobe = [bool(active[i] and valid[i]) for i in range(self.lanes)]
        bad_sync = any(strobe[i] and not self.synced[i] and data[i] != SYNC for i in range(self.lanes))
        overflow = any(strobe[i] and self.synced[i] and len(self.queue[i]) == DEPTH and not (deliver and lane == i)
                       for i in range(self.lanes))
        missing = not running and any(self.synced) and not any(active)
        restart = any(self.ended[i] and active[i] for i in range(self.lanes))
        quiet = False
        if bad_sync or overflow or missing or restart:
            event['err'] |= ERR_LANE
            self.drop, self.buffer = True, []
        elif deliver:
            self.turn = (lane + 1) % self.lanes
            self.packet_byte(self.queue[lane].popleft(), event)
        elif running and not active[lane]:  # the lane whose turn it is has ended
            if self.buffer:
                event['err'] |= ERR_TRUNCATED
                self.buffer = []
            if any(active) or any(self.queue):
                event['err'] |= ERR_LANE
                self.drop = True
            else:
                quiet = True
        if self.drop or quiet:
            self.clear_lanes()
        else:
            for i in range(self.lanes):
                if self.synced[i] and not active[i]:
                    self.ended[i] = True
                if strobe[i]:
                    if self.synced[i]:
                        self.queue[i].append(data[i])
                    else:
                        self.synced[i] = True
        if event['err'] and self.in_frame:
            self.dirty = True
        return event

    def packet_byte(self, byte, event):
        self.buffer.append(byte)
        size = len(self.buffer)
        if size < 4:
            return
        if size == 4:
            decoded = header_decode(*self.buffer)
            if decoded is None:
                event['err'] |= ERR_HEADER
                self.drop, self.buffer = True, []
                return
            value, corrected = decoded
            self.kind, self.count = value & 0xff, value >> 8
            event['hdr_fix'] = int(corrected)
            if not self.kind & LONG:
                self.short(event)
                self.buffer = []
                return
            self.emit = False
            if self.kind != T_ROW:
                event['pkt_ignored'] = 1
            elif not self.in_line or self.row_seen:
                event['err'] |= ERR_SEQUENCE
            else:
                self.row_seen = True
                if not 1 <= self.count <= self.max_line or self.width not in (None, self.count):
                    event['err'] |= ERR_COUNT
                else:
                    self.emit, self.width = True, self.count
            return
        index = size - 4                    # 1-based position after the header
        if index <= self.count:
            if self.emit:
                event.update(pix_valid=1, pix_data=byte, pix_first=int(index == 1), pix_last=int(index == self.count))
        elif index == self.count + 2:
            if self.emit:
                payload = self.buffer[4:4 + self.count]
                good = crc16(payload) == self.buffer[-2] | self.buffer[-1] << 8
                event.update(row_done=1, row_ok=int(good))
                if not good:
                    event['err'] |= ERR_CRC
            self.buffer = []

    def short(self, event):
        kind, number = self.kind, self.count
        if kind == T_FS:
            event.update(frame_start=1, evt_num=number)
            if self.in_frame:
                event['err'] |= ERR_SEQUENCE
            else:
                self.dirty = False
            self.in_frame, self.in_line, self.row_seen = True, False, False
            self.line_cnt, self.width, self.frame_no = 0, None, number
        elif kind == T_FE:
            if not self.in_frame:
                event['err'] |= ERR_SEQUENCE
                return
            wrong = self.in_line or number != self.frame_no
            if wrong:
                event['err'] |= ERR_SEQUENCE
            event.update(frame_end=1, evt_num=self.frame_no, frame_clean=int(not self.dirty and not wrong))
            self.in_frame = self.in_line = False
        elif kind == T_LS:
            if not self.in_frame or self.in_line:
                event['err'] |= ERR_SEQUENCE
                return
            if number != self.line_cnt:
                event['err'] |= ERR_SEQUENCE
            self.in_line, self.row_seen = True, False
        elif kind == T_LE:
            if not self.in_line:
                event['err'] |= ERR_SEQUENCE
                return
            if not self.row_seen or number != self.line_cnt:
                event['err'] |= ERR_SEQUENCE
            self.in_line = False
            self.line_cnt = (self.line_cnt + 1) & 0xffff
        else:
            event['pkt_ignored'] = 1


def expect(rows, lanes, max_line):
    """Outputs visible in each row: row t shows the result of the clocks before it."""
    receiver = Receiver(lanes, max_line)
    visible, outputs = blank(), []
    for row in rows:
        outputs.append(visible)
        visible = receiver.edge(row['rst_n'], row['active'], row['valid'], row['data'])
    return outputs

"""Independent Python model of packet_sum: one bit per step, no lookup table."""
POLY = 0x1021
# Published check values of the nine ASCII digits "123456789" for this polynomial:
# start value 0xFFFF gives 0x29B1, start value 0x0000 gives 0x31C3.
KNOWN = {0xFFFF: 0x29B1, 0x0000: 0x31C3}
DIGITS = b'123456789'


def step(crc, byte):
    for bit in range(7, -1, -1):
        feedback = (crc >> 15) ^ (byte >> bit & 1)
        crc = (crc << 1) & 0xFFFF
        if feedback:
            crc ^= POLY
    return crc


def block(data, init):
    crc = init
    for byte in data:
        crc = step(crc, byte)
    return crc


def parse_data(text):
    """Return (value, unknown bit count); x and z read as 0."""
    if len(text) != 8 or set(text) - set('01xz'):
        raise ValueError('data must be 8 digits of 0, 1, x or z')
    return int(text.replace('x', '0').replace('z', '0'), 2), sum(c in 'xz' for c in text)


class Channel:
    def __init__(self, init):
        self.init = init
        self.done = self.crc = self.length = 0
        self.packets = 0
        self.bytes = []

    def cycle(self, rst_n, valid, data, last):
        """One rising clock edge; returns the bytes of a packet that just ended."""
        finished = None
        if not rst_n:
            self.bytes = []
            self.done = self.crc = self.length = 0
            return finished
        self.done = int(bool(valid and last))
        if valid:
            self.bytes.append(data)
            if last:
                self.crc = block(self.bytes, self.init)
                self.length = min(len(self.bytes), 255)
                self.packets += 1
                finished, self.bytes = self.bytes, []
        return finished


def expected(rows, init):
    """Outputs after every clock, the block CRC of every packet, and the counters."""
    channels = [Channel(init), Channel(init)]
    outputs, blocks = [], []
    unknown_valid = unknown_idle = 0
    for rst_n, *fields in rows:
        line = []
        for index, channel in enumerate(channels):
            valid, text, last = fields[3 * index:3 * index + 3]
            value, unknown = parse_data(text)
            if rst_n and valid:
                unknown_valid += unknown
            else:
                unknown_idle += unknown
            finished = channel.cycle(rst_n, valid, value, last)
            line += [channel.done, channel.crc, channel.length]
            if finished is not None and len(finished) <= 512:
                blocks.append((index, len(finished), block(finished, init)))
        outputs.append(tuple(line))
    counts = dict(rows=len(rows), packets0=channels[0].packets, packets1=channels[1].packets,
                  unknown_valid=unknown_valid, unknown_idle=unknown_idle)
    return outputs, blocks, counts

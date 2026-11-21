#!/usr/bin/env python3
"""Sensor packet receiver: lane merge and skew, header ECC, payload CRC, frame and line order."""
import importlib.util
from pathlib import Path
import random
import sys

HERE = Path(__file__).resolve().parent


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


M = load('sensor_packet_model', HERE / 'model.py')
SOBEL = load('sensor_packet_sobel_model', HERE.parent / 'local-image-sobel/model.py')
NAME = 'local-sensor-packet'
TOP = 'sensor_packet_tb'
CONFIGS = {'lanes2': dict(LANES=2, MAX_LINE=8, PIPE_W=5, PIPE_H=4),
           'lanes4': dict(LANES=4, MAX_LINE=6, PIPE_W=6, PIPE_H=3)}
ITERATIONS = {'smoke': 40, 'nightly': 120}
SOURCES = [HERE / 'rtl/sensor_packet_rx.sv', HERE.parent / 'local-conv-window/rtl/conv_window.sv',
           HERE.parent / 'local-image-sobel/rtl/sobel_stream.sv', HERE / 'tb/sensor_packet_tb.sv']
EXTRA_INPUTS = [HERE / 'model.py', HERE.parent / 'local-image-sobel/model.py']
MUTANTS = 10
# Mutation 4 shows first as a lane error with two lanes and as a wrong frame number with four.
LABELS = {1: 'SP_FRAME', 2: 'SP_ERROR', 3: 'SP_ROW', 4: {2: 'SP_ERROR', 4: 'SP_FRAME'}, 5: 'SP_ERROR',
          6: 'SP_ERROR', 7: 'SP_ERROR', 8: 'SP_ERROR', 9: 'SP_FRAME', 10: 'SP_ERROR'}
GOALS = ['lanes/aligned', 'lanes/skew', 'lanes/skew-limit', 'lanes/overflow', 'lanes/bad-sync',
         'lanes/length-mismatch', 'lanes/idle-strobe', 'lanes/missing', 'header/clean', 'header/corrected-data',
         'header/corrected-check', 'header/uncorrectable', 'header/reserved-bits', 'packet/ignored-short',
         'packet/ignored-long', 'row/crc-ok', 'row/crc-error', 'row/count-zero', 'row/count-max', 'row/count-over',
         'row/width-mismatch', 'row/truncated', 'header/truncated', 'seq/frame-clean', 'seq/frame-restart',
         'seq/frame-end-outside', 'seq/frame-number', 'seq/frame-end-in-line', 'seq/line-start-outside',
         'seq/line-start-twice', 'seq/line-number', 'seq/line-end-outside', 'seq/line-end-without-row',
         'seq/line-end-number', 'seq/row-outside-line', 'seq/row-twice', 'burst/multi-packet', 'burst/partial-word',
         'burst/too-early', 'reset/midpacket', 'frame/dirty', 'frame/dirty-other']
IDLE_BYTE, GAP_BYTE = 0x5a, 0xa5        # driven while a lane has nothing to say; must never be taken
FS, FE, LS, LE, ROW = M.T_FS, M.T_FE, M.T_LS, M.T_LE, M.T_ROW


def flat(packets):
    return [byte for packet in packets for byte in packet]


class Stim:
    """Builds the lane inputs row by row and keeps the reference receiver in step."""

    def __init__(self, lanes, max_line):
        self.lanes, self.max_line = lanes, max_line
        self.rows, self.outputs, self.scenes, self.pipe, self.pipe_frames = [], [], [], 0, []
        self.receiver, self.visible = M.Receiver(lanes, max_line), M.blank()

    def row(self, rst_n=1):
        self.rows.append(dict(rst_n=rst_n, active=[0] * self.lanes, valid=[0] * self.lanes,
                              data=[IDLE_BYTE] * self.lanes, pipe=self.pipe, tags=0))

    def idle(self, count=1):
        for _ in range(count):
            self.row()

    def reset(self, count=2):
        for _ in range(count):
            self.row(rst_n=0)

    def gap(self, skew=0):
        return M.DEPTH * self.lanes + skew + 8

    def burst(self, stream, skew=None, sync=None, extra=None, missing=(), gap=None, reset_at=None):
        """Put one burst on the lanes. Stream byte k goes to lane k % LANES, one byte per LANES rows."""
        lanes = self.lanes
        skew = list(skew or [0] * lanes)
        start = len(self.rows)
        present = [i for i in range(lanes) if i not in missing]
        last_start = start + max(skew[i] for i in present)
        plan = {}                                   # (row, lane) -> byte
        for i in present:
            first = start + skew[i]
            plan[first, i] = M.SYNC if sync is None or i not in sync else sync[i]
            data = list(stream[i::lanes]) + list((extra or {}).get(i, []))
            for j, byte in enumerate(data):
                plan[first + lanes * (j + 1) + i, i] = byte
        ends = {i: max(max(r for r, lane in plan if lane == i), last_start) for i in present}
        while len(self.rows) <= max(ends.values()):
            self.row()
        for i in present:
            for r in range(start + skew[i], ends[i] + 1):
                self.rows[r]['active'][i] = 1
                self.rows[r]['data'][i] = GAP_BYTE
        for (r, i), byte in plan.items():
            self.rows[r]['valid'][i] = 1
            self.rows[r]['data'][i] = byte
        if reset_at is not None:
            for r in range(start + reset_at, min(start + reset_at + 2, len(self.rows))):
                self.rows[r]['rst_n'] = 0
        self.idle(self.gap(max(skew)) if gap is None else gap)
        return start

    def sync(self):
        """Run the reference over the rows added since the last call."""
        for row in self.rows[len(self.outputs):]:
            self.outputs.append(self.visible)
            self.visible = self.receiver.edge(row['rst_n'], row['active'], row['valid'], row['data'])

    def close(self):
        """Leave any open frame, so that the next scene starts outside a frame."""
        self.sync()
        if self.receiver.in_frame:
            self.burst(M.short_packet(FE, self.receiver.frame_no))
            self.sync()

    def scene(self, goal, build, expect, allow=0, forbid=None):
        """Add a scene and tag the first row whose expected outputs satisfy `expect`.

        The scene must report nothing but the error bits in `allow`, and no row may satisfy
        `forbid`. A scene that does not show what it was written for is a mistake in the plan.
        """
        self.close()
        begin = len(self.rows)
        build()
        self.idle(2)
        self.sync()
        window = range(begin, len(self.outputs))
        seen = 0
        for r in window:
            seen |= self.outputs[r]['err']
        hits = [r for r in window if expect(self.outputs[r])]
        if not hits or seen & ~allow or (forbid and any(forbid(self.outputs[r]) for r in window)):
            raise ValueError(f'scene {goal} does not show its effect (errors {seen:#x})')
        self.rows[hits[0]]['tags'] |= 1 << GOALS.index(goal)
        self.close()

    def vectors(self):
        self.sync()
        packed = []
        for row, out in zip(self.rows, self.outputs):
            flags = (out['pix_valid'] | out['pix_first'] << 1 | out['pix_last'] << 2 | out['row_done'] << 3 |
                     out['row_ok'] << 4 | out['frame_start'] << 5 | out['frame_end'] << 6 | out['frame_clean'] << 7 |
                     out['hdr_fix'] << 8 | out['pkt_ignored'] << 9 | out['err'] << 10)
            inputs = (row['pipe'] << 41 | row['rst_n'] << 40 | sum(bit << 36 + i for i, bit in enumerate(row['active'])) |
                      sum(bit << 32 + i for i, bit in enumerate(row['valid'])) |
                      sum(byte << 8 * i for i, byte in enumerate(row['data'])))
            packed.append([inputs, out['evt_num'] << 24 | out['pix_data'] << 16 | flags, row['tags']])
        return packed


def lines_of(pixels, width):
    return [pixels[i:i + width] for i in range(0, len(pixels), width)]


def small_frame(number, widths=(3, 3), base=0x10):
    return M.frame_packets(number, [[(base + 7 * line + 3 * x) & 0xff for x in range(width)]
                                    for line, width in enumerate(widths)])


def flip(packet, bits):
    """Flip bits of a packet; bit n is bit n % 8 of byte n // 8."""
    packet = list(packet)
    for bit in bits:
        packet[bit // 8] ^= 1 << bit % 8
    return packet


def skew_limit(lanes, max_line):
    """Smallest lateness of lane 0 that overflows another lane's queue, for a long burst."""
    stream = flat(small_frame(0, (max_line, max_line, max_line)))
    for late in range(1, 16 * lanes):
        s = Stim(lanes, max_line)
        s.reset()
        s.burst(stream, skew=[late] + [0] * (lanes - 1))
        s.sync()
        if any(out['err'] & M.ERR_LANE for out in s.outputs):
            return late
    raise ValueError('no skew overflows the lane queues')


def boundary_stim(lanes, max_line, pipe_w, pipe_h):
    s = Stim(lanes, max_line)
    lane_only, none = M.ERR_LANE, 0
    err = lambda mask: (lambda out: out['err'] & mask)          # noqa: E731
    clean_end = lambda out: out['frame_end'] and out['frame_clean']  # noqa: E731
    dirty_end = lambda out: out['frame_end'] and not out['frame_clean']  # noqa: E731
    late0 = skew_limit(lanes, max_line)
    long_stream = flat(small_frame(0, (max_line, max_line, max_line)))

    # Two clean frames through the Sobel pipeline: one packet per burst, then a whole frame per burst.
    s.pipe = 1
    s.reset()
    frames = SOBEL.directed(pipe_w, pipe_h)
    first, second = frames[2], frames[4]
    s.pipe_frames = [first, second]

    def one_packet_per_burst():
        for packet in M.frame_packets(1, lines_of(first, pipe_w)):
            s.burst(packet)
    s.scene('lanes/aligned', one_packet_per_burst, clean_end)
    s.scene('burst/multi-packet', lambda: s.burst(flat(M.frame_packets(2, lines_of(second, pipe_w))),
                                                  skew=[1] + [0] * (lanes - 1)), clean_end)
    s.idle(2 * pipe_w + 12)                 # let the pipeline finish its zero padding
    s.pipe = 0
    s.idle(2)

    # Lanes.
    s.scene('lanes/skew', lambda: s.burst(flat(small_frame(3)), skew=[0] * (lanes - 1) + [3]), clean_end)
    s.scene('lanes/skew-limit', lambda: s.burst(long_stream, skew=[late0 - 1] + [0] * (lanes - 1)), clean_end)
    s.scene('lanes/overflow', lambda: s.burst(long_stream, skew=[late0] + [0] * (lanes - 1)),
            err(M.ERR_LANE), lane_only, forbid=lambda out: out['frame_end'])
    s.scene('lanes/bad-sync', lambda: s.burst(flat(small_frame(4)), sync={lanes - 1: M.SYNC ^ 1}),
            err(M.ERR_LANE), lane_only, forbid=lambda out: out['frame_start'])
    s.scene('lanes/length-mismatch', lambda: s.burst(M.short_packet(0x11, 5), extra={lanes - 1: [0x33]}),
            err(M.ERR_LANE), lane_only)
    s.scene('lanes/missing', lambda: s.burst(M.short_packet(0x11, 6), missing=(lanes - 1,)),
            err(M.ERR_LANE), lane_only, forbid=lambda out: out['pkt_ignored'])

    def idle_strobe():
        # Strobes without lane_active are not bytes: on every lane long before a burst, on one lane
        # in the row before it, and on a lane that has already ended while the others go on.
        s.idle(4)
        for r in (-4, -3):
            s.rows[r]['valid'] = [1] * lanes
            s.rows[r]['data'] = [M.SYNC] * lanes
        s.rows[-1]['valid'][0] = 1
        s.rows[-1]['data'][0] = M.SYNC
        start = s.burst(flat([M.short_packet(0x12, 7), M.long_packet(0x33, [1, 2, 3, 4, 5])]))
        late = next(r for r in range(start + 1, len(s.rows))
                    if not s.rows[r]['active'][lanes - 1] and any(s.rows[r]['active']))
        s.rows[late]['valid'][lanes - 1] = 1
        s.rows[late]['data'][lanes - 1] = 0x3c
    s.scene('lanes/idle-strobe', idle_strobe, lambda out: out['pkt_ignored'])
    s.scene('burst/partial-word', lambda: s.burst(flat([M.short_packet(0x13, 1), M.long_packet(0x33, [1, 2, 3])])),
            lambda out: out['pkt_ignored'])

    def too_early():
        s.burst(M.short_packet(0x14, 1), gap=1)    # one quiet row is not enough to see the end
        s.burst(M.short_packet(FS, 0x77))
    s.scene('burst/too-early', too_early, err(M.ERR_LANE), lane_only, forbid=lambda out: out['frame_start'])

    # Header code: every single flipped bit is repaired and the repaired number is used.
    s.scene('header/clean', lambda: s.burst(flat([M.short_packet(FS, 0x1234), M.short_packet(FE, 0x1234)])),
            lambda out: out['frame_start'] and not out['hdr_fix'] and out['evt_num'] == 0x1234)

    def single_flips(bits, number):
        def build():
            for bit in bits:
                s.burst(flat([flip(M.short_packet(FS, number + bit), [bit]), M.short_packet(FE, number + bit)]))
        return build
    s.scene('header/corrected-data', single_flips(range(24), 0xa500), lambda out: out['frame_start'] and out['hdr_fix'])
    s.scene('header/corrected-check', single_flips(range(24, 30), 0x5a00),
            lambda out: out['frame_start'] and out['hdr_fix'])
    # Flips in a row packet: the repaired count decides how many pixels follow.
    s.scene('row/crc-ok', lambda: s.burst(flat(
        [packet if index != 2 else flip(packet, [9]) for index, packet in enumerate(small_frame(8))])), clean_end)

    def double_flips():
        for pair in ((0, 1), (3, 17), (8, 23), (5, 24), (22, 29), (24, 25), (26, 28), (0, 23), (7, 8), (15, 16)):
            s.burst(flat([flip(M.short_packet(0x15, 0x0f0f), pair), M.short_packet(0x16, 1)]))
        # An odd number of flips whose syndrome names position 30 or 31, where the code has no bit.
        for triple in ((2, 27, 28), (24, 25, 26, 27, 28)):
            s.burst(flat([flip(M.short_packet(0x15, 0x0f0f), triple), M.short_packet(0x16, 1)]))
    s.scene('header/uncorrectable', double_flips, err(M.ERR_HEADER), M.ERR_HEADER,
            forbid=lambda out: out['pkt_ignored'] or out['hdr_fix'])

    def reserved_bits():
        for bit in (30, 31):
            s.burst(flat([flip(M.short_packet(0x15, 3), [bit]), M.short_packet(0x16, 1)]))
    s.scene('header/reserved-bits', reserved_bits, err(M.ERR_HEADER), M.ERR_HEADER,
            forbid=lambda out: out['pkt_ignored'])
    s.scene('header/truncated', lambda: s.burst(M.short_packet(0x15, 3)[:2]), err(M.ERR_TRUNCATED), M.ERR_TRUNCATED)

    # Packets that are not for this layer are skipped by their length.
    s.scene('packet/ignored-short', lambda: s.burst(flat([M.short_packet(0x1f, 0xffff)] + small_frame(9))),
            lambda out: out['pkt_ignored'], forbid=dirty_end)
    s.scene('packet/ignored-long', lambda: s.burst(flat(
        [M.long_packet(0x3f, [9, 8, 7, 6, 5], crc=0x1234), M.long_packet(0x20, [], crc=0)] + small_frame(10))),
            lambda out: out['pkt_ignored'], forbid=dirty_end)

    # Rows.
    def framed(number, *middle):
        return flat([M.short_packet(FS, number), *middle, M.short_packet(FE, number)])

    def line(index, row, end=None):
        return [M.short_packet(LS, index), row, M.short_packet(LE, index if end is None else end)]
    bad_pixel = flip(M.long_packet(ROW, [1, 2, 3]), [4 * 8 + 5])
    bad_crc_low = flip(M.long_packet(ROW, [1, 2, 3]), [7 * 8])
    bad_crc_high = flip(M.long_packet(ROW, [1, 2, 3]), [8 * 8 + 7])

    def crc_errors():
        for number, row in ((20, bad_pixel), (21, bad_crc_low), (22, bad_crc_high)):
            s.burst(framed(number, *line(0, row)))
    s.scene('row/crc-error', crc_errors, err(M.ERR_CRC), M.ERR_CRC, forbid=clean_end)
    s.scene('frame/dirty', lambda: s.burst(framed(23, *line(0, bad_pixel), *line(1, M.long_packet(ROW, [4, 5, 6])))),
            dirty_end, M.ERR_CRC)

    def dirty_by_other_errors():
        # A lane error, a truncated packet and a header that cannot be used each spoil the open frame.
        for number, bad in ((46, dict(stream=M.short_packet(0x17, 1), sync={0: 0})),
                            (47, dict(stream=M.short_packet(0x17, 1)[:3])),
                            (48, dict(stream=flip(M.short_packet(0x17, 1), (1, 2))))):
            s.burst(M.short_packet(FS, number))
            s.burst(**bad)
            s.burst(M.short_packet(FE, number))
    s.scene('frame/dirty-other', dirty_by_other_errors, dirty_end, M.ERR_LANE | M.ERR_TRUNCATED | M.ERR_HEADER,
            forbid=lambda out: clean_end(out) or out['pkt_ignored'])
    s.scene('row/count-zero', lambda: s.burst(framed(24, *line(0, M.long_packet(ROW, [])))),
            err(M.ERR_COUNT), M.ERR_COUNT, forbid=lambda out: out['pix_valid'] or out['row_done'])
    full = list(range(0x40, 0x40 + max_line))
    def count_limits():
        s.burst(framed(25, *line(0, M.long_packet(ROW, full))))
        s.burst(framed(125, *line(0, M.long_packet(ROW, [0x99]))))       # and the shortest row
    s.scene('row/count-max', count_limits, clean_end)
    s.scene('row/count-over', lambda: s.burst(framed(26, *line(0, M.long_packet(ROW, full + [0x77])))),
            err(M.ERR_COUNT), M.ERR_COUNT, forbid=lambda out: out['pix_valid'] or out['row_done'])
    s.scene('row/width-mismatch', lambda: s.burst(framed(
        27, *line(0, M.long_packet(ROW, [1, 2, 3])), *line(1, M.long_packet(ROW, [1, 2, 3, 4])),
        *line(2, M.long_packet(ROW, [5, 6, 7])))), err(M.ERR_COUNT), M.ERR_COUNT)

    def truncated_rows():
        whole = M.long_packet(ROW, [0x21, 0x22, 0x23])
        for number, cut in ((28, 6), (29, 8)):       # inside the pixels, and before the last CRC byte
            s.burst(flat([M.short_packet(FS, number), M.short_packet(LS, 0)]))
            s.burst(whole[:cut])
            s.burst(flat([M.short_packet(LE, 0), M.short_packet(FE, number)]))
    s.scene('row/truncated', truncated_rows, err(M.ERR_TRUNCATED), M.ERR_TRUNCATED, forbid=clean_end)

    # Order of frames and lines: one scene per rule, each breaking only that rule.
    row = M.long_packet(ROW, [0x31, 0x32, 0x33])
    seq = M.ERR_SEQUENCE
    s.scene('seq/frame-clean', lambda: s.burst(framed(30, *line(0, row), *line(1, row), *line(2, row))), clean_end)
    wide = M.long_packet(ROW, [0x51, 0x52, 0x53, 0x54])

    def restart():
        # The new frame starts from line 0, outside a line, and with its own width.
        s.burst(flat([M.short_packet(FS, 31), M.short_packet(LS, 0), row,
                      M.short_packet(FS, 32), *line(0, wide), M.short_packet(FE, 32)]))
        s.burst(flat([M.short_packet(FS, 33), *line(0, row),
                      M.short_packet(FS, 34), *line(0, wide), M.short_packet(FE, 34)]))
    s.scene('seq/frame-restart', restart, err(seq), seq, forbid=clean_end)
    s.scene('seq/frame-end-outside', lambda: s.burst(M.short_packet(FE, 33)), err(seq), seq,
            forbid=lambda out: out['frame_end'])
    s.scene('seq/frame-number', lambda: s.burst(flat([M.short_packet(FS, 34), M.short_packet(FE, 35)])),
            err(seq), seq, forbid=clean_end)
    s.scene('seq/frame-end-in-line', lambda: s.burst(flat([M.short_packet(FS, 36), M.short_packet(LS, 0), row,
                                                           M.short_packet(FE, 36)])), err(seq), seq, forbid=clean_end)
    s.scene('seq/line-start-outside', lambda: s.burst(flat([M.short_packet(LS, 0), row])), err(seq), seq,
            forbid=lambda out: out['pix_valid'])
    s.scene('seq/line-start-twice', lambda: s.burst(framed(37, M.short_packet(LS, 0), *line(0, row))),
            err(seq), seq, forbid=clean_end)
    s.scene('seq/line-number', lambda: s.burst(framed(38, M.short_packet(LS, 1), row, M.short_packet(LE, 0))),
            err(seq), seq, forbid=clean_end)
    s.scene('seq/line-end-outside', lambda: s.burst(framed(39, M.short_packet(LE, 0))), err(seq), seq, forbid=clean_end)
    s.scene('seq/line-end-without-row', lambda: s.burst(framed(40, M.short_packet(LS, 0), M.short_packet(LE, 0))),
            err(seq), seq, forbid=clean_end)
    s.scene('seq/line-end-number', lambda: s.burst(framed(41, *line(0, row, end=1))), err(seq), seq, forbid=clean_end)
    s.scene('seq/row-outside-line', lambda: s.burst(framed(42, row)), err(seq), seq,
            forbid=lambda out: out['pix_valid'] or clean_end(out))
    s.scene('seq/row-twice', lambda: s.burst(framed(43, M.short_packet(LS, 0), row, row, M.short_packet(LE, 0))),
            err(seq), seq, forbid=clean_end)

    # Reset in the middle of a row; the rest of the burst no longer starts with the sync byte.
    s.scene('reset/midpacket', lambda: s.burst(framed(44, *line(0, M.long_packet(ROW, full))), reset_at=4 * lanes + 9),
            err(M.ERR_LANE), lane_only, forbid=lambda out: out['frame_end'])
    s.close()
    s.burst(flat(small_frame(45)))          # and the layer works again afterwards
    return s


def random_stim(seed, iterations, lanes, max_line):
    rng = random.Random(seed)
    s = Stim(lanes, max_line)
    s.reset()
    limit = skew_limit(lanes, max_line)
    number = 0
    for _ in range(iterations):
        kind = rng.randrange(20)
        skew = [rng.randrange(limit + 2) if rng.randrange(4) == 0 else rng.randrange(3) for _ in range(lanes)]
        if kind == 0:
            s.reset(rng.randrange(1, 3))
        elif kind < 3:
            payload = [rng.randrange(256) for _ in range(rng.randrange(0, max_line + 2))]
            packet = (M.long_packet(rng.choice((ROW, 0x35)), payload) if rng.randrange(2)
                      else M.short_packet(rng.randrange(0x20), rng.randrange(4)))
            s.burst(packet, skew=skew)
        else:
            number += 1
            width = rng.randrange(1, max_line + 1)
            packets = M.frame_packets(number, [[rng.randrange(256) for _ in range(width)]
                                               for _ in range(rng.randrange(1, 4))])
            options = {}
            damage = rng.randrange(16)
            victim = rng.randrange(len(packets))
            if damage == 0:
                packets[victim] = flip(packets[victim], [rng.randrange(30)])
            elif damage == 1:
                packets[victim] = flip(packets[victim], rng.sample(range(32), 2))
            elif damage == 2:
                packets[victim] = flip(packets[victim], [rng.randrange(8 * len(packets[victim]))])
            elif damage == 3:
                del packets[victim]
            elif damage == 4:
                packets.insert(victim, packets[victim])
            elif damage == 5:
                other = rng.randrange(len(packets))
                packets[victim], packets[other] = packets[other], packets[victim]
            elif damage == 6:
                options['sync'] = {rng.randrange(lanes): rng.randrange(256)}
            elif damage == 7:
                options['extra'] = {rng.randrange(lanes): [rng.randrange(256)]}
            elif damage == 8 and lanes > 1:
                options['missing'] = (rng.randrange(lanes),)
            elif damage == 9:
                options['gap'] = rng.randrange(0, 6)
            stream = flat(packets)
            if damage == 10:
                stream = stream[:rng.randrange(1, len(stream))]
            if damage == 11:
                options['reset_at'] = rng.randrange(1, len(stream) + lanes)
            if rng.randrange(3) == 0 and damage not in (10,):   # split into one burst per packet
                for packet in packets:
                    s.burst(packet, skew=skew)
            else:
                s.burst(stream, skew=skew, **options)
    s.idle(4)
    return s


def counts(stim):
    stim.sync()
    outputs = stim.outputs
    pipe = [value for frame in stim.pipe_frames for value in
            SOBEL.sobel(frame, len(frame) // stim.pipe_h, stim.pipe_h)] if stim.pipe_frames else []
    return dict(pixels=sum(o['pix_valid'] for o in outputs), rows_ok=sum(o['row_ok'] for o in outputs),
                frames_clean=sum(o['frame_clean'] for o in outputs),
                errors=sum(bin(o['err']).count('1') for o in outputs), fixes=sum(o['hdr_fix'] for o in outputs),
                pipe_pixels=len(pipe),
                pipe_sum=sum((index % 255 + 1) * value for index, value in enumerate(pipe)) & 0x7fffffff)


def label(mutation, lanes):
    entry = LABELS[mutation]
    return entry[lanes] if isinstance(entry, dict) else entry


def make_cases(args, parameters):
    lanes, max_line = parameters['LANES'], parameters['MAX_LINE']
    fixed = boundary_stim(lanes, max_line, parameters['PIPE_W'], parameters['PIPE_H'])
    fixed.pipe_h = parameters['PIPE_H']
    baseline, expected = fixed.vectors(), counts(fixed)
    cases = [dict(id='boundaries', vectors=baseline, counts=expected, mutation=args.demo_bug,
                  category='functional', expected_failure=None)]
    for seed in range(args.seed, args.seed + (3 if args.profile == 'nightly' else 1)):
        stim = random_stim(seed, args.iterations, lanes, max_line)
        stim.pipe_h = parameters['PIPE_H']
        cases.append(dict(id=f'random-seed{seed}', vectors=stim.vectors(), counts=counts(stim),
                          mutation=args.demo_bug, category='functional', expected_failure=None))
    for mutation in range(1, MUTANTS + 1):
        cases.append(dict(id=f'detect-mutation{mutation}', vectors=baseline, counts=expected, mutation=mutation,
                          category='mutation', expected_failure=label(mutation, lanes)))
    return cases


if __name__ == '__main__':
    runner = load('local_runner', HERE.parent / 'local-common/runner.py')
    sys.exit(runner.main(sys.modules[__name__]))

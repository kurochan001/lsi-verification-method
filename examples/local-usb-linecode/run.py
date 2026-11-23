#!/usr/bin/env python3
"""Full-speed USB token/data line-code oracle with a controllably faulty channel."""
import importlib.util
from pathlib import Path
import random
import sys

HERE = Path(__file__).resolve().parent
NAME = 'local-usb-linecode'
TOP = 'usb_tb'
CONFIGS = {'tok': {'PKT': 0}, 'dat': {'PKT': 1}}
ITERATIONS = {'smoke': 8, 'nightly': 30}
SOURCES = [HERE / 'rtl/usb_linecode.sv', HERE / 'rtl/usb_linecode_rx.sv', HERE / 'tb/usb_tb.sv']
LABELS = ['USB_STUFF', 'USB_CRC', 'USB_PID', 'USB_LINE']
SYNC, PID, DATA, CRC, STUFF, EOP = range(6)
J, K, SE0 = 1, 2, 0


def least_first(value, count):
    return [(value >> k) & 1 for k in range(count)]


def crc_bits(bits, width):
    # Direct polynomial division. Bits are listed in transmission order.
    mask = (1 << width) - 1
    dividend = mask
    for bit in bits:
        dividend = (dividend << 1) ^ (bit << width)
    generator = {5: 0x25, 16: 0x18005}[width]
    while dividend.bit_length() > width:
        dividend ^= generator << (dividend.bit_length() - width - 1)
    return least_first(dividend ^ mask, width)[::-1]


def stuffed_bits(pid, payload, width):
    body = [(b, PID) for b in least_first(((pid ^ 15) << 4) | pid, 8)]
    body += [(b, DATA) for b in payload]
    body += [(b, CRC) for b in crc_bits(payload, width)]
    wire = [(b, SYNC) for b in [0]*7 + [1]]
    for bit, tag in body:
        wire.append((bit, tag))
        if [v for v, _ in wire[-6:]] == [1]*6:
            wire.append((0, STUFF))
    return wire


def encode(raw):
    level = J
    levels = []
    for bit, _ in raw:
        if bit == 0:
            level = J if level == K else K
        levels.append(level)
    return levels + [SE0, SE0, J]


def frame(pkt, pid, payload, nbytes, fault=None, cut=None):
    width = 16 if pkt else 5
    data = least_first(payload, 8*nbytes if pkt else 11)
    raw = stuffed_bits(pid, data, width)
    altered = list(raw)
    if fault in (PID, CRC, STUFF):
        # Change a complement bit, an FCS bit, or a stuffed zero respectively.
        indexes = [i for i, (_, kind) in enumerate(raw) if kind == fault]
        k = indexes[-1] if fault in (PID, CRC) else indexes[0]
        altered[k] = (1 - raw[k][0], fault)
    tx, rx = encode(raw), encode(altered)
    if fault == EOP:
        rx[-2] = J  # only one SE0 before the first J
    rows = [[1, pid, payload, nbytes, 0, 0]]
    for index, (left, right, kind) in enumerate(zip(tx, rx, [tag for _, tag in raw] + [EOP]*3)):
        if cut is not None and index == cut:
            return rows + [[0, 0, 0, 0, 0, 0]]
        rows.append([2, left, left ^ right, kind, int(index == len(tx)-1), 0])
    # On a short EOP, the receiver reported the result at the preceding symbol.
    flags = {None: 0, PID: 1, CRC: 2, STUFF: 4, EOP: 8}[fault]
    rows.append([3, pid, payload, nbytes if pkt else 2, flags, 0])
    return rows


def vectors(seed, count, parameters):
    pkt = parameters['PKT']
    pid = 3 if pkt else 1
    size = 8 if pkt else 2
    ones = (1 << (64 if pkt else 11))-1
    rows = [[0, 0, 0, 0, 0, 0]]
    rows.extend(frame(pkt, pid, ones, size))
    rows.extend(frame(pkt, pid, ones, size, fault=STUFF))
    for fault in (PID, CRC, EOP):
        rows.extend(frame(pkt, pid, 0, size, fault=fault))
    rows.extend(frame(pkt, pid, 0, size, cut=12))
    rows.extend(frame(pkt, pid, 0x159, size))
    if pkt:
        rows.extend(frame(pkt, 11, 0, 0))
        rows.append([4, 0, 0, 9, 0, 0])
    rng = random.Random(seed)
    for _ in range(count):
        nbytes = rng.randrange(9) if pkt else 2
        pid = rng.choice((3, 11) if pkt else (1, 9, 5, 13))
        value = rng.getrandbits(8*nbytes if pkt else 11)
        rows.extend(frame(pkt, pid, value, nbytes))
    return rows


def make_cases(args, parameters):
    base = vectors(args.seed, 0, parameters)
    cases = [dict(id='boundaries', vectors=base, mutation=args.demo_bug,
                  category='functional', expected_failure=None)]
    for seed in range(args.seed, args.seed + (3 if args.profile == 'nightly' else 1)):
        cases.append(dict(id=f'random-seed{seed}', vectors=vectors(seed, args.iterations, parameters),
                          mutation=args.demo_bug, category='functional', expected_failure=None))
    for mutation, label in enumerate(LABELS, start=1):
        cases.append(dict(id=f'detect-mutation{mutation}', vectors=base, mutation=mutation,
                          category='mutation', expected_failure=label))
    for case in cases:
        case['counts'] = {'steps': len(case['vectors'])}
    return cases


if __name__ == '__main__':
    spec = importlib.util.spec_from_file_location('local_runner', HERE.parent / 'local-common/runner.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    sys.exit(module.main(sys.modules[__name__]))

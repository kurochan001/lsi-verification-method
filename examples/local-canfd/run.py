#!/usr/bin/env python3
"""Independent frame oracle: construct whole bit strings, divide GF(2) polynomials."""
import importlib.util
from pathlib import Path
import random
import sys

HERE = Path(__file__).resolve().parent
NAME = 'local-canfd'
TOP = 'canfd_tb'
CONFIGS = {f'x{n}': {'RATIO': n} for n in (3, 5)}
ITERATIONS = {'smoke': 4, 'nightly': 12}
SOURCES = [HERE / 'rtl/canfd_tx.sv', HERE / 'tb/canfd_tb.sv']
LABELS = ['CANFD_STUFF', 'CANFD_CRC', 'CANFD_STREAM', 'CANFD_STREAM']
LENGTHS = tuple(range(9)) + (12, 16, 20, 24, 32, 48, 64)
GENERATORS = {15: 0xC599, 17: 0x3685B, 21: 0x302899}
BODY, DYNAMIC, FIXED, SBC, CRC, TAIL = range(6)


def bits(value, width):
    return [(value >> k) & 1 for k in reversed(range(width))]


def checksum(message, width, initial):
    dividend = initial
    for bit in message:
        dividend = (dividend << 1) ^ (bit << width)
    while dividend.bit_length() > width:
        dividend ^= GENERATORS[width] << (dividend.bit_length() - width - 1)
    return dividend


def symbols(fd, brs, identifier, dlc, data):
    length = LENGTHS[dlc] if fd else min(8, dlc)
    if len(data) != length:
        raise ValueError('payload length differs from DLC')
    header = [0] + bits(identifier, 11) + [0, 0]
    header += [1, 0, brs, 0] if fd else [0]
    body = header + bits(dlc, 4) + [b for octet in data for b in bits(octet, 8)]
    width = 21 if length > 16 else (17 if fd else 15)
    raw = [(b, BODY) for b in body]
    if not fd:
        raw += [(b, CRC) for b in bits(checksum(body, 15, 0), 15)]
    wire = []
    for index, (value, kind) in enumerate(raw):
        fast = int(fd and brs and index >= 17)
        # Check the previous five transmitted bits, including earlier stuff.
        if len(wire) >= 5 and len({b for b, _, _ in wire[-5:]}) == 1:
            wire.append((1-wire[-1][0], DYNAMIC, fast))
        wire.append((value, kind, fast))
    if fd:
        count = sum(kind == DYNAMIC for _, kind, _ in wire) % 8
        gray = bits(count ^ (count >> 1), 3)
        count_bits = gray + [sum(gray) % 2]
        crc = checksum([value for value, _, _ in wire] + count_bits, width, 1 << (width-1))
        trailer = [(b, SBC) for b in count_bits] + [(b, CRC) for b in bits(crc, width)]
        for index, (value, kind) in enumerate(trailer):
            if index % 4 == 0:
                wire.append((1-wire[-1][0], FIXED, brs))
            wire.append((value, kind, brs))
    elif len({b for b, _, _ in wire[-5:]}) == 1:
        wire.append((1-wire[-1][0], DYNAMIC, 0))
    return wire + [(1, TAIL, 0)] * 13


def frame(fd, brs, identifier, dlc, data, cut=None):
    # Row commands: 0 reset, 1 start, 2 check a bit and its duration, 3 idle.
    rows = [[1, fd | (brs << 1), identifier, dlc, int.from_bytes(data.ljust(64, b'\0'), 'big')]]
    for value, kind, fast in symbols(fd, brs, identifier, dlc, data)[:cut]:
        rows.append([2, value, kind, fast, 0])
    rows.append([3 if cut is None else 0, 0, 0, 0, 0])
    return rows


def vectors(seed, count):
    rows = [[0, 0, 0, 0, 0]]
    cases = [(0, 0, 0, 0), (1, 1, 0x555, 10), (1, 1, 0x7ff, 11),
             (1, 0, 0, 15), (0, 0, 0x123, 15), (1, 0, 1, 0)]
    for fd, brs, identifier, dlc in cases:
        length = LENGTHS[dlc] if fd else min(dlc, 8)
        data = bytes([0xff, 0xa9, 0x03, 0x80] * 16)[:length]
        rows.extend(frame(fd, brs, identifier, dlc, data))
    rows.extend(frame(1, 1, 0x321, 1, b'\x96', cut=25))
    rows.extend(frame(0, 0, 0x5a3, 1, b'\x7f'))
    rng = random.Random(seed)
    for _ in range(count):
        fd = rng.randrange(2)
        dlc = rng.randrange(16)
        length = LENGTHS[dlc] if fd else min(dlc, 8)
        rows.extend(frame(fd, fd and rng.randrange(2), rng.randrange(2048), dlc, rng.randbytes(length)))
    return rows


def make_cases(args, parameters):
    base = vectors(args.seed, 0)
    cases = [dict(id='boundaries', vectors=base, mutation=args.demo_bug,
                  category='functional', expected_failure=None)]
    for seed in range(args.seed, args.seed + (3 if args.profile == 'nightly' else 1)):
        cases.append(dict(id=f'random-seed{seed}', vectors=vectors(seed, args.iterations),
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

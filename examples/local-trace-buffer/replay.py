#!/usr/bin/env python3
"""Turn a trace buffer dump into the input rows of a simulation: the fixed regression of a field
failure. The dump lists the window oldest first: index, valid, data and the trigger mark.

A replay needs a known state. The frame monitor's state is known right after a flag that follows
a data byte (the frame length is 0 in every revision), so the replay starts at the first such
flag in the window, after a reset. A window without one cannot be replayed, and is refused.
"""
import argparse
from pathlib import Path
import sys

FLAG = 0x7e


class TraceError(ValueError):
    pass


def parse(text):
    """Header settings and the samples of a dump; anything malformed is refused."""
    header, samples = {}, []
    for number, line in enumerate(text.splitlines(), 1):
        if line.startswith('#'):
            for item in line[1:].split():
                if '=' in item:
                    key, value = item.split('=', 1)
                    header[key] = value
            continue
        if not line.strip():
            continue
        fields = line.split()
        if len(fields) != 4:
            raise TraceError(f'line {number}: expected index, valid, data and trigger')
        index, valid, data, trigger = (int(f, 16) for f in fields)
        if index != len(samples) or valid > 1 or data > 0xff or trigger > 1:
            raise TraceError(f'line {number}: index out of order or a field out of range')
        samples.append((valid, data, trigger))
    if 'depth' not in header or not samples or len(samples) > int(header['depth']):
        raise TraceError('missing depth, empty window or more samples than the depth')
    if sum(s[2] for s in samples) != 1:
        raise TraceError('the window must mark exactly one trigger sample')
    return header, samples


def sync_point(samples):
    """Index of the first flag whose previous valid sample in the window is a data byte."""
    previous = None
    for index, (valid, data, _) in enumerate(samples):
        if not valid:
            continue
        if data == FLAG and previous is not None and previous != FLAG:
            return index
        previous = data
    raise TraceError('no flag after a data byte in the window: the trace is too short to replay')


def replay(samples):
    """(valid, data) per clock from the sync point to the end, and the trigger's offset in it."""
    start = sync_point(samples)
    trigger = next(i for i, s in enumerate(samples) if s[2])
    # The error shown on the trigger sample comes from the bytes before it, so the known state
    # has to come strictly earlier.
    if trigger <= start:
        raise TraceError('no known state before the trigger: the trace is too short to replay')
    return [(v, d) for v, d, _ in samples[start:]], trigger - start


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('trace', type=Path)
    args = parser.parse_args()
    try:
        rows, trigger = replay(parse(args.trace.read_text())[1])
    except TraceError as error:
        print(f'refused: {error}', file=sys.stderr)
        return 1
    for valid, data in rows:
        print(f'{valid:x} {data:02x}')
    print(f'# trigger at replay clock {trigger}', file=sys.stderr)
    return 0


if __name__ == '__main__':
    sys.exit(main())

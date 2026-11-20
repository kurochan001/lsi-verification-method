#!/usr/bin/env python3
"""Solve a generated RC netlist with the repository's pinned ngspice library."""
import argparse
from bisect import bisect_left
import csv
import ctypes as C
import math
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'tools'))
import ngspice


def solve(prefix, deck, ticks, period, output):
    snapshot = ngspice.snapshot(prefix)
    lib = C.CDLL(snapshot['library'])
    messages = []
    exits = []
    text_type = C.CFUNCTYPE(C.c_int, C.c_char_p, C.c_int, C.c_void_p)
    exit_type = C.CFUNCTYPE(C.c_int, C.c_int, C.c_bool, C.c_bool, C.c_int, C.c_void_p)

    @text_type
    def text(message, _id, _data):
        messages.append(message.decode(errors='replace'))
        return 0

    @exit_type
    def exited(status, _unload, _quit, _id, _data):
        exits.append(status)
        return 0

    lib.ngSpice_nospinit()
    lib.ngSpice_nospiceinit()
    lib.ngSpice_Init.argtypes = [C.c_void_p] * 7
    lib.ngSpice_Init.restype = C.c_int
    if lib.ngSpice_Init(text, None, exited, None, None, None, None):
        raise ValueError('ngspice initialization failed')

    lib.ngSpice_Command.argtypes = [C.c_char_p]
    lib.ngSpice_Command.restype = C.c_int

    def command(line):
        if lib.ngSpice_Command(C.create_string_buffer(line.encode())):
            raise ValueError(f'ngspice command failed: {line}')

    command('version')
    if not any(re.search(r'\bngspice-' + re.escape(snapshot['release']) + r'\b', m) for m in messages):
        raise ValueError('actual ngspice version differs')
    lines = [C.create_string_buffer(line.encode()) for line in deck.read_text().splitlines()]
    array = (C.c_char_p * (len(lines) + 1))(*[C.cast(line, C.c_char_p) for line in lines], None)
    lib.ngSpice_Circ.argtypes = [C.POINTER(C.c_char_p)]
    if lib.ngSpice_Circ(array):
        raise ValueError('ngspice circuit import failed')

    lib.ngSpice_SetBkpt.argtypes = [C.c_double]
    lib.ngSpice_SetBkpt.restype = C.c_bool
    for tick in range(1, ticks):
        if not lib.ngSpice_SetBkpt(tick * period):
            raise ValueError(f'cannot place breakpoint for cycle {tick}')
    command(f'tran {period/40:.17g} {(ticks-1)*period:.17g} 0 {period/40:.17g} uic')
    if exits or any('error:' in m.lower() for m in messages):
        raise ValueError('ngspice analysis failed: ' + '\n'.join(messages))

    lib.ngGet_Vec_Info.argtypes = [C.c_char_p]
    lib.ngGet_Vec_Info.restype = C.POINTER(ngspice.Vector)

    def vector(name):
        pointer = lib.ngGet_Vec_Info(C.create_string_buffer(name.encode()))
        if not pointer or not pointer.contents.real or pointer.contents.length < ticks:
            raise ValueError(f'missing ngspice vector {name}')
        value = pointer.contents
        return value.real[:value.length]

    times, voltages = vector('time'), vector('v(filtered)')
    if len(times) != len(voltages) or not all(map(math.isfinite, times + voltages)):
        raise ValueError('invalid ngspice vector values')
    if any(b <= a for a, b in zip(times, times[1:])):
        raise ValueError('ngspice time is not strictly increasing')
    if abs(times[-1] - (ticks-1)*period) > 1e-12:
        raise ValueError('transient stopped before the requested end')
    samples = [(0, 0.0, 0.0)]  # Explicit IC of 0 V at the first digital edge.
    for tick in range(1, ticks):
        target = tick * period
        i = bisect_left(times, target)
        nearest = min(range(max(0, i-1), min(i+1, len(times))), key=lambda j: abs(times[j]-target))
        if abs(times[nearest] - target) > 1e-12:
            raise ValueError(f'no ngspice solver point at cycle {tick}')
        samples.append((tick, times[nearest], voltages[nearest]))
    with output.open('w', newline='') as stream:
        writer = csv.writer(stream)
        writer.writerow(['cycle', 'time_s', 'voltage_v'])
        writer.writerows(samples)
    ngspice.verify(snapshot)
    print(f'SPICE_PASS points={len(times)} cycles={len(samples)}')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('prefix', type=Path)
    parser.add_argument('deck', type=Path)
    parser.add_argument('ticks', type=int)
    parser.add_argument('period', type=float)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    if args.ticks < 2 or not math.isfinite(args.period) or args.period <= 0:
        parser.error('positive period and at least two ticks required')
    try:
        solve(args.prefix, args.deck, args.ticks, args.period, args.output)
    except (OSError, KeyError, ValueError) as exc:
        print('SPICE_ERROR', exc, file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())

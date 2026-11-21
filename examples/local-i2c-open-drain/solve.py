#!/usr/bin/env python3
"""Solve one SDA line with the pinned ngspice library and report its threshold crossings."""
import argparse
import csv
import ctypes as C
import json
import math
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'tools'))
import ngspice


def crossings(times, values, level, name):
    """Times at which a sampled waveform crosses a level, by linear interpolation, with the direction."""
    found = []
    for i in range(1, len(times)):
        a, b = values[i-1] - level, values[i] - level
        if (a < 0) != (b < 0):
            fraction = a / (a - b)
            found.append(dict(t=times[i-1] + (times[i] - times[i-1]) * fraction, level=name, direction=int(b >= 0)))
    return found


def measure(times, sda, vih, vil, windows):
    if not (len(times) == len(sda)) or len(times) < 2:
        raise ValueError('ngspice vectors are missing or differ in length')
    if not all(map(math.isfinite, [*times, *sda])):
        raise ValueError('non-finite value in an ngspice vector')
    if any(b <= a for a, b in zip(times, times[1:])):
        raise ValueError('ngspice time is not strictly increasing')
    found = sorted(crossings(times, sda, vih, 'vih') + crossings(times, sda, vil, 'vil'), key=lambda c: c['t'])
    spans = []
    for start, stop in windows:
        inside = [sda[i] for i, t in enumerate(times) if start <= t <= stop]
        if not inside:
            raise ValueError('measurement window holds no solver point')
        spans.append(dict(start=start, stop=stop, min=min(inside), max=max(inside)))
    return dict(points=len(times), stop=times[-1], initial=sda[0], crossings=found, windows=spans)


def solve(prefix, deck, request, output, trace):
    snapshot = ngspice.snapshot(prefix)
    lib = C.CDLL(snapshot['library'])
    messages, exits = [], []
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
    stop, step = request['stop'], request['step']
    command(f'tran {step:.17g} {stop:.17g} 0 {step:.17g} uic')
    if exits or any('error' in m.lower() or 'aborted' in m.lower() or 'timestep too small' in m.lower() for m in messages):
        raise ValueError('ngspice analysis failed: ' + ' | '.join(m for m in messages if 'error' in m.lower() or 'abort' in m.lower()
                                                                    or 'timestep' in m.lower())[:400])
    lib.ngGet_Vec_Info.argtypes = [C.c_char_p]
    lib.ngGet_Vec_Info.restype = C.POINTER(ngspice.Vector)

    def vector(name):
        pointer = lib.ngGet_Vec_Info(C.create_string_buffer(name.encode()))
        if not pointer or not pointer.contents.real or pointer.contents.length < 2:
            raise ValueError(f'missing ngspice vector {name} (the analysis did not run to completion): ' + ' | '.join(messages[-3:])[:300])
        value = pointer.contents
        return value.real[:value.length]

    times, sda = vector('time'), vector('v(sda)')
    record = measure(times, sda, request['vih'], request['vil'], [tuple(w) for w in request['windows']])
    if abs(record['stop'] - stop) > 1e-12:
        raise ValueError('transient stopped before the requested end')
    keep = max(1, len(times) // 4000)
    with trace.open('w', newline='') as stream:
        writer = csv.writer(stream)
        writer.writerow(['time_s', 'sda_v'])
        for i in range(0, len(times), keep):
            writer.writerow([f'{times[i]:.9e}', f'{sda[i]:.5f}'])
    ngspice.verify(snapshot)
    output.write_text(json.dumps(record, indent=1) + '\n')
    print(f"SPICE_PASS points={record['points']} crossings={len(record['crossings'])}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('prefix', type=Path)
    parser.add_argument('deck', type=Path)
    parser.add_argument('request', type=Path, help='JSON with stop, step, vih, vil and windows')
    parser.add_argument('output', type=Path)
    parser.add_argument('trace', type=Path)
    args = parser.parse_args()
    try:
        request = json.loads(args.request.read_text())
        for key in ('stop', 'step', 'vih', 'vil'):
            request[key] = float(request[key])
        if not all(math.isfinite(request[k]) for k in ('stop', 'step', 'vih', 'vil')) or request['step'] <= 0 \
                or request['stop'] <= request['step'] or not 0 < request['vil'] < request['vih']:
            raise ValueError('positive finite stop and step, and 0 < vil < vih, required')
        solve(args.prefix, args.deck, request, args.output, args.trace)
    except (OSError, KeyError, ValueError, TypeError) as exc:
        print('SPICE_ERROR', exc, file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())

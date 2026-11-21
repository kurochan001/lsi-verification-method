#!/usr/bin/env python3
"""Solve one supply scenario with the pinned ngspice library and report detector events."""
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

LEVEL = 0.5  # the detector output is digitised by an ideal threshold at half scale


def crossings(times, values, level=LEVEL):
    """Times at which a sampled waveform crosses a level, by linear interpolation."""
    found = []
    for i in range(1, len(times)):
        a, b = values[i-1] - level, values[i] - level
        if (a < 0) != (b < 0):
            fraction = a / (a - b)
            found.append((i, fraction, int(b >= 0)))
    return found


def at(series, index, fraction):
    return series[index-1] + (series[index] - series[index-1]) * fraction


def measure(times, vdd, vdiv, det, lookback, windows):
    if not (len(times) == len(vdd) == len(vdiv) == len(det)) or len(times) < 2:
        raise ValueError('ngspice vectors are missing or differ in length')
    if not all(map(math.isfinite, [*times, *vdd, *vdiv, *det])):
        raise ValueError('non-finite value in an ngspice vector')
    if any(b <= a for a, b in zip(times, times[1:])):
        raise ValueError('ngspice time is not strictly increasing')
    events = []
    for index, fraction, value in crossings(times, det):
        t = at(times, index, fraction)
        first = index
        while first > 0 and times[first-1] >= t - lookback:
            first -= 1
        before = vdd[first:index] or [vdd[index-1]]
        events.append(dict(t=t, value=value, vdd=at(vdd, index, fraction), vdiv=at(vdiv, index, fraction),
                           vdd_max_before=max(before), vdd_min_before=min(before)))
    spans = []
    for start, stop in windows:
        inside = [i for i, t in enumerate(times) if start <= t <= stop]
        if not inside:
            raise ValueError('measurement window holds no solver point')
        spans.append(dict(start=start, stop=stop, det_min=min(det[i] for i in inside), det_max=max(det[i] for i in inside),
                          vdd_min=min(vdd[i] for i in inside), vdiv_min=min(vdiv[i] for i in inside)))
    return dict(points=len(times), stop=times[-1], initial_det=det[0], final_det=det[-1], events=events, windows=spans)


def solve(prefix, deck, stop, step, lookback, windows, output, trace):
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
    command(f'tran {step:.17g} {stop:.17g} 0 {step:.17g} uic')
    if exits or any('error' in m.lower() for m in messages):
        raise ValueError('ngspice analysis failed: ' + ' | '.join(m for m in messages if 'error' in m.lower())[:400])
    lib.ngGet_Vec_Info.argtypes = [C.c_char_p]
    lib.ngGet_Vec_Info.restype = C.POINTER(ngspice.Vector)

    def vector(name):
        pointer = lib.ngGet_Vec_Info(C.create_string_buffer(name.encode()))
        if not pointer or not pointer.contents.real or pointer.contents.length < 2:
            raise ValueError(f'missing ngspice vector {name} (the analysis did not run to completion): ' + ' | '.join(messages[-3:])[:300])
        value = pointer.contents
        return value.real[:value.length]

    times, vdd, vdiv, det = (vector(name) for name in ('time', 'v(vdd)', 'v(vdiv)', 'v(det)'))
    record = measure(times, vdd, vdiv, det, lookback, windows)
    if abs(record['stop'] - stop) > 1e-12:
        raise ValueError('transient stopped before the requested end')
    keep = max(1, len(times) // 2000)
    with trace.open('w', newline='') as stream:
        writer = csv.writer(stream)
        writer.writerow(['time_s', 'vdd_v', 'vdiv_v', 'det'])
        for i in range(0, len(times), keep):
            writer.writerow([f'{times[i]:.9e}', f'{vdd[i]:.6f}', f'{vdiv[i]:.6f}', f'{det[i]:.6f}'])
    ngspice.verify(snapshot)
    output.write_text(json.dumps(record, indent=1) + '\n')
    print(f"SPICE_PASS points={record['points']} events={len(record['events'])}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('prefix', type=Path)
    parser.add_argument('deck', type=Path)
    parser.add_argument('request', type=Path, help='JSON with stop, step, lookback and windows')
    parser.add_argument('output', type=Path)
    parser.add_argument('trace', type=Path)
    args = parser.parse_args()
    try:
        request = json.loads(args.request.read_text())
        stop, step, lookback = (float(request[k]) for k in ('stop', 'step', 'lookback'))
        if not all(map(math.isfinite, (stop, step, lookback))) or step <= 0 or stop <= step or lookback <= 0:
            raise ValueError('positive finite stop, step and lookback required')
        solve(args.prefix, args.deck, stop, step, lookback, [tuple(w) for w in request['windows']], args.output, args.trace)
    except (OSError, KeyError, ValueError, TypeError) as exc:
        print('SPICE_ERROR', exc, file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())

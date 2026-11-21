#!/usr/bin/env python3
"""Measure the teaching flip-flop with the repository's pinned ngspice shared library.

Reads a list of jobs, writes one record per job. It only measures: every comparison with
the table and every pass/fail decision is made by the caller.
"""
import argparse
import ctypes as C
import importlib.util
import json
import math
from pathlib import Path
import re
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / 'tools'))
import ngspice

spec = importlib.util.spec_from_file_location('liberty_cells', HERE / 'cells.py')
CELLS = importlib.util.module_from_spec(spec)
spec.loader.exec_module(CELLS)

HALF = CELLS.VDD / 2
DEGRADE = 1.10            # a capture fails when CLK->Q is more than 10 % slower than the reference
RESOLUTION = 1e-12        # the search stops when the bracket is this narrow
MAX_PROBES = 16
REFERENCE_SETUP = 1.0e-9  # data this early is "settled": the reference CLK->Q delay
WINDOW = 1.0e-9           # Q must cross within this time after the clock edge


class SpiceError(ValueError):
    pass


class Session:
    def __init__(self, prefix):
        self.snapshot = ngspice.snapshot(prefix)
        self.lib = lib = C.CDLL(self.snapshot['library'])
        self.messages = []
        self.exits = []
        text_type = C.CFUNCTYPE(C.c_int, C.c_char_p, C.c_int, C.c_void_p)
        exit_type = C.CFUNCTYPE(C.c_int, C.c_int, C.c_bool, C.c_bool, C.c_int, C.c_void_p)

        def text(message, _id, _data):
            self.messages.append(message.decode(errors='replace'))
            return 0

        def exited(status, _unload, _quit, _id, _data):
            self.exits.append(status)
            return 0

        self.callbacks = (text_type(text), exit_type(exited))  # keep them alive
        lib.ngSpice_nospinit()
        lib.ngSpice_nospiceinit()
        lib.ngSpice_Init.argtypes = [C.c_void_p] * 7
        lib.ngSpice_Init.restype = C.c_int
        if lib.ngSpice_Init(C.cast(self.callbacks[0], C.c_void_p), None, C.cast(self.callbacks[1], C.c_void_p),
                            None, None, None, None):
            raise SpiceError('ngspice initialization failed')
        lib.ngSpice_Command.argtypes = [C.c_char_p]
        lib.ngSpice_Command.restype = C.c_int
        lib.ngSpice_Circ.argtypes = [C.POINTER(C.c_char_p)]
        lib.ngSpice_Circ.restype = C.c_int
        lib.ngGet_Vec_Info.argtypes = [C.c_char_p]
        lib.ngGet_Vec_Info.restype = C.POINTER(ngspice.Vector)
        self.command('version')
        if not any(re.search(r'\bngspice-' + re.escape(self.snapshot['release']) + r'\b', m) for m in self.messages):
            raise SpiceError('actual ngspice version differs')
        self.runs = 0

    def command(self, line):
        if self.lib.ngSpice_Command(C.create_string_buffer(line.encode())):
            raise SpiceError('ngspice command failed: ' + line)

    def solve(self, deck, analysis, names):
        """Load one circuit, run one analysis, return the named vectors, then drop the circuit."""
        start = len(self.messages)
        buffers = [C.create_string_buffer(line.encode()) for line in deck]
        array = (C.c_char_p * (len(buffers) + 1))(*[C.cast(b, C.c_char_p) for b in buffers], None)
        try:
            if self.lib.ngSpice_Circ(array):
                raise SpiceError('ngspice circuit import failed')
            self.command(analysis)
            said = self.messages[start:]
            problem = [m for m in said if re.search(r'error|singular|aborted|not converge|timestep too small', m, re.I)]
            if self.exits or problem:
                raise SpiceError('ngspice analysis failed: ' + ' | '.join(problem[:3] or ['exit']))
            vectors = {}
            for name in names:
                pointer = self.lib.ngGet_Vec_Info(C.create_string_buffer(name.encode()))
                if not pointer or not pointer.contents.real or pointer.contents.length < 1:
                    raise SpiceError('missing ngspice vector ' + name)
                value = pointer.contents
                vectors[name] = value.real[:value.length]
            if len({len(v) for v in vectors.values()}) != 1 or not all(math.isfinite(x) for v in vectors.values() for x in v):
                raise SpiceError('invalid ngspice vector values')
            self.runs += 1
            return vectors
        finally:
            for line in ('destroy all', 'remcirc'):
                self.lib.ngSpice_Command(C.create_string_buffer(line.encode()))


def crossing(times, values, level, after, rising):
    """First time after `after` at which the waveform crosses `level` in the given direction."""
    for i in range(1, len(times)):
        if times[i] < after:
            continue
        a, b = values[i - 1], values[i]
        if (a < level <= b) if rising else (a > level >= b):
            return times[i - 1] + (level - a) / (b - a) * (times[i] - times[i - 1])
    return None


def capture(session, job, data_time, back_time=None):
    """One transient. Returns the measured CLK->Q delay (None if Q never switches) and the final Q."""
    deck = CELLS.capture_deck(job['new'], data_time, job['clock_slew'], job['data_slew'], job['load'],
                              job.get('settings'), job.get('fault'), back_time)
    v = session.solve(deck, CELLS.transient(job.get('settings')), ['time', 'v(q)', 'v(clk)', 'v(d)'])
    times, q, clock = v['time'], v['v(q)'], v['v(clk)']
    if job.get('trace') and data_time != CELLS.CAPTURE - REFERENCE_SETUP:   # the capture under test, not its reference
        rows = [f'{t:.6e},{c:.4f},{d:.4f},{y:.4f}' for t, c, d, y in zip(times, clock, v['v(d)'], q)
                if CELLS.CAPTURE - 0.3e-9 <= t <= CELLS.CAPTURE + 0.6e-9]
        Path(job['trace']).write_text('time_s,clk_v,d_v,q_v\n' + '\n'.join(rows) + '\n')
    if abs(times[-1] - CELLS.STOP) > 1e-13 or any(b <= a for a, b in zip(times, times[1:])):
        raise SpiceError('transient stopped early or time is not increasing')
    rising = bool(job['new'])
    edge = crossing(times, clock, HALF, CELLS.CAPTURE - 0.5e-9, True)
    switch = crossing(times, q, HALF, CELLS.CAPTURE - 0.2e-9, rising)
    record = dict(points=len(times), final_q=q[-1], clock_edge=edge, delay=None, transition=None)
    if edge is not None and switch is not None and switch - edge <= WINDOW:
        lo, hi = (0.2 * CELLS.VDD, 0.8 * CELLS.VDD) if rising else (0.8 * CELLS.VDD, 0.2 * CELLS.VDD)
        first = crossing(times, q, lo, CELLS.CAPTURE - 0.2e-9, rising)
        last = crossing(times, q, hi, CELLS.CAPTURE - 0.2e-9, rising)
        record.update(delay=switch - edge, transition=None if first is None or last is None else last - first)
    return record


def captured(record, job, reference, criterion):
    """Did the flip-flop take the new value, by the chosen criterion?"""
    target = job['new'] * CELLS.VDD
    if record['delay'] is None or abs(record['final_q'] - target) > 0.1 * CELLS.VDD:
        return False
    return criterion == 'captures' or record['delay'] <= DEGRADE * reference


def run_delay(session, job):
    record = capture(session, job, CELLS.CAPTURE - REFERENCE_SETUP)
    if record['delay'] is None:
        raise SpiceError('Q does not switch after the clock edge')
    return record


def run_point(session, job):
    """A single capture at a given data offset (and optional return offset), judged by the criterion."""
    reference = run_delay(session, job)['delay']
    back = None if job.get('back') is None else CELLS.CAPTURE + job['back']
    record = capture(session, job, CELLS.CAPTURE - job['offset'], back)
    return dict(record, reference=reference, captured=captured(record, job, reference, job.get('criterion', 'degrade')))


def run_search(session, job):
    """Bisect the smallest setup (or hold) time that still captures. Every probe is recorded."""
    reference = run_delay(session, job)['delay']
    criterion = job.get('criterion', 'degrade')
    probes = []

    def passes(value):
        if job['kind'] == 'setup':
            record = capture(session, job, CELLS.CAPTURE - value)
        else:  # hold: data arrives early, then returns to the old value `value` after the clock edge
            record = capture(session, job, CELLS.CAPTURE - REFERENCE_SETUP, CELLS.CAPTURE + value)
        ok = captured(record, job, reference, criterion)
        probes.append(dict(value=value, captured=ok, delay=record['delay'], final_q=record['final_q']))
        return ok

    low, high = job['low'], job['high']   # low must fail, high must capture
    if passes(low) or not passes(high):
        raise SpiceError('search bracket does not contain the boundary')
    while high - low > RESOLUTION:
        if len(probes) >= MAX_PROBES:
            raise SpiceError('search did not converge within the probe limit')
        middle = (low + high) / 2
        if passes(middle):
            high = middle
        else:
            low = middle
    return dict(value=high, fails_at=low, reference=reference, probes=probes, criterion=criterion)


def run_sweep(session, job):
    """Capture verdicts over a list of values, to show that pass/fail has a single boundary."""
    reference = run_delay(session, job)['delay']
    rows = []
    for value in job['values']:
        if job['kind'] == 'sweep-setup':
            record = capture(session, job, CELLS.CAPTURE - value)
        else:
            record = capture(session, job, CELLS.CAPTURE - REFERENCE_SETUP, CELLS.CAPTURE + value)
        rows.append(dict(value=value, captured=captured(record, job, reference, 'degrade'), delay=record['delay']))
    return dict(reference=reference, rows=rows)


def run_device(session, job):
    v = session.solve(CELLS.device_deck(job['device'], job['vgs'], job['vds']), 'op', ['i(vd)'])
    return dict(current=-v['i(vd)'][0])


def run_threshold(session, job):
    return dict(voltage=session.solve(CELLS.threshold_deck(), 'op', ['v(x)'])['v(x)'][0])


KINDS = dict(delay=run_delay, point=run_point, setup=run_search, hold=run_search, device=run_device,
             threshold=run_threshold)
KINDS['sweep-setup'] = KINDS['sweep-hold'] = run_sweep


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('prefix', type=Path)
    parser.add_argument('jobs', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    try:
        jobs = json.loads(args.jobs.read_text())
        session = Session(args.prefix)
        results = []
        for job in jobs:
            try:
                results.append(dict(id=job['id'], kind=job['kind'], error=None, **KINDS[job['kind']](session, job)))
            except SpiceError as exc:   # one failed job must not hide the others, nor pass silently
                results.append(dict(id=job['id'], kind=job['kind'], error=str(exc)))
        ngspice.verify(session.snapshot)
        args.output.write_text(json.dumps(dict(runs=session.runs, results=results), indent=1) + '\n')
    except (OSError, KeyError, ValueError, TypeError) as exc:
        print('SPICE_ERROR', exc, file=sys.stderr)
        return 1
    print(f'SPICE_DONE jobs={len(results)} runs={session.runs}')
    return 0


if __name__ == '__main__':
    sys.exit(main())

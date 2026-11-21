#!/usr/bin/env python3
"""Run a list of decks through the pinned ngspice library and report every job as data or as a failure.

A job is never reported as good because the analysis command returned zero. ngspice returns zero
from a transient that it aborted, so the worker also reads the messages, the last time point and
every measured value.
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

spec = importlib.util.spec_from_file_location('spice_regression_model', HERE / 'model.py')
M = importlib.util.module_from_spec(spec)
spec.loader.exec_module(M)

ABORT = re.compile(r'timestep too small|aborted|no convergence|iteration limit', re.I)


class Library:
    def __init__(self, prefix):
        self.snapshot = ngspice.snapshot(prefix)
        self.lib = C.CDLL(self.snapshot['library'])
        self.messages, self.exits = [], []
        text_type = C.CFUNCTYPE(C.c_int, C.c_char_p, C.c_int, C.c_void_p)
        exit_type = C.CFUNCTYPE(C.c_int, C.c_int, C.c_bool, C.c_bool, C.c_int, C.c_void_p)
        self._text = text_type(lambda message, _i, _d: self.messages.append(message.decode(errors='replace')) or 0)
        self._exit = exit_type(lambda status, _u, _q, _i, _d: self.exits.append(status) or 0)
        self.lib.ngSpice_nospinit()
        self.lib.ngSpice_nospiceinit()
        self.lib.ngSpice_Init.argtypes = [C.c_void_p] * 7
        self.lib.ngSpice_Init.restype = C.c_int
        if self.lib.ngSpice_Init(C.cast(self._text, C.c_void_p), None, C.cast(self._exit, C.c_void_p),
                                 None, None, None, None):
            raise ValueError('ngspice initialization failed')
        self.lib.ngSpice_Command.argtypes = [C.c_char_p]
        self.lib.ngSpice_Command.restype = C.c_int
        self.lib.ngSpice_Circ.argtypes = [C.POINTER(C.c_char_p)]
        self.lib.ngSpice_Circ.restype = C.c_int
        self.lib.ngGet_Vec_Info.argtypes = [C.c_char_p]
        self.lib.ngGet_Vec_Info.restype = C.POINTER(ngspice.Vector)
        self.command('version')
        if not any(re.search(r'\bngspice-' + re.escape(self.snapshot['release']) + r'\b', m) for m in self.messages):
            raise ValueError('actual ngspice version differs')

    def command(self, line):
        return self.lib.ngSpice_Command(C.create_string_buffer(line.encode()))

    def circuit(self, lines):
        buffers = [C.create_string_buffer(line.encode()) for line in lines]
        array = (C.c_char_p * (len(buffers) + 1))(*[C.cast(b, C.c_char_p) for b in buffers], None)
        return self.lib.ngSpice_Circ(array)

    def vector(self, name):
        pointer = self.lib.ngGet_Vec_Info(C.create_string_buffer(name.encode()))
        if not pointer or not pointer.contents.real or pointer.contents.length < 1:
            return None
        return pointer.contents.real[:pointer.contents.length]


def measure(item, data):
    """One measurement computed here from the saved waveforms, independent of ngspice's own meas."""
    kind = item['kind']
    times = data['time']
    if kind == 'delay':
        return M.delay(times, data[item['source']], data[item['target']], item['level'], item['source_rising'])
    if kind == 'period':
        return M.period(times, data[item['signal']], item['level'])
    if kind == 'swing_ratio':
        return M.swing_ratio(times, data[item['source']], data[item['target']])
    if kind == 'crossing':
        found = M.crossings(times, data[item['signal']], item['level'], True)
        if not found:
            raise M.Mismatch('SPICE_MEASURE', 'the waveform never crosses the level')
        return found[0]
    if kind == 'rise':
        low = M.crossings(times, data[item['signal']], item['low'], True)
        high = M.crossings(times, data[item['signal']], item['high'], True)
        if not low or not high:
            raise M.Mismatch('SPICE_MEASURE', 'the waveform never completes the rise')
        return high[0] - low[0]
    if kind == 'rc_error':
        return M.rc_error(times, data[item['signal']], item['tau'])
    raise ValueError('unknown measurement kind: ' + kind)


def run_job(library, job):
    """Return the record of one job. status is 'ok' or a failure label."""
    library.messages.clear()
    record = dict(id=job['id'], status='ok', detail='', values={}, tool={}, points=0)

    def fail(label, detail):
        record.update(status=label, detail=detail, messages=[m for m in library.messages if 'stdout' not in m][-6:])
        return record

    if library.circuit(job['deck']) or library.exits:
        return fail('SPICE_NETLIST', 'ngspice rejected the deck')
    if any('error' in m.lower() for m in library.messages):
        return fail('SPICE_NETLIST', 'ngspice reported an error while reading the deck')
    code = library.command(job['tran'])
    text = '\n'.join(library.messages)
    if library.exits:
        return fail('SPICE_FATAL', 'ngspice asked to exit')
    data = {}
    for name in job['vectors']:
        values = library.vector(name)
        if values is None:
            return fail('SPICE_CONVERGENCE' if ABORT.search(text) else 'SPICE_MEASURE', f'vector {name} is missing')
        data[name] = values
    record['points'] = len(data['time'])
    if code or ABORT.search(text) or abs(data['time'][-1] - job['stop']) > 1e-6 * job['stop']:
        return fail('SPICE_CONVERGENCE', f"analysis stopped at {data['time'][-1]:.6g} s of {job['stop']:.6g} s")
    if any('error' in m.lower() for m in library.messages):
        return fail('SPICE_ERROR', 'ngspice reported an error during the analysis')
    if len({len(v) for v in data.values()}) != 1 or any(b <= a for a, b in zip(data['time'], data['time'][1:])):
        return fail('SPICE_ERROR', 'vector lengths differ or time does not increase')
    if not all(math.isfinite(x) for values in data.values() for x in values):
        return fail('SPICE_NONFINITE', 'a waveform holds a value that is not finite')
    try:
        for item in job.get('measure', []):
            record['values'][item['name']] = M.finite(item['name'], float(measure(item, data)))
        for name, line in job.get('tool_measure', {}).items():
            library.command(line)
            value = library.vector(name)
            if value is None:
                raise M.Mismatch('SPICE_MEASURE', f'ngspice could not measure {name}')
            record['tool'][name] = M.finite(name, float(value[0]))
    except M.Mismatch as exc:
        return fail(exc.label, str(exc))
    if job.get('dump'):
        path = Path(job['dump'])
        names = job['vectors']
        with path.open('w') as stream:
            stream.write(','.join(names) + '\n')
            for row in zip(*(data[n] for n in names)):
                stream.write(','.join(f'{x:.9g}' for x in row) + '\n')
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('prefix', type=Path)
    parser.add_argument('jobs', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    try:
        jobs = json.loads(args.jobs.read_text())
        library = Library(args.prefix)
        records = []
        for job in jobs:
            if library.exits:  # the library cannot be used after it asked to exit
                records.append(dict(id=job['id'], status='SPICE_FATAL', detail='ngspice is no longer usable',
                                    values={}, tool={}, points=0))
                continue
            records.append(run_job(library, job))
            library.command('remcirc')
            library.command('destroy all')
        ngspice.verify(library.snapshot)
        args.output.write_text(json.dumps(records, indent=1) + '\n')
    except (OSError, KeyError, ValueError, TypeError) as exc:
        print('SPICE_ERROR', exc, file=sys.stderr)
        return 1
    print(f'SPICE_DONE jobs={len(records)} ok={sum(r["status"] == "ok" for r in records)}')
    return 0


if __name__ == '__main__':
    sys.exit(main())

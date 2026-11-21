#!/usr/bin/env python3
"""Solve the capacitor DAC with the repository's pinned ngspice library.

One clock cycle is one transient analysis.  The switch positions are fixed inside a cycle, so
each cycle gets its own small netlist; the capacitor voltages at the end of a cycle become the
initial conditions of the next one.  The comparator answer that ngspice gives at the end of a
trial cycle decides the next netlist, which is how the loop through the SAR search is closed.

Everything that could silently pass is an error here: a failed command, a message that
mentions an error, a missing or short vector, a value that is not finite, an analysis that
stops before the end of the cycle.
"""
import argparse
import ctypes as C
import json
import math
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'tools'))
import ngspice


class Solver:
    def __init__(self, prefix):
        self.snapshot = ngspice.snapshot(prefix)
        self.lib = lib = C.CDLL(self.snapshot['library'])
        self.messages, self.exits = [], []
        text_type = C.CFUNCTYPE(C.c_int, C.c_char_p, C.c_int, C.c_void_p)
        exit_type = C.CFUNCTYPE(C.c_int, C.c_int, C.c_bool, C.c_bool, C.c_int, C.c_void_p)
        self._text = text_type(lambda m, _i, _d: self.messages.append(m.decode(errors='replace')) or 0)
        self._exit = exit_type(lambda s, _u, _q, _i, _d: self.exits.append(s) or 0)
        lib.ngSpice_nospinit()
        lib.ngSpice_nospiceinit()
        lib.ngSpice_Init.argtypes = [C.c_void_p] * 7
        lib.ngSpice_Init.restype = C.c_int
        if lib.ngSpice_Init(self._text, None, self._exit, None, None, None, None):
            raise ValueError('ngspice initialization failed')
        lib.ngSpice_Command.argtypes = [C.c_char_p]
        lib.ngSpice_Command.restype = C.c_int
        lib.ngSpice_Circ.argtypes = [C.POINTER(C.c_char_p)]
        lib.ngGet_Vec_Info.argtypes = [C.c_char_p]
        lib.ngGet_Vec_Info.restype = C.POINTER(ngspice.Vector)
        self.command('version')
        release = re.escape(self.snapshot['release'])
        if not any(re.search(r'\bngspice-' + release + r'\b', m) for m in self.messages):
            raise ValueError('actual ngspice version differs')
        self.analyses = 0

    def command(self, line):
        if self.lib.ngSpice_Command(C.create_string_buffer(line.encode())):
            raise ValueError(f'ngspice command failed: {line}')

    def vector(self, name):
        pointer = self.lib.ngGet_Vec_Info(C.create_string_buffer(name.encode()))
        if not pointer or not pointer.contents.real or pointer.contents.length < 2:
            raise ValueError(f'missing ngspice vector {name}')
        values = pointer.contents.real[:pointer.contents.length]
        if not all(map(math.isfinite, values)):
            raise ValueError(f'ngspice vector {name} is not finite')
        return values

    def cycle(self, deck, period, options, names):
        """Run one clock cycle and return the time axis and the named node voltages."""
        before = len(self.messages)
        lines = [C.create_string_buffer(line.encode()) for line in deck]
        array = (C.c_char_p * (len(lines) + 1))(*[C.cast(line, C.c_char_p) for line in lines], None)
        if self.lib.ngSpice_Circ(array):
            raise ValueError('ngspice circuit import failed')
        step = period / options['steps']
        self.command(f'tran {step!r} {period!r} 0 {step!r} uic')
        recent = self.messages[before:]
        if self.exits or any(re.search(r'error|singular|too small|aborted', m, re.I) for m in recent):
            raise ValueError('ngspice analysis failed: ' + ' | '.join(recent[-6:]))
        time = self.vector('time')
        if any(b <= a for a, b in zip(time, time[1:])):
            raise ValueError('ngspice time is not strictly increasing')
        if abs(time[-1] - period) > period * 1e-9:
            raise ValueError('transient stopped before the end of the cycle')
        values = {name: self.vector(f'v({name})') for name in names}
        if any(len(v) != len(time) for v in values.values()):
            raise ValueError('ngspice vectors differ in length')
        self.command('destroy all')
        self.command('remcirc')
        self.analyses += 1
        return time, values


def deck(circuit, rails, top_closed, state, vin_v, options, broken=False):
    """Netlist of one cycle.  rails[k] names the node that bottom plate k is switched to."""
    lines = ['* one clock cycle of the capacitor DAC (teaching values, not a process model)',
             f'Vin vin 0 DC {vin_v!r}', f"Vref vref 0 DC {circuit['vref_v']!r}"]
    for k, (cap, resistance) in enumerate(zip(circuit['caps_f'], circuit['switch_ohm'])):
        lines += [f'R{k} {rails[k]} b{k} {resistance!r}',
                  f"C{k} top b{k} {cap!r} ic={state['top'] - state[f'b{k}']!r}"]
    lines += [f"Cp top 0 {circuit['cp_f']!r} ic={state['top']!r}",
              f"Rtop top 0 {(circuit['ron_ohm'] if top_closed else circuit['roff_ohm'])!r}",
              # A comparator that is close to ideal: 1 V when the top plate is below 0 V.
              'Bcmp cmp 0 V = 0.5 * (1 - tanh(v(top) / 100u))', 'Rcmp cmp 0 1k']
    if broken:
        lines.append('Rbroken top missing_model_node nosuchvalue')
    lines += [f".options reltol={options['reltol']!r} abstol=1e-14 vntol=1e-9 chgtol=1e-19 "
              f"method={options['method']}", '.end']
    return lines


def nodes(circuit):
    return ['top', 'cmp', *[f'b{k}' for k in range(len(circuit['caps_f']))]]


def discharged(circuit):
    return {name: 0.0 for name in nodes(circuit) if name != 'cmp'}


def convert(solver, circuit, vin_v, period, options, broken=False):
    """One conversion: a sample cycle, then one trial cycle per bit, most significant first."""
    bits = len(circuit['caps_f']) - 1
    count = bits + 1
    names = nodes(circuit)
    state = discharged(circuit)
    _, values = solver.cycle(deck(circuit, ['vin'] * count, True, state, vin_v, options, broken),
                             period, options, names)
    state = {name: values[name][-1] for name in names if name != 'cmp'}
    sample_top = state['top']
    code, answers, tops = 0, [], []
    for bit in reversed(range(bits)):
        trial = code | 1 << bit
        rails = ['vref' if trial >> k & 1 else '0' for k in range(bits)] + ['0']
        _, values = solver.cycle(deck(circuit, rails, False, state, vin_v, options), period,
                                 options, names)
        state = {name: values[name][-1] for name in names if name != 'cmp'}
        answer = int(values['cmp'][-1] > 0.5)
        answers.append(answer)
        tops.append(state['top'])
        if answer:
            code = trial
    return dict(code=code, answers=answers, tops=tops, sample_top=sample_top)


def waveform(solver, circuit, vin_v, period, options):
    """Top-plate waveform of the sample cycle and of the first trial cycle."""
    bits = len(circuit['caps_f']) - 1
    names = nodes(circuit)
    time, values = solver.cycle(deck(circuit, ['vin'] * (bits + 1), True, discharged(circuit),
                                     vin_v, options), period, options, names)
    sample = dict(time=time, top=values['top'])
    state = {name: values[name][-1] for name in names if name != 'cmp'}
    rails = ['vref' if k == bits - 1 else '0' for k in range(bits + 1)]
    time, values = solver.cycle(deck(circuit, rails, False, state, vin_v, options), period,
                                options, names)
    return dict(sample=sample, trial=dict(time=time, top=values['top']), start_top=state['top'])


def run(prefix, request):
    solver = Solver(prefix)
    results = []
    for job in request['jobs']:
        circuit, options, period = job['circuit'], job['options'], job['period_s']
        if job['kind'] == 'convert':
            results.append([convert(solver, circuit, vin, period, options, job.get('broken', False))
                            for vin in job['inputs_v']])
        elif job['kind'] == 'waveform':
            results.append(waveform(solver, circuit, job['inputs_v'][0], period, options))
        else:
            raise ValueError('unknown job kind')
    ngspice.verify(solver.snapshot)
    return dict(results=results, analyses=solver.analyses)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('prefix', type=Path)
    parser.add_argument('request', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    try:
        answer = run(args.prefix, json.loads(args.request.read_text()))
        args.output.write_text(json.dumps(answer))
    except (OSError, KeyError, ValueError, TypeError) as exc:
        print('SPICE_ERROR', exc, file=sys.stderr)
        return 1
    print(f"SPICE_PASS analyses={answer['analyses']}")
    return 0


if __name__ == '__main__':
    sys.exit(main())

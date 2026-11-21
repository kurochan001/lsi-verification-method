#!/usr/bin/env python3
"""DPI-C reference model: the same C model inside Verilator and through files for Icarus."""
import importlib.util
import json
import math
from pathlib import Path
import random
import re
import sys

HERE = Path(__file__).resolve().parent


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


E = load('dpi_model_evidence', HERE.parent / 'local-exploration-common/evidence.py')
M = load('dpi_model_python', HERE / 'model.py')
P = E.P

NAME = 'local-dpi-model'
REQUIREMENTS = HERE / 'requirements.json'
RTL = HERE / 'rtl/packet_sum.sv'
MODEL_C = [HERE / 'model/packet_model.c', HERE / 'model/packet_model.h']
SOURCES = [Path(__file__), HERE / 'model.py', REQUIREMENTS, RTL, HERE / 'tb/dpi_tb.sv', HERE / 'tb/file_tb.sv',
           HERE / 'tb/dpi_probe_tb.sv', *MODEL_C, HERE / 'model/packet_dpi.c', HERE / 'model/packet_cli.c',
           HERE / 'model/probe_dpi.c']
CONFIGS = {'init-ffff': 0xFFFF, 'init-0000': 0x0000}
# RTL mutations and the checker that must report each one, in both routes.
MUTANTS = {1: 'SUM_CRC', 2: 'SUM_CRC', 3: 'SUM_LEN', 4: 'SUM_CRC', 5: 'SUM_DONE'}
# C model faults and what the comparison with the Python model must report.
MODEL_FAULTS = {
    1: ['MODEL_BLOCK', 'MODEL_CRC'],             # wrong polynomial in the table
    2: ['MODEL_COUNT', 'MODEL_CRC', 'MODEL_DONE', 'MODEL_LEN'],  # one state shared by all instances
    3: ['MODEL_LEN'],                            # reset keeps the byte count
    4: ['MODEL_BLOCK'],                          # block function drops the last byte
    5: ['MODEL_LEN'],                            # counts idle cycles, like RTL mutation 3
}
# Values the type probe must print. The two marked lines are properties of a 2-state
# simulator, not of the DPI: X and Z are gone before and after the call.
PROBE = {
    'byte': '127', 'shortint': '0', 'int': '2147483647', 'longint': '9000000000', 'real': '0.375',
    'bit': '123456783f',
    'logic_in_unknown': '0',      # 8'bxxzz_1010 arrives with bval == 0
    'logic_out': '00001111',      # bval 0xF0 written by C is dropped
    'string': '8', 'handle': '1234', 'open4': '10004', 'open6': '210006',
    'context_scope_length': str(len('dpi_probe_tb')), 'export_function': '10', 'export_task': '710',
}
IDLE = (0, '00000000', 0)
XIDLE = (0, 'xxxxxxxx', 0)
RESET = [0, *IDLE, *IDLE]


def packet(data, gaps=None, unknown_gaps=False):
    """One channel's cycles for a packet; gaps maps a byte index to idle cycles before it."""
    cycles = []
    for index, byte in enumerate(data):
        cycles += [XIDLE if unknown_gaps else IDLE] * (gaps or {}).get(index, 0)
        cycles.append((1, format(byte, '08b'), int(index == len(data) - 1)))
    return cycles


def partial(data):
    """The first bytes of a packet that does not end."""
    return [(1, format(byte, '08b'), 0) for byte in data]


def merge(first, second):
    length = max(len(first), len(second))
    first = list(first) + [IDLE] * (length - len(first))
    second = list(second) + [IDLE] * (length - len(second))
    return [[1, *a, *b] for a, b in zip(first, second)]


def directed():
    rows = [RESET, RESET]
    rows += merge(packet(M.DIGITS), [])                                   # one channel, known answer
    rows += merge([IDLE], packet([0xA5]))                                 # last on the first byte
    rows += merge(packet([1, 2, 3, 4, 5]) + packet([0xFF]) + packet([9, 8, 7, 6, 5, 4]),
                  packet([0x10, 0x20, 0x30, 0x40, 0x50, 0x60, 0x70], {2: 1, 5: 2}, unknown_gaps=True))
    rows += [[1, *IDLE, *IDLE], RESET]                                    # reset while idle
    rows += merge(partial([0xDE, 0xAD, 0xBE]), partial([0x55, 0xAA]))      # neither packet ends ...
    rows += [RESET]                                                       # ... before this reset
    rows += merge(packet([0x01, 0x02, 0x03, 0x04]), packet([0xF0, 0x0F, 0x33]))
    long_packet = packet(bytes((7 * i + 3) & 0xFF for i in range(260)))
    short = []
    for start in range(0, 240, 12):
        short += packet(bytes((start + k) & 0xFF for k in range(6)), {0: 2, 3: 1})
    rows += merge(short, long_packet)
    rows += [[1, *IDLE, *IDLE]] * 2
    return rows


def randomized(seed, packets):
    rng = random.Random(seed)
    channels = []
    for _ in range(2):
        cycles = []
        for _ in range(packets):
            data = bytes(rng.randrange(256) for _ in range(rng.choice((1, 1, 2, 3, 5, 8, 12))))
            gaps = {i: rng.randrange(3) for i in range(len(data)) if rng.random() < 0.3}
            cycles += packet(data, gaps, unknown_gaps=rng.random() < 0.5) + [IDLE] * rng.randrange(3)
        channels.append(cycles)
    rows = [RESET, RESET] + merge(*channels)
    for _ in range(max(1, packets // 8)):
        rows.insert(rng.randrange(3, len(rows)), RESET)
    return rows + [[1, *IDLE, *IDLE]] * 2


def unknown_on_valid():
    return [RESET, RESET, [1, 1, '0011x001', 1, *IDLE], [1, *IDLE, *IDLE]]


def single_channel():
    return [RESET, RESET] + merge(packet(M.DIGITS) + packet([1, 2, 3]), []) + [[1, *IDLE, *IDLE]] * 2


def goals(rows):
    """Stimulus properties that a passing run has exercised."""
    found = set()
    inside = [0, 0]          # bytes of the open packet per channel
    after_last = [False, False]
    alone = [True, True]
    data = [[], []]
    active = False
    for rst_n, *fields in rows:
        channel = [fields[0:3], fields[3:6]]
        if not rst_n:
            if any(inside):
                found.add('reset/mid-packet')
            elif active:
                found.add('reset/idle')
            inside = [0, 0]
            after_last = [False, False]
            alone = [True, True]
            data = [[], []]
            continue
        for c, (valid, text, last) in enumerate(channel):
            other = channel[1 - c][0]
            if not valid:
                if 'x' in text:
                    found.add('unknown/idle-data')
                if inside[c]:
                    found.add('stream/idle-gap')
                after_last[c] = False
                continue
            active = True
            if after_last[c]:
                found.add('stream/back-to-back')
            if other and inside[c] != inside[1 - c]:
                found.add('instances/interleaved')
            alone[c] = alone[c] and not other
            inside[c] += 1
            data[c].append(int(text.replace('x', '0'), 2))
            after_last[c] = bool(last)
            if last:
                if inside[c] == 1:
                    found.add('stream/single-byte')
                if inside[c] > 255:
                    found.add('stream/long-saturated')
                if bytes(data[c]) == M.DIGITS:
                    found.add('stream/known-answer')
                if alone[c]:
                    found.add('instances/one-active')
                inside[c] = 0
                alone[c] = True
                data[c] = []
    return found


def write_vectors(path, rows):
    path.write_text(''.join(' '.join(str(field) for field in row) + '\n' for row in rows))


def read_cli(expected_path, summary_path):
    outputs = []
    for line in expected_path.read_text().splitlines():
        fields = line.split()
        if len(fields) != 6:
            raise ValueError('MODEL_FORMAT: expected row')
        outputs.append((int(fields[0]), int(fields[1], 16), int(fields[2], 16),
                        int(fields[3]), int(fields[4], 16), int(fields[5], 16)))
    blocks, counts = [], None
    for line in summary_path.read_text().splitlines():
        fields = line.split()
        if fields[:1] == ['B'] and len(fields) == 4:
            blocks.append((int(fields[1]), int(fields[2]), int(fields[3], 16)))
        elif fields[:1] == ['COUNT'] and counts is None:
            counts = {key: int(value) for key, value in (field.split('=') for field in fields[1:])}
        else:
            raise ValueError('MODEL_FORMAT: summary row')
    if counts is None:
        raise ValueError('MODEL_FORMAT: counters missing')
    return outputs, blocks, counts


def cross(rows, init, cli):
    """Labels of every difference between the C model's files and the Python model."""
    outputs, blocks, counts = M.expected(rows, init)
    got_outputs, got_blocks, got_counts = cli
    labels = set()
    if len(outputs) != len(got_outputs):
        labels.add('MODEL_COUNT')
    for want, got in zip(outputs, got_outputs):
        for offset in (0, 3):
            if want[offset] != got[offset]:
                labels.add('MODEL_DONE')
            if want[offset + 1] != got[offset + 1]:
                labels.add('MODEL_CRC')
            if want[offset + 2] != got[offset + 2]:
                labels.add('MODEL_LEN')
    if [b[:2] for b in blocks] != [b[:2] for b in got_blocks]:
        labels.add('MODEL_COUNT')
    elif blocks != got_blocks:
        labels.add('MODEL_BLOCK')
    if counts != got_counts:
        labels.add('MODEL_COUNT')
    return sorted(labels)


def probe_values(log):
    pairs = re.findall(r'^PROBE (\w+)=(\S+)$', log, re.M)
    if len(pairs) != len(dict(pairs)):
        raise ValueError('PROBE: duplicate line')
    return dict(pairs)


def simulation_counts(log):
    pairs = re.findall(r'^COUNT (\w+)=(\d+)$', log, re.M)
    if len(pairs) != len(dict(pairs)):
        return None
    return {key: int(value) for key, value in pairs}


def catalog(path=REQUIREMENTS):
    data = json.loads(path.read_text())
    listed = [goal for item in data['requirements'] for goal in item['goals']]
    if not listed or len(set(listed)) != len(listed):
        raise ValueError('empty or duplicate goals')
    return data, set(listed)


def vector_sets(profile, seed):
    seeds = range(seed, seed + (3 if profile == 'nightly' else 1))
    sets = {'directed': directed()}
    for value in seeds:
        sets[f'random-seed{value}'] = randomized(value, 120 if profile == 'nightly' else 24)
    return sets


def plan_ids(configurations, vectors):
    ids = ['cli-build', 'probe-build', 'probe-types', 'known-answer']
    for name in configurations:
        ids += [f'{name}-dpi-build', f'{name}-file-build']
        for vector in vectors:
            ids += [f'{name}-{kind}-{vector}' for kind in ('cross', 'dpi', 'file', 'agree')]
        for mutation in MUTANTS:
            ids += [f'{name}-dpi-mutant-{mutation}', f'{name}-file-mutant-{mutation}']
        ids += [f'{name}-file-x-on-valid', f'{name}-dpi-x-blind']
    ids += [f'model-fault-{fault}-cross' for fault in MODEL_FAULTS]
    ids += ['model-fault-1-dpi-known-answer', 'model-fault-3-dpi-ambiguous', 'model-fault-2-single-channel-miss',
            'model-fault-5-common-mode-miss', 'requirements-and-coverage']
    return ids


class Run:
    def __init__(self, args, evidence):
        self.args = args
        self.e = evidence
        self.out = evidence.out
        self.cli = self.out / 'packet_cli'
        self.cli_ok = False
        self.records = []
        self.credited = set()

    def execute(self, command, log, timeout=None, cwd=None):
        return P.execute([str(part) for part in command], log, timeout or self.args.timeout, cwd or self.out)

    def credit(self, ok, *names):
        if ok:
            self.credited.update(names)
        return ok

    def record(self, name, ok, detail, **extra):
        self.records.append(dict(id=name, success=bool(ok), detail=detail, **extra))
        return self.e.check(name, ok, detail)

    def build_cli(self):
        build = self.execute([self.args.cc, '-std=c11', '-O1', '-Wall', '-Wextra', '-Werror', '-I', HERE / 'model',
                              '-o', self.cli, HERE / 'model/packet_cli.c', HERE / 'model/packet_model.c'],
                             self.out / 'cli-build.log', self.args.build_timeout)
        self.cli_ok = not build['error'] and build['returncode'] == 0
        return self.record('cli-build', self.cli_ok, build)

    def model_files(self, directory, rows, init, fault=0, instances=2):
        """Run the C model over a vector file. Returns (vectors, expected, parsed files)."""
        directory.mkdir(parents=True, exist_ok=True)
        vectors, expected, summary = directory / 'vectors.txt', directory / 'expected.txt', directory / 'model-summary.txt'
        write_vectors(vectors, rows)
        if not self.cli_ok:
            raise ValueError('MODEL_TOOL: model program was not built')
        run = self.execute([self.cli, init, fault, instances, vectors, expected, summary], directory / 'model.log')
        if run['error'] or run['returncode'] != 0:
            raise ValueError('MODEL_TOOL: model program failed')
        return vectors, expected, read_cli(expected, summary)

    def build_dpi(self, name, init):
        directory = self.out / f'{name}-dpi-obj'
        build = self.execute([self.args.verilator, '--binary', '--timing', '--trace', '-Wall', '-Wno-TIMESCALEMOD',
                              '-j', self.args.jobs, '--Mdir', directory, '--top-module', 'dpi_tb', f'-GINIT={init}',
                              '-CFLAGS', f'-I{HERE / "model"}', RTL, HERE / 'tb/dpi_tb.sv',
                              HERE / 'model/packet_model.c', HERE / 'model/packet_dpi.c'],
                             self.out / f'{name}-dpi-build.log', self.args.build_timeout)
        ok = not build['error'] and build['returncode'] == 0 and (directory / 'Vdpi_tb').is_file()
        self.record(f'{name}-dpi-build', ok, build)
        return directory / 'Vdpi_tb' if ok else None

    def build_file(self, name, init, mutation):
        binary = self.out / f'{name}-file-m{mutation}.vvp'
        build = self.execute([self.args.iverilog, '-g2012', '-s', 'file_tb', f'-Pfile_tb.INIT={init}',
                              f'-Pfile_tb.MUTATION={mutation}', '-o', binary, RTL, HERE / 'tb/file_tb.sv'],
                             self.out / f'{name}-file-m{mutation}-build.log')
        return binary if not build['error'] and build['returncode'] == 0 else None

    def simulate(self, route, binary, directory, rows, vectors, expected=None, mutation=0, fault=0, label=None, wave=True):
        directory.mkdir(parents=True, exist_ok=True)
        observed = directory / f'{route}-observed.txt'
        log = directory / f'{route}-simulation.log'
        waveform = directory / f'{route}-wave.vcd'
        if binary is None:
            log.write_text('build failed\n')
            execution = dict(returncode=None, error='build failed', seconds=0)
        elif route == 'dpi':
            execution = self.execute([binary, f'+VECTORS={vectors}', f'+OBSERVED={observed}', f'+MUTATION={mutation}',
                                      f'+MODEL_FAULT={fault}', *([f'+WAVE={waveform}'] if wave else [])], log, cwd=directory)
        else:
            execution = self.execute([self.args.vvp, binary, f'+VECTORS={vectors}', f'+EXPECTED={expected}',
                                      f'+OBSERVED={observed}', *([f'+WAVE={waveform}'] if wave else [])], log, cwd=directory)
        text = log.read_text(errors='replace')
        status, message = P.classify(dict(checks=len(rows), expected_failure=label), execution, text)
        counts = simulation_counts(text)
        if status == 'pass':
            want = M.expected(rows, 0)[2]
            need = {key: want[key] for key in ('packets0', 'packets1')}
            if route == 'dpi':
                need['noted'] = want['packets0'] + want['packets1']
            if counts != need:
                status, message = 'error', 'count evidence differs'
            elif wave and (not waveform.is_file() or '$enddefinitions' not in waveform.read_text(errors='replace')):
                status, message = 'error', 'waveform missing'
        result = dict(route=route, status=status, message=message, mutation=mutation, model_fault=fault,
                      expected_failure=label, checks=len(rows), counts=counts, observed=str(observed), **execution)
        P.write_json(directory / f'{route}-result.json', result)
        return result

    def probe(self):
        directory = self.out / 'probe-obj'
        build = self.execute([self.args.verilator, '--binary', '--timing', '-Wall', '-j', self.args.jobs, '--Mdir', directory,
                              '--top-module', 'dpi_probe_tb', HERE / 'tb/dpi_probe_tb.sv', HERE / 'model/probe_dpi.c'],
                             self.out / 'probe-build.log', self.args.build_timeout)
        built = not build['error'] and build['returncode'] == 0
        self.record('probe-build', built, build)
        values, message = {}, 'build failed'
        if built:
            run = self.execute([directory / 'Vdpi_probe_tb'], self.out / 'probe.log')
            text = (self.out / 'probe.log').read_text(errors='replace')
            try:
                values = probe_values(text)
                message = 'type mapping as pinned'
                if run['error'] or run['returncode'] != 0 or 'RESULT PASS checks=15' not in text:
                    message = 'probe did not complete'
                elif values != PROBE:
                    message = 'probe values differ: ' + json.dumps({k: values.get(k) for k in PROBE if values.get(k) != PROBE[k]})
            except ValueError as exc:
                message = str(exc)
        ok = message == 'type mapping as pinned'
        self.record('probe-types', ok, message, values=values)
        self.credit(ok, 'types/two-state', 'types/four-state', 'types/string-and-handle', 'types/open-array-ranges',
                    'types/context-and-export')

    def known_answer(self):
        rows = [RESET, RESET] + merge(packet(M.DIGITS), packet(M.DIGITS)) + [[1, *IDLE, *IDLE]]
        ok, detail = True, {}
        for init, value in M.KNOWN.items():
            try:
                if M.block(M.DIGITS, init) != value:
                    raise ValueError('Python model differs from the published value')
                _, _, (outputs, blocks, _) = self.model_files(self.out / f'known-{init:04x}', rows, init)
                if blocks != [(0, 9, value), (1, 9, value)] or outputs[-1][1] != value or outputs[-1][4] != value:
                    raise ValueError('C model differs from the published value')
                detail[f'{init:04x}'] = f'{value:04x}'
            except (OSError, ValueError, KeyError, IndexError) as exc:
                ok, detail[f'{init:04x}'] = False, str(exc)
        self.record('known-answer', ok, detail)
        self.credit(ok, 'model/known-answer')

    def configuration(self, name, init, vectors):
        dpi = self.build_dpi(name, init)
        files = {mutation: self.build_file(name, init, mutation) for mutation in [0, *MUTANTS]}
        self.record(f'{name}-file-build', all(files.values()), {str(k): str(v) for k, v in files.items()})
        clean = True
        directed_inputs = None
        for vector, rows in vectors.items():
            directory = self.out / f'{name}-{vector}'
            try:
                paths = self.model_files(directory, rows, init)
                labels = cross(rows, init, paths[2])
                agreed = not labels
                detail = 'C and Python models agree' if agreed else 'differences: ' + ', '.join(labels)
            except (OSError, ValueError, KeyError, IndexError) as exc:
                paths, agreed, detail = None, False, str(exc)
                write_vectors(directory / 'vectors.txt', rows)
            self.record(f'{name}-cross-{vector}', agreed, detail)
            vectors_path = directory / 'vectors.txt'
            expected_path = paths[1] if paths else directory / 'missing-expected.txt'
            a = self.simulate('dpi', dpi, directory, rows, vectors_path)
            b = self.simulate('file', files[0], directory, rows, vectors_path, expected_path)
            self.record(f'{name}-dpi-{vector}', a['status'] == 'pass', a['message'], result=a)
            self.record(f'{name}-file-{vector}', b['status'] == 'pass', b['message'], result=b)
            same = a['status'] == b['status'] == 'pass' and Path(a['observed']).read_text() == Path(b['observed']).read_text()
            self.record(f'{name}-agree-{vector}', same, 'both routes observed the same outputs on every clock' if same
                        else 'routes differ or one did not pass')
            good = agreed and same
            clean = clean and good
            self.credit(good, *goals(rows), 'model/independent-cross-check', 'route/observed-identical')
            if vector == 'directed':
                directed_inputs = (rows, vectors_path, expected_path)
                self.credit(a['status'] == 'pass', 'dpi/pure-import', 'dpi/context-import-and-export',
                            'dpi/open-array', 'dpi/handle-per-instance')
        rows, vectors_path, expected_path = directed_inputs
        detected = True
        for mutation, label in MUTANTS.items():
            directory = self.out / f'{name}-mutant-{mutation}'
            a = self.simulate('dpi', dpi, directory, rows, vectors_path, mutation=mutation, label=label, wave=False)
            b = self.simulate('file', files[mutation], directory, rows, vectors_path, expected_path, mutation=mutation,
                              label=label, wave=False)
            self.record(f'{name}-dpi-mutant-{mutation}', a['status'] == 'detected', a['message'], result=a)
            self.record(f'{name}-file-mutant-{mutation}', b['status'] == 'detected', b['message'], result=b)
            detected = detected and a['status'] == b['status'] == 'detected'
        self.credit(detected, 'route/same-detections')
        # Unknown data with valid high: the 4-state route reports it, the 2-state route cannot.
        rows = unknown_on_valid()
        directory = self.out / f'{name}-x-on-valid'
        try:
            vectors_path, expected_path, parsed = self.model_files(directory, rows, init)
            counted = parsed[2]['unknown_valid'] == 1
        except (OSError, ValueError, KeyError, IndexError):
            vectors_path, expected_path, counted = directory / 'vectors.txt', directory / 'missing-expected.txt', False
        b = self.simulate('file', files[0], directory, rows, vectors_path, expected_path, label='SUM_X_INPUT', wave=False)
        ok = b['status'] == 'detected' and counted
        self.record(f'{name}-file-x-on-valid', ok, b['message'], result=b)
        self.credit(ok, 'unknown/valid-flagged-by-file-route')
        a = self.simulate('dpi', dpi, directory, rows, vectors_path, wave=False)
        blind = a['status'] == 'pass'
        self.record(f'{name}-dpi-x-blind', blind, 'the 2-state simulator passed the same stimulus: no unknown bit reached C'
                    if blind else 'pinned tool behaviour changed: review the X policy. ' + a['message'], result=a)
        self.credit(blind, 'unknown/invisible-to-dpi-route')
        return dpi, clean

    def model_faults(self, name, init, dpi, rows):
        found = True
        for fault, want in MODEL_FAULTS.items():
            directory = self.out / f'model-fault-{fault}'
            try:
                labels = cross(rows, init, self.model_files(directory, rows, init, fault)[2])
                detail = 'reported: ' + ', '.join(labels)
            except (OSError, ValueError, KeyError, IndexError) as exc:
                labels, detail = None, str(exc)
            ok = labels == want
            found = found and ok
            self.record(f'model-fault-{fault}-cross', ok, detail if ok else f'{detail}; expected {want}')
        self.credit(found, 'model/faults-detected')
        def with_fault(fault, mutation=0, label=None):
            directory = self.out / f'model-fault-{fault}-dpi'
            directory.mkdir()
            write_vectors(directory / 'vectors.txt', rows)
            return self.simulate('dpi', dpi, directory, rows, directory / 'vectors.txt', mutation=mutation, fault=fault,
                                 label=label, wave=False)
        # The published check value, evaluated inside the simulation, stops a wrong polynomial at once.
        a = with_fault(1, label='SUM_KNOWN')
        ok = a['status'] == 'detected'
        self.record('model-fault-1-dpi-known-answer', ok, a['message'], result=a)
        self.credit(ok, 'model/known-answer-in-simulation')
        # Without such an anchor a wrong model looks exactly like a wrong design.
        a = with_fault(3, label=MUTANTS[3])
        ok = a['status'] == 'detected'
        self.record('model-fault-3-dpi-ambiguous', ok, 'correct RTL fails with the label of RTL mutation 3' if ok else a['message'], result=a)
        self.credit(ok, 'model/wrong-model-looks-like-wrong-design')
        # One instance cannot show that two instances share their state.
        single = single_channel()
        try:
            labels = cross(single, init, self.model_files(self.out / 'model-fault-2-single', single, init, 2, instances=1)[2])
            both = cross(rows, init, self.model_files(self.out / 'model-fault-2-both', rows, init, 2)[2])
            ok, detail = labels == [] and both == MODEL_FAULTS[2], dict(single_channel=labels, two_channels=both)
        except (OSError, ValueError, KeyError, IndexError) as exc:
            ok, detail = False, str(exc)
        self.record('model-fault-2-single-channel-miss', ok, detail)
        self.credit(ok, 'model/single-instance-miss')
        # The same mistake on both sides passes; only the independent model objects.
        a = with_fault(5, mutation=3)
        ok = a['status'] == 'pass'
        self.record('model-fault-5-common-mode-miss', ok, 'RTL mutation 3 and model fault 5 agree with each other'
                    if ok else a['message'], result=a)
        self.credit(ok, 'model/common-mode-miss')


def run(args):
    configurations = CONFIGS if args.configuration == 'all' else {args.configuration: CONFIGS[args.configuration]}
    vectors = vector_sets(args.profile, args.seed)
    requirements, required = catalog()
    plan = dict(configurations=configurations, vectors={name: len(rows) for name, rows in vectors.items()},
                mutants=MUTANTS, model_faults=MODEL_FAULTS, requirements_revision=requirements['revision'])
    evidence = E.Evidence(NAME, args, SOURCES, plan, plan_ids(configurations, vectors))
    P.write_json(evidence.out / 'tools.json', {name: P.execute([tool, flag], evidence.out / f'{name}-version.log', args.timeout, evidence.out)
                 for name, tool, flag in (('verilator', args.verilator, '--version'), ('iverilog', args.iverilog, '-V'),
                                          ('vvp', args.vvp, '-V'), ('cc', args.cc, '--version'))})
    r = Run(args, evidence)
    r.build_cli()
    r.probe()
    r.known_answer()
    first = None
    for name, init in configurations.items():
        dpi, _ = r.configuration(name, init, vectors)
        if first is None:
            first = (name, init, dpi)
    r.model_faults(*first, vectors['directed'])
    missing = sorted(required - r.credited)
    unknown = sorted(r.credited - required)
    evidence.check('requirements-and-coverage', not missing and not unknown,
                   dict(goals=len(required), reached=len(required & r.credited), missing=missing, unlisted=unknown))
    P.write_json(evidence.out / 'executions.json', r.records)
    P.write_json(evidence.out / 'coverage.json', dict(goals=sorted(required), reached=sorted(r.credited)))
    return evidence.finish()


def main():
    p = E.parser(__doc__, NAME)
    p.add_argument('--configuration', choices=['all', *CONFIGS], default='all')
    p.add_argument('--verilator', default='verilator')
    p.add_argument('--cc', default='cc')
    p.add_argument('--jobs', type=int, default=4)
    p.add_argument('--build-timeout', type=float, default=300)
    args = p.parse_args()
    E.validate(p, args)
    if args.jobs < 1 or not math.isfinite(args.build_timeout) or args.build_timeout <= 0:
        p.error('positive jobs/build timeout required')
    try:
        return run(args)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print('RUNNER_ERROR', exc, file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())

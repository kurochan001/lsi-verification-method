#!/usr/bin/env python3
"""One bench on the RTL and on its synthesized netlist: four mutants that only the netlist exposes."""
import importlib.util
from pathlib import Path
import random
import shutil
import subprocess
import sys

HERE = Path(__file__).resolve().parent
NAME = 'local-gate-sim'
TOP = 'arbiter_tb'
CONFIGS = {'rtl': {'GATE': 0}, 'gate': {'GATE': 1}}
ITERATIONS = {'smoke': 400, 'nightly': 4000}
RTL = HERE / 'rtl/burst_arbiter.sv'
SOURCES = [RTL, HERE / 'tb/arbiter_tb.sv']
LABELS = {1: 'ARB_X', 2: 'ARB_DATA', 3: 'ARB_X', 4: 'ARB_DATA'}
# Generic gates, then only plain D flip-flops: synchronous resets become logic in front of
# them, as with a cell library without reset flops. Initial values are removed, as ASIC
# flip-flops have none.
SYNTHESIS = ('read_verilog -sv burst_arbiter.sv; chparam -set MUTATION {m} burst_arbiter; '
             'synth -top burst_arbiter -flatten; setattr -unset init w:*; dfflegalize -cell $_DFF_P_ x; '
             'opt_clean; stat; write_verilog -noattr -noexpr netlist.v')


def add_arguments(parser):
    parser.add_argument('--yosys', default='yowasp-yosys')
    parser.add_argument('--cell-library', type=Path, help="Yosys simcells.v; found from the Yosys installation by default")


def cell_library(args):
    if args.cell_library:
        return args.cell_library.resolve()
    found = importlib.util.find_spec('yowasp_yosys')
    if found and found.origin:
        return Path(found.origin).parent / 'share/simcells.v'
    try:
        datdir = subprocess.run(['yosys-config', '--datdir'], capture_output=True, text=True, timeout=30).stdout.strip()
    except OSError:
        datdir = ''
    return Path(datdir) / 'simcells.v'


def build_sources(args, configuration, parameters, mutation, directory):
    """RTL as written, or a netlist that Yosys synthesizes with this mutation fixed."""
    if not parameters['GATE']:
        return SOURCES, dict(command=[], returncode=0, error=None, seconds=0)
    directory.mkdir()
    shutil.copy2(RTL, directory / RTL.name)
    library = cell_library(args)
    execution = PROCESS.execute([args.yosys, '-q', '-l', 'synthesis.log', '-p', SYNTHESIS.format(m=mutation)],
                                directory / 'yosys-console.log', args.timeout * 6, directory)
    if not execution['error'] and not library.is_file():
        execution['error'] = f'cell library not found: {library}; pass --cell-library'
    return [directory / 'netlist.v', library, SOURCES[1]], execution


def lowest(req):
    return (req & -req).bit_length() - 1


class Model:
    """Cycle model of the specification: outputs during a cycle, then the state after its edge."""

    def __init__(self):
        self.reset()

    def reset(self):
        self.state, self.beat, self.valid, self.last, self.id, self.bursts = 'idle', 0, 0, 0, 0, 0

    def step(self, rst_n, req):
        outputs = [self.valid, self.last, self.id, self.bursts]
        if not rst_n:
            self.reset()
        elif self.state == 'idle' and req:
            self.state, self.beat, self.valid, self.id = 'burst', 0, 1, lowest(req)
        elif self.state == 'burst':
            self.last = int(self.beat == 2)
            if self.beat == 3:
                self.state, self.valid, self.bursts = 'gap', 0, (self.bursts + 1) % 256
            self.beat = (self.beat + 1) % 4
        elif self.state == 'gap':
            self.state = 'idle'
        return outputs


class Plan:
    def __init__(self):
        self.model, self.rows = Model(), []

    def cycle(self, req=0, rst_n=1, count=1):
        for _ in range(count):
            self.rows.append([rst_n, req, *self.model.step(rst_n, req)])

    def burst(self, req):
        """Hold req until its burst has started, then drop it until the arbiter is idle again."""
        while not self.model.valid:
            self.cycle(req)
        while self.model.state != 'idle':
            self.cycle(0)


def boundary_vectors():
    p = Plan()
    p.cycle(rst_n=0, count=3)
    p.cycle(0, count=4)                                   # idle without requests
    for req in (0b0001, 0b0010, 0b0100, 0b1000):          # each requester alone
        p.burst(req)
    for req in (0b0011, 0b0110, 0b1001, 0b1100, 0b1111):  # conflicts, lowest index wins
        p.burst(req)
    p.cycle(0b1010, count=14)                             # held request: back-to-back bursts
    while p.model.state != 'gap':
        p.cycle(0b1000)
    p.cycle(0b1000)                                       # request changes between the gap
    p.cycle(0b0001, count=2)                              # and the arbitration cycle
    while p.model.state != 'idle':
        p.cycle(0)
    rng = random.Random(1)
    while p.model.bursts != 4:                            # through the counter wrap
        p.cycle(rng.randrange(1, 16))
    while not (p.model.valid and p.model.beat == 2):
        p.cycle(0b0100)
    p.cycle(0b0100, rst_n=0, count=2)                     # reset in the middle of a burst
    p.cycle(0b0100, count=8)
    return p.rows


def random_vectors(seed, cycles):
    rng = random.Random(seed)
    p = Plan()
    p.cycle(rst_n=0, count=2)
    while len(p.rows) < cycles:
        roll = rng.random()
        req = 0 if roll < 0.25 else rng.choice((1, 2, 4, 8)) if roll < 0.5 else rng.randrange(1, 16)
        p.cycle(req, rst_n=int(rng.random() > 0.01), count=rng.randrange(1, 4))
    return p.rows


def counts(rows):
    started = completed = previous = 0
    for row in rows:
        started += bool(row[0] and row[2] and not previous)
        completed += bool(row[0] and row[3])
        previous = row[2]
    return dict(bursts=started, completed=completed)


def make_cases(args, parameters):
    base = boundary_vectors()
    cases = [dict(id='boundaries', vectors=base, mutation=args.demo_bug, category='functional',
                  expected_failure=None)]
    for seed in range(args.seed, args.seed + (3 if args.profile == 'nightly' else 1)):
        cases.append(dict(id=f'random-seed{seed}', vectors=random_vectors(seed, args.iterations),
                          mutation=args.demo_bug, category='functional', expected_failure=None))
    for mutation in range(1, 5):
        if parameters['GATE']:
            cases.append(dict(id=f'detect-mutation{mutation}', vectors=base, mutation=mutation,
                              category='mutation', expected_failure=LABELS[mutation]))
        else:  # the same mutant passes in RTL simulation
            cases.append(dict(id=f'invisible-mutation{mutation}', vectors=base, mutation=mutation,
                              category='diagnostic', expected_failure=None))
    for case in cases:
        case['counts'] = counts(case['vectors'])
    return cases


spec = importlib.util.spec_from_file_location('local_runner', HERE.parent / 'local-common/runner.py')
RUNNER = importlib.util.module_from_spec(spec)
spec.loader.exec_module(RUNNER)
PROCESS = RUNNER.PROCESS

if __name__ == '__main__':
    sys.exit(RUNNER.main(sys.modules[__name__]))

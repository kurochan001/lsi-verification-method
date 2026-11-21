#!/usr/bin/env python3
"""A synthesizable self-checking test bench: LFSR stimulus, MISR signature, one pass bit, on the
RTL and on the netlist that Yosys synthesizes from the same code."""
import importlib.util
from pathlib import Path
import random
import re
import shutil
import subprocess
import sys

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('selftest_model', HERE / 'model.py')
M = importlib.util.module_from_spec(spec)
spec.loader.exec_module(M)

NAME = 'local-synth-testbench'
TOP = 'selftest_tb'
RTL = [HERE / 'rtl/alu_unit.sv', HERE / 'rtl/selftest_harness.sv']
SOURCES = [*RTL, HERE / 'tb/selftest_tb.sv']
EXTRA_INPUTS = [HERE / 'model.py']
SHAPES = {'rtl-p64': (0, 64, 0xace1), 'netlist-p40': (1, 40, 0x1d2b)}
CONFIGS = {name: dict(NETLIST=netlist, PATTERNS=patterns, SEED=seed, GOLDEN=M.golden(seed, patterns))
           for name, (netlist, patterns, seed) in SHAPES.items()}
ITERATIONS = {'smoke': 4, 'nightly': 12}
MUTANTS = 7
LABELS = {1: 'ST_RESPONSE', 2: 'ST_RESPONSE', 3: 'ST_RESPONSE', 4: 'ST_STIMULUS', 5: 'ST_SIGNATURE',
          6: 'ST_DONE', 7: 'ST_PASS'}
# Generic gates and plain D flip-flops only; the synchronous reset becomes logic in front of them.
SYNTHESIS = ('read_verilog -sv alu_unit.sv selftest_harness.sv; '
             'chparam -set PATTERNS {patterns} -set SEED {seed} -set GOLDEN {golden} -set MUTATION {m} selftest_harness; '
             'synth -top selftest_harness -flatten; setattr -unset init w:*; dfflegalize -cell $_DFF_P_ x; '
             'opt_clean; tee -o stat.txt stat; write_verilog -noattr -noexpr netlist.v')


def flip_flops(patterns):
    """Every register the self-test needs: LFSR, signature, ALU result, pattern counter and the
    four control bits. Losing any of them means synthesis removed part of the bench."""
    return 16 + 16 + 9 + (patterns).bit_length() + 4


def structure(stat_text, patterns):
    """Flip-flop count from `stat`, and whether it is exactly the registers of the design."""
    found = re.findall(r'^\s+(\d+)\s+\$_DFF_P_\s*$', stat_text, re.M) or \
        [m[1] for m in re.finditer(r'^\s+\$_DFF_P_\s+(\d+)\s*$', stat_text, re.M)]
    count = int(found[-1]) if found else 0
    return count, count == flip_flops(patterns)


def add_arguments(parser):
    parser.add_argument('--yosys', default='yowasp-yosys')
    parser.add_argument('--cell-library', type=Path, help="Yosys simcells.v; found from the Yosys installation by default")


def cell_library(args):
    """simcells.v of the Yosys that synthesizes, unless --cell-library names one."""
    if args.cell_library:
        return args.cell_library.resolve()
    executable = shutil.which(args.yosys)
    if Path(args.yosys).name.startswith('yowasp-'):
        found = importlib.util.find_spec('yowasp_yosys')
        candidates = [Path(found.origin).parent / 'share/simcells.v'] if found and found.origin else []
        if executable:
            candidates += sorted(Path(executable).resolve().parent.parent.glob('lib/python*/site-packages/yowasp_yosys/share/simcells.v'))
        return next((c for c in candidates if c.is_file()), Path('simcells.v'))
    config = Path(executable).with_name('yosys-config') if executable else None
    try:
        command = [str(config) if config and config.exists() else 'yosys-config', '--datdir']
        datdir = subprocess.run(command, capture_output=True, text=True, timeout=30).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        datdir = ''
    return Path(datdir or '.') / 'simcells.v'


def build_sources(args, configuration, parameters, mutation, directory):
    """The RTL as written, or the netlist synthesized from it with this mutation fixed."""
    if not parameters['NETLIST']:
        return SOURCES, dict(command=[], returncode=0, error=None, seconds=0)
    process = sys.modules['local_runner'].PROCESS
    directory.mkdir()
    for source in RTL:
        shutil.copy2(source, directory / source.name)
    library = cell_library(args)
    script = SYNTHESIS.format(patterns=parameters['PATTERNS'], seed=parameters['SEED'],
                              golden=parameters['GOLDEN'], m=mutation)
    execution = process.execute([args.yosys, '-q', '-l', 'synthesis.log', '-p', script],
                                directory / 'yosys-console.log', args.timeout * 6, directory)
    execution.update(log=f'{directory.name}/yosys-console.log', cell_library=str(library))
    if not execution['error'] and execution['returncode'] == 0:
        stat = (directory / 'stat.txt').read_text(errors='replace') if (directory / 'stat.txt').is_file() else ''
        count, kept = structure(stat, parameters['PATTERNS'])
        execution.update(flip_flops=count, expected_flip_flops=flip_flops(parameters['PATTERNS']))
        if not kept:
            execution['error'] = f'synthesized structure lost: {count} flip-flops, expected {flip_flops(parameters["PATTERNS"])}'
    if not execution['error'] and not library.is_file():
        execution['error'] = f'cell library not found: {library}; pass --cell-library'
    return [directory / 'netlist.v', library, SOURCES[-1]], execution


def new_bench(parameters):
    return M.Bench(parameters['SEED'], parameters['PATTERNS'], parameters['GOLDEN'])


def single_fault(patterns):
    return {patterns // 3: 0x004}


def alias_faults(patterns):
    first = 0x0a5
    k = patterns // 2
    return {k: first, k + 1: M.cancelling_fault(first)}


def scenario_rows(parameters):
    """Every goal on purpose: clean runs in the full view, restart, start held while busy, reset
    in a run and after it, then the chip view with a clean run, one wrong response and two."""
    p = parameters['PATTERNS']
    b = new_bench(parameters)
    b.reset(2)
    b.idle(2)
    b.view = 1
    b.run(ignored_start_at=(0, 1, p // 2, p))       # start stays high in busy rows: ignored
    b.cycle(start=1)                                # restart from done
    for _ in range(p // 2):
        b.cycle()
    b.reset()                                       # reset in the middle of a run
    b.idle(1)
    b.run()
    b.reset()                                       # reset after done
    b.idle(1)
    b.view = 0
    b.run()
    b.run(faults=single_fault(p))                   # one wrong response: pass must drop
    b.run(faults={1: 0x100, p - 1: 0x001})          # two unrelated wrong responses
    b.view = 1
    b.run()
    return b.rows


def chip_rows(parameters):
    """Only what a board shows: two clean runs and a restart."""
    b = new_bench(parameters)
    b.reset(2)
    b.view = 0
    b.run()
    b.run()
    return b.rows


def alias_rows(parameters, view):
    """Two wrong responses whose differences cancel in the signature."""
    b = new_bench(parameters)
    b.reset(2)
    b.view = view
    b.run(faults=alias_faults(parameters['PATTERNS']))
    return b.rows


def random_rows(seed, iterations, parameters):
    rng = random.Random(seed)
    p = parameters['PATTERNS']
    b = new_bench(parameters)
    b.reset(2)
    for _ in range(iterations):
        kind = rng.randrange(6)
        if kind == 0:
            b.view = 1
            b.run(ignored_start_at=tuple(rng.sample(range(p + 1), 3)), tail=rng.randrange(1, 4))
        elif kind == 1:
            b.cycle(start=1)
            for _ in range(rng.randrange(1, p)):
                b.cycle(start=rng.randrange(2))
            b.reset(rng.randrange(1, 3))
        elif kind < 4:
            b.view = 0
            faults = {rng.randrange(p): rng.randrange(1, 1 << 9) for _ in range(rng.randrange(1, 4))}
            b.run(faults=faults, tail=rng.randrange(1, 3))
        else:
            b.view = rng.randrange(2)
            b.run(tail=rng.randrange(1, 3))
    b.idle(1)
    return b.rows


def counts(rows):
    runs = passes = 0
    previous = None
    for row in rows:
        if not row[0]:
            continue
        if previous is not None and row[6] and not previous[6] and previous[5]:
            runs += 1
            passes += row[7]
        previous = row
    return dict(runs=runs, passes=passes)


def make_cases(args, parameters):
    scenario = scenario_rows(parameters)
    cases = [dict(id='scenario', vectors=scenario, mutation=args.demo_bug, category='functional', expected_failure=None)]
    for seed in range(args.seed, args.seed + (3 if args.profile == 'nightly' else 1)):
        cases.append(dict(id=f'random-seed{seed}', vectors=random_rows(seed, args.iterations, parameters),
                          mutation=args.demo_bug, category='functional', expected_failure=None))
    for mutation in range(1, MUTANTS + 1):
        cases.append(dict(id=f'detect-mutation{mutation}', vectors=scenario, mutation=mutation,
                          category='mutation', expected_failure=LABELS[mutation]))
    # The chip view sees a wrong ALU only through the signature, as pass=0 at done.
    cases.append(dict(id='detect-mutation1-chip-view', vectors=chip_rows(parameters), mutation=1,
                      category='mutation', expected_failure='ST_PASS'))
    # Two wrong responses that cancel: the full view sees them, the chip view passes.
    cases.append(dict(id='detect-aliasing-full-view', vectors=alias_rows(parameters, 1), mutation=0,
                      category='mutation', expected_failure='ST_RESPONSE'))
    cases.append(dict(id='survive-aliasing-chip-view', vectors=alias_rows(parameters, 0), mutation=0,
                      category='diagnostic', expected_failure=None))
    for case in cases:
        case['counts'] = counts(case['vectors'])
    return cases


if __name__ == '__main__':
    spec = importlib.util.spec_from_file_location('local_runner', HERE.parent / 'local-common/runner.py')
    runner = importlib.util.module_from_spec(spec)
    sys.modules['local_runner'] = runner
    spec.loader.exec_module(runner)
    sys.exit(runner.main(sys.modules[__name__]))

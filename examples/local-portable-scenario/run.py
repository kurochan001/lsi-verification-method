#!/usr/bin/env python3
"""Portable scenarios: one scenario model (actions, resources, constraints) generates both a
block-level realization against the DMA alone and an RV32I program for the CPU of a small SoC;
both runs of a scenario are compared with the same expected record and memory."""
import importlib.util
from pathlib import Path
import random
import sys

HERE = Path(__file__).resolve().parent
NAME = 'local-portable-scenario'
TOP = 'portable_tb'
spec = importlib.util.spec_from_file_location('portable_scenario_model', HERE / 'scenario.py')
MODEL = importlib.util.module_from_spec(spec)
spec.loader.exec_module(MODEL)
CONFIGS = {'wait0': dict(WAIT=0), 'wait2': dict(WAIT=2)}
ITERATIONS = {'smoke': 2, 'nightly': 4}   # random scenarios per seed, each run in both realizations
SOURCES = [HERE.parent / 'local-riscv-decoder/rtl/rv32i_decoder.sv', HERE.parent / 'local-riscv-iss/rtl/rv32i_core.sv',
           HERE / 'rtl/scn_dma.sv', HERE / 'rtl/scn_soc.sv', HERE / 'tb/portable_tb.sv']
EXTRA_INPUTS = [HERE / 'scenario.py', HERE.parent / 'local-riscv-iss/iss.py']
MUTANTS = 6
BLOCK, SOC = MODEL.BLOCK, MODEL.SOC
# Mutation -> (scenario, realizations that must detect it, label). 5 and 6 are integration
# errors of the SoC: the block realization of the same scenario passes, and is run as a diagnostic.
DETECTS = {1: ('basic', (BLOCK, SOC), 'SCN_RESULT'),          # one word short
           2: ('errors', (BLOCK, SOC), 'SCN_RESULT'),         # the end of the destination not checked
           3: ('both-pending', (BLOCK, SOC), 'SCN_RESULT'),   # an acknowledge clears every pending bit
           4: ('basic', (BLOCK, SOC), 'SCN_RESULT'),          # channel 1 reads from its destination
           5: ('contention', (SOC,), 'SCN_RESULT'),           # the DMA passes while the CPU holds the RAM
           6: ('basic', (SOC,), 'SCN_RESULT')}                # channel 1 window decoded onto channel 0
MODE_NAME = {BLOCK: 'block', SOC: 'soc'}


def case(name, actions, mode, mutation=0, label=None, category='functional', stall=False):
    rows, counts = MODEL.rows(actions, mode, stall)
    return dict(id=f'{MODE_NAME[mode]}-{name}', vectors=rows, mutation=mutation, expected_failure=label,
                category=category, counts=counts, scenario=name)


def scenarios(args):
    named = MODEL.directed()
    for seed in range(args.seed, args.seed + (3 if args.profile == 'nightly' else 1)):
        draw = random.Random(seed)
        for k in range(args.iterations):
            named[f'random-seed{seed}-{k}'] = MODEL.generate(draw.getrandbits(32))
    for name, actions in named.items():
        MODEL.check(actions)   # a generated scenario that breaks a rule stops the plan
    return named


def make_cases(args, parameters):
    named = scenarios(args)
    cases = []
    for name, actions in named.items():
        for mode in (BLOCK, SOC):
            # The block memory refuses every third clock in the contention scenario and in half of the random ones.
            stall = name == 'contention' or (name.startswith('random') and name.endswith(('0', '2')))
            cases.append(case(name, actions, mode, args.demo_bug, stall=stall))
    for mutation, (name, modes, label) in DETECTS.items():
        for mode in modes:
            cases.append(case(f'detect-mutation{mutation}-{name}', named[name], mode, mutation, label, 'mutation'))
        if modes == (SOC,):
            cases.append(case(f'survive-mutation{mutation}-{name}', named[name], BLOCK, mutation, None, 'diagnostic'))
    return cases


if __name__ == '__main__':
    spec = importlib.util.spec_from_file_location('local_runner', HERE.parent / 'local-common/runner.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    sys.exit(module.main(sys.modules[__name__]))

#!/usr/bin/env python3
"""Secure boot: the ROM starts a hardware check of the flash image (magic, length, version,
SHA-256 digest against OTP) and jumps to it only on PASS; fetches, keys, the secure lifecycle
registers and debug are opened by hardware on PASS alone."""
import importlib.util
from pathlib import Path
import random
import sys

HERE = Path(__file__).resolve().parent
NAME = 'local-secure-boot'
TOP = 'secure_boot_tb'
spec = importlib.util.spec_from_file_location('secure_boot_model', HERE / 'model.py')
MODEL = importlib.util.module_from_spec(spec)
spec.loader.exec_module(MODEL)
CONFIGS = {'max112-wait0': dict(IMG_MAX=112, WAIT=0), 'max80-wait2': dict(IMG_MAX=80, WAIT=2)}
ITERATIONS = {'smoke': 2, 'nightly': 4}  # random boots per seed
SOURCES = [HERE.parent / 'local-riscv-decoder/rtl/rv32i_decoder.sv', HERE.parent / 'local-riscv-iss/rtl/rv32i_core.sv',
           HERE.parent / 'local-sha256/rtl/sha256_engine.sv', HERE.parent / 'local-secure-lifecycle/rtl/secure_lifecycle.sv',
           HERE / 'rtl/boot_ctrl.sv', HERE / 'rtl/secure_boot_soc.sv', HERE / 'tb/secure_boot_tb.sv']
EXTRA_INPUTS = [HERE / 'model.py', HERE.parent / 'local-riscv-iss/iss.py']
MUTANTS = 9
# The scenario that exposes each mutation, and the check that fires first.
DETECTS = {1: ('tamper-low-byte', 'BOOT_VERDICT'),       # only the last digest byte compared
           2: ('length-unaligned', 'BOOT_VERDICT'),      # a length that is not whole words accepted
           3: ('golden', 'BOOT_VERDICT'),                # version comparison reversed
           4: ('rom-ignores-verdict', 'BOOT_KEY'),       # key readable after FAIL
           5: ('irq-jumps-to-image', 'BOOT_EXEC'),       # flash fetch open until FAIL
           6: ('unverified-tail', 'BOOT_EXEC'),          # no upper bound on the fetch gate
           7: ('rom-ignores-verdict', 'BOOT_VERDICT'),   # STATUS writable: the verdict forged
           8: ('lifecycle-prod', 'BOOT_DEBUG'),          # debug ignores the lifecycle
           9: ('reset-during-image', 'BOOT_RESET')}      # PASS not cleared by reset


def case(name, scenario, mutation=0, label=None, category='functional'):
    rows, out = scenario.rows()
    return dict(id=name, vectors=rows, mutation=mutation, expected_failure=label, category=category,
                counts=out['counts'])


def make_cases(args, parameters):
    max_len = parameters['IMG_MAX']
    scenarios = {s.name: s for s in MODEL.directed(max_len)}
    cases = [case(name, s, args.demo_bug) for name, s in scenarios.items()]
    for seed in range(args.seed, args.seed + (3 if args.profile == 'nightly' else 1)):
        draw = random.Random(seed)
        for k in range(args.iterations):
            s = MODEL.random_scenario(draw.getrandbits(32), max_len)
            cases.append(case(f'random-seed{seed}-{k}', s, args.demo_bug))
    for mutation, (name, label) in DETECTS.items():
        cases.append(case(f'detect-mutation{mutation}', scenarios[name], mutation, label, 'mutation'))
    return cases


if __name__ == '__main__':
    spec = importlib.util.spec_from_file_location('local_runner', HERE.parent / 'local-common/runner.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    sys.exit(module.main(sys.modules[__name__]))

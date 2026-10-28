#!/usr/bin/env python3
"""IEEE 1149.1 TAP controller, IDCODE, BYPASS and boundary-scan example."""
import importlib.util
from pathlib import Path
import random
import sys

HERE = Path(__file__).resolve().parent
NAME = 'local-jtag-tap'
TOP = 'jtag_tap_tb'
CONFIGS = {
    'id12345679': {'IDCODE': 0x12345679},
    'iddeadbeef': {'IDCODE': 0xdeadbeef},
}
ITERATIONS = {'smoke': 8, 'nightly': 20}
SOURCES = [HERE / 'rtl/jtag_tap.sv', HERE / 'tb/jtag_tap_tb.sv']

TLR, RTI, SEL_DR, CAP_DR, SHIFT_DR, EXIT1_DR, PAUSE_DR, EXIT2_DR = range(8)
UPD_DR, SEL_IR, CAP_IR, SHIFT_IR, EXIT1_IR, PAUSE_IR, EXIT2_IR, UPD_IR = range(8, 16)
IDCODE_IR, BYPASS, SAMPLE, EXTEST = 1, 15, 2, 3


class Plan:
    def __init__(self, idcode):
        self.idcode = idcode
        self.rows = []
        self.prev_tck = 0
        self.clear()

    def clear(self):
        self.state = TLR
        self.ir = IDCODE_IR
        self.ir_bits = [1, 0, 0, 0]
        self.dr_bits = [0]
        self.update_value = 0
        self.tdo = 0
        self.pin_out = 0

    @property
    def id_shift(self):
        return sum(bit << i for i, bit in enumerate(self.dr_bits))

    @staticmethod
    def bits(value, width):
        return [(value >> i) & 1 for i in range(width)]

    def transition(self, state, tms):
        table = {
            TLR: TLR if tms else RTI, RTI: SEL_DR if tms else RTI,
            SEL_DR: SEL_IR if tms else CAP_DR, CAP_DR: EXIT1_DR if tms else SHIFT_DR,
            SHIFT_DR: EXIT1_DR if tms else SHIFT_DR, EXIT1_DR: UPD_DR if tms else PAUSE_DR,
            PAUSE_DR: EXIT2_DR if tms else PAUSE_DR, EXIT2_DR: UPD_DR if tms else SHIFT_DR,
            UPD_DR: SEL_DR if tms else RTI, SEL_IR: TLR if tms else CAP_IR,
            CAP_IR: EXIT1_IR if tms else SHIFT_IR, SHIFT_IR: EXIT1_IR if tms else SHIFT_IR,
            EXIT1_IR: UPD_IR if tms else PAUSE_IR, PAUSE_IR: EXIT2_IR if tms else PAUSE_IR,
            EXIT2_IR: UPD_IR if tms else SHIFT_IR, UPD_IR: SEL_DR if tms else RTI,
        }
        return table.get(state, TLR)

    def step(self, tck=0, tms=0, tdi=0, trst=1, pin_in=0):
        if not trst:
            self.clear()
        else:
            rise = tck and not self.prev_tck
            fall = (not tck) and self.prev_tck
            if rise:
                old_state = self.state
                if old_state == CAP_DR:
                    value, width = (self.idcode, 32) if self.ir == IDCODE_IR else ((pin_in, 8) if self.ir in (SAMPLE, EXTEST) else (0, 1))
                    self.dr_bits = self.bits(value, width)
                elif old_state == SHIFT_DR:
                    self.dr_bits = self.dr_bits[1:] + [tdi & 1]
                elif old_state == CAP_IR:
                    self.ir_bits = [1, 0, 0, 0]
                elif old_state == SHIFT_IR:
                    self.ir_bits = self.ir_bits[1:] + [tdi & 1]
                self.state = self.transition(old_state, tms)
            if fall:
                if self.state == TLR:
                    self.ir = IDCODE_IR
                elif self.state == UPD_IR:
                    self.ir = sum(bit << i for i, bit in enumerate(self.ir_bits))
                if self.state == UPD_DR and self.ir in (SAMPLE, EXTEST):
                    self.update_value = sum(bit << i for i, bit in enumerate(self.dr_bits))
                self.tdo = self.dr_bits[0] if self.state == SHIFT_DR else (self.ir_bits[0] if self.state == SHIFT_IR else 0)
        self.pin_out = self.update_value if self.ir == EXTEST else pin_in & 0xff
        self.rows.append([tck, tms, tdi, trst, pin_in & 0xff, self.tdo,
                          self.pin_out, self.state, self.ir])
        self.prev_tck = tck

    def clock(self, tms=0, tdi=0, pin_in=0):
        self.step(tck=0, tms=tms, tdi=tdi, pin_in=pin_in)
        self.step(tck=1, tms=tms, tdi=tdi, pin_in=pin_in)

    def reset(self, count=4):
        for _ in range(count):
            self.step(tck=0, trst=0)
        self.step(tck=0, trst=1)

    def go_shift_dr(self):
        self.clock(1); self.clock(0); self.clock(0)

    def go_shift_ir(self):
        self.clock(1); self.clock(1); self.clock(0); self.clock(0)

    def exit_dr(self):
        self.clock(1); self.clock(0)

    def exit_ir(self):
        self.clock(1); self.clock(0)

    def load_ir(self, bits):
        self.go_shift_ir()
        for index, bit in enumerate(bits):
            self.clock(tms=int(index == len(bits) - 1), tdi=bit)
        self.exit_ir()

    def shift_dr(self, bits):
        self.go_shift_dr()
        for index, bit in enumerate(bits):
            self.clock(tms=int(index == len(bits) - 1), tdi=bit)
        self.exit_dr()

    def boundary_scan(self, value, pin_value=0x5a):
        self.clock(1, pin_in=pin_value); self.clock(0, pin_in=pin_value); self.clock(0, pin_in=pin_value)
        for index, bit in enumerate(self.bits(value, 8)):
            self.clock(tms=int(index == 7), tdi=bit, pin_in=pin_value)
        self.clock(1, pin_in=pin_value); self.clock(0, pin_in=pin_value)

    def fixed(self):
        self.reset()
        self.clock(0)
        # IDCODE read: 32 shifts with the reset instruction.
        self.shift_dr([0] * 32)
        self.load_ir(self.bits(BYPASS, 4))
        self.shift_dr([1, 0, 1])
        self.load_ir(self.bits(SAMPLE, 4))
        self.boundary_scan(0x3c)
        # PRELOAD is applied as soon as EXTEST is updated, before another DR scan.
        self.load_ir(self.bits(EXTEST, 4))
        self.boundary_scan(0xa5, 0x96)
        self.load_ir(self.bits(IDCODE_IR, 4))
        self.step(tck=0, pin_in=0x69)
        # An unimplemented instruction selects the one-bit BYPASS data register.
        self.load_ir(self.bits(8, 4))
        self.shift_dr([1, 0, 1])
        # PAUSE/EXIT2 path and a second IR update.
        self.load_ir([1, 1, 1, 1])
        self.go_shift_dr()
        self.clock(1); self.clock(0); self.clock(1); self.clock(0)
        self.clock(1); self.clock(1); self.clock(0)
        # Reset recovery after a short TRST pulse.
        self.reset()
        self.clock(0)
        self.load_ir([0, 1, 0, 0])
        self.shift_dr([0, 1, 0, 1, 0, 1, 0, 0])

    def random(self, rng, count):
        self.reset()
        self.clock(0)
        instructions = [self.bits(value, 4) for value in (IDCODE_IR, BYPASS, SAMPLE, EXTEST, 8)]
        for _ in range(count):
            if rng.randrange(10) == 0:
                self.reset()
                self.clock(0)
            self.load_ir(rng.choice(instructions))
            length = rng.choice((1, 8, 16, 32))
            self.shift_dr([rng.randrange(2) for _ in range(length)])


def vectors(seed, iterations, parameters, boundary=False):
    p = Plan(parameters['IDCODE'])
    p.fixed()
    if not boundary:
        p.random(random.Random(seed), iterations)
    return p.rows


def make_cases(args, parameters):
    base = vectors(args.seed, 0, parameters, True)
    cases = [dict(id='boundaries', vectors=base, mutation=args.demo_bug,
                  category='functional', expected_failure=None)]
    for seed in range(args.seed, args.seed + (3 if args.profile == 'nightly' else 1)):
        cases.append(dict(id=f'random-seed{seed}', vectors=vectors(seed, args.iterations, parameters),
                          mutation=args.demo_bug, category='functional', expected_failure=None))
    for mutation, label in ((1, 'JTAG_TDO'), (2, 'JTAG_IR'),
                            (3, 'JTAG_BOUNDARY'), (4, 'JTAG_STATE')):
        cases.append(dict(id=f'detect-mutation{mutation}', vectors=base, mutation=mutation,
                          category='mutation', expected_failure=label))
    for case in cases:
        case['counts'] = {'steps': len(case['vectors'])}
    return cases


if __name__ == '__main__':
    spec = importlib.util.spec_from_file_location('local_runner', HERE.parent / 'local-common/runner.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    sys.exit(module.main(sys.modules[__name__]))

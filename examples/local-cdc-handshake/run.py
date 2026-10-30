#!/usr/bin/env python3
"""Four-phase req/ack CDC, pulse synchronizer and reset synchronizer example."""
import importlib.util
from pathlib import Path
import random
import sys

HERE = Path(__file__).resolve().parent
NAME = 'local-cdc-handshake'
TOP = 'cdc_handshake_tb'
CONFIGS = {'sync2': {'SYNC_STAGES': 2}, 'sync3': {'SYNC_STAGES': 3}}
ITERATIONS = {'smoke': 30, 'nightly': 120}
SOURCES = [HERE / 'rtl/cdc_handshake.sv', HERE / 'tb/cdc_handshake_tb.sv']


def make_clocks(profile, count, seed=17):
    rng = random.Random(seed + profile)
    if profile == 0:
        wh, rh, offset = 2, 4, 0
    elif profile == 1:
        wh, rh, offset = 4, 2, 0
    elif profile == 2:
        wh, rh, offset = 3, 3, 2
    else:
        wh, rh, offset = 2, 4, 0
    wc = rc = 0
    wnext = wh
    rnext = rh + offset
    rows = []
    for tick in range(count):
        rows.append((wc, rc))
        if tick + 1 == wnext:
            wc ^= 1
            wnext += max(1, wh + (rng.choice((-1, 0, 1)) if profile == 3 else 0))
        if tick + 1 == rnext:
            rc ^= 1
            rnext += max(1, rh + (rng.choice((-1, 0, 1)) if profile == 3 else 0))
    return rows


class Plan:
    def __init__(self, stages):
        self.stages = stages
        self.rows = []
        self.prev_sc = self.prev_dc = 0
        self.set_profile(0)
        self.reset_state()

    def reset_state(self):
        self.req = 0
        self.data_reg = 0
        self.req_sync = [0] * self.stages
        self.ack = 0
        self.ack_sync = [0] * self.stages
        self.rst_sync = [0] * self.stages
        self.toggle = 0
        self.pulse_sync = [0] * self.stages
        self.pulse_prev = 0
        self.last_accept = 0
        self.last_srise = 0
        self.last_drise = 0
        self.last_dst_valid = 0
        self.last_dst_accept = 0

    def set_profile(self, profile, seed=17):
        self.profile = profile
        self.clocks = make_clocks(profile, 50000, seed)
        self.tick = 0
        self.prev_sc = self.prev_dc = 0

    def step(self, svalid=0, sdata=0, dready=0, spulse=0, rst=1):
        sc, dc = self.clocks[self.tick]
        srise = int(sc and not self.prev_sc)
        drise = int(dc and not self.prev_dc)
        self.last_srise = srise
        self.last_drise = drise
        if not rst:
            self.reset_state()
            self.rows.append([sc, dc, 0, svalid, sdata, dready, spulse, self.profile,
                              0, 0, 0, 0, 0])
            self.prev_sc, self.prev_dc = sc, dc
            self.tick += 1
            return
        src_ready_pre = int(not self.req and not self.ack_sync[-1])
        dst_rst_old = self.rst_sync[-1]
        dst_valid_pre = int(dst_rst_old and self.req_sync[-1] and not self.ack)
        self.last_accept = int(srise and svalid and src_ready_pre)
        self.last_dst_valid = dst_valid_pre
        self.last_dst_accept = int(drise and dst_valid_pre and dready)

        req_next = self.req
        data_next = self.data_reg
        ack_sync_next = list(self.ack_sync)
        toggle_next = self.toggle
        if srise:
            ack_sync_next = [self.ack] + self.ack_sync[:-1]
            if self.ack_sync[-1]:
                req_next = 0
            if self.last_accept:
                req_next = 1
                data_next = sdata & 0xff
            if spulse:
                toggle_next = not self.toggle

        req_sync_next = list(self.req_sync)
        ack_next = self.ack
        pulse_sync_next = list(self.pulse_sync)
        pulse_prev_next = self.pulse_prev
        rst_sync_next = list(self.rst_sync)
        if drise:
            if not dst_rst_old:
                req_sync_next = [0] * self.stages
                ack_next = 0
                pulse_sync_next = [0] * self.stages
                pulse_prev_next = 0
            else:
                req_sync_next = [self.req] + self.req_sync[:-1]
                pulse_sync_next = [self.toggle] + self.pulse_sync[:-1]
                pulse_prev_next = self.pulse_sync[-1]
                if dst_valid_pre and dready:
                    ack_next = 1
                if not self.req_sync[-1]:
                    ack_next = 0
            rst_sync_next = [1] + self.rst_sync[:-1]

        self.req = req_next
        self.data_reg = data_next
        self.ack_sync = ack_sync_next
        self.toggle = toggle_next
        self.req_sync = req_sync_next
        self.ack = ack_next
        self.pulse_sync = pulse_sync_next
        self.pulse_prev = pulse_prev_next
        self.rst_sync = rst_sync_next

        dst_rst = self.rst_sync[-1]
        src_ready = int(not self.req and not self.ack_sync[-1])
        dst_valid = int(dst_rst and self.req_sync[-1] and not self.ack)
        dst_pulse = int(dst_rst and (self.pulse_sync[-1] ^ self.pulse_prev))
        self.rows.append([sc, dc, 1, svalid, sdata, dready, spulse, self.profile,
                          src_ready, dst_valid, self.data_reg, dst_pulse, dst_rst])
        self.prev_sc, self.prev_dc = sc, dc
        self.tick += 1

    def reset_ticks(self, count=5):
        for _ in range(count):
            self.step(rst=0)
        for _ in range(40):
            self.step(rst=1)

    def send(self, value, stall=0):
        for _ in range(300):
            self.step(svalid=1, sdata=value, dready=0)
            if self.last_accept:
                break
        else:
            raise ValueError('source handshake did not complete')
        for _ in range(300):
            if self.last_dst_accept:
                break
            # The source already offers different next data; the held request must not change.
            if self.last_dst_valid:
                if stall:
                    self.step(svalid=1, sdata=value ^ 0xa5, dready=0)
                    if self.last_drise and self.last_dst_valid:
                        stall -= 1
                    continue
                self.step(svalid=1, sdata=value ^ 0xa5, dready=1)
            else:
                self.step(svalid=1, sdata=value ^ 0xa5, dready=0)

        else:
            raise ValueError('destination handshake did not complete')

    def pulse(self):
        for _ in range(30):
            self.step(spulse=1)
            if self.last_srise:
                break
        for _ in range(40):
            self.step()

    def fixed(self):
        self.set_profile(0)
        self.reset_ticks()
        self.send(0x00, stall=3)
        self.send(0xff)
        self.send(0x55, stall=1)
        self.send(0xaa)
        self.send(0x12)
        # Leave a request in flight and reset both domains.
        for _ in range(30):
            self.step(svalid=1, sdata=0x3c)
            if self.last_accept:
                break
        self.step()
        self.step(rst=0)
        self.set_profile(1)
        self.reset_ticks()
        self.send(0x5a)
        self.send(0xa5, stall=2)
        self.set_profile(2)
        self.reset_ticks()
        self.send(0x00)
        self.send(0xff)
        self.send(0x55)
        self.set_profile(0)
        self.reset_ticks()
        self.pulse()
        self.pulse()
        self.set_profile(2)
        self.reset_ticks()
        self.pulse()

    def random(self, rng, count):
        self.set_profile(3, rng.getrandbits(32))
        self.reset_ticks()
        for _ in range(count):
            if rng.randrange(20) == 0:
                self.reset_ticks()
            self.send(rng.getrandbits(8), stall=rng.randrange(4))
            if rng.randrange(4) == 0:
                self.pulse()


def vectors(seed, iterations, parameters, boundary=False):
    p = Plan(parameters['SYNC_STAGES'])
    p.fixed()
    if not boundary:
        p.random(random.Random(seed), iterations)
    # Drain both req/ack return and delayed pulse observations before declaring pass.
    for _ in range(120):
        p.step(dready=1)
    if p.req or p.ack or any(p.ack_sync) or any(p.req_sync):
        raise ValueError('handshake still pending at end of plan')
    return p.rows


def make_cases(args, parameters):
    base = vectors(args.seed, 0, parameters, True)
    cases = [dict(id='boundaries', vectors=base, mutation=args.demo_bug,
                  category='functional', expected_failure=None)]
    for seed in range(args.seed, args.seed + (3 if args.profile == 'nightly' else 1)):
        cases.append(dict(id=f'random-seed{seed}', vectors=vectors(seed, args.iterations, parameters),
                          mutation=args.demo_bug, category='functional', expected_failure=None))
    for mutation, label in ((1, 'CDC_DATA'), (2, 'CDC_READY'),
                            (3, 'CDC_PULSE'), (4, 'CDC_RESET')):
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

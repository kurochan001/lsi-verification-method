#!/usr/bin/env python3
"""Wishbone B4 classic to APB4 bridge: waits, errors, byte selects and abandoned cycles."""
import importlib.util
from pathlib import Path
import random
import sys

HERE = Path(__file__).resolve().parent
NAME = 'local-wishbone-apb'
TOP = 'wb_apb_tb'
CONFIGS = {'aw16': dict(AW=16), 'aw8': dict(AW=8)}
ITERATIONS = {'smoke': 40, 'nightly': 300}
SOURCES = [HERE / 'rtl/wb_apb_bridge.sv', HERE / 'tb/wb_apb_tb.sv']
MUTANTS = 9
LABELS = {1: 'WBA_RESPONSE', 2: 'WBA_APB', 3: 'WBA_APB', 4: 'WBA_APB', 5: 'WBA_RESPONSE',
          6: 'WBA_DATA', 7: 'WBA_APB', 8: 'WBA_APB', 9: 'WBA_RESPONSE'}
# With the comparison against the model switched off, only the protocol monitors judge the run.
MONITOR_LABELS = {2: 'WBA_APB_PROTOCOL', 3: 'WBA_APB_PROTOCOL', 4: 'WBA_APB_PROTOCOL', 7: 'WBA_APB_PROTOCOL'}
MONITOR_MISSES = (1, 5, 6, 8, 9)
OFF = dict(cyc=0, stb=0, we=0, adr=0, dat=0, sel=0)
PHASES = ('setup', 'wait', 'complete', 'response')


def request(we, adr, dat=0, sel=15):
    return dict(cyc=1, stb=1, we=we, adr=adr, dat=dat, sel=sel)


def select(word, sel):
    """Keep the selected byte lanes of a word."""
    return sum(word & (0xff << (8 * lane)) for lane in range(4) if sel >> lane & 1)


class Plan:
    """Lays out each transfer as an explicit timeline of clocks. It keeps no bridge state:
    every row is written from the request, the number of APB wait clocks and the clock in
    which the master leaves, so it does not repeat the state machine of the circuit."""

    def __init__(self, compare=1):
        self.rows = []
        self.compare = compare
        self.completed = 0

    def row(self, master=OFF, rst=1, pready=0, pslverr=0, prdata=0, ack=0, err=0, rdat=0, apb=None):
        apb = apb or dict(psel=0, penable=0, pwrite=0, paddr=0, pwdata=0, pstrb=0)
        self.rows.append([rst, master['cyc'], master['stb'], master['we'], master['adr'], master['dat'], master['sel'],
                          pready, pslverr, prdata, self.compare, ack, err, rdat,
                          apb['psel'], apb['penable'], apb['pwrite'], apb['paddr'], apb['pwdata'], apb['pstrb']])

    def idle(self, count=1, master=OFF, pready=0, pslverr=0, prdata=0):
        """Clocks in which nothing may be accepted or answered."""
        if master['cyc'] and master['stb']:
            raise ValueError('an idle clock cannot carry a request')
        for _ in range(count):
            self.row(master, pready=pready, pslverr=pslverr, prdata=prdata)

    def reset(self, count=1):
        for _ in range(count):
            self.row(rst=0)

    def transfer(self, req, wait=0, err=0, rdata=0, leave=None, pending=None, reset=None, noise=0, setup_ready=0):
        """One accepted request.

        leave:   (phase, index) of the first clock in which the master has dropped CYC.
        pending: the request the master presents from the clock after it left, while the
                 abandoned APB transfer is still running. It is accepted only afterwards.
        reset:   (phase, index) of a clock with reset asserted; the transfer ends there.
        noise:   drive PSLVERR and PRDATA during the wait clocks, where they mean nothing.
        """
        apb = dict(psel=1, penable=0, pwrite=req['we'], paddr=req['adr'],
                   pwdata=req['dat'] if req['we'] else 0, pstrb=req['sel'] if req['we'] else 0)
        timeline = [('setup', 0)] + [('wait', k) for k in range(wait)] + [('complete', 0), ('response', 0)]
        self.row(req)  # the clock in which the request is taken; nothing is driven yet
        gone = False
        master = req
        for position in timeline:
            phase = position[0]
            if reset == position:
                # Reset is sampled at the end of this clock, so the APB outputs still show the phase.
                self.row(rst=0, apb=None if phase == 'response' else dict(apb, penable=int(phase != 'setup')))
                return
            if leave == position:
                gone, master = True, OFF
            elif gone and pending is not None:
                master = pending
            if phase == 'response':
                if leave == position:
                    self.row(OFF)  # the answer was ready, but the master left in this very clock
                elif not gone:
                    self.row(req, ack=int(not err), err=int(bool(err)),
                             rdat=select(rdata, req['sel']) if not err and not req['we'] else 0)
                    self.completed += 1
                # A cycle abandoned earlier has no response clock at all: the next clock is free.
                break
            if phase == 'setup':
                self.row(master, pready=setup_ready, pslverr=setup_ready, prdata=0xffffffff if setup_ready else 0, apb=apb)
            elif phase == 'wait':
                self.row(master, pslverr=noise, prdata=0xa5a5a5a5 if noise else 0, apb=dict(apb, penable=1))
            else:
                self.row(master, pready=1, pslverr=err, prdata=rdata, apb=dict(apb, penable=1))
        if pending is not None:
            self.transfer(pending, wait=1, rdata=0x0badcafe)


def fixed(aw, compare=1):
    """Every rule and every boundary once, in a fixed order."""
    top = (1 << aw) - 1
    p = Plan(compare)
    p.reset(2)
    p.idle(2)
    # Plain transfers: both directions, both ends of the address range, each wait length.
    p.transfer(request(1, 0, 0x11223344), wait=0)
    p.transfer(request(0, 0), wait=0, rdata=0x11223344)
    p.transfer(request(1, top, 0xa5a55a5a), wait=1)
    p.transfer(request(0, top), wait=1, rdata=0xa5a55a5a)
    p.transfer(request(1, 4, 0xffffffff), wait=3, noise=1)
    p.transfer(request(0, 4), wait=4, rdata=0xffffffff, noise=1)
    p.idle()
    # Byte selects: each single lane, an empty select and a mixed one, for writes and reads.
    for sel in (1, 2, 4, 8, 0, 5, 10):
        p.transfer(request(1, 8, 0x89abcdef, sel))
        p.transfer(request(0, 8, sel=sel), rdata=0x76543210)
    # Errors: the slave refuses a write and a read; an error flag outside the last clock means nothing.
    p.transfer(request(1, 12, 0xdead0001), err=1)
    p.transfer(request(0, 12), wait=2, err=1, rdata=0xffffffff)
    p.transfer(request(0, 12), wait=2, noise=1, rdata=0x00c0ffee)
    # Clocks that look like a request or an answer but are neither.
    p.idle(2, dict(OFF, cyc=1))                      # cycle open, no strobe
    p.idle(2, dict(OFF, stb=1, we=1, adr=top, dat=0xffffffff, sel=15))  # strobe without a cycle
    p.idle(2, pready=1, pslverr=1, prdata=0xffffffff)  # APB answer with nothing selected
    p.transfer(request(0, 16), setup_ready=1, wait=1, rdata=0x01020304)  # PREADY high in the setup clock
    # The master leaves in each clock of a transfer; with and without a new request already waiting.
    for position in (('setup', 0), ('wait', 0), ('wait', 1), ('complete', 0), ('response', 0)):
        for follower in (None, request(0, 0x24, sel=3), request(1, 0x28, 0x0f0f0f0f, 12)):
            p.transfer(request(1, 0x20, 0x13572468), wait=2, leave=position, pending=follower)
            p.idle()
        p.transfer(request(0, 0x20), wait=2, rdata=0x24681357, leave=position, pending=request(0, 0x2c))
    p.transfer(request(1, 0x30, 1), wait=0, leave=('setup', 0), pending=request(0, 0x34))
    p.transfer(request(0, 0x30), wait=0, err=1, leave=('complete', 0), pending=request(1, 0x34, 2))
    # Back-to-back requests with no idle clock, then one separated by a single idle clock.
    for index in range(4):
        p.transfer(request(index & 1, 0x40 + 4 * index, 0x1000 + index), wait=index & 1, rdata=0x2000 + index)
    p.idle()
    p.transfer(request(0, 0x50), rdata=0x50505050)
    # Reset in each clock of a transfer, then the first transfer after it.
    for position in (('setup', 0), ('wait', 0), ('wait', 1), ('complete', 0), ('response', 0)):
        p.transfer(request(1, 0x60, 0x600d0000), wait=2, reset=position)
        p.transfer(request(0, 0x64), wait=1, rdata=0x64646464)
    p.transfer(request(1, 0x68, 3), wait=1, leave=('wait', 0), reset=('complete', 0))
    p.transfer(request(0, 0x6c), rdata=0x6c)
    p.idle(2)
    return p


def vectors(seed, iterations, aw, boundary=False, compare=1):
    p = fixed(aw, compare)
    if boundary:
        return p.rows
    rng = random.Random(seed * 1009 + aw)
    top = (1 << aw) - 1

    def make():
        return request(rng.randrange(2), rng.choice((0, top, rng.randrange(top + 1))), rng.getrandbits(32),
                       rng.choice((15, 15, 15, rng.randrange(16))))
    for _ in range(iterations):
        roll = rng.randrange(20)
        wait = rng.choice((0, 0, 1, 1, 2, 3, 5))
        position = rng.choice([('setup', 0), ('complete', 0), ('response', 0)] + [('wait', k) for k in range(wait)])
        options = dict(wait=wait, err=int(rng.randrange(6) == 0), rdata=rng.getrandbits(32), noise=rng.randrange(2),
                       setup_ready=rng.randrange(2))
        if roll == 0:
            p.transfer(make(), reset=position, **options)
        elif roll < 5:
            p.transfer(make(), leave=position, pending=make() if rng.randrange(2) else None, **options)
        else:
            p.transfer(make(), **options)
        if rng.randrange(3) == 0:
            p.idle(rng.randrange(1, 3), rng.choice((OFF, dict(OFF, cyc=1), dict(OFF, stb=1, adr=top))),
                   pready=rng.randrange(2), pslverr=rng.randrange(2), prdata=rng.getrandbits(32))
    p.idle(2)
    return p.rows


def make_cases(args, parameters):
    aw = parameters['AW']
    base = vectors(args.seed, 0, aw, True)
    blind = vectors(args.seed, 0, aw, True, compare=0)
    cases = [dict(id='boundaries', vectors=base, mutation=args.demo_bug, expected_failure=None, category='functional')]
    for seed in range(args.seed, args.seed + (3 if args.profile == 'nightly' else 1)):
        cases.append(dict(id=f'random-seed{seed}', vectors=vectors(seed, args.iterations, aw), mutation=args.demo_bug,
                          expected_failure=None, category='functional'))
    for mutation in range(1, MUTANTS + 1):
        cases.append(dict(id=f'detect-mutation{mutation}', vectors=base, mutation=mutation,
                          expected_failure=LABELS[mutation], category='mutation'))
    for mutation, label in MONITOR_LABELS.items():
        cases.append(dict(id=f'monitor-detects-mutation{mutation}', vectors=blind, mutation=mutation,
                          expected_failure=label, category='mutation'))
    for mutation in MONITOR_MISSES:
        cases.append(dict(id=f'monitor-misses-mutation{mutation}', vectors=blind, mutation=mutation,
                          expected_failure=None, category='diagnostic'))
    for case in cases:
        case['counts'] = {'steps': len(case['vectors'])}
    return cases


if __name__ == '__main__':
    spec = importlib.util.spec_from_file_location('local_runner', HERE.parent / 'local-common/runner.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    sys.exit(module.main(sys.modules[__name__]))

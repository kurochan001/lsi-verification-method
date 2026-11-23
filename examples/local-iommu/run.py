#!/usr/bin/env python3
"""IOMMU-lite DMA address translation: TLB hit/miss, permission faults and invalidate."""
import importlib.util
from pathlib import Path
import random
import sys

HERE = Path(__file__).resolve().parent
NAME = 'local-iommu'
TOP = 'iommu_tb'
CONFIGS = {'tlb1': {'TLB': 1}, 'tlb3': {'TLB': 3}}
ITERATIONS = {'smoke': 200, 'nightly': 1000}
SOURCES = [HERE / 'rtl/iommu.sv', HERE / 'tb/iommu_tb.sv']

MISS, PERM = 1, 2  # fault types: 00 none, 01 miss, 10 permission


class Plan:
    def __init__(self, tlb):
        self.tlb_n = tlb
        self.rows = []
        self.reset()

    def reset(self):
        self.tab = [dict(v=0, vpn=0, pfn=0, wr=0) for _ in range(4)]
        self.tlb = [dict(v=0, vpn=0, pfn=0, wr=0) for _ in range(4)]  # slots 3..TLB stay 0
        self.rr = 0
        self.busy, self.cnt = 0, 0
        self.hold = None
        self.resp = None

    def pins(self):
        vpn_pin = 0
        val_pin = 0
        for i in range(self.tlb_n):
            vpn_pin |= self.tlb[i]['vpn'] << (2 * i)
            val_pin |= self.tlb[i]['v'] << i
        return vpn_pin, val_pin

    def step(self, rst=1, req=0, vpn=0, wr=0, tup=0, sel=0, tvpn=0, tpfn=0, twr=0, tvb=0):
        if not rst:
            self.rows.append([0] * 16)
            self.reset()
            return
        busy, gnt, pfn, fault = self.busy, 0, 0, 0
        if self.resp is not None:
            gnt, pfn, fault = 1, self.resp['pfn'], self.resp['fault']
        tvpn_pin, tval_pin = self.pins()
        self.rows.append([1, req, vpn, wr, tup, sel, tvpn, tpfn, twr, tvb,
                          busy, gnt, pfn, fault, tvpn_pin, tval_pin])
        # --- same-edge order: request / lookup / hit, then table update (invalidate last) ---
        self.resp = None  # every response is a one-cycle grant
        if self.busy:
            if self.cnt == 1 and self.hold is not None:
                hit = self.tlookup(self.hold['vpn'])  # table as it was before this edge
                if hit is not None:
                    slot = self.rr % self.tlb_n
                    self.tlb[slot] = dict(v=1, vpn=hit['vpn'], pfn=hit['pfn'], wr=hit['wr'])
                    self.rr = (slot + 1) % self.tlb_n
                self.resp = self.policy(self.hold, hit)
                self.hold = None
                self.busy = 0
            else:
                self.cnt -= 1
        elif req:
            hit = next((e for e in self.tlb[:self.tlb_n]
                        if e['v'] and e['vpn'] == vpn), None)
            if hit is not None:
                self.resp = self.policy(dict(vpn=vpn, wr=wr), hit)
            else:
                self.busy, self.cnt = 1, 2
                self.hold = dict(vpn=vpn, wr=wr)
        if tup and sel < 4:
            old_vpn = self.tab[sel]['vpn']
            self.tab[sel] = dict(v=tvb, vpn=tvpn, pfn=tpfn, wr=twr)
            for i in range(self.tlb_n):  # a stale hit must be impossible (the tag stays, v clears)
                if self.tlb[i]['v'] and self.tlb[i]['vpn'] in (old_vpn, tvpn):
                    self.tlb[i]['v'] = 0

    @staticmethod
    def policy(req, entry):
        if entry is None:
            return dict(pfn=0, fault=MISS)
        if req['wr'] and not entry['wr']:
            return dict(pfn=entry['pfn'], fault=PERM)
        return dict(pfn=entry['pfn'], fault=0)

    def tlookup(self, vpn):
        return next((e for e in self.tab if e['v'] and e['vpn'] == vpn), None)

    def req(self, vpn, wr=0, **kw):
        self.step(req=1, vpn=vpn, wr=wr, **kw)

    def idle(self, **kw):
        self.step(**kw)

    def fixed(self):
        self.step(rst=0)
        # table: e0 vpn0 pfn1 RW, e1 vpn1 pfn2 RO, e2 vpn2 pfn3 RW, e3 vpn3 pfn4 invalid
        self.step(tup=1, sel=0, tvpn=0, tpfn=1, twr=1, tvb=1)
        self.step(tup=1, sel=1, tvpn=1, tpfn=2, twr=0, tvb=1)
        self.step(tup=1, sel=2, tvpn=2, tpfn=3, twr=1, tvb=1)
        self.step(tup=1, sel=3, tvpn=3, tpfn=4, twr=1, tvb=0)
        self.step(tup=1, sel=5, tvpn=0, tpfn=7, twr=1, tvb=1)  # out-of-range select: ignored
        self.idle()
        self.req(0)          # walk 8-9, grant row 10 (mutation 3 diverges at row 9)
        self.idle()
        self.idle()
        self.idle()
        self.req(0)          # held hit request; the TLB path answers both rows
        self.req(0)
        self.idle()
        self.idle()
        self.req(1, wr=1)    # walk -> permission fault grant on row 18
        self.idle()
        self.idle()
        self.idle()
        self.req(1, wr=1)    # RO entry straight from the TLB (mutation 1 diverges at row 20)
        self.idle()
        self.idle()
        self.req(3)          # the walk sees only the invalid entry (mutation 4 diverges at row 24)
        self.idle()
        self.idle()
        self.idle()
        self.idle(tup=1, sel=1, tvpn=1, tpfn=6, twr=0, tvb=1)  # update + TLB invalidate (mutation 2)
        self.idle()
        self.req(1, wr=1)    # refetch: pfn 6 and the permission fault again
        self.idle()
        self.idle()
        self.idle()
        self.idle(tup=1, sel=2, tvpn=2, tpfn=3, twr=1, tvb=1)  # an update while...
        self.req(2)          # ...idle, then a fresh walk
        self.req(0)          # held under backpressure while the vpn 2 walk runs
        self.req(0, tup=1, sel=2, tvpn=2, tpfn=3, twr=1, tvb=1)  # held under backpressure, update while busy
        self.idle(tup=1, sel=2, tvpn=2, tpfn=3, twr=1, tvb=1)  # the grant survives this update
        self.req(1, wr=1)    # refetch vpn 1 again
        self.idle()
        self.idle()
        self.idle()
        self.idle()
        self.idle()
        self.idle()
        self.step(rst=0)
        self.idle()
        self.step(tup=1, sel=3, tvpn=3, tpfn=5, twr=1, tvb=1)
        self.req(3)
        self.idle()
        self.idle()
        self.idle()
        # after reset the table is empty again: rebuild it and fill every slot,
        # so the last fill provably lands on a still-occupied slot (tlb/replace)
        self.idle(tup=1, sel=0, tvpn=0, tpfn=1, twr=1, tvb=1)
        self.idle(tup=1, sel=1, tvpn=1, tpfn=2, twr=1, tvb=1)
        self.idle(tup=1, sel=2, tvpn=2, tpfn=3, twr=1, tvb=1)
        self.req(0)
        self.idle()
        self.idle()
        self.idle()
        self.idle()
        self.req(1)
        self.idle()
        self.idle()
        self.idle()
        self.idle()
        self.req(2)
        self.idle()
        self.idle()
        self.idle()

    def random(self, rng, count):
        self.step(rst=0)
        for _ in range(count):
            roll = rng.randrange(100)
            if roll == 0:
                self.step(rst=0)
            elif roll < 60:
                self.req(rng.randrange(4), rng.randrange(2))
            elif roll < 90:
                self.step(tup=1, sel=rng.randrange(8), tvpn=rng.randrange(4),
                          tpfn=rng.randrange(16), twr=rng.randrange(2), tvb=rng.randrange(2))
            else:
                self.idle()


def vectors(seed, iterations, parameters, boundary=False):
    p = Plan(parameters['TLB'])
    p.fixed()
    if not boundary:
        p.random(random.Random(seed), iterations)
    p.idle()
    p.step(rst=0)
    return p.rows


def make_cases(args, parameters):
    base = vectors(args.seed, 0, parameters, True)
    cases = [dict(id='boundaries', vectors=base, mutation=args.demo_bug,
                  category='functional', expected_failure=None)]
    for seed in range(args.seed, args.seed + (3 if args.profile == 'nightly' else 1)):
        cases.append(dict(id=f'random-seed{seed}', vectors=vectors(seed, args.iterations, parameters),
                          mutation=args.demo_bug, category='functional', expected_failure=None))
    for mutation, label in ((1, 'IOMMU_FAULT'), (2, 'IOMMU_STATE'), (3, 'IOMMU_XLAT'),
                            (4, 'IOMMU_XLAT')):
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

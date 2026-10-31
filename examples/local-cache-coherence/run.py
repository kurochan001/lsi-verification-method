#!/usr/bin/env python3
"""Coherent reads checked against an architectural memory with no caches."""
import importlib.util
from pathlib import Path
import random
import sys

HERE=Path(__file__).resolve().parent
NAME='local-cache-coherence';TOP='coherence_tb'
CONFIGS={'latency1':{'LATENCY':1},'latency3':{'LATENCY':3}}
ITERATIONS={'smoke':100,'nightly':1000}
SOURCES=[HERE/'rtl/coherent_pair.sv',HERE/'tb/coherence_tb.sv']


class Plan:
    def __init__(self,latency):
        self.latency=latency;self.memory=[0]*16;self.remaining=0
        self.valid=0;self.data=0;self.core=0;self.rows=[]

    def cycle(self,rst=1,valid=0,core=0,write=0,addr=0,data=0,ready=1):
        if not rst:
            self.memory=[0]*16;self.remaining=0;self.valid=0;self.data=0;self.core=0
        can_accept=int(bool(rst and not self.remaining and not self.valid))
        self.rows.append([rst,valid,core,write,addr,data,ready,can_accept,self.valid,self.core,self.data,
                          sum(word<<(32*i) for i,word in enumerate(self.memory))])
        if rst:
            if self.valid and ready:self.valid=0
            if self.remaining:
                self.remaining-=1
                if not self.remaining:self.valid=1
            if valid and can_accept:
                if write:self.memory[addr]=data
                self.data=self.memory[addr];self.core=core;self.remaining=self.latency
        return can_accept

    def transfer(self,core,addr,write=0,data=0,stall=0):
        # Request is held until accepted; response is held while ready=0.
        for _ in range(self.latency+4):
            if self.cycle(valid=1,core=core,addr=addr,write=write,data=data,ready=0):break
        else:raise ValueError('request not accepted')
        for _ in range(self.latency):self.cycle(ready=0)
        for _ in range(stall):self.cycle(valid=1,core=1-core,addr=15,ready=0)
        self.cycle()


def vectors(seed,iterations,latency,boundary=False):
    p=Plan(latency);p.cycle(rst=0)
    p.transfer(0,1);p.transfer(1,1);p.transfer(0,1) # S/S, read hit
    p.transfer(0,1,1,0xaabbccdd,3) # S->M, peer invalidate, held response
    p.transfer(0,1,1,0x12345678) # M hit
    p.transfer(1,1) # dirty forwarding M->S
    p.transfer(1,1,1,0xdeadbeef);p.transfer(0,1)
    p.transfer(0,2,1,0x24681357);p.transfer(0,3) # dirty eviction
    p.transfer(1,2);p.transfer(0,2);p.transfer(1,2,1,0x89abcdef)
    p.cycle(valid=1,core=1,addr=7);p.cycle(rst=0);p.transfer(0,2)
    if not boundary:
        rng=random.Random(seed)
        for _ in range(iterations):
            if rng.randrange(30)==0:p.cycle(rst=0)
            p.transfer(rng.randrange(2),rng.randrange(16),rng.randrange(2),rng.getrandbits(32),rng.randrange(4))
    p.cycle();return p.rows


def make_cases(args,parameters):
    latency=parameters['LATENCY'];base=vectors(args.seed,0,latency,True)
    cases=[dict(id='boundaries',vectors=base,mutation=args.demo_bug,expected_failure=None,category='functional')]
    for seed in range(args.seed,args.seed+(3 if args.profile=='nightly' else 1)):
        cases.append(dict(id=f'random-seed{seed}',vectors=vectors(seed,args.iterations,latency),mutation=args.demo_bug,expected_failure=None,category='functional'))
    for m in range(1,5):
        cases.append(dict(id=f'detect-mutation{m}',vectors=base,mutation=m,expected_failure='CACHE_RESPONSE' if m==4 else 'CACHE_DATA',category='mutation'))
    for c in cases:c['counts']={'steps':len(c['vectors'])}
    return cases


if __name__=='__main__':
    spec=importlib.util.spec_from_file_location('runner',HERE.parent/'local-common/runner.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    sys.exit(module.main(sys.modules[__name__]))

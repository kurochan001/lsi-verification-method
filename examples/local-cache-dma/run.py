#!/usr/bin/env python3
"""Explicit cache clean/invalidate around bypass DMA, eviction and stale-data scenarios."""
import importlib.util
from pathlib import Path
import random
import sys
HERE=Path(__file__).resolve().parent
NAME='local-cache-dma';TOP='cache_tb';CONFIGS={'one-line':dict(LINES=1,LATENCY=1),'two-lines':dict(LINES=2,LATENCY=3)}
ITERATIONS={'smoke':40,'nightly':250};SOURCES=[HERE/'rtl/cache_dma.sv',HERE/'tb/cache_tb.sv']
def merge(old,new,strobe):
    mask=sum(255<<(8*i) for i in range(4) if strobe&(1<<i))
    return (old&~mask)|(new&mask)
class Plan:
    def __init__(self,lines,latency):self.lines=lines;self.latency=latency;self.rows=[];self.reset()
    def reset(self):self.memory=[0]*16;self.cache={};self.pending=None;self.delay=0;self.response=None
    def cycle(self,rst=1,valid=0,op=0,addr=0,data=0,ready=1,debug=0,strb=15):
        if not rst:self.reset()
        available=int(bool(rst and self.pending is None and self.response is None))
        response=self.response or (0,0)
        self.rows.append([rst,valid,op,addr,data,ready,debug,strb,available,int(self.response is not None),*response,self.memory[debug]])
        if rst:
            if self.response is not None and ready:self.response=None
            if self.pending is not None:
                if self.delay:self.delay-=1
                else:
                    command,a,d,st=self.pending;self.pending=None;slot=a%self.lines;line=self.cache.get(slot);error=value=0
                    hit=line is not None and line[0]==a
                    if command in (1,2):
                        if not hit:
                            if line and line[2]:self.memory[line[0]]=line[1]
                            line=[a,self.memory[a],False];self.cache[slot]=line
                        if command==2:line[1]=merge(line[1],d,st);line[2]=True
                        else:value=line[1]
                    elif command==3:
                        if hit and line[2]:self.memory[a]=line[1];line[2]=False
                    elif command==4:
                        if hit and line[2]:error=1
                        elif hit:del self.cache[slot]
                    elif command==5:value=self.memory[a]
                    elif command==6:self.memory[a]=merge(self.memory[a],d,st)
                    else:error=1
                    self.response=(error,value)
            if available and valid:self.pending=(op,addr,data,strb);self.delay=self.latency
        return self.rows[-1]
    def command(self,op,addr=0,data=0,stall=0,strb=15):
        if not self.cycle(valid=1,op=op,addr=addr,data=data,ready=0,strb=strb)[8]:raise ValueError('request not accepted')
        for _ in range(self.latency+4):
            row=self.cycle(ready=0)
            if row[9]:break
        else:raise ValueError('missing response')
        for _ in range(stall):self.cycle(ready=0)
        self.cycle(ready=1)
        for a in range(16):self.cycle(debug=a)
def vectors(seed,iterations,parameters,boundary=False):
    p=Plan(parameters['LINES'],parameters['LATENCY']);p.cycle(rst=0)
    p.command(2,0,0x11223344);p.command(5,0);p.command(4,0);p.command(3,0);p.command(5,0)
    p.command(6,0,0xaabbccdd);p.command(1,0,stall=3);p.command(4,0);p.command(1,0)
    p.command(2,0,0x55667788,strb=5);p.command(1,0);p.command(6,0,0x11223344,strb=10);p.command(6,0,0xffffffff,strb=0);
    p.command(2,0,0x1357);p.command(2,parameters['LINES'],0x2468);p.command(5,0)
    p.command(1,0);p.command(0);p.cycle(valid=1,op=2,addr=1,data=99);p.cycle(rst=0);p.command(1,1)
    if not boundary:
        rng=random.Random(seed)
        for _ in range(iterations):p.command(rng.randint(1,6),rng.randrange(16),rng.getrandbits(32),rng.randrange(4),rng.randrange(16))
    p.cycle();return p.rows

def make_cases(args,parameters):
    base=vectors(args.seed,0,parameters,True)
    cs=[dict(id='boundaries',vectors=base,mutation=args.demo_bug,category='functional',expected_failure=None)]
    for seed in range(args.seed,args.seed+(3 if args.profile=='nightly' else 1)):
        cs.append(dict(id=f'random-seed{seed}',vectors=vectors(seed,args.iterations,parameters),mutation=args.demo_bug,category='functional',expected_failure=None))
    for m,label in ((1, 'CACHE_MEMORY'), (2, 'CACHE_DATA'), (3, 'CACHE_MEMORY'), (4, 'CACHE_MEMORY')):
        cs.append(dict(id=f'detect-mutation{m}',vectors=base,mutation=m,category='mutation',expected_failure=label))
    for c in cs:c['counts']={'steps':len(c['vectors'])}
    return cs

if __name__=='__main__':
    spec=importlib.util.spec_from_file_location('local_runner',HERE.parent/'local-common/runner.py')
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);sys.exit(m.main(sys.modules[__name__]))

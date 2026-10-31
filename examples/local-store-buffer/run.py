#!/usr/bin/env python3
"""Posted stores, own forwarding and fences, checked against ordered visibility events."""
import importlib.util
from pathlib import Path
import random
import sys
HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('store_litmus',HERE/'litmus.py')
L=importlib.util.module_from_spec(spec);spec.loader.exec_module(L)
NAME='local-store-buffer';TOP='ordering_tb'
CONFIGS={'depth2':{'DEPTH':2},'depth3':{'DEPTH':3}}
ITERATIONS={'smoke':180,'nightly':2000}
SOURCES=[HERE/'rtl/store_buffer.sv',HERE/'tb/ordering_tb.sv'];EXTRA_INPUTS=[HERE/'litmus.py']


class Plan:
    def __init__(self,depth):
        self.depth=depth;self.cw=depth.bit_length();self.rows=[];self.queue=[[],[]];self.memory=[0]*4;self.valid=0;self.response=(0,0,0)
        self.counts=dict(steps=0,stores=0,commits=0,loads=0,fences=0)

    def cycle(self,rst=1,valid=0,core=0,op=0,address=0,data=0,drain=None,ready=1,tag=0):
        if not rst:self.queue=[[],[]];self.memory=[0]*4;self.valid=0;self.response=(0,0,0)
        commit=int(bool(rst and drain is not None and self.queue[drain]))
        remaining=len(self.queue[core])-int(bool(commit and drain==core))
        accept=int(bool(rst and not self.valid and (op==0 or (op==1 and remaining<self.depth) or (op==2 and remaining==0))))
        self.rows.append([rst,valid,core,op,address,data,int(drain is not None),drain or 0,ready,tag,accept,commit,self.valid,*self.response,
                          sum(word<<(32*i) for i,word in enumerate(self.memory)),
                          len(self.queue[0])|(len(self.queue[1])<<self.cw)])
        self.counts['steps']+=1
        if not rst:return accept
        if self.valid and ready:self.valid=0
        if commit:
            addr,value=self.queue[drain].pop(0);self.memory[addr]=value;self.counts['commits']+=1
        if valid and accept:
            value=0
            if op==0:
                matching=[v for a,v in self.queue[core] if a==address]
                value=matching[-1] if matching else self.memory[address];self.counts['loads']+=1
            if op==1:self.queue[core].append((address,data));value=data;self.counts['stores']+=1
            if op==2:self.counts['fences']+=1
            self.response=(core,op,value);self.valid=1
        return accept

    def transfer(self,core,op,address=0,data=0,drain=None,stall=0):
        if not self.cycle(valid=1,core=core,op=op,address=address,data=data,drain=drain):raise ValueError('request blocked')
        for _ in range(stall):self.cycle(ready=0)
        self.cycle()


def vectors(seed,iterations,depth,boundary=False):
    p=Plan(depth);p.cycle(rst=0)
    p.transfer(0,1,0,0x11);p.transfer(0,0,0);p.transfer(1,0,0)
    p.transfer(0,1,0,0x22);p.cycle(valid=1,core=0,op=2)
    p.cycle(drain=0);p.transfer(1,0,0);p.transfer(1,0,0,drain=0,stall=2);p.transfer(0,2)
    for i in range(depth):p.transfer(1,1,(i+1)%4,0x30+i)
    p.cycle(valid=1,core=1,op=1,address=3,data=99)
    p.transfer(1,1,3,99,drain=1)
    while p.queue[1]:p.cycle(drain=1)
    p.transfer(0,1,2,123);p.cycle(rst=0)
    for fenced in (False,True):
        for outcome,events in sorted(L.explore(fenced)['witnesses'].items()):
            p.cycle(rst=0,tag=2 if fenced else 1)
            for event in events:
                if event[0]=='issue':_,core,op,address,data=event;p.transfer(core,op,address,data)
                else:p.cycle(drain=event[1])
            p.cycle(tag=4 if fenced else 3)
    if not boundary:
        rng=random.Random(seed)
        for _ in range(iterations):
            core=rng.randrange(2);op=rng.randrange(3);address=rng.randrange(4);data=rng.getrandbits(32)
            drain=rng.choice((None,0,1))
            if p.cycle(valid=1,core=core,op=op,address=address,data=data,drain=drain):
                for _ in range(rng.randrange(3)):p.cycle(ready=0,drain=rng.choice((None,0,1)))
                p.cycle()
        for core in (0,1):
            while p.queue[core]:p.cycle(drain=core)
    p.cycle();return p.rows,p.counts


def make_cases(args,parameters):
    depth=parameters['DEPTH'];base,counts=vectors(args.seed,0,depth,True)
    cases=[dict(id='boundaries',vectors=base,counts=counts,mutation=args.demo_bug,expected_failure=None,category='functional')]
    for seed in range(args.seed,args.seed+(3 if args.profile=='nightly' else 1)):
        rows,stats=vectors(seed,args.iterations,depth)
        cases.append(dict(id=f'random-seed{seed}',vectors=rows,counts=stats,mutation=args.demo_bug,expected_failure=None,category='functional'))
    for m,label in ((1,'ORDER_DATA'),(2,'ORDER_FLOW'),(3,'ORDER_MEMORY'),(4,'ORDER_DATA')):
        cases.append(dict(id=f'detect-mutation{m}',vectors=base,counts=counts,mutation=m,expected_failure=label,category='mutation'))
    return cases


if __name__=='__main__':
    spec=importlib.util.spec_from_file_location('runner',HERE.parent/'local-common/runner.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);sys.exit(module.main(sys.modules[__name__]))

#!/usr/bin/env python3
import importlib.util
from pathlib import Path
import random
import sys
HERE=Path(__file__).resolve().parent
NAME='local-counter-snapshot';TOP='counter_tb';CONFIGS={'wait0': {'WAIT_CYCLES': 0}, 'wait2': {'WAIT_CYCLES': 2}}
ITERATIONS={'smoke': 20, 'nightly': 150};SOURCES=[HERE/'rtl/counter.sv',HERE/'tb/counter_tb.sv']
MASK=(1<<64)-1
class Plan:
    def __init__(self,wait):self.wait=wait;self.rows=[];self.reset()
    def reset(self):self.count=0;self.pending=0;self.snap=None;self.load=0;self.cmp_low=0;self.compare=0;self.enabled=0;self.irq_en=0;self.left=0
    def cycle(self,rst=1,sel=0,enable=0,write=0,addr=0,data=0):
        if not rst:self.reset()
        ready=int(bool(rst and sel and enable and self.left==0));bad=addr not in (0,4,8,12,16,20,24,28) or bool(write and addr in (0,4));err=int(ready and bad)
        reads={0:self.count&0xffffffff,4:(self.snap if self.snap is not None else self.count>>32),16:self.compare&0xffffffff,20:self.compare>>32,24:self.enabled|self.irq_en<<1,28:self.pending}
        value=reads.get(addr,0);self.rows.append([rst,sel,enable,write,addr,data,ready,err,value,self.count,self.pending,int(bool(self.pending and self.irq_en)),int(self.snap is not None)])
        if rst:
            old=self.count;hit=self.enabled and ((old+1)&MASK)==self.compare
            if self.enabled:self.count=(old+1)&MASK
            if sel and not enable:self.left=self.wait
            elif sel and enable and self.left:self.left-=1
            if ready and not bad:
                if write:
                    if addr==8:self.load=data
                    elif addr==12:self.count=((data<<32)|self.load)&MASK;self.snap=None;hit=False
                    elif addr==16:self.cmp_low=data
                    elif addr==20:self.compare=(data<<32)|self.cmp_low
                    elif addr==24:self.enabled=data&1;self.irq_en=(data>>1)&1
                    elif addr==28 and data&1:self.pending=0
                elif addr==0:self.snap=old>>32
                elif addr==4:self.snap=None
            if hit:self.pending=1
    def access(self,addr,write=0,data=0):
        self.cycle(sel=1,write=write,addr=addr,data=data)
        for _ in range(self.wait+1):self.cycle(sel=1,enable=1,write=write,addr=addr,data=data)
        self.cycle()
    def load_count(self,value):self.access(8,1,value&0xffffffff);self.access(12,1,value>>32)
def vectors(seed,iterations,parameters,boundary=False):
    p=Plan(parameters['WAIT_CYCLES']);p.cycle(rst=0)
    p.load_count(0x5fffffffc);p.access(0);p.access(24,1,3)
    for _ in range(12):p.cycle()
    p.access(4);p.access(0);p.access(4);p.access(24,1,0)
    p.load_count(MASK-2);p.access(24,1,3)
    for _ in range(8):p.cycle()
    p.access(24,1,0);p.load_count(100);p.access(16,1,150);p.access(20,1,0);p.access(24,1,3)
    while p.count<150-(p.wait+2):p.cycle()
    p.access(28,1,1);p.access(28);p.access(28,1,1)
    # While counting, LOAD_HI lands on a match edge and COMPARE_HI lands where only the new value would match.
    p.access(24,1,0);p.load_count(990);p.access(16,1,1000);p.access(20,1,0);p.access(8,1,0x12345678);p.access(24,1,1)
    while p.count+p.wait+2<1000:p.cycle()
    p.access(12,1,0);target=p.count+20;p.access(16,1,target)
    while p.count+p.wait+2<target:p.cycle()
    p.access(20,1,0);p.access(28);p.access(24,1,0)
    p.access(0);p.cycle(rst=0);p.access(0);p.access(4);p.access(3)
    if not boundary:
        rng=random.Random(seed)
        for _ in range(iterations):
            p.access(24,1,0);p.load_count(rng.getrandbits(64));p.access(24,1,3);p.access(0)
            for _ in range(rng.randrange(10)):p.cycle()
            p.access(4)
    return p.rows

def make_cases(args,parameters):
    base=vectors(args.seed,0,parameters,True)
    cs=[dict(id='boundaries',vectors=base,mutation=args.demo_bug,category='functional',expected_failure=None)]
    for seed in range(args.seed,args.seed+(3 if args.profile=='nightly' else 1)):
        cs.append(dict(id=f'random-seed{seed}',vectors=vectors(seed,args.iterations,parameters),mutation=args.demo_bug,category='functional',expected_failure=None))
    for mutation,label in [(1, 'COUNT_READ'), (2, 'COUNT_STATE'), (3, 'COUNT_IRQ'), (4, 'COUNT_READ')]:
        cs.append(dict(id=f'detect-mutation{mutation}',vectors=base,mutation=mutation,category='mutation',expected_failure=label))
    for c in cs:c['counts']={'steps':len(c['vectors'])}
    return cs
if __name__=='__main__':
    spec=importlib.util.spec_from_file_location('local_runner',HERE.parent/'local-common/runner.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);sys.exit(m.main(sys.modules[__name__]))

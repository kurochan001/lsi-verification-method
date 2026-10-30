#!/usr/bin/env python3
"""Priority interrupt selection, claim/complete, pending retention and reassertion."""
import importlib.util
from pathlib import Path
import random
import sys
HERE=Path(__file__).resolve().parent
NAME='local-priority-irq';TOP='priority_irq_tb';CONFIGS={'level':dict(LEVEL=1,WAIT_CYCLES=1),'edge':dict(LEVEL=0,WAIT_CYCLES=2)}
ITERATIONS={'smoke':32,'nightly':250};SOURCES=[HERE/'rtl/priority_irq.sv',HERE/'tb/priority_irq_tb.sv']
class Plan:
    def __init__(self,level,wait):self.level=level;self.wait=wait;self.rows=[];self.reset()
    def reset(self):self.pending=set();self.service=set();self.enables=set();self.priorities=[0]*4;self.threshold=0;self.previous=0;self.remaining=0
    def cycle(self,rst=1,sel=0,enable=0,write=0,addr=0,data=0,sources=0):
        if not rst:self.reset()
        choices=[i for i in self.pending if i in self.enables and self.priorities[i]>0]
        winner=min(choices,key=lambda i:(-self.priorities[i],i)) if choices else None
        ready=int(bool(rst and sel and enable and not self.remaining))
        mapped=addr in (0,4,8,12,16,32,36,40,44)
        bad=not mapped or (write and addr in (8,12)) or (write and addr==16 and data-1 not in self.service)
        values={0:sum(1<<i for i in self.enables),4:self.threshold,8:sum(1<<i for i in self.pending),12:sum(1<<i for i in self.service),16:0 if winner is None else winner+1,**{32+4*i:p for i,p in enumerate(self.priorities)}}
        irq=int(bool(rst and winner is not None and self.priorities[winner]>self.threshold))
        self.rows.append([rst,sel,enable,write,addr,data,sources,ready,int(ready and bad),irq,values.get(addr,0),values[8],values[12]])
        if rst:
            arrivals=sources if self.level else sources&~self.previous;self.previous=sources
            self.pending|={i for i in range(4) if arrivals&(1<<i) and i not in self.service}
            if sel and not enable:self.remaining=self.wait
            elif sel and enable and self.remaining:self.remaining-=1
            if ready and not bad:
                if write:
                    if addr==0:self.enables={i for i in range(4) if data&(1<<i)}
                    elif addr==4:self.threshold=data&3
                    elif addr==16:self.service.remove(data-1)
                    elif addr>=32:self.priorities[(addr-32)//4]=data&3
                elif addr==16 and winner is not None:self.pending.discard(winner);self.service.add(winner)
        return ready,values.get(addr,0),bad
    def transfer(self,addr,write=0,data=0,sources=0):
        self.cycle(sel=1,addr=addr,write=write,data=data,sources=sources)
        for _ in range(self.wait+2):
            ready,value,bad=self.cycle(sel=1,enable=1,addr=addr,write=write,data=data,sources=sources)
            if ready:break
        else:raise ValueError('APB did not finish')
        self.cycle(sources=sources);return value
    def pulse(self,mask):self.cycle(sources=0);self.cycle(sources=mask);self.cycle(sources=0)
def vectors(seed,iterations,parameters,boundary=False):
    p=Plan(parameters['LEVEL'],parameters['WAIT_CYCLES']);p.cycle(rst=0)
    for i in range(4):p.transfer(32+4*i,1,2)
    p.pulse(15);p.transfer(8);p.transfer(0,1,15)
    p.transfer(4,1,2);p.transfer(16);p.transfer(4,1,0) # threshold suppresses IRQ, not claim
    p.transfer(16);p.transfer(16);p.transfer(16);p.transfer(16)
    p.transfer(16,1,0);p.transfer(16,1,1);p.pulse(1);p.transfer(16);p.transfer(16,1,1,sources=1);p.cycle(sources=1);p.transfer(8,sources=1)
    p.cycle(rst=0)
    for i in range(4):p.transfer(32+4*i,1,i%3+1)
    p.transfer(0,1,15);p.pulse(15);p.transfer(16);p.transfer(24,1,1);p.transfer(8,1,15);p.transfer(12,1,15) # RO writes: error, no side effect
    if not boundary:
        rng=random.Random(seed)
        for _ in range(iterations):
            p.pulse(rng.randrange(16));p.transfer(rng.choice((0,4,8,12,16,32,36,40,44)),rng.randrange(2),rng.randrange(16))
    p.cycle(rst=0);p.cycle();return p.rows

def make_cases(args,parameters):
    base=vectors(args.seed,0,parameters,True)
    cs=[dict(id='boundaries',vectors=base,mutation=args.demo_bug,category='functional',expected_failure=None)]
    for seed in range(args.seed,args.seed+(3 if args.profile=='nightly' else 1)):
        cs.append(dict(id=f'random-seed{seed}',vectors=vectors(seed,args.iterations,parameters),mutation=args.demo_bug,category='functional',expected_failure=None))
    for m,label in ((1, 'PRIO_READ'), (2, 'PRIO_IRQ'), (3, 'PRIO_SERVICE'), (4, 'PRIO_PENDING')):
        cs.append(dict(id=f'detect-mutation{m}',vectors=base,mutation=m,category='mutation',expected_failure=label))
    for c in cs:c['counts']={'steps':len(c['vectors'])}
    return cs

if __name__=='__main__':
    spec=importlib.util.spec_from_file_location('local_runner',HERE.parent/'local-common/runner.py')
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);sys.exit(m.main(sys.modules[__name__]))

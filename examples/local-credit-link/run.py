#!/usr/bin/env python3
"""Two credit-based virtual channels: accounting, data order, starvation and reset."""
from collections import deque
import importlib.util
from pathlib import Path
import random
import sys
HERE=Path(__file__).resolve().parent
NAME='local-credit-link';TOP='credit_tb';CONFIGS={f'depth{d}':dict(DEPTH=d) for d in (2,4)}
ITERATIONS={'smoke':100,'nightly':1000};SOURCES=[HERE/'rtl/credit_link.sv',HERE/'tb/credit_tb.sv']
class Plan:
    def __init__(self,depth):self.depth=depth;self.rows=[];self.reset()
    def reset(self):self.queue=[deque(),deque()];self.outstanding=[0,0];self.order=[0,1];self.bad=0;self.offer=None
    def cycle(self,rst=1,valid=0,channel=0,data=0,returns=0):
        if not rst:self.reset()
        if rst and self.offer is not None:valid=1;channel,data=self.offer
        credit=[self.depth-n for n in self.outstanding];chosen=next((c for c in self.order if self.queue[c] and credit[c]),None)
        tx=int(bool(rst and chosen is not None));ch=chosen if tx else 0;payload=self.queue[ch][0] if tx else 0
        ready=int(bool(rst and len(self.queue[channel])<self.depth));queued=len(self.queue[0])|(len(self.queue[1])<<4)
        self.rows.append([rst,valid,channel,data,returns,ready,tx,ch,payload,credit[0]|credit[1]<<4,queued,self.bad])
        if rst:
            self.offer=(channel,data) if valid and not ready else None
            self.bad=int(any(returns&(1<<c) and self.outstanding[c]==0 for c in range(2)))
            old=list(self.outstanding)
            if tx:self.queue[ch].popleft();self.outstanding[ch]+=1;self.order=[1-ch,ch]
            if valid and ready:self.queue[channel].append(data)
            for c in range(2):
                if returns&(1<<c) and old[c]>0:self.outstanding[c]-=1
        return self.rows[-1]
    def drain(self):
        for _ in range(200):
            if not any(self.queue) and not any(self.outstanding) and self.offer is None:break
            self.cycle(returns=sum(1<<c for c in range(2) if self.outstanding[c]>0))
        else:raise ValueError('drain did not complete')
        self.cycle()
def vectors(seed,iterations,parameters,boundary=False):
    d=parameters['DEPTH'];p=Plan(d);p.cycle(rst=0);p.cycle(returns=3);p.cycle()
    for c in range(2):
        for i in range(2*d+3):p.cycle(valid=1,channel=c,data=c*80+i)
    for _ in range(3):p.cycle()
    p.drain()
    for i in range(16):p.cycle(valid=1,channel=i%2,data=i,returns=sum(1<<c for c in range(2) if p.outstanding[c]>0))
    p.drain();p.cycle(valid=1,data=99);p.cycle();p.cycle(rst=0);p.cycle(valid=1,channel=1,data=55);p.drain()
    p.cycle(valid=1,data=7);p.cycle(returns=1);p.drain() # excess return on the same edge as a send
    if not boundary:
        rng=random.Random(seed)
        for _ in range(iterations):
            ret=sum(1<<c for c in range(2) if p.outstanding[c] and rng.randrange(3)==0)
            p.cycle(valid=rng.randrange(2),channel=rng.randrange(2),data=rng.randrange(256),returns=ret)
            if rng.randrange(80)==0:p.cycle(rst=0)
    p.drain();return p.rows

def make_cases(args,parameters):
    base=vectors(args.seed,0,parameters,True)
    cs=[dict(id='boundaries',vectors=base,mutation=args.demo_bug,category='functional',expected_failure=None)]
    for seed in range(args.seed,args.seed+(3 if args.profile=='nightly' else 1)):
        cs.append(dict(id=f'random-seed{seed}',vectors=vectors(seed,args.iterations,parameters),mutation=args.demo_bug,category='functional',expected_failure=None))
    for m,label in ((1, 'CREDIT_COUNT'), (2, 'CREDIT_CONTROL'), (3, 'CREDIT_DATA'), (4, 'CREDIT_COUNT')):
        cs.append(dict(id=f'detect-mutation{m}',vectors=base,mutation=m,category='mutation',expected_failure=label))
    for c in cs:c['counts']={'steps':len(c['vectors'])}
    return cs

if __name__=='__main__':
    spec=importlib.util.spec_from_file_location('local_runner',HERE.parent/'local-common/runner.py')
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);sys.exit(m.main(sys.modules[__name__]))

#!/usr/bin/env python3
"""Clock stop/drain/wakeup and asynchronous reset assertion with synchronous release."""
import importlib.util
from pathlib import Path
import random
import sys
HERE=Path(__file__).resolve().parent
NAME='local-clock-reset';TOP='clock_reset_tb';CONFIGS={f'sync{s}':dict(STAGES=s,LATENCY=4) for s in (2,3)}
ITERATIONS={'smoke':24,'nightly':160};SOURCES=[HERE/'rtl/clock_reset.sv',HERE/'tb/clock_reset_tb.sv']
class Plan:
    def __init__(self,stages,latency):self.stages=stages;self.latency=latency;self.state=0;self.pipe=0;self.remaining=0;self.acc=0;self.completed=0;self.operand=0;self.rows=[]
    def cycle(self,rst=1,reset=1,stop=0,wake=0,valid=0,data=0):
        if not rst:self.state=0
        if not rst or not reset:self.pipe=0;self.remaining=0;self.acc=0;self.completed=0;self.operand=0
        enabled=int(self.state!=2 or not rst);released=(self.pipe>>(self.stages-1))&1
        ready=int(bool(rst and released and self.state==0 and not stop and not self.remaining))
        self.rows.append([rst,reset,stop,wake,valid,data,ready,int(self.state==2),enabled,released,self.acc,self.completed])
        pending=bool(self.remaining)
        if enabled and rst and reset:
            self.pipe=((self.pipe<<1)|1)&((1<<self.stages)-1)
            if not released:self.remaining=0;self.acc=0;self.completed=0;self.operand=0
            else:
                if self.remaining:
                    self.remaining-=1
                    if not self.remaining:self.acc=(self.acc+self.operand)&255;self.completed+=1
                if ready and valid:self.operand=data;self.remaining=self.latency
        if rst:
            if self.state==0 and stop:self.state=1
            elif self.state==1 and not pending:self.state=2
            elif self.state==2 and wake:self.state=3
            elif self.state==3 and released:self.state=0
        return self.rows[-1]
    def idle(self,n=1,**kw):
        for _ in range(n):self.cycle(**kw)
    def operation(self,data):
        for _ in range(30):
            if self.cycle(valid=1,data=data)[6]:break
        else:raise ValueError('no ready')
    def nap(self,reset=False):
        for _ in range(30):
            if self.cycle(stop=1,valid=1,data=99)[7]:break
        else:raise ValueError('did not stop')
        self.idle(4,stop=1,valid=1,data=88)
        if reset:self.cycle(reset=0,stop=1);self.idle(3,stop=1)
        self.cycle(wake=1);self.idle(self.stages+4)
def vectors(seed,iterations,stages,latency,boundary=False):
    p=Plan(stages,latency);p.cycle(rst=0);p.idle(stages+2)
    p.operation(0x35);p.nap();p.operation(7);p.idle(latency+2);p.nap(True)
    p.operation(9);p.cycle(reset=0);p.idle(stages+2);p.operation(11);p.idle(latency+2);p.nap()
    if not boundary:
        rng=random.Random(seed)
        for _ in range(iterations):
            p.operation(rng.randrange(256));p.idle(rng.randrange(latency+2));p.nap(rng.randrange(4)==0)
    p.cycle(rst=0);p.idle(stages+3);return p.rows
def make_cases(args,parameters):
    s=parameters['STAGES'];l=parameters['LATENCY'];base=vectors(args.seed,0,s,l,True)
    cs=[dict(id='boundaries',vectors=base,mutation=args.demo_bug,category='functional',expected_failure=None)]
    for seed in range(args.seed,args.seed+(3 if args.profile=='nightly' else 1)):
        cs.append(dict(id=f'random-seed{seed}',vectors=vectors(seed,args.iterations,s,l),mutation=args.demo_bug,category='functional',expected_failure=None))
    for m,label in ((1,'CLOCK_CONTROL'),(2,'CLOCK_CONTROL'),(3,'CLOCK_DATA'),(4,'CLOCK_CONTROL')):
        cs.append(dict(id=f'detect-mutation{m}',vectors=base,mutation=m,category='mutation',expected_failure=label))
    for c in cs:c['counts']={'steps':len(c['vectors'])}
    return cs

if __name__=='__main__':
    spec=importlib.util.spec_from_file_location('local_runner',HERE.parent/'local-common/runner.py')
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);sys.exit(m.main(sys.modules[__name__]))

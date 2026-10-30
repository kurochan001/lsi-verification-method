#!/usr/bin/env python3
"""Power sequencing, drain, isolation and retention in a digital behavioral model."""
import importlib.util
from pathlib import Path
import random
import sys
HERE=Path(__file__).resolve().parent
NAME='local-power';TOP='power_tb'
CONFIGS={f'latency{n}':dict(LATENCY=n) for n in (1,3)}
ITERATIONS={'smoke':24,'nightly':200}
SOURCES=[HERE/'rtl/power_island.sv',HERE/'tb/power_tb.sv']

class Oracle:
    def __init__(self,latency):self.latency=latency;self.time=0;self.reset()
    def reset(self):self.mode=0;self.due=None;self.acc=0;self.saved=0;self.keep=0;self.operand=0;self.done=0
    def step(self,inputs):
        rst,sleep,wake,retain,valid,data=inputs
        if not rst:self.reset()
        ready=int(rst and self.mode==0 and not sleep and self.due is None)
        isolated=int(self.mode>=3);power=int(self.mode!=4)
        pre=[ready,power,isolated,power,int(self.mode==4),self.done,0 if isolated else self.acc]
        if rst:
            old_pending=self.due is not None;self.done=0
            if old_pending and power and self.time==self.due:
                self.acc=(self.acc+self.operand)&255;self.due=None;self.done=1
            if valid and ready:self.operand=data;self.due=self.time+self.latency+1
            if self.mode==0 and sleep:self.mode=1;self.keep=retain
            elif self.mode==1 and not old_pending:self.mode=2
            elif self.mode==2:
                if self.keep:self.saved=self.acc
                self.mode=3
            elif self.mode==3:self.mode=4
            elif self.mode==4 and wake:self.mode=5
            elif self.mode==5:self.acc=0;self.mode=6
            elif self.mode==6:self.acc=self.saved if self.keep else 0;self.mode=0
        self.time+=1
        return [*inputs,*pre]

class Plan:
    def __init__(self,latency):self.model=Oracle(latency);self.rows=[]
    def cycle(self,rst=1,sleep=0,wake=0,retain=0,valid=0,data=0):
        r=self.model.step([rst,sleep,wake,retain,valid,data]);self.rows.append(r);return r
    def idle(self,n=1,**kw):
        for _ in range(n):self.cycle(**kw)
    def operation(self,data):
        for _ in range(30):
            if self.cycle(valid=1,data=data)[6]:break
        else:raise ValueError('operation not accepted')
        self.idle(self.model.latency+2)
    def nap(self,keep,pending=False):
        if pending:self.cycle(valid=1,data=7)
        for _ in range(30):
            # retain is offered only on the accepting edge, then inverted until OFF.
            if self.cycle(sleep=1,retain=keep if self.model.mode==0 else 1-keep,valid=1,data=99)[10]:break
        else:raise ValueError('sleep did not drain')
        self.idle(3,sleep=1,retain=1-keep)
        self.cycle(wake=1)
        self.idle(4)

def boundary_vectors(latency):
    p=Plan(latency);p.cycle(rst=0);p.operation(0x31);p.nap(1,True);p.operation(3)
    p.nap(0);p.operation(0x77);p.nap(1)
    p.cycle(sleep=1);p.cycle(wake=1);p.cycle(rst=0);p.idle(3)
    p.nap(1);p.cycle(rst=0);p.idle(2);return p.rows

def random_vectors(seed,iterations,latency):
    rng=random.Random(seed);p=Plan(latency);p.cycle(rst=0)
    for _ in range(iterations):
        p.operation(rng.randrange(256));p.nap(rng.randrange(2),bool(rng.randrange(2)))
        if rng.randrange(5)==0:p.cycle(rst=0)
    p.cycle(rst=0);p.idle(2);return p.rows

def counts(rows):
    return dict(accepted=sum(bool(r[0] and r[4] and r[6]) for r in rows),completed=sum(r[11] for r in rows),
                off_cycles=sum(r[10] for r in rows))
def make_cases(args,parameters):
    latency=parameters['LATENCY'];baseline=boundary_vectors(latency)
    cases=[dict(id='boundaries',vectors=baseline,mutation=args.demo_bug,category='functional',expected_failure=None)]
    for seed in range(args.seed,args.seed+(3 if args.profile=='nightly' else 1)):
        cases.append(dict(id=f'random-seed{seed}',vectors=random_vectors(seed,args.iterations,latency),mutation=args.demo_bug,category='functional',expected_failure=None))
    for m,label in ((1,'POWER_ISOLATION'),(2,'POWER_DATA'),(3,'POWER_ISOLATION'),(4,'POWER_CONTROL')):
        cases.append(dict(id=f'detect-mutation{m}',vectors=baseline,mutation=m,category='mutation',expected_failure=label))
    for c in cases:c['counts']=counts(c['vectors'])
    return cases
if __name__=='__main__':
    spec=importlib.util.spec_from_file_location('local_runner',HERE.parent/'local-common/runner.py')
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);sys.exit(m.main(sys.modules[__name__]))

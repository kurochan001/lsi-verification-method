#!/usr/bin/env python3
"""Signed two-tap fixed-point arithmetic, rounding, saturation and handshake timing."""
import importlib.util
from pathlib import Path
import random
import sys
HERE=Path(__file__).resolve().parent
NAME='local-dsp';TOP='dsp_tb';CONFIGS={'q3-latency1':dict(FRAC=3,LATENCY=1),'q4-latency3':dict(FRAC=4,LATENCY=3)}
ITERATIONS={'smoke':64,'nightly':500}
SOURCES=[HERE/'rtl/fir2.sv',HERE/'tb/dsp_tb.sv']
def signed(value):return value if value<128 else value-256
def quantize(accumulator,frac):
    whole,remainder=divmod(abs(accumulator),1<<frac)
    rounded=(whole+int(2*remainder>=(1<<frac)))*(1 if accumulator>=0 else -1)
    return max(-128,min(127,rounded))&255,int(not -128<=rounded<=127)
class Oracle:
    def __init__(self,frac,latency):self.frac=frac;self.latency=latency;self.time=0;self.reset()
    def reset(self):self.previous=0;self.pending=None;self.output=None
    def step(self,inputs):
        rst,valid,sample,c0,c1,ready=inputs
        if not rst:self.reset()
        take=int(bool(rst and self.pending is None and self.output is None))
        pre=[take,int(self.output is not None),*(self.output or (0,0))]
        if rst:
            if self.output is not None and ready:self.output=None
            if self.pending and self.time==self.pending[0]:self.output=self.pending[1];self.pending=None
            if valid and take:
                acc=signed(sample)*signed(c0)+self.previous*signed(c1);self.previous=signed(sample)
                self.pending=(self.time+self.latency,quantize(acc,self.frac))
        self.time+=1;return [*inputs,*pre]
class Plan:
    def __init__(self,frac,latency):self.model=Oracle(frac,latency);self.rows=[]
    def cycle(self,rst=1,valid=0,sample=0,c0=0,c1=0,ready=1):
        row=self.model.step([rst,valid,sample&255,c0&255,c1&255,ready]);self.rows.append(row);return row
    def operation(self,sample,c0,c1,stall=0):
        self.cycle(valid=1,sample=sample,c0=c0,c1=c1);blocked=dict(valid=1,sample=0x5a,c0=0x33,c1=0x77) # offered but not accepted
        for _ in range(self.model.latency+1+stall):self.cycle(ready=0,**blocked)
        self.cycle(**blocked);self.cycle()
def boundary_vectors(frac,latency):
    p=Plan(frac,latency);p.cycle(rst=0)
    for x,a,b in [(0,0,0),(127,1<<frac,0),(-128,1<<frac,0),(1,1<<(frac-1),0),(-1,1<<(frac-1),0),(3,3,0),(-3,3,0),(127,127,127),(-128,127,127),(-128,127,0),(17,-7,13),(0,0,16)]:p.operation(x,a,b,3)
    p.cycle(valid=1,sample=55,c0=12,c1=0);p.cycle(rst=0);p.cycle();p.operation(0,0,127)
    p.cycle(rst=0);p.cycle();return p.rows
def random_vectors(seed,iterations,frac,latency):
    rng=random.Random(seed);p=Plan(frac,latency);p.cycle(rst=0)
    for _ in range(iterations):p.operation(*(rng.randrange(-128,128) for _ in range(3)),stall=rng.randrange(7))
    p.cycle(rst=0);p.cycle();return p.rows
def counts(rows):
    return dict(accepted=sum(bool(r[0] and r[1] and r[6]) for r in rows),completed=sum(bool(r[7] and r[5]) for r in rows),
                clipped=sum(bool(r[7] and r[5] and r[9]) for r in rows))
def make_cases(args,parameters):
    f,l=parameters['FRAC'],parameters['LATENCY'];baseline=boundary_vectors(f,l)
    cases=[dict(id='boundaries',vectors=baseline,mutation=args.demo_bug,category='functional',expected_failure=None)]
    for seed in range(args.seed,args.seed+(3 if args.profile=='nightly' else 1)):
        cases.append(dict(id=f'random-seed{seed}',vectors=random_vectors(seed,args.iterations,f,l),mutation=args.demo_bug,category='functional',expected_failure=None))
    for m in range(1,5):cases.append(dict(id=f'detect-mutation{m}',vectors=baseline,mutation=m,category='mutation',expected_failure='DSP_DATA'))
    for c in cases:c['counts']=counts(c['vectors'])
    return cases
if __name__=='__main__':
    spec=importlib.util.spec_from_file_location('local_runner',HERE.parent/'local-common/runner.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);sys.exit(m.main(sys.modules[__name__]))

#!/usr/bin/env python3
"""Load, capture, unload: run generated ATPG patterns through real scan RTL."""
import importlib.util
from pathlib import Path
import random
import sys

HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('scan_atpg_model',HERE/'atpg.py')
A=importlib.util.module_from_spec(spec);spec.loader.exec_module(A)
NAME='local-scan-atpg';TOP='scan_tb'
CONFIGS={'forward':{'REVERSE':0},'reverse':{'REVERSE':1}}
ITERATIONS={'smoke':80,'nightly':1000}
SOURCES=[HERE/'rtl/scan_logic.sv',HERE/'tb/scan_tb.sv'];EXTRA_INPUTS=[HERE/'atpg.py']


class Plan:
    def __init__(self,reverse):self.reverse=reverse;self.q=0;self.good=0;self.rows=[]

    def cycle(self,rst=1,se=0,si=0,x=0,fault=None,phase=0):
        if not rst:self.q=self.good=0
        site,value=fault if fault else (0,0)
        so=(self.q>>(0 if self.reverse else 3))&1
        good_so=(self.good>>(0 if self.reverse else 3))&1
        self.rows.append([rst,se,si,x,int(fault is not None),site,value,self.q,so,phase,good_so])
        if rst:
            if se:
                self.q=(self.q>>1)|(si<<3) if self.reverse else ((self.q<<1)|si)&15
                self.good=(self.good>>1)|(si<<3) if self.reverse else ((self.good<<1)|si)&15
            else:
                self.good=A.functional(self.q,x);self.q=A.faulty(self.q,x,fault)

    def pattern(self,q,x,fault=None):
        load=range(4) if self.reverse else range(3,-1,-1)
        for bit in load:self.cycle(se=1,si=(q>>bit)&1,phase=1)
        self.cycle(x=x,fault=fault,phase=2)
        for _ in range(4):self.cycle(se=1,x=x,fault=fault,phase=3)


def vectors(seed,iterations,reverse,boundary=False):
    p=Plan(reverse);p.cycle(rst=0)
    # Exhaust every fault-free assignment; ATPG then exercises all named faults.
    for q in range(16):
        for x in range(4):p.pattern(q,x)
    for fault in A.FAULTS:
        for q,x in A.report()['patterns']:p.pattern(q,x,fault)
    p.cycle(rst=0)
    if not boundary:
        rng=random.Random(seed)
        for _ in range(iterations):
            p.cycle(se=rng.randrange(2),si=rng.randrange(2),x=rng.randrange(4))
    p.cycle();return p.rows


def make_cases(args,parameters):
    reverse=parameters['REVERSE'];base=vectors(args.seed,0,reverse,True)
    cases=[dict(id='boundaries',vectors=base,mutation=args.demo_bug,expected_failure=None,category='functional')]
    for seed in range(args.seed,args.seed+(3 if args.profile=='nightly' else 1)):
        cases.append(dict(id=f'random-seed{seed}',vectors=vectors(seed,args.iterations,reverse),mutation=args.demo_bug,expected_failure=None,category='functional'))
    for m,label in ((1,'SCAN_SHIFT'),(2,'SCAN_SHIFT'),(3,'SCAN_CAPTURE'),(4,'SCAN_CAPTURE')):
        cases.append(dict(id=f'detect-mutation{m}',vectors=base,mutation=m,expected_failure=label,category='mutation'))
    for c in cases:c['counts']={'steps':len(c['vectors']),'detectable_faults':A.report()['detectable']}
    return cases


if __name__=='__main__':
    spec=importlib.util.spec_from_file_location('runner',HERE.parent/'local-common/runner.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    sys.exit(module.main(sys.modules[__name__]))

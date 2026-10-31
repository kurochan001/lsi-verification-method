#!/usr/bin/env python3
"""SHA-256 with hashlib oracle, bounded padding and iterative compression."""
import hashlib
import importlib.util
from pathlib import Path
import random
import sys
HERE=Path(__file__).resolve().parent
NAME='local-sha256'
TOP='sha256_tb'
CONFIGS={'round1':{'ROUNDS':1},'round2':{'ROUNDS':2}}
ITERATIONS={'smoke':12,'nightly':60}
SOURCES=[HERE/'rtl/sha256_engine.sv',HERE/'tb/sha256_tb.sv']

class Plan:
    # Control timing only; digest values come from a separate standard-library implementation.
    def __init__(self,rounds):
        self.rounds=rounds;self.rows=[];self.reset()
    def reset(self):
        self.state='idle';self.valid=0;self.error=0;self.digest=0;self.data=bytearray();self.size=0;self.left=0;self.block=0
    def cycle(self,rst=1,cmd=0,length=0,valid=0,data=0,ready=1):
        cr=int(rst and self.state=='idle' and not self.valid);br=int(rst and self.state=='load')
        self.rows.append([rst,cmd,length,valid,data,ready,cr,br,int(rst and self.valid),self.error,self.digest])
        if not rst:self.reset();return cr,br
        if self.valid and ready:self.valid=0
        if cr and cmd:
            self.size=length;self.data=bytearray();self.error=int(length>119);self.block=0
            if self.error:self.valid=1;self.digest=0
            else:self.state='load' if length else 'pad'
        elif self.state=='load' and valid:
            self.data.append(data)
            if len(self.data)==self.size:self.state='pad'
        elif self.state=='pad':self.state='init'
        elif self.state=='init':self.state='round';self.left=64//self.rounds
        elif self.state=='round':
            self.left-=1
            if not self.left:
                if self.size>55 and self.block==0:self.block=1;self.state='init'
                else:self.digest=int.from_bytes(hashlib.sha256(self.data).digest(),'big');self.valid=1;self.state='idle'
        return cr,br
    def message(self,data,hold=0,gaps=False):
        assert len(data)<=119
        while not self.cycle(cmd=1,length=len(data))[0]:pass
        for i,b in enumerate(data):
            if gaps and i%3==0:self.cycle(data=0xde)
            assert self.cycle(valid=1,data=b,cmd=1,length=127)[1]
        while not self.valid:self.cycle(cmd=1,length=127,valid=1,data=0xba)
        for _ in range(hold):self.cycle(ready=0,cmd=1,length=127)
        self.cycle();self.cycle()

def vectors(seed,iterations,rounds):
    p=Plan(rounds);p.cycle(rst=0)
    p.message(b'',3);p.message(b'abc',3)
    for n in (1,55,56,63,64,65,119):p.message(bytes((i*17+n)%256 for i in range(n)),2,True)
    for n in (120,127):p.cycle(cmd=1,length=n);p.cycle(ready=0);p.cycle();p.cycle()
    p.cycle(cmd=1,length=10);p.cycle(valid=1,data=0x41);p.cycle(rst=0) # cancel partial input
    p.cycle(cmd=1,length=0);p.cycle();p.cycle();p.cycle();p.cycle(rst=0) # cancel compression
    p.message(b'after reset')
    rng=random.Random(seed)
    for _ in range(iterations):p.message(rng.randbytes(rng.randrange(120)),rng.randrange(4),True)
    p.cycle();return p.rows

def make_cases(args,parameters):
    rounds=parameters['ROUNDS'];base=vectors(args.seed,0,rounds)
    def case(name,rows,m,expected=None,category='functional'):
        return dict(id=name,vectors=rows,counts={'steps':len(rows)},mutation=m,expected_failure=expected,category=category)
    cases=[case('boundaries',base,args.demo_bug)]
    for seed in range(args.seed,args.seed+(3 if args.profile=='nightly' else 1)):
        cases.append(case(f'random-seed{seed}',vectors(seed,args.iterations,rounds),args.demo_bug))
    cases += [case(f'detect-mutation{m}',base,m,'SHA_DIGEST','mutation') for m in range(1,5)]
    return cases

if __name__=='__main__':
    spec=importlib.util.spec_from_file_location('runner',HERE.parent/'local-common/runner.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);sys.exit(module.main(sys.modules[__name__]))

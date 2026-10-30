#!/usr/bin/env python3
"""APB access denial, no side effects and one-way configuration locks."""
import importlib.util
from pathlib import Path
import random
import sys
HERE=Path(__file__).resolve().parent
NAME='local-access-control';TOP='access_tb';CONFIGS={f'wait{w}':dict(WAIT_CYCLES=w) for w in (0,2)}
ITERATIONS={'smoke':40,'nightly':300};SOURCES=[HERE/'rtl/protected_regs.sv',HERE/'tb/access_tb.sv']
class Plan:
    def __init__(self,wait):self.wait=wait;self.remaining=0;self.values={0:0,16:0,20:0};self.rows=[]
    def cycle(self,rst=1,sel=0,enable=0,write=0,addr=0,data=0,prot=1):
        if not rst:self.remaining=0;self.values={0:0,16:0,20:0}
        authority=bool(prot&1 and not prot&6)
        deny=addr not in self.values or (addr in (16,20) and not authority) or (write and addr==16 and self.values[20])
        ready=int(bool(rst and sel and enable and self.remaining==0));err=int(bool(ready and deny))
        read=self.values.get(addr,0) if not deny else 0
        self.rows.append([rst,sel,enable,write,addr,data,prot,ready,err,read,self.values[0],self.values[16],self.values[20]])
        if rst:
            if sel and not enable:self.remaining=self.wait
            elif sel and enable and self.remaining:self.remaining-=1
            if ready and write and not deny:
                if addr==20:self.values[20]|=data&1
                else:self.values[addr]=data
        return ready
    def transfer(self,addr,write=0,data=0,prot=1):
        self.cycle(sel=1,addr=addr,write=write,data=data,prot=prot)
        for _ in range(self.wait+2):
            if self.cycle(sel=1,enable=1,addr=addr,write=write,data=data,prot=prot):break
        else:raise ValueError('no APB completion')
        self.cycle()
def vectors(seed,iterations,wait,boundary=False):
    p=Plan(wait);p.cycle(rst=0);p.cycle()
    p.transfer(16,1,0xaabbccdd);p.transfer(16)
    for prot in range(8):
        p.transfer(0,1,0x12340000+prot,prot);p.transfer(0,prot=prot)
        p.transfer(16,1,0xdeadbeef,prot);p.transfer(16,prot=prot)
    p.transfer(24,1,0x78);p.transfer(0x30,1,0x55);p.transfer(0x80);p.transfer(0x94,1,1);p.transfer(20,1,1);p.transfer(16,1,99);p.transfer(20,1,0);p.transfer(16)
    p.cycle(rst=0);p.transfer(16,1,0x1357);p.transfer(16)
    if not boundary:
        rng=random.Random(seed)
        for _ in range(iterations):
            if rng.randrange(9)==0:p.cycle(rst=0)
            p.transfer(rng.choice((0,16,20,24,0x30,0x80,0x94)),rng.randrange(2),rng.getrandbits(32),rng.randrange(8))
    p.cycle();return p.rows
def make_cases(args,parameters):
    wait=parameters['WAIT_CYCLES'];base=vectors(args.seed,0,wait,True)
    cs=[dict(id='boundaries',vectors=base,mutation=args.demo_bug,expected_failure=None,category='functional')]
    for seed in range(args.seed,args.seed+(3 if args.profile=='nightly' else 1)):
        cs.append(dict(id=f'random-seed{seed}',vectors=vectors(seed,args.iterations,wait),mutation=args.demo_bug,expected_failure=None,category='functional'))
    for m,label in ((1,'ACCESS_RESPONSE'),(2,'ACCESS_RESPONSE'),(3,'ACCESS_STATE'),(4,'ACCESS_READ')):
        cs.append(dict(id=f'detect-mutation{m}',vectors=base,mutation=m,expected_failure=label,category='mutation'))
    for c in cs:c['counts']={'steps':len(c['vectors'])}
    return cs

if __name__=='__main__':
    spec=importlib.util.spec_from_file_location('local_runner',HERE.parent/'local-common/runner.py')
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);sys.exit(m.main(sys.modules[__name__]))

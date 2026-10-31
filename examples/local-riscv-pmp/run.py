#!/usr/bin/env python3
"""PMP checking by byte membership, independently of RTL interval overlap."""
import importlib.util
from pathlib import Path
import random
import sys

HERE=Path(__file__).resolve().parent
NAME='local-riscv-pmp'; TOP='pmp_tb'
CONFIGS={'pa16':{'AW':16},'pa18':{'AW':18}}
ITERATIONS={'smoke':120,'nightly':1500}
SOURCES=[HERE/'rtl/pmp.sv',HERE/'tb/pmp_tb.sv']


class Plan:
    def __init__(self,aw):
        self.aw=aw;self.cfg=[0]*4;self.pa=[0]*4;self.rows=[]

    def region(self,i):
        mode=(self.cfg[i]>>3)&3;p=self.pa[i]
        if mode==0:return range(0)
        if mode==1:return range(self.pa[i-1]*4 if i else 0,p*4)
        if mode==2:return range(p*4,p*4+4)
        # Decode from the first zero bit, using integer arithmetic.
        k=0
        while p&(1<<k):k+=1
        length=1<<(k+3);base=(p*4)//length*length
        return range(base,base+length)

    def check(self,address,size,kind,machine):
        byte_addresses=range(address,address+(1<<size));hit=4;allow=bool(machine)
        for i in range(4):
            region=self.region(i)
            inside=[byte in region for byte in byte_addresses]
            if any(inside):
                hit=i
                permission=bool(self.cfg[i]&(1<<kind)) if kind<3 else False
                allow=all(inside) and (permission or (machine and not self.cfg[i]&128))
                break
        if size==3 or kind==3 or byte_addresses.stop>1<<self.aw:allow=False
        return int(allow),hit

    def cycle(self,rst=1,cfg=0,pa=0,index=0,data=0,address=0,size=0,kind=0,machine=0):
        if not rst:self.cfg=[0]*4;self.pa=[0]*4
        allow,hit=self.check(address,size,kind,machine)
        self.rows.append([rst,cfg,pa,index,data,address,size,kind,machine,allow,hit,
                          sum(v<<(8*i) for i,v in enumerate(self.cfg)),
                          sum(v<<((self.aw-2)*i) for i,v in enumerate(self.pa))])
        if rst:
            locked=bool(self.cfg[index]&128)
            tor_locked=index<3 and self.cfg[index+1]&128 and (self.cfg[index+1]>>3)&3==1
            if cfg and not locked:self.cfg[index]=(data&0x9d)|((data&2) if data&1 else 0)
            if pa and not locked and not tor_locked:self.pa[index]=data&((1<<(self.aw-2))-1)

    def entry(self,i,mode,base,permission=7,lock=False,length=8):
        address=base//4 if mode!=3 else base//4+(length//8-1)
        self.cycle(pa=1,index=i,data=address)
        self.cycle(cfg=1,index=i,data=(mode<<3)|permission|(128 if lock else 0))


def vectors(seed,iterations,aw,boundary=False):
    p=Plan(aw);p.cycle(rst=0);p.cycle(machine=1);p.cycle()
    p.entry(0,1,0x100,1)
    for addr in (0,0xfc,0xff,0x100):
        for kind in range(3):p.cycle(address=addr,size=2,kind=kind)
    p.cycle(address=0x20,kind=1,machine=1) # unlocked M bypass
    p.entry(1,2,0x100,5)
    p.cycle(address=0x100,kind=2);p.cycle(address=0x101,size=2,machine=1)
    p.entry(2,3,0,7,length=512) # lower-priority wider region
    p.cycle(address=0x20,kind=1);p.cycle(address=0xfe,size=2)
    p.cycle(address=0x180,kind=1);p.cycle(address=0x180,kind=2)
    p.entry(3,1,0x400,1,True)
    p.cycle(address=0x300,kind=1,machine=1) # locked denies M
    p.cycle(pa=1,index=2,data=0x123);p.cycle(cfg=1,index=3,data=0)
    p.cycle(pa=1,index=3,data=0);p.cycle(address=0x300)
    p.cycle(rst=0);p.entry(0,3,0,7,length=1<<aw)
    p.cycle(address=(1<<aw)-1,size=2);p.cycle(address=(1<<aw)-4,size=2)
    p.cycle(rst=0);p.entry(0,1,0x100,0,True);p.entry(1,1,0x80,7)
    p.cycle(address=0x120);p.cycle(cfg=1,index=2,data=2) # WARL reserved RW
    if not boundary:
        rng=random.Random(seed)
        for _ in range(iterations):
            if rng.randrange(12)==0:p.cycle(rst=0)
            index=rng.randrange(4)
            p.cycle(cfg=1,index=index,data=rng.choice((0,8,16,24))+rng.choice((0,1,3,4,5,7))+rng.choice((0,0,128)))
            p.cycle(pa=1,index=index,data=rng.getrandbits(aw-2))
            region=p.region(index)
            candidates=[rng.randrange(1<<aw),0,(1<<aw)-1]
            if region:candidates += [max(0,min((1<<aw)-1,x)) for x in (region.start-1,region.start,region.stop-1,region.stop)]
            for address in candidates:
                p.cycle(address=address,size=rng.randrange(3),kind=rng.randrange(3),machine=rng.randrange(2))
    p.cycle();return p.rows


def make_cases(args,parameters):
    aw=parameters['AW'];base=vectors(args.seed,0,aw,True)
    cases=[dict(id='boundaries',vectors=base,mutation=args.demo_bug,expected_failure=None,category='functional')]
    for seed in range(args.seed,args.seed+(3 if args.profile=='nightly' else 1)):
        cases.append(dict(id=f'random-seed{seed}',vectors=vectors(seed,args.iterations,aw),mutation=args.demo_bug,expected_failure=None,category='functional'))
    for m,label in ((1,'PMP_DECISION'),(2,'PMP_DECISION'),(3,'PMP_DECISION'),(4,'PMP_STATE')):
        cases.append(dict(id=f'detect-mutation{m}',vectors=base,mutation=m,expected_failure=label,category='mutation'))
    for c in cases:c['counts']={'steps':len(c['vectors'])}
    return cases


if __name__=='__main__':
    spec=importlib.util.spec_from_file_location('runner',HERE.parent/'local-common/runner.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    sys.exit(module.main(sys.modules[__name__]))

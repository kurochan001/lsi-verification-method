#!/usr/bin/env python3
"""Sv32 walks checked against a transaction-level page-table interpreter."""
import importlib.util
from pathlib import Path
import random
import sys

HERE=Path(__file__).resolve().parent
NAME='local-sv32';TOP='sv32_tb'
CONFIGS={'wait0':{'WAIT_CYCLES':0},'wait2':{'WAIT_CYCLES':2}}
ITERATIONS={'smoke':80,'nightly':800}
SOURCES=[HERE/'rtl/sv32_walk.sv',HERE/'tb/sv32_tb.sv']


def translate(va,root,kind,user,sum_enable,mxr,memory,bare=False):
    """Return the complete read trace and architectural result; no clock state."""
    if bare:return [],va,0
    reads=[];table=root*4096
    for level in (1,0):
        index=(va//(4096*(1024**level)))%1024;address=table+4*index
        pte=memory.get(address,0);error=pte is None
        reads.append((address,0 if error else pte,int(error)))
        if error:return reads,0,2
        v,r,w,x,u,a,d=(bool(pte&(1<<b)) for b in (0,1,2,3,4,6,7))
        if not v or (w and not r):return reads,0,1
        if not (r or x):
            if level==0 or u or a or d:return reads,0,1
            table=(pte//1024)*4096;continue
        page_size=4096*(1024**level);base=(pte//1024)*4096
        allowed=(r or (mxr and x)) if kind==0 else w if kind==1 else x if kind==2 else False
        privilege=u if user else not u or (sum_enable and kind!=2)
        if base%page_size or not allowed or not privilege or not a or (kind==1 and not d):return reads,0,1
        return reads,base+(va%page_size),0
    raise AssertionError('walk must finish in two levels')


class Plan:
    def __init__(self,wait):
        self.wait=wait;self.rows=[];self.reads=[];self.reply=None;self.result=(0,0);self.valid=0

    def cycle(self,rst=1,request=None,ready=1,mem_ready=1):
        if not rst:self.reads=[];self.reply=None;self.valid=0;self.result=(0,0)
        fields=request or dict(va=0,root=0,kind=0,user=0,sum_enable=0,mxr=0,memory={},bare=0)
        can_accept=int(bool(rst and not self.reads and not self.valid))
        mem_addr,pte,error=self.reads[0] if self.reads else (0,0,0)
        self.rows.append([rst,int(request is not None),fields['bare'],fields['user'],fields['sum_enable'],fields['mxr'],
                          fields['va'],fields['root'],fields['kind'],ready,mem_ready,pte,error,
                          can_accept,int(bool(self.reads)),mem_addr,self.valid,*self.result])
        if rst:
            if self.valid and ready:self.valid=0
            if self.reads and mem_ready:
                self.reads.pop(0)
                if not self.reads:self.result=self.reply;self.valid=1
            if request and can_accept:
                reads,pa,fault=translate(**fields)
                self.reads=list(reads);self.reply=(pa,fault);self.result=(0,0)
                if not reads:self.result=self.reply;self.valid=1
        return can_accept

    def transfer(self,*,va=0x81234567,root=0x3fffff,kind=0,user=1,sum_enable=0,mxr=0,
                 memory=None,bare=0,stall=0):
        request=dict(va=va,root=root,kind=kind,user=user,sum_enable=sum_enable,mxr=mxr,memory=memory or {},bare=bare)
        if not self.cycle(request=request):raise ValueError('request blocked')
        while self.reads:
            for _ in range(self.wait):self.cycle(mem_ready=0)
            self.cycle()
        for _ in range(stall):self.cycle(ready=0)
        self.cycle()


def page_table(va,root,l1,l0=0):
    memory={root*4096+((va>>22)&1023)*4:l1}
    if (l1&15)==1:memory[(l1>>10)*4096+((va>>12)&1023)*4]=l0
    return memory


def vectors(seed,iterations,wait,boundary=False):
    p=Plan(wait);p.cycle(rst=0);va=0x81234567;root=0x3fffff;pointer=(0x2fffff<<10)|1
    def run(l1,l0=0,**options):p.transfer(memory=page_table(va,root,l1,l0),**options)
    p.transfer(bare=1,va=0xffffffff,stall=3)
    run(pointer,(0x3abcde<<10)|0xdf,stall=2) # 4K, PA above 32 bits
    run((0x300000<<10)|0xdf) # aligned 4M
    run((0x300001<<10)|0xdf) # misaligned 4M
    run(pointer,(0x1234<<10)|0x59,mxr=1) # execute-only readable with MXR
    run(pointer,(0x1234<<10)|0x59,mxr=0)
    run(pointer,(0x1234<<10)|0xdf,user=0,sum_enable=1) # S data in U page
    run(pointer,(0x1234<<10)|0xdf,user=0,sum_enable=1,kind=2) # forbidden even with SUM
    run(pointer,(0x1234<<10)|0xcf) # U in supervisor page
    run(pointer,(0x1234<<10)|0x9f) # A=0
    run(pointer,(0x1234<<10)|0x5f,kind=1) # D=0
    run(pointer,(0x1234<<10)|0xd5,kind=1) # reserved R=0,W=1
    run(0);run(pointer,1) # invalid V, last-level non-leaf
    run(pointer|0x40) # reserved A on non-leaf
    p.transfer(memory={root*4096+((va>>22)&1023)*4:None})
    p.cycle(request=dict(va=va,root=root,kind=0,user=1,sum_enable=0,mxr=0,memory=page_table(va,root,pointer,0xdf),bare=0))
    p.cycle(mem_ready=0);p.cycle(rst=0);p.transfer(bare=1,va=123)
    if not boundary:
        rng=random.Random(seed)
        for _ in range(iterations):
            address=rng.getrandbits(32);root=rng.getrandbits(22);ptr=(rng.getrandbits(22)<<10)|1
            flags=rng.randrange(256);ppn=rng.getrandbits(22)
            if rng.randrange(2):l1=ptr;l0=(ppn<<10)|flags
            else:l1=((ppn&~1023)<<10)|flags;l0=0
            p.transfer(va=address,root=root,kind=rng.randrange(3),user=rng.randrange(2),sum_enable=rng.randrange(2),mxr=rng.randrange(2),
                       memory=page_table(address,root,l1,l0),stall=rng.randrange(3))
    p.cycle();return p.rows


def make_cases(args,parameters):
    wait=parameters['WAIT_CYCLES'];base=vectors(args.seed,0,wait,True)
    cases=[dict(id='boundaries',vectors=base,mutation=args.demo_bug,expected_failure=None,category='functional')]
    for seed in range(args.seed,args.seed+(3 if args.profile=='nightly' else 1)):
        cases.append(dict(id=f'random-seed{seed}',vectors=vectors(seed,args.iterations,wait),mutation=args.demo_bug,expected_failure=None,category='functional'))
    for m in range(1,5):cases.append(dict(id=f'detect-mutation{m}',vectors=base,mutation=m,expected_failure='VM_RESULT',category='mutation'))
    for c in cases:c['counts']={'steps':len(c['vectors'])}
    return cases


if __name__=='__main__':
    spec=importlib.util.spec_from_file_location('runner',HERE.parent/'local-common/runner.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);sys.exit(module.main(sys.modules[__name__]))

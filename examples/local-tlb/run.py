#!/usr/bin/env python3
"""Sv32 TLB integration: interval-based translation cache and quiescent SFENCE."""
import importlib.util
from pathlib import Path
import random
import sys
HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('tlb_walk_model',HERE.parent/'local-sv32/run.py')
W=importlib.util.module_from_spec(spec);spec.loader.exec_module(W)
NAME='local-tlb';TOP='tlb_tb'
CONFIGS={'entries2':{'ENTRIES':2},'entries4':{'ENTRIES':4}}
ITERATIONS={'smoke':80,'nightly':600}
SOURCES=[HERE/'rtl/sv32_tlb.sv',W.HERE/'rtl/sv32_walk.sv',HERE/'tb/tlb_tb.sv'];EXTRA_INPUTS=[W.HERE/'run.py']


class Plan:
    def __init__(self,entries):
        self.entries=entries;self.cache=[None]*entries;self.next=0;self.rows=[]
        self.phase='idle';self.valid=0;self.result=(0,0);self.reads=[];self.fill=None

    def lookup(self,q):
        if q['bare']:return None
        return next((e for e in self.cache if e and q['va'] in e['range'] and (e['global'] or e['asid']==q['asid'])),None)

    def cycle(self,rst=1,request=None,fence=None,ready=1,mem_ready=1):
        if not rst:
            self.cache=[None]*self.entries;self.next=0;self.phase='idle';self.valid=0;self.result=(0,0);self.reads=[];self.fill=None
        q=request or dict(va=0,root=0,asid=0,kind=0,user=0,sum_enable=0,mxr=0,bare=0,memory={})
        f=fence or (0,0,0,0);fready=int(bool(rst and self.phase=='idle' and not self.valid));accept=int(bool(fready and fence is None))
        entry=self.lookup(q);hit=int(bool(request and accept and entry));memory_valid=int(self.phase=='reads')
        address,data,error=self.reads[0] if memory_valid else (0,0,0)
        self.rows.append([rst,int(request is not None),q['bare'],q['user'],q['sum_enable'],q['mxr'],q['va'],q['root'],q['asid'],q['kind'],
                          int(fence is not None),*f,ready,mem_ready,data,error,accept,hit,fready,memory_valid,address,self.valid,*self.result])
        if not rst:return accept,fready
        if self.valid and ready:self.valid=0
        if self.phase=='start':self.phase='reads'
        elif self.phase=='reads' and mem_ready:
            self.reads.pop(0)
            if not self.reads:self.phase='capture'
        elif self.phase=='capture':
            self.phase='idle';self.valid=1;self.result=self.reply
            if self.fill:self.cache[self.next]=self.fill;self.next=(self.next+1)%self.entries
        if fence is not None and fready:
            av,sv,va,asid=f
            self.cache=[None if e and (not av or va in e['range']) and (not sv or (not e['global'] and e['asid']==asid)) else e for e in self.cache]
        if request and accept:
            if entry:
                flags=entry['flags'];allowed=(bool(flags&2) or (q['mxr'] and flags&8)) if q['kind']==0 else bool(flags&4) if q['kind']==1 else bool(flags&8) if q['kind']==2 else False
                privilege=bool(flags&16) if q['user'] else not flags&16 or (q['sum_enable'] and q['kind']!=2)
                ok=allowed and privilege and flags&64 and (q['kind']!=1 or flags&128)
                self.result=(entry['base']+q['va']-entry['range'].start,0) if ok else (0,1);self.valid=1
            else:
                fields={k:v for k,v in q.items() if k!='asid'};reads,pa,fault=W.translate(**fields)
                if q['bare']:self.result=(pa,fault);self.valid=1
                else:
                    self.phase='start';self.reads=list(reads);self.reply=(pa,fault);self.result=(0,0);self.fill=None
                    flags,large,global_entry=W.metadata(reads,fault)
                    if not fault:
                        size=4194304 if large else 4096;begin=q['va']//size*size
                        self.fill={'range':range(begin,begin+size),'base':pa-q['va']%size,'flags':flags,'global':global_entry,'asid':q['asid']}
        return accept,fready

    def transfer(self,memory,va=0x40001020,asid=0,kind=0,user=1,sum_enable=0,mxr=0,bare=0,stall=0):
        q=dict(va=va,root=asid+1,asid=asid,kind=kind,user=user,sum_enable=sum_enable,mxr=mxr,bare=bare,memory=memory)
        if not self.cycle(request=q)[0]:raise ValueError('blocked request')
        while not self.valid:self.cycle(mem_ready=0) if self.phase=='reads' and len(self.rows)%3==0 else self.cycle()
        for _ in range(stall):self.cycle(ready=0)
        self.cycle()

    def fence(self,av=0,sv=0,va=0,asid=0):
        f=(av,sv,va,asid)
        while not self.cycle(fence=f)[1]:pass
        self.cycle()


def mapping(memory,va,asid,ppn,flags=0xdf,large=False,global_parent=False):
    root=asid+1
    if large:memory[root*4096+(va>>22)*4]=(ppn<<10)|flags
    else:
        table=0x200+asid*1024+(va>>22)
        memory[root*4096+(va>>22)*4]=(table<<10)|1|(32 if global_parent else 0)
        memory[table*4096+((va>>12)&1023)*4]=(ppn<<10)|flags


def vectors(seed,iterations,entries,boundary=False):
    p=Plan(entries);m={};a=0x40001020;b=a+4096;g=0x60001020;s=0x80401000;d=0x70001020
    asids=(0,1,2,3,0x101,0x1ff)
    for asid in asids:
        mapping(m,a,asid,0x10000+asid*0x1000);mapping(m,b,asid,0x20000+asid*0x1000)
        mapping(m,g,asid,0x33000,global_parent=True)
        mapping(m,s,asid,0x300000,large=True);mapping(m,d,asid,0x44000,flags=0x5f)
    p.cycle(rst=0);p.transfer(m);p.transfer(m,va=a+7,stall=2);p.transfer(m,va=b);p.transfer(m,asid=1);p.transfer(m,asid=0x101)
    p.transfer(m,va=g);p.transfer(m,va=g,asid=2);p.fence(sv=1,asid=0);p.transfer(m,va=g,asid=3)
    p.fence(av=1,va=g);p.transfer(m,va=g)
    p.fence();p.transfer(m,va=s);p.transfer(m,va=s+0x201234)
    p.fence(av=1,sv=1,va=s+0x123000,asid=0);mapping(m,s,0,0x310000,large=True);p.transfer(m,va=s+0x201234)
    p.transfer(m,va=d);p.transfer(m,va=d,kind=1)
    p.transfer(m,va=0xdead0000);p.transfer(m,va=0xffffffff,bare=1)
    p.cycle(rst=0)
    for i in range(entries+1):
        va=0x50000000+i*4096;mapping(m,va,0,0x50000+i);p.transfer(m,va=va)
    p.transfer(m,va=0x50000000)
    p.cycle(rst=0)
    q=dict(va=a,root=1,asid=0,kind=0,user=1,sum_enable=0,mxr=0,bare=0,memory=m)
    p.cycle(request=q);p.cycle(fence=(1,0,a,0),mem_ready=0)
    while not p.valid:p.cycle(fence=(1,0,a,0))
    p.cycle(fence=(1,0,a,0),ready=0);p.cycle(fence=(1,0,a,0))
    p.cycle(request=q,fence=(1,0,a,0));p.transfer(m)
    p.fence();p.cycle(request=q);p.cycle();p.cycle(rst=0);p.transfer(m)
    if not boundary:
        rng=random.Random(seed)
        for _ in range(iterations):
            if rng.randrange(6)==0:p.fence(rng.randrange(2),rng.randrange(2),rng.choice((a,b,g,s,d)),rng.choice(asids))
            p.transfer(m,va=rng.choice((a,b,g,s,d))+rng.randrange(16),asid=rng.choice(asids),kind=rng.randrange(3),
                       user=rng.randrange(2),sum_enable=rng.randrange(2),mxr=rng.randrange(2),stall=rng.randrange(3))
    p.cycle();return p.rows


def make_cases(args,parameters):
    entries=parameters['ENTRIES'];base=vectors(args.seed,0,entries,True)
    cases=[dict(id='boundaries',vectors=base,mutation=args.demo_bug,expected_failure=None,category='functional')]
    for seed in range(args.seed,args.seed+(3 if args.profile=='nightly' else 1)):
        cases.append(dict(id=f'random-seed{seed}',vectors=vectors(seed,args.iterations,entries),mutation=args.demo_bug,expected_failure=None,category='functional'))
    for m in range(1,5):cases.append(dict(id=f'detect-mutation{m}',vectors=base,mutation=m,expected_failure='TLB_RESULT' if m==4 else 'TLB_FLOW',category='mutation'))
    for c in cases:c['counts']={'steps':len(c['vectors'])}
    return cases


if __name__=='__main__':
    spec=importlib.util.spec_from_file_location('runner',HERE.parent/'local-common/runner.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);sys.exit(module.main(sys.modules[__name__]))

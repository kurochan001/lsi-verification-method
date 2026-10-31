#!/usr/bin/env python3
"""Abstract DRAM command scheduler with absolute-time reference and native memory model."""
import importlib.util
from pathlib import Path
import random
import sys
HERE=Path(__file__).resolve().parent
NAME='local-dram'
TOP='dram_tb'
CONFIGS={'fast':dict(TRCD=2,TRP=2,TRAS=3,TWR=6,TRFC=5,CL=2,TREFI=24),
         'slow':dict(TRCD=3,TRP=3,TRAS=5,TWR=8,TRFC=7,CL=3,TREFI=36)}
ITERATIONS={'smoke':40,'nightly':300}
SOURCES=[HERE/'rtl/dram_controller.sv',HERE/'tb/dram_tb.sv']
class Plan:
    def __init__(self,params):self.p=params;self.t=0;self.rows=[];self.reset()
    def reset(self):
        self.open=[None,None];self.col_at=[0,0];self.pre_at=[0,0];self.act_at=[0,0]
        self.quiet_at=0;self.refresh_origin=self.t+1;self.state='idle';self.response=None;self.request=None;self.due=0;self.mem={}
    def cycle(self,rst=1,req=None,ready=1):
        p,t=self.p,self.t;refresh=t-self.refresh_origin>=p['TREFI'];cmd=0;bank=0
        can=int(rst and self.state=='idle' and self.response is None and not refresh and t>=self.quiet_at)
        if rst and t>=self.quiet_at:
            if self.state=='idle' and refresh:
                opened=next((b for b in range(2) if self.open[b] is not None),None)
                if opened is not None:
                    bank=opened
                    if t>=self.pre_at[bank]:cmd=4
                elif t>=max(self.act_at):cmd=5
            elif self.state=='access':
                write,bank,row,col,data=self.request
                if self.open[bank] is None:
                    if t>=self.act_at[bank]:cmd=1
                elif self.open[bank]!=row:
                    if t>=self.pre_at[bank]:cmd=4
                elif t>=self.col_at[bank]:cmd=3 if write else 2
        r=(0,1,3,3,0xa5a5a5a5) if req is None else req
        self.rows.append([rst,int(req is not None),*r,ready,can,int(rst and self.response is not None),0 if self.response is None else self.response,cmd])
        if not rst:self.reset()
        else:
            if self.response is not None and ready:self.response=None
            if can and req is not None:
                self.request=req;self.state='access'
                if req[0]:self.mem[req[1:4]]=req[4]
                else:self.expected=self.mem.get(req[1:4],0)
            elif self.state=='read' and t==self.due:self.response=self.expected;self.state='idle'
            if cmd==1:
                self.open[bank]=self.request[2];self.col_at[bank]=t+p['TRCD'];self.pre_at[bank]=t+p['TRAS']
            elif cmd==2:self.state='read';self.due=t+p['CL']
            elif cmd==3:self.pre_at[bank]=max(self.pre_at[bank],t+p['TWR']);self.response=0;self.state='idle'
            elif cmd==4:self.open[bank]=None;self.act_at[bank]=t+p['TRP']
            elif cmd==5:self.refresh_origin=t+1;self.quiet_at=t+p['TRFC']
        self.t+=1;return can
    def access(self,write,bank,row,col,data=0,hold=0):
        req=(write,bank,row,col,data)
        while not self.cycle(req=req):pass
        while self.response is None:self.cycle()
        for _ in range(hold):self.cycle(ready=0)
        value=self.response;self.cycle();self.cycle();return value

def vectors(seed,iterations,params):
    p=Plan(params);p.cycle(rst=0)
    # Every cell has a distinct value; a wrong column cannot hide behind zero-filled memory.
    for bank in range(2):
        for row in range(4):
            for col in range(4):p.access(1,bank,row,col,0x12340000|(bank<<8)|(row<<4)|col)
    for bank in range(2):
        for row in range(4):
            for col in range(4):p.access(0,bank,row,col)
    p.access(1,0,0,0,0x89abcdef);p.access(0,0,1,0) # write recovery before conflicting row
    p.access(0,1,3,2,hold=params['TREFI']+2*params['TRFC']) # refresh while response held
    for _ in range(params['TREFI']+params['TRFC']):p.cycle()
    while not p.cycle(req=(0,0,2,1,0)):pass
    p.cycle(rst=0);p.access(0,0,2,1) # fixture reset clears memory and cancels work
    rng=random.Random(seed)
    for _ in range(iterations):p.access(rng.randrange(2),rng.randrange(2),rng.randrange(4),rng.randrange(4),rng.getrandbits(32),rng.randrange(4))
    p.cycle();return p.rows

def make_cases(args,parameters):
    base=vectors(args.seed,0,parameters)
    def case(name,rows,m,expected=None,category='functional'):
        return dict(id=name,vectors=rows,counts={'steps':len(rows)},mutation=m,expected_failure=expected,category=category)
    cases=[case('boundaries',base,args.demo_bug)]
    for seed in range(args.seed,args.seed+(3 if args.profile=='nightly' else 1)):
        cases.append(case(f'random-seed{seed}',vectors(seed,args.iterations,parameters),args.demo_bug))
    for m,label in ((1,'DRAM_TIMING'),(2,'DRAM_STATE'),(3,'DRAM_TIMING'),(4,'DRAM_ADDRESS')):
        cases.append(case(f'detect-mutation{m}',base,m,label,'mutation'))
    return cases
if __name__=='__main__':
    spec=importlib.util.spec_from_file_location('runner',HERE.parent/'local-common/runner.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);sys.exit(module.main(sys.modules[__name__]))

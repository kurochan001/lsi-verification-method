#!/usr/bin/env python3
"""SECDED memory: repair writeback, scrub/write races, fault notification."""
import importlib.util
from pathlib import Path
import random
import sys
HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('ecc_codebook',HERE.parent/'local-ecc/run.py');ECC=importlib.util.module_from_spec(spec);spec.loader.exec_module(ECC)
NAME='local-ecc-memory';TOP='ecc_memory_tb';CONFIGS={f'depth{d}':dict(DEPTH=d) for d in (4,8)}
ITERATIONS={'smoke':50,'nightly':400}
SOURCES=[HERE.parent/'local-ecc/rtl/secded.sv',HERE/'rtl/ecc_memory.sv',HERE/'tb/ecc_memory_tb.sv'];EXTRA_INPUTS=[Path(ECC.__file__)]
class Plan:
    def __init__(self,depth):self.depth=depth;self.mem=[0]*depth;self.cursor=0;self.sc=self.su=0;self.rows=[]
    def cycle(self,rst=1,wr=0,rd=0,scrub=0,inject=0,addr=0,ia=0,data=0,mask=0):
        if not rst:self.mem=[0]*self.depth;self.cursor=0;self.sc=self.su=0
        fixed,value,c,u=ECC.decode(self.mem[addr]);sf,sv,sc,su=ECC.decode(self.mem[self.cursor])
        self.rows.append([rst,wr,rd,scrub,inject,addr,ia,data,mask,value,int(rd and c),int(rd and u),self.cursor,self.sc,self.su])
        if rst:
            old=list(self.mem);cursor=self.cursor;self.sc=self.su=0
            if scrub:
                self.sc=sc;self.su=su
                if sc:self.mem[cursor]=sf
                self.cursor=(cursor+1)%self.depth
            if rd and c:self.mem[addr]=fixed
            if wr:self.mem[addr]=ECC.CODEBOOK[data]
            if inject:self.mem[ia]=old[ia]^mask
    def at(self,index):
        while self.cursor!=index:self.cycle(scrub=1)
def vectors(seed,iterations,depth,boundary=False):
    p=Plan(depth);p.cycle(rst=0)
    for a in range(depth):p.cycle(wr=1,addr=a,data=(a*37+0x23)%256)
    # Each bit corrected by foreground read and re-read clean.
    for bit in range(13):
        p.cycle(inject=1,ia=1,mask=1<<bit);p.cycle(rd=1,addr=1);p.cycle(rd=1,addr=1)
    p.cycle(inject=1,ia=2,mask=3);p.cycle(rd=1,addr=2);p.at(2);p.cycle(scrub=1);p.cycle(rd=1,addr=2)
    p.cycle(wr=1,addr=2,data=55);p.cycle(inject=1,ia=0,mask=4);p.at(0)
    p.cycle(scrub=1);p.cycle(rd=1,addr=0) # must be clean after background repair
    p.cycle(inject=1,ia=0,mask=8);p.at(0);p.cycle(scrub=1,wr=1,addr=0,data=0xe7);p.cycle(rd=1,addr=0)
    p.cycle(inject=1,ia=1,mask=16);p.at(1);p.cycle(scrub=1,rd=1,addr=1);p.cycle(rd=1,addr=1)
    if not boundary:
        rng=random.Random(seed)
        for _ in range(iterations):
            addr=rng.randrange(depth);p.cycle(wr=1,addr=addr,data=rng.randrange(256))
            p.cycle(inject=1,ia=addr,mask=sum(1<<b for b in rng.sample(range(13),rng.randrange(3))))
            p.cycle(rd=1,addr=addr,scrub=rng.randrange(2));p.cycle(rd=1,addr=addr)
    p.cycle(rst=0);p.cycle(rd=1);p.cycle();return p.rows
def make_cases(args,parameters):
    depth=parameters['DEPTH'];base=vectors(args.seed,0,depth,True)
    cs=[dict(id='boundaries',vectors=base,mutation=args.demo_bug,expected_failure=None,category='functional')]
    for seed in range(args.seed,args.seed+(3 if args.profile=='nightly' else 1)):
        cs.append(dict(id=f'random-seed{seed}',vectors=vectors(seed,args.iterations,depth),mutation=args.demo_bug,expected_failure=None,category='functional'))
    for m,label in ((1,'ECC_MEMORY_FLAGS'),(2,'ECC_MEMORY_DATA'),(3,'ECC_MEMORY_FLAGS'),(4,'ECC_MEMORY_FLAGS')):
        cs.append(dict(id=f'detect-mutation{m}',vectors=base,mutation=m,expected_failure=label,category='mutation'))
    for c in cs:c['counts']={'steps':len(c['vectors'])}
    return cs

if __name__=='__main__':
    spec=importlib.util.spec_from_file_location('local_runner',HERE.parent/'local-common/runner.py')
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);sys.exit(m.main(sys.modules[__name__]))

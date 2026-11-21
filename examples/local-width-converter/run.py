#!/usr/bin/env python3
"""AXI4-Lite 64->32 width conversion with independent byte-memory oracle."""
import importlib.util
from pathlib import Path
import random
import sys
HERE=Path(__file__).resolve().parent
NAME='local-width-converter';TOP='width_tb';CONFIGS={f'wait{w}':dict(WAIT_CYCLES=w) for w in (0,2)}
ITERATIONS={'smoke':40,'nightly':300};SOURCES=[HERE/'rtl/axi_width64to32.sv',HERE/'tb/width_tb.sv']
class Plan:
    def __init__(self):self.memory=bytearray(64);self.rows=[]
    def op(self,kind,addr=0,data=0,strb=255,awdelay=0,wdelay=0,stall=0,error=255,then=None):
        # kinds: reset, write, read, write interrupted after first lower response, read interrupted.
        # then: a second operation on the same address, ('w',data,strobe) or ('r',). The test bench
        # offers it while the first is still in progress; the adapter must finish the first, then run it.
        first=self.apply(kind,addr,data,strb,error);second=(0,0,0);code=0;data2=0;strb2=0
        if then:
            if kind not in (1,2):raise ValueError('a second operation needs a complete first one')
            code=1 if then[0]=='w' else 2;data2,strb2=(then[1],then[2]) if code==1 else (0,0)
            second=self.apply(code,addr,data2,strb2,error)
        self.rows.append([kind,addr,data,strb,awdelay,wdelay,stall,error,*first,code,*second,data2,strb2])
    def apply(self,kind,addr,data,strb,error):
        response=2 if addr%8 else 0;read=0;subs=0
        if kind and not addr%8:
            for half in range(2):
                if kind in (1,3) and not ((strb>>(4*half))&15):continue
                a=addr+half*4;subs+=1;bad=a==error
                if bad:response=2
                if kind in (1,3) and not bad:
                    for lane in range(4):
                        if strb&(1<<(half*4+lane)):self.memory[a+lane]=(data>>(8*(half*4+lane)))&255
                elif kind in (2,4) and not bad:read|=int.from_bytes(self.memory[a:a+4],'little')<<(half*32)
                if kind in (3,4):break
        return read,response,subs
def vectors(seed,iterations,boundary=False):
    p=Plan();p.op(0)
    p.op(1,0,0x0123456789abcdef);p.op(2,0,stall=4)
    p.op(1,48,0x1111,error=48) # A preceding SLVERR makes the zero-strobe OKAY observable.
    for mask in (0,1,8,15,16,128,240,0x55,0xaa,255):
        p.op(1,8,0x78563412efcdab90,mask,awdelay=3 if mask&1 else 0,wdelay=2 if not mask&1 else 0,stall=3);p.op(2,8)
    p.op(1,16,0xaabbccddeeff1122,error=20);p.op(2,16,error=20,stall=2)
    p.op(1,24,0x1122334455667788,error=24);p.op(2,24,error=24)
    p.op(1,40,0x2222);p.op(2,40) # Preceding OKAY B/R make the misaligned SLVERR observable.
    p.op(1,3,0xffffffffffffffff);p.op(2,3)
    p.op(3,32,0x1122334455667788);p.op(2,32);p.op(4,32);p.op(2,32)
    # A second request waits while the adapter is busy. It must neither be dropped nor disturb the first.
    p.op(1,56,0x0f1e2d3c4b5a6978,then=('w',0xa1b2c3d4e5f60718,0x3c),stall=2);p.op(2,56)
    p.op(1,56,0x1020304050607080,0xc3,awdelay=2,then=('r',));p.op(2,56,then=('w',0x99aabbccddeeff00,255),stall=1)
    p.op(2,56,then=('r',));p.op(1,16,0x5a5a5a5a5a5a5a5a,error=20,then=('w',0xa5a5a5a5a5a5a5a5,0xf0));p.op(2,16,error=16,then=('r',))
    p.op(1,3,0x1234,then=('r',));p.op(1,8,0x77,0,then=('w',0x8899aabbccddeeff,0x81))
    if not boundary:
        rng=random.Random(seed)
        for _ in range(iterations):
            a=rng.randrange(8)*8;k=rng.choice((1,2));then=rng.choice((None,None,None,('r',),('w',rng.getrandbits(64),rng.randrange(256))))
            p.op(k,a,rng.getrandbits(64),rng.randrange(256),rng.randrange(5),rng.randrange(5),rng.randrange(5),rng.choice((255,255,a,a+4)),then)
    p.op(2,0);return p.rows
def make_cases(args,parameters):
    base=vectors(args.seed,0,True)
    cs=[dict(id='boundaries',vectors=base,mutation=args.demo_bug,category='functional',expected_failure=None)]
    for seed in range(args.seed,args.seed+(3 if args.profile=='nightly' else 1)):
        cs.append(dict(id=f'random-seed{seed}',vectors=vectors(seed,args.iterations),mutation=args.demo_bug,category='functional',expected_failure=None))
    for m,label in ((1,'WIDTH_SUBDATA'),(2,'WIDTH_SUBSTRB'),(3,'WIDTH_RESPONSE'),(4,'WIDTH_HOLD')):
        cs.append(dict(id=f'detect-mutation{m}',vectors=base,mutation=m,category='mutation',expected_failure=label))
    for c in cs:c['counts']={'steps':len(c['vectors'])}
    return cs
if __name__=='__main__':
    spec=importlib.util.spec_from_file_location('local_runner',HERE.parent/'local-common/runner.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);sys.exit(m.main(sys.modules[__name__]))

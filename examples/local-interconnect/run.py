#!/usr/bin/env python3
"""Two-master/two-target AXI4 routing, IDs, bursts, contention and round robin."""
import importlib.util
from pathlib import Path
import random
import sys
HERE=Path(__file__).resolve().parent
NAME='local-interconnect';TOP='interconnect_tb';CONFIGS={'two-by-two':{}}
ITERATIONS={'smoke':48,'nightly':500}
SOURCES=[HERE.parent/'local-axi4/rtl/axi4_ram.sv',HERE/'rtl/axi_interconnect.sv',HERE/'tb/interconnect_tb.sv']
def request(op=0,address=0,beats=1,ident=0,seed=0x12345678,mode=0,awdelay=0,wdelay=0,stall=0):
    return [op,address,beats,ident,seed,mode,awdelay,wdelay,stall]
def pattern(seed,beat):return (seed+0x01030507*beat)&0xffffffff
def mask(mode,beat):return (15,5,0,1<<(beat%4))[mode]
class Plan:
    def __init__(self):self.memory=bytearray(16384);self.rows=[]
    def batch(self,a=None,b=None):
        requests=[a or request(),b or request()];row=[]
        first,second=requests
        if (first[0] and second[0] and (first[0]==1 or second[0]==1) and
                first[1]<second[1]+4*second[2] and second[1]<first[1]+4*first[2]):
            raise ValueError('concurrent memory collisions require an ordering oracle; excluded from this plan')
        for r in requests:
            op,address,beats,ident,seed,mode,awd,wd,stall=r
            error=3 if address>=16384 else 2 if address%4 or (address%8192)+4*beats>8192 or address//4096!=(address+4*beats-1)//4096 else 0
            expected=[int.from_bytes(self.memory[address+4*k:address+4*k+4],'little') if not error else 0 for k in range(beats)] if op==2 else [0]*beats
            row += [*r,error,*expected,*([0]*(4-beats))]
        # Concurrent read/write collisions are excluded; subsequent batches see all completed writes.
        for r in requests:
            op,address,beats,ident,seed,mode,*_=r
            if op!=1 or address>=16384 or address%4 or address//4096!=(address+4*beats-1)//4096:continue
            for beat in range(beats):
                data=pattern(seed,beat)
                for lane in range(4):
                    if mask(mode,beat)&(1<<lane):self.memory[address+4*beat+lane]=(data>>(8*lane))&255
        self.rows.append(row)
def boundary_vectors():
    p=Plan();p.batch(request(1,0)) # Leave target 0's next priority at master 1.
    p.batch(request(1,0,4,1),request(1,64,4,2,seed=0x76543210,stall=5))
    p.batch(request(2,0,4,1,stall=3),request(2,64,4,2,stall=5))
    p.batch(request(1,8192,2,0,mode=1,awdelay=3),request(1,8256,3,3,mode=3,wdelay=3))
    p.batch(request(2,8192,2,0),request(2,8256,3,3))
    p.batch(request(1,0,1,0),request(2,8192,1,0))
    p.batch(request(2,0,1,1),request(1,8192,1,1))
    p.batch(request(1,16384,2,1),request(2,16448,3,2))
    p.batch(request(2,4092,2,2),request(1,12284,2,3))
    p.batch(request(1,4,2,1,mode=2),request(1,8196,2,1,mode=2))
    p.batch(request(2,4,2,1),request(2,8196,2,1));return p.rows
def random_vectors(seed,iterations):
    rng=random.Random(seed);p=Plan()
    for _ in range(iterations):
        req=[]
        for m in range(2):
            req.append(request(rng.choice((1,2)),8192*rng.randrange(2)+64*m+4*rng.randrange(4),
                rng.randint(1,4),rng.randrange(4),rng.getrandbits(32),rng.randrange(4),rng.randrange(4),rng.randrange(4),rng.randrange(6)))
        p.batch(*req)
    return p.rows
def counts(rows):
    requests=[r[i:i+14] for r in rows for i in (0,14)]
    return dict(writes=sum(r[0]==1 for r in requests),reads=sum(r[0]==2 for r in requests),
                write_beats=sum(r[2] for r in requests if r[0]==1),read_beats=sum(r[2] for r in requests if r[0]==2),
                errors=sum(bool(r[0] and r[9]) for r in requests))
def make_cases(args,parameters):
    baseline=boundary_vectors();cases=[dict(id='boundaries',vectors=baseline,mutation=args.demo_bug,category='functional',expected_failure=None)]
    for seed in range(args.seed,args.seed+(3 if args.profile=='nightly' else 1)):
        cases.append(dict(id=f'random-seed{seed}',vectors=random_vectors(seed,args.iterations),mutation=args.demo_bug,category='functional',expected_failure=None))
    for m,label in ((1,'IC_RESPONSE'),(2,'IC_ROUTE'),(3,'IC_FAIRNESS'),(4,'IC_DATA')):
        cases.append(dict(id=f'detect-mutation{m}',vectors=baseline,mutation=m,category='mutation',expected_failure=label))
    for c in cases:c['counts']=counts(c['vectors'])
    return cases
if __name__=='__main__':
    spec=importlib.util.spec_from_file_location('local_runner',HERE.parent/'local-common/runner.py')
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);sys.exit(m.main(sys.modules[__name__]))

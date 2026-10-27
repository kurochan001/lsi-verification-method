#!/usr/bin/env python3
import importlib.util
from pathlib import Path
import random
import sys
HERE=Path(__file__).resolve().parent
NAME='local-mbist';TOP='mbist_tb';CONFIGS={'cells8': {'DEPTH': 8}, 'cells16': {'DEPTH': 16}}
ITERATIONS={'smoke': 20, 'nightly': 120};SOURCES=[HERE/'rtl/mbist.sv',HERE/'tb/mbist_tb.sv']
def march(depth):
    trace=[(a,1,0) for a in range(depth)]
    for addresses,old,new in [(range(depth),0,1),(range(depth),1,0),(range(depth-1,-1,-1),0,1),(range(depth-1,-1,-1),1,0)]:
        trace += [(a,w,d) for a in addresses for w,d in [(0,old),(1,new)]]
    return trace+[(a,0,0) for a in range(depth)]
def oracle(depth,fault,victim,aggressor,kind):
    memory=[0]*depth;first=None
    def physical(a):return aggressor if fault==3 and a==victim else a
    for address,write,data in march(depth):
        index=physical(address);value=kind if fault==1 and address==victim else memory[index]
        if not write:
            if value!=data and first is None:first=address
        else:
            old=memory[index];value=data
            if fault==1 and address==victim:value=kind
            if fault==2 and address==victim and old==kind and data!=kind:value=old
            memory[index]=value
            if fault==4 and address==aggressor and old==0 and value==1:memory[victim]^=1
    return int(first is not None),first or 0
def row(depth,fault=0,victim=1,aggressor=0,kind=0,stall=0,reset=0):
    failed,address=oracle(depth,fault,victim,aggressor,kind)
    plan=sum(((a<<2)|(w<<1)|d)<<(8*i) for i,(a,w,d) in enumerate(march(depth)))
    return [fault,victim,aggressor,kind,stall,reset,failed,address,plan]
def vectors(seed,iterations,parameters,boundary=False):
    d=parameters['DEPTH'];rows=[row(d,0),row(d,1,kind=0),row(d,1,kind=1),row(d,2,kind=0),row(d,2,kind=1),row(d,3),row(d,4),row(d,0,stall=3,reset=1)]
    if not boundary:
        rng=random.Random(seed)
        for _ in range(iterations):
            v,a=rng.sample(range(d),2);rows.append(row(d,rng.randrange(5),v,a,rng.randrange(2),rng.choice((0,3,4)),rng.randrange(8)==0))
    return rows

def make_cases(args,parameters):
    base=vectors(args.seed,0,parameters,True)
    cs=[dict(id='boundaries',vectors=base,mutation=args.demo_bug,category='functional',expected_failure=None)]
    for seed in range(args.seed,args.seed+(3 if args.profile=='nightly' else 1)):
        cs.append(dict(id=f'random-seed{seed}',vectors=vectors(seed,args.iterations,parameters),mutation=args.demo_bug,category='functional',expected_failure=None))
    for mutation,label in [(1, 'MBIST_STATUS'), (2, 'MBIST_ADDRESS'), (3, 'MBIST_OP'), (4, 'MBIST_COUNT')]:
        cs.append(dict(id=f'detect-mutation{mutation}',vectors=base,mutation=mutation,category='mutation',expected_failure=label))
    for c in cs:c['counts']={'steps':len(c['vectors'])}
    return cs
if __name__=='__main__':
    spec=importlib.util.spec_from_file_location('local_runner',HERE.parent/'local-common/runner.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);sys.exit(m.main(sys.modules[__name__]))

#!/usr/bin/env python3
"""AXI descriptor-ring fetch + existing APB DMA copy engine + aggregate completion IRQ."""
import importlib.util
from pathlib import Path
import random
import sys
HERE=Path(__file__).resolve().parent
NAME='local-descriptor-dma';TOP='descriptor_tb';CONFIGS={'ring2':dict(DEPTH=2,STALL_PERIOD=0),'ring4-stalls':dict(DEPTH=4,STALL_PERIOD=3)}
ITERATIONS={'smoke':20,'nightly':160};SOURCES=[HERE.parent/'local-axi4/rtl/axi4_ram.sv',HERE.parent/'local-dma/rtl/apb_dma.sv',HERE/'rtl/descriptor_dma.sv',HERE/'tb/descriptor_tb.sv']
def row(depth,head,count,seed=17,fault=0,position=0,abort=0,reset=0):
    invalid=head>=depth or count>depth;complete=0;fetches=0;written=0;err=int(invalid);stopped=0
    if not invalid:
        for index in range(count):
            slot=(head+index)%depth;fetches+=1
            if index==position and fault in (1,2,3):err=1;break
            if index==position and abort:stopped=1;break
            written|=1<<slot
            if index==position and fault==4:err=1;break
            complete+=1
    return [head,count,seed,fault,position,abort,reset,complete,err,stopped,fetches,written]
def vectors(seed,iterations,depth,boundary=False):
    rows=[row(depth,0,0),row(depth,0,1),row(depth,depth-1,depth),row(depth,0,depth,fault=1),row(depth,0,depth,fault=2),
        row(depth,0,depth,fault=3,position=1),row(depth,0,depth,fault=4,position=1),row(depth,0,depth,abort=1),row(depth,0,depth,abort=2,position=1),
        row(depth,depth,1),row(depth,0,depth+1),row(depth,0,depth,reset=1)]
    if not boundary:
        rng=random.Random(seed)
        for _ in range(iterations):
            count=rng.randint(0,depth);fault=rng.randrange(5) if count else 0;abort=rng.randrange(3) if count and not fault else 0
            rows.append(row(depth,rng.randrange(depth),count,rng.randrange(256),fault,rng.randrange(count) if count else 0,abort,int(rng.randrange(10)==0)))
    return rows
def make_cases(args,parameters):
    depth=parameters['DEPTH'];base=vectors(args.seed,0,depth,True)
    cs=[dict(id='boundaries',vectors=base,mutation=args.demo_bug,category='functional',expected_failure=None)]
    for seed in range(args.seed,args.seed+(3 if args.profile=='nightly' else 1)):cs.append(dict(id=f'random-seed{seed}',vectors=vectors(seed,args.iterations,depth),mutation=args.demo_bug,category='functional',expected_failure=None))
    for m,label in ((1,'SG_FETCH'),(2,'SG_STATUS'),(3,'SG_IRQ'),(4,'SG_DATA')):cs.append(dict(id=f'detect-mutation{m}',vectors=base,mutation=m,category='mutation',expected_failure=label))
    for c in cs:c['counts']={'steps':len(c['vectors'])}
    return cs
if __name__=='__main__':
    spec=importlib.util.spec_from_file_location('local_runner',HERE.parent/'local-common/runner.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);sys.exit(m.main(sys.modules[__name__]))

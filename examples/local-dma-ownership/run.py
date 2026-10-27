#!/usr/bin/env python3
import importlib.util
from pathlib import Path
import random
import sys
HERE=Path(__file__).resolve().parent
NAME='local-dma-ownership';TOP='owned_tb';CONFIGS={'ring2': {'DEPTH': 2, 'STALL_PERIOD': 0}, 'ring4-stalls': {'DEPTH': 4, 'STALL_PERIOD': 3}}
ITERATIONS={'smoke': 12, 'nightly': 60};SOURCES=[HERE.parent/'local-axi4/rtl/axi4_ram.sv',HERE.parent/'local-dma/rtl/apb_dma.sv',HERE.parent/'local-descriptor-dma/rtl/descriptor_dma.sv',HERE/'rtl/owned_ring.sv',HERE/'tb/owned_tb.sv']
def row(depth,seed=17,turns=2,invalid=0,reset=0):
    memory=[((a*13+7)^seed)&255 for a in range(8192)]
    for turn in range(turns):
        for slot in range(depth):
            if invalid and turn==0 and slot==depth-1:continue
            source=256+128*turn+16*slot;destination=1024+32*slot;words=1+(slot+turn)%4
            memory[destination:destination+4*words]=memory[source:source+4*words]
    digest=sum((i+1)*value for i,value in enumerate(memory))&0xffffffff
    return [seed,turns,invalid,reset,digest]
def vectors(seed,iterations,parameters,boundary=False):
    depth=parameters['DEPTH'];rows=[row(depth),row(depth,31,3,1),row(depth,27,2,0,1)]
    if not boundary:
        rng=random.Random(seed)
        for _ in range(iterations):rows.append(row(depth,rng.randrange(256),rng.randint(2,3),rng.randrange(2),rng.randrange(5)==0))
    return rows

def make_cases(args,parameters):
    base=vectors(args.seed,0,parameters,True)
    cs=[dict(id='boundaries',vectors=base,mutation=args.demo_bug,category='functional',expected_failure=None)]
    for seed in range(args.seed,args.seed+(3 if args.profile=='nightly' else 1)):
        cs.append(dict(id=f'random-seed{seed}',vectors=vectors(seed,args.iterations,parameters),mutation=args.demo_bug,category='functional',expected_failure=None))
    for mutation,label in [(1, 'OWN_RESPONSE'), (2, 'OWN_STATE'), (3, 'OWN_ORDER'), (4, 'OWN_DATA')]:
        cs.append(dict(id=f'detect-mutation{mutation}',vectors=base,mutation=mutation,category='mutation',expected_failure=label))
    for c in cs:c['counts']={'steps':len(c['vectors'])}
    return cs
if __name__=='__main__':
    spec=importlib.util.spec_from_file_location('local_runner',HERE.parent/'local-common/runner.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);sys.exit(m.main(sys.modules[__name__]))

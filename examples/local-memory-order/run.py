#!/usr/bin/env python3
"""Same-address multi-master ordering against an independently scheduled byte-memory model."""
import importlib.util
from pathlib import Path
import random
import sys
HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('old_interconnect',HERE.parent/'local-interconnect/run.py');BASE=importlib.util.module_from_spec(spec);spec.loader.exec_module(BASE)
NAME='local-memory-order';TOP='memory_order_tb';CONFIGS={'two-by-two':{}};ITERATIONS={'smoke':48,'nightly':500}
SOURCES=[*BASE.SOURCES[:-1],HERE/'memory_order_tb.sv'];EXTRA_INPUTS=[Path(BASE.__file__)]
def batch(a,b=None):
    return [*a,0,0,0,0,0,*(b or BASE.request()),0,0,0,0,0]
def boundary_vectors():
    r=BASE.request;rows=[]
    for base in (0,8192):
        rows += [batch(r(1,base,1,1,seed=0x11223344),r(2,base,1,2)),
                 batch(r(1,base,1,1,seed=0xaabbccdd,wdelay=12),r(2,base,1,2,stall=25)),
                 batch(r(1,base,1,1,seed=0x87654321),r(2,base,1,2,awdelay=15)),
                 batch(r(1,base,4,0,seed=0x13579bdf,mode=1),r(1,base,4,3,seed=0x2468ace0,mode=3)),
                 batch(r(2,base,4,0),r(2,base,4,3)),
                 batch(r(1,base,2,1,seed=0,mode=2),r(2,base,2,1,stall=5))]
    return rows
def random_vectors(seed,iterations):
    rng=random.Random(seed);r=BASE.request;rows=[]
    for _ in range(iterations):
        address=8192*rng.randrange(2)+4*rng.randrange(8)
        req=[r(rng.choice((1,2)),address,rng.randint(1,4),rng.randrange(4),rng.getrandbits(32),rng.randrange(4),rng.randrange(10),rng.randrange(15),rng.randrange(8)) for _ in range(2)]
        rows.append(batch(*req))
    return rows
def make_cases(args,parameters):
    baseline=boundary_vectors();cases=[dict(id='boundaries',vectors=baseline,mutation=args.demo_bug,category='functional',expected_failure=None)]
    for seed in range(args.seed,args.seed+(3 if args.profile=='nightly' else 1)):
        cases.append(dict(id=f'random-seed{seed}',vectors=random_vectors(seed,args.iterations),mutation=args.demo_bug,category='functional',expected_failure=None))
    for m,label in ((1,'IC_RESPONSE'),(2,'IC_ROUTE'),(3,'ORDER_READ'),(4,'ORDER_WRITE')):
        cases.append(dict(id=f'detect-mutation{m}',vectors=baseline,mutation=m,category='mutation',expected_failure=label))
    for c in cases:c['counts']=BASE.counts(c['vectors'])
    return cases
if __name__=='__main__':
    spec=importlib.util.spec_from_file_location('local_runner',HERE.parent/'local-common/runner.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);sys.exit(m.main(sys.modules[__name__]))

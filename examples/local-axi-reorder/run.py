#!/usr/bin/env python3
import importlib.util
from pathlib import Path
import random
import sys
HERE=Path(__file__).resolve().parent
NAME='local-axi-reorder';TOP='reorder_tb';CONFIGS={'slots2': {'SLOTS': 2}, 'slots4': {'SLOTS': 4}}
ITERATIONS={'smoke': 16, 'nightly': 100};SOURCES=[HERE.parent/'local-axi4/rtl/axi4_ram.sv',HERE/'rtl/reorder.sv',HERE/'tb/reorder_tb.sv']
def order(ids):
    # Independent per-ID queues; choose the newest currently eligible queue head.
    queues={i:[] for i in set(ids)}
    for index,i in enumerate(ids):queues[i].append(index)
    result=[]
    while any(queues.values()):
        i=max((i for i in queues if queues[i]),key=lambda i:queues[i][0]);result.append(queues[i].pop(0))
    return result
def row(ids,lengths,mask,seed,stall,reset=0):
    packed=lambda values,bits:sum(value<<(bits*i) for i,value in enumerate(values))
    return [packed(ids,2),packed([n-1 for n in lengths],2),mask,seed,stall,reset,packed(order(ids),2)]
def vectors(seed,iterations,parameters,boundary=False):
    n=parameters['SLOTS'];rows=[row([0]*n,[2]*n,15,17,3),row([i%2 for i in range(n)],[1+i%4 for i in range(n)],5,31,4),row([i%2 for i in range(n)],[4]*n,0,19,3,1),row([i%4 for i in range(n)],[3]*n,10,27,0)]
    if not boundary:
        rng=random.Random(seed)
        for _ in range(iterations):rows.append(row([rng.randrange(4) for i in range(n)],[rng.randint(1,4) for i in range(n)],rng.randrange(16),rng.getrandbits(32),rng.choice((0,3,4)),int(rng.randrange(10)==0)))
    return rows

def make_cases(args,parameters):
    base=vectors(args.seed,0,parameters,True)
    cs=[dict(id='boundaries',vectors=base,mutation=args.demo_bug,category='functional',expected_failure=None)]
    for seed in range(args.seed,args.seed+(3 if args.profile=='nightly' else 1)):
        cs.append(dict(id=f'random-seed{seed}',vectors=vectors(seed,args.iterations,parameters),mutation=args.demo_bug,category='functional',expected_failure=None))
    for mutation,label in [(1, 'AXIO_BID'), (2, 'AXIO_RID'), (3, 'AXIO_DATA'), (4, 'AXIO_DATA')]:
        cs.append(dict(id=f'detect-mutation{mutation}',vectors=base,mutation=mutation,category='mutation',expected_failure=label))
    for c in cs:c['counts']={'steps':len(c['vectors'])}
    return cs
if __name__=='__main__':
    spec=importlib.util.spec_from_file_location('local_runner',HERE.parent/'local-common/runner.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);sys.exit(m.main(sys.modules[__name__]))

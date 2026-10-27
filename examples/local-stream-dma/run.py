#!/usr/bin/env python3
import importlib.util
from pathlib import Path
import random
import sys
HERE=Path(__file__).resolve().parent
NAME='local-stream-dma';TOP='stream_dma_tb';CONFIGS={'fifo2': {'FIFO_DEPTH': 2, 'STALL_PERIOD': 0}, 'fifo4-stalls': {'FIFO_DEPTH': 4, 'STALL_PERIOD': 3}}
ITERATIONS={'smoke': 18, 'nightly': 120};SOURCES=[HERE.parent/'local-axi4/rtl/axi4_ram.sv',HERE.parent/'local-axis/rtl/axis_packet_fifo.sv',HERE/'rtl/stream_dma.sv',HERE/'tb/stream_dma_tb.sv']
def row(direction,address,byte_count,seed=17,mode=0,position=0):
    invalid=address%4!=0 or byte_count>32 or address+((byte_count+3)//4)*4>8192
    words=(byte_count+3)//4;error=int(invalid or (byte_count>0 and mode in (1,2,3,4)))
    completed=0 if invalid else words
    if byte_count and mode in (1,3,4):completed=position
    if byte_count and mode==2:completed=position+1
    transferred=min(byte_count,completed*4) if not invalid else 0
    return [direction,address,byte_count,seed,mode,position,error,transferred]
def vectors(seed,iterations,parameters,boundary=False):
    rows=[row(0,256,31),row(1,512,31),row(0,256,0),row(1,512,0),row(0,256,1),row(1,512,1),row(0,256,12,mode=1,position=1),row(1,512,12,mode=2,position=1),row(1,512,12,mode=3,position=1),row(1,512,12,mode=4,position=1),row(0,256,16,mode=5),row(1,512,16,mode=5),row(0,257,4),row(1,512,33)]
    if not boundary:
        rng=random.Random(seed)
        for _ in range(iterations):
            d=rng.randrange(2);length=rng.randrange(33);mode=rng.choice((0,0,5,2,3,4) if d else (0,0,1,5)) if length else 0
            rows.append(row(d,4*rng.randrange(64,512),length,rng.getrandbits(32),mode,rng.randrange((length+3)//4) if length else 0))
    return rows

def make_cases(args,parameters):
    base=vectors(args.seed,0,parameters,True)
    cs=[dict(id='boundaries',vectors=base,mutation=args.demo_bug,category='functional',expected_failure=None)]
    for seed in range(args.seed,args.seed+(3 if args.profile=='nightly' else 1)):
        cs.append(dict(id=f'random-seed{seed}',vectors=vectors(seed,args.iterations,parameters),mutation=args.demo_bug,category='functional',expected_failure=None))
    for mutation,label in [(1, 'STREAM_KEEP'), (2, 'STREAM_LAST'), (3, 'STREAM_MEMORY'), (4, 'STREAM_DATA')]:
        cs.append(dict(id=f'detect-mutation{mutation}',vectors=base,mutation=mutation,category='mutation',expected_failure=label))
    for c in cs:c['counts']={'steps':len(c['vectors'])}
    return cs
if __name__=='__main__':
    spec=importlib.util.spec_from_file_location('local_runner',HERE.parent/'local-common/runner.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);sys.exit(m.main(sys.modules[__name__]))

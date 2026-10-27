#!/usr/bin/env python3
"""APB programming + AXI4 memory-to-memory DMA + completion IRQ, abort and errors."""
import importlib.util
from pathlib import Path
import random
import sys
HERE=Path(__file__).resolve().parent
NAME='local-dma';TOP='dma_tb';CONFIGS={'no-stall':dict(STALL_PERIOD=0),'request-stalls':dict(STALL_PERIOD=3)}
ITERATIONS={'smoke':24,'nightly':200}
SOURCES=[HERE.parent/'local-axi4/rtl/axi4_ram.sv',HERE/'rtl/apb_dma.sv',HERE/'tb/dma_tb.sv']
def vector(src=0,dst=256,words=8,seed=17,fault=0,abort=0,reset=0,mask=0):
    bad=bool(words>32 or src%4 or dst%4 or src+words*4>8192 or dst+words*4>8192 or
             (words and src<dst+4*words and dst<src+4*words))
    chunk=min(words,4,(4096-src%4096)//4,(4096-dst%4096)//4) if not bad else 0
    written=0 if bad or fault==1 or abort==1 else chunk if fault==2 or abort==2 else words
    read_words=0 if bad else chunk if fault or abort else words
    bursts=0;left=words;a=src;b=dst
    while left and not bad:
        step=min(left,4,(4096-a%4096)//4,(4096-b%4096)//4);bursts+=1;left-=step;a+=4*step;b+=4*step
        if fault or abort:break
    writes=0 if not written else bursts
    return [src,dst,words,seed,fault,abort,reset,mask,int(bad or bool(fault)),int(bool(abort) and not fault and not bad),written,read_words,bursts,writes]
def boundary_vectors():
    return [vector(words=0),vector(words=1),vector(words=7),vector(src=4092,dst=512,words=6),
            vector(src=64,dst=4092,words=6),vector(fault=1),vector(fault=2),vector(abort=1),vector(abort=2),
            vector(reset=1),vector(mask=1),vector(src=3),vector(dst=4),vector(src=8188,words=2)]
def random_vectors(seed,iterations):
    rng=random.Random(seed);rows=[]
    for _ in range(iterations):
        src=rng.choice((0,64,4080,4092));dst=rng.choice((512,1024,6144,7168));words=rng.randint(0,24)
        fault=rng.choice((0,0,0,1,2)) if words else 0;abort=rng.randrange(3) if words and not fault else 0
        rows.append(vector(src,dst,words,rng.randrange(256),fault,abort,int(rng.randrange(9)==0),rng.randrange(2)))
    return rows
def counts(rows):
    return dict(starts=sum(1+bool(r[6]) for r in rows),read_bursts=sum(r[12] for r in rows),write_bursts=sum(r[13] for r in rows),
                read_beats=sum(r[11] for r in rows),write_beats=sum(r[10] for r in rows),completions=len(rows))
def make_cases(args,parameters):
    baseline=boundary_vectors();cases=[dict(id='boundaries',vectors=baseline,mutation=args.demo_bug,category='functional',expected_failure=None)]
    for seed in range(args.seed,args.seed+(3 if args.profile=='nightly' else 1)):
        cases.append(dict(id=f'random-seed{seed}',vectors=random_vectors(seed,args.iterations),mutation=args.demo_bug,category='functional',expected_failure=None))
    for m,label in ((1,'DMA_BOUNDARY'),(2,'DMA_DATA'),(3,'DMA_IRQ'),(4,'DMA_ADDRESS')):
        cases.append(dict(id=f'detect-mutation{m}',vectors=baseline,mutation=m,category='mutation',expected_failure=label))
    for c in cases:c['counts']=counts(c['vectors'])
    return cases
if __name__=='__main__':
    spec=importlib.util.spec_from_file_location('local_runner',HERE.parent/'local-common/runner.py')
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);sys.exit(m.main(sys.modules[__name__]))

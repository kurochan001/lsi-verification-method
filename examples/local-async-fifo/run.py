#!/usr/bin/env python3
"""Dual-clock FIFO with a queue oracle and independently delayed absolute counts."""
from collections import deque
import importlib.util
from pathlib import Path
import random
import sys

HERE=Path(__file__).resolve().parent
NAME='local-async-fifo';TOP='async_fifo_tb'
CONFIGS={f'depth{d}-sync{s}':dict(DEPTH=d,SYNC_STAGES=s) for d in (4,8) for s in (2,3)}
ITERATIONS={'smoke':600,'nightly':5000}
SOURCES=[HERE/'rtl/async_fifo.sv',HERE/'tb/async_fifo_tb.sv']


def schedule(seed,depth,stages,profile,random_ticks=0):
    rng=random.Random(seed)
    wh,rh=((3,5),(5,3),(4,4),(3,5))[profile]
    wc=rc=0;wnext=1;rnext=2 if profile!=2 else 1
    commands=[]
    patterns=[0,255,85,1,128]
    # Durations include synchronization and flag-update latency at either clock ratio.
    span=(depth+stages+5)*max(wh,rh)*2
    phases=[(20,'reset'),(span,'empty'),(span,'fill'),(span,'drain'),
            (depth*max(wh,rh)*24,'both'),(span,'fill'),(20,'reset'),
            (span,'fill'),(span,'drain'),(random_ticks,'random'),(span,'drain')]
    tick=0
    for length,mode in phases:
        for _ in range(length):
            if tick==wnext:
                wc^=1;wnext+=wh+(rng.choice((-1,0,1)) if profile==3 else 0)
            if tick==rnext:
                rc^=1;rnext+=rh+(rng.choice((-1,0,1)) if profile==3 else 0)
            we=int(mode in ('fill','both') or (mode=='random' and rng.randrange(4)!=0))
            re=int(mode in ('empty','drain','both') or (mode=='random' and rng.randrange(4)!=0))
            value=patterns[(tick//2)%5] if mode!='random' else rng.randrange(256)
            commands.append([wc,rc,int(mode!='reset'),we,value,re,profile])
            tick+=1
    return commands


def reference(commands,depth,stages):
    queue=deque();written=read=0
    wp=[0]*stages;rp=[0]*stages
    full=0;empty=1;valid=data=0;previous_w=previous_r=0
    rows=[];counts=dict(writes=0,reads=0,blocked_writes=0,blocked_reads=0)
    for command in commands:
        wc,rc,rst,we,value,re,_=command
        wrise=wc and not previous_w;rrise=rc and not previous_r
        old_w,old_r=written,read
        if not rst:
            queue.clear();written=read=0;wp=[0]*stages;rp=[0]*stages
            full=0;empty=1;valid=data=0
        else:
            accepted_w=bool(wrise and we and not full)
            accepted_r=bool(rrise and re and not empty)
            if wrise:
                counts['blocked_writes']+=int(we and full)
                full=int(written+accepted_w-rp[-1]>=depth)
                rp=[old_r,*rp[:-1]]
            if rrise:
                counts['blocked_reads']+=int(re and empty)
                empty=int(read+accepted_r==wp[-1])
                wp=[old_w,*wp[:-1]]
                valid=int(accepted_r)
            if accepted_r:
                assert queue,'oracle underflow'
                data=queue.popleft();read+=1;counts['reads']+=1
            if accepted_w:
                queue.append(value);written+=1;counts['writes']+=1
            assert 0<=len(queue)<=depth,'oracle overflow'
        rows.append([*command,full,empty,valid,data])
        previous_w,previous_r=wc,rc
    assert not queue,'final drain incomplete'
    return rows,counts


def make_cases(args,parameters):
    depth,stages=parameters['DEPTH'],parameters['SYNC_STAGES']
    baseline=[]
    # Each schedule ends in a drained FIFO; initial clock levels are restarted safely under reset.
    for profile in range(4):
        baseline.extend([[0,0,0,0,0,0,profile],*schedule(17,depth,stages,profile)])
    vectors,counts=reference(baseline,depth,stages)
    result=[dict(id='boundaries-clocks',vectors=vectors,counts=counts,mutation=args.demo_bug,
                 expected_failure=None,category='functional')]
    for seed in range(args.seed,args.seed+(3 if args.profile=='nightly' else 1)):
        rows,totals=reference(schedule(seed,depth,stages,3,args.iterations),depth,stages)
        result.append(dict(id=f'random-seed{seed}',seed=seed,vectors=rows,counts=totals,
                           mutation=args.demo_bug,expected_failure=None,category='functional'))
    for m,label in ((1,'ASYNC_DATA'),(2,'ASYNC_FLAGS'),(3,'ASYNC_VALID'),(4,'ASYNC_GRAY')):
        result.append(dict(id=f'detect-mutation{m}',vectors=vectors,counts=counts,mutation=m,
                           expected_failure=label,category='mutation'))
    return result


if __name__=='__main__':
    spec=importlib.util.spec_from_file_location('local_runner',HERE.parent/'local-common/runner.py')
    support=importlib.util.module_from_spec(spec);spec.loader.exec_module(support)
    sys.exit(support.main(sys.modules[__name__]))

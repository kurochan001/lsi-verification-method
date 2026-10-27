#!/usr/bin/env python3
"""AXI4-Stream packet boundaries, valid byte lanes, stalls and reset flushing."""
from collections import deque
import importlib.util
from pathlib import Path
import random
import sys
HERE=Path(__file__).resolve().parent
NAME='local-axis';TOP='axis_tb';CONFIGS={f'depth{d}':dict(DEPTH=d) for d in (2,4)}
ITERATIONS={'smoke':32,'nightly':300}
SOURCES=[HERE/'rtl/axis_packet_fifo.sv',HERE/'tb/axis_tb.sv']
def mask(keep):return sum(255<<(lane*8) for lane in range(4) if keep&(1<<lane))
class Oracle:
    def __init__(self,depth):self.depth=depth;self.queue=deque();self.in_open=self.out_open=False
    def step(self,inputs):
        rst,valid,data,keep,last,ready=inputs;flush=int(not rst and bool(self.queue or self.in_open or self.out_open))
        if not rst:self.queue.clear();self.in_open=self.out_open=False
        output=self.queue[0] if self.queue else (0,0,0)
        iv=int(bool(rst and (len(self.queue)<self.depth or (self.queue and ready))))
        ov=int(bool(rst and self.queue));pre=[iv,ov,*output]
        if rst:
            if ov and ready:self.queue.popleft();self.out_open=not bool(output[2])
            if valid and iv:self.queue.append((data,keep,last));self.in_open=not bool(last)
        return [*inputs,*pre,flush]
class Plan:
    def __init__(self,depth):self.model=Oracle(depth);self.rows=[]
    def cycle(self,rst=1,valid=0,data=0,keep=0,last=0,ready=1):
        row=self.model.step([rst,valid,data,keep,last,ready]);self.rows.append(row);return row
    def beat(self,data,keep,last,stall=0):
        for guard in range(100):
            if self.cycle(valid=1,data=data,keep=keep,last=last,ready=int(guard>=stall))[6]:return
        raise ValueError('stream beat never accepted')
    def drain(self):
        while self.model.queue:self.cycle()
        self.cycle()
    def packet(self,beats,stall=0):
        for index,(data,keep) in enumerate(beats):self.beat(data,keep,int(index==len(beats)-1),stall)
        self.drain()
def boundary_vectors(depth):
    p=Plan(depth);p.cycle(rst=0)
    p.packet([(0x11223344,15)])
    p.packet([(0xabcdef12,5),(0x76543210,3)],4)
    p.packet([(0x12340000+i,0 if i==1 else 15) for i in range(depth+2)],4)
    for i in range(depth):p.beat(0xa5a50000+i,15,0,5)
    p.cycle(rst=0);p.packet([(0x87654321,1)])
    p.beat(0xdeadbeef,15,0);p.cycle();p.cycle(rst=0)
    p.packet([(0,15),(0xffffffff,15)],2);p.cycle(rst=0);p.cycle();return p.rows
def random_vectors(seed,iterations,depth):
    rng=random.Random(seed);p=Plan(depth);p.cycle(rst=0)
    for _ in range(iterations):
        n=rng.randint(1,10);beats=[(rng.getrandbits(32),rng.randrange(16) if i<n-1 else rng.randint(1,15)) for i in range(n)]
        p.packet(beats,rng.randrange(7))
        if rng.randrange(5)==0:
            p.beat(rng.getrandbits(32),15,0,2);p.cycle(rst=0)
    p.drain();p.cycle(rst=0);p.cycle();return p.rows
def counts(rows):
    return dict(accepted=sum(bool(r[0] and r[1] and r[6]) for r in rows),delivered=sum(bool(r[7] and r[5]) for r in rows),
        packets=sum(bool(r[7] and r[5] and r[10]) for r in rows),bytes=sum(r[9].bit_count() for r in rows if r[7] and r[5]),flushes=sum(r[11] for r in rows))
def make_cases(args,parameters):
    depth=parameters['DEPTH'];baseline=boundary_vectors(depth)
    cases=[dict(id='boundaries',vectors=baseline,mutation=args.demo_bug,category='functional',expected_failure=None)]
    for seed in range(args.seed,args.seed+(3 if args.profile=='nightly' else 1)):
        cases.append(dict(id=f'random-seed{seed}',vectors=random_vectors(seed,args.iterations,depth),mutation=args.demo_bug,category='functional',expected_failure=None))
    for m,label in ((1,'AXIS_META'),(2,'AXIS_META'),(3,'AXIS_DATA'),(4,'AXIS_CONTROL')):
        cases.append(dict(id=f'detect-mutation{m}',vectors=baseline,mutation=m,category='mutation',expected_failure=label))
    for c in cases:c['counts']=counts(c['vectors'])
    return cases
if __name__=='__main__':
    spec=importlib.util.spec_from_file_location('local_runner',HERE.parent/'local-common/runner.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);sys.exit(m.main(sys.modules[__name__]))

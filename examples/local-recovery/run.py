#!/usr/bin/env python3
"""Tagged timeout isolation, late response rejection and subsequent recovery."""
import importlib.util
from pathlib import Path
import random
import sys
HERE=Path(__file__).resolve().parent
NAME='local-recovery';TOP='recovery_tb';CONFIGS={f'timeout{n}':dict(TIMEOUT=n,TAG_BITS=4) for n in (4,8)}
ITERATIONS={'smoke':32,'nightly':300}
SOURCES=[HERE/'rtl/timeout_guard.sv',HERE/'tb/recovery_tb.sv']

class Oracle:
    def __init__(self,timeout):self.timeout=timeout;self.time=0;self.reset()
    def reset(self):self.request=None;self.accepted=None;self.result=None;self.serial=0;self.drop=0
    def step(self,inputs):
        rst,uv,ud,ur,ready,rv,tag,data=inputs
        if not rst:self.reset()
        send=self.request is not None and self.accepted is None and self.result is None
        waiting=self.request is not None and self.accepted is not None and self.result is None
        pre=[int(rst and self.request is None and self.serial<15),int(self.result is not None),
             0 if self.result is None else self.result[0],0 if self.result is None else self.result[1],
             int(rst and send),0 if self.request is None else self.request[1],0 if self.request is None else self.request[0],int(bool(rst)),self.drop]
        # Payloads are compared only while their VALID is asserted.
        if rst:
            self.drop=int(bool(rv and not(waiting and tag==self.request[0])))
            if self.result is not None and ur:self.request=self.result=self.accepted=None
            if uv and pre[0]:self.serial+=1;self.request=(self.serial,ud)
            if send and ready:self.accepted=self.time
            if waiting:
                if rv and tag==self.request[0]:self.result=(0,data)
                elif self.time>=self.accepted+self.timeout:self.result=(1,0)
        self.time+=1;return [*inputs,*pre]

class Plan:
    def __init__(self,timeout):self.model=Oracle(timeout);self.rows=[];self.epoch=0
    def cycle(self,rst=1,uv=0,data=0,ur=0,ready=1,rv=0,tag=0,response=0):
        if not rst:self.epoch+=1
        row=self.model.step([rst,uv,data,ur,ready,rv,tag,response]);self.rows.append(row);return row
    def begin(self,data,stall=0):
        if self.model.serial==15:
            for _ in range(3):self.cycle(uv=1,data=0xfa)
            self.cycle(rst=0) # Coordinated target flush; serial values may then be reused.
        self.cycle(uv=1,data=data,ready=0)
        for _ in range(stall):self.cycle(ready=0)
        self.cycle();return self.model.serial
    def finish(self,stall=0):
        for _ in range(stall):self.cycle()
        self.cycle(ur=1);self.cycle()
    def wait_result(self):
        for _ in range(self.model.timeout+3):
            if self.model.result is not None:return
            self.cycle()
        raise ValueError('timeout did not complete')
    def transaction(self,data,respond=True,delay=1,stall=0):
        tag=self.begin(data,2)
        if respond:
            for _ in range(delay-1):self.cycle()
            self.cycle(rv=1,tag=tag,response=data^0x5a)
        self.wait_result();self.finish(stall);return tag

def boundary_vectors(timeout):
    p=Plan(timeout);p.cycle(rst=0)
    p.transaction(0x11,stall=3)
    old=p.begin(0x22);p.wait_result();p.cycle(rv=1,tag=old,response=0xee);p.finish(2)
    current=p.begin(0x33)
    p.cycle(rv=1,tag=old,response=0xee) # Late reply while a new request is outstanding.
    p.cycle(rv=1,tag=current,response=0x33^0x5a);p.wait_result();p.finish()
    p.transaction(0x44,delay=timeout,stall=2) # Matching response wins on the timeout edge.
    p.transaction(0x55,respond=False)
    while p.model.serial<15:p.transaction(0x77)
    p.transaction(0x66);p.cycle(rst=0);p.cycle();return p.rows

def random_vectors(seed,iterations,timeout):
    rng=random.Random(seed);p=Plan(timeout);p.cycle(rst=0);old=0;old_epoch=p.epoch
    for _ in range(iterations):
        data=rng.randrange(256);current=p.begin(data,rng.randrange(4))
        if old and old_epoch==p.epoch:p.cycle(rv=1,tag=old,response=0xee)
        if rng.randrange(3):p.cycle(rv=1,tag=current,response=data^0x5a)
        p.wait_result();p.finish(rng.randrange(5));old=current;old_epoch=p.epoch
    p.cycle(rst=0);p.cycle();return p.rows

def counts(rows):
    return dict(requests=sum(bool(r[0] and r[1] and r[8]) for r in rows),responses=sum(bool(r[9] and r[3]) for r in rows),
                timeouts=sum(bool(r[9] and r[10] and r[3]) for r in rows),dropped=sum(r[16] for r in rows))
def make_cases(args,parameters):
    timeout=parameters['TIMEOUT'];baseline=boundary_vectors(timeout)
    cases=[dict(id='boundaries',vectors=baseline,mutation=args.demo_bug,category='functional',expected_failure=None)]
    for seed in range(args.seed,args.seed+(3 if args.profile=='nightly' else 1)):
        cases.append(dict(id=f'random-seed{seed}',vectors=random_vectors(seed,args.iterations,timeout),mutation=args.demo_bug,category='functional',expected_failure=None))
    for m,label in ((1,'RECOVERY_CONTROL'),(2,'RECOVERY_CONTROL'),(3,'RECOVERY_TAG'),(4,'RECOVERY_CONTROL')):
        cases.append(dict(id=f'detect-mutation{m}',vectors=baseline,mutation=m,category='mutation',expected_failure=label))
    for c in cases:c['counts']=counts(c['vectors'])
    return cases
if __name__=='__main__':
    spec=importlib.util.spec_from_file_location('local_runner',HERE.parent/'local-common/runner.py')
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);sys.exit(m.main(sys.modules[__name__]))

#!/usr/bin/env python3
"""APB/timer/watchdog integration using register semantics and deadline oracles."""
import importlib.util
from pathlib import Path
import random
import sys
HERE=Path(__file__).resolve().parent
NAME='local-apb-timer';TOP='apb_timer_tb'
CONFIGS={f'width{w}-wait{n}':dict(WIDTH=w,WAIT_CYCLES=n) for w in (4,8) for n in (0,2)}
ITERATIONS={'smoke':40,'nightly':300}
SOURCES=[HERE.parent/'local-timer-watchdog/rtl/timer_watchdog.sv',HERE/'rtl/apb_timer.sv',HERE/'tb/apb_timer_tb.sv']


class Deadline:
    def __init__(self):self.time=0;self.end=None;self.saved=0
    @property
    def count(self):return 0 if self.end is None else self.end-self.time
    def step(self,enable,load=None,kick=False,periodic=False):
        self.time+=bool(enable)
        if load is not None:
            self.saved=load;self.end=self.time+load if load else None
        elif enable and kick:self.end=self.time+self.saved if self.saved else None
        elif enable and self.end is not None and self.time>=self.end:
            self.end=self.time+self.saved if periodic and self.saved else None
            return 1
        return 0


class Oracle:
    def __init__(self,width,wait):
        self.mask=(1<<width)-1;self.wait=wait;self.reset()
    def reset(self):
        self.timer=Deadline();self.watchdog=Deadline()
        self.control=self.tr=self.wr=self.pending=self.expired=self.request=self.remaining=0
    def step(self,command):
        rst,sel,access,write,address,data=command
        known=address in (0,4,8,12,16,20,24,28)
        ready=int(bool(rst and sel and access and self.remaining==0))
        error=int(bool(ready and (not known or (write and address not in (0,4,8,12)))))
        read={0:self.control,4:self.tr,8:self.wr,12:0,
              16:self.pending|(self.expired<<1)|(self.request<<2),
              20:self.timer.count,24:self.watchdog.count,28:0x54494d52}.get(address,0)
        commit=ready and write and not error
        cmd=data if commit and address==12 else 0
        if not rst:self.reset()
        else:
            self.expired=self.timer.step(self.control&1,self.tr if cmd&1 else None,periodic=bool(self.control&2))
            self.request=self.watchdog.step(self.control&4,self.wr if cmd&2 else None,kick=bool(cmd&4))
            self.pending=int(bool(self.expired or (self.pending and not cmd&8)))
            if sel and not access:self.remaining=self.wait
            elif sel and access and self.remaining:self.remaining-=1
            if commit:
                if address==0:self.control=data&15
                elif address==4:self.tr=data&self.mask
                elif address==8:self.wr=data&self.mask
        return [*command,ready,error,read,self.timer.count,self.watchdog.count,self.pending,
                int(bool(self.pending and self.control&8)),self.request,self.expired,self.control,self.tr,self.wr]


class Plan:
    def __init__(self,width,wait):self.model=Oracle(width,wait);self.wait=wait;self.rows=[]
    def cycle(self,rst=1,sel=0,access=0,write=0,address=0,data=0):
        self.rows.append(self.model.step([rst,sel,access,write,address,data]))
    def idle(self,n=1):
        for _ in range(n):self.cycle()
    def apb(self,address,data=None,abort=False):
        write=int(data is not None);value=0 if data is None else data
        self.cycle(sel=1,write=write,address=address,data=value)
        if abort:
            self.cycle(rst=0,sel=1,access=1,write=write,address=address,data=value);self.idle()
        else:
            for _ in range(self.wait+1):self.cycle(sel=1,access=1,write=write,address=address,data=value)


def boundary_vectors(width,wait):
    p=Plan(width,wait);maximum=(1<<width)-1
    p.cycle(rst=0);p.idle()
    for address in (0,4,8,12,16,20,24,28):p.apb(address)
    p.apb(0,0);p.apb(4,0xffffffff);p.apb(8,maximum)
    p.apb(4);p.apb(8);p.apb(12,3)  # Load while disabled; high bits truncate.
    p.idle(3);p.apb(0,5);p.idle(maximum+2)
    p.apb(16);p.apb(20);p.apb(24)
    p.apb(0,0);p.apb(4,1);p.apb(8,1);p.apb(12,3)
    p.apb(0,7)  # Periodic reload=1: expiry on every enabled clock; IRQ masked.
    p.apb(12,8);p.apb(16);p.apb(12,1)  # Clear vs expiry, then load vs expiry.
    p.apb(0,11);p.apb(16)  # Unmask already pending IRQ.
    p.apb(0,8);p.apb(12,8);p.apb(16)  # Disable timer and clear.
    p.apb(0,0);p.apb(8,wait+2);p.apb(12,2);p.apb(0,12)
    p.apb(12,4)  # Counter is one on the command completion edge: kick wins.
    p.apb(0,0);p.apb(8,3);p.apb(12,6)  # Load + kick: load wins.
    p.apb(0,0);p.apb(4,wait+2);p.apb(8,wait+2);p.apb(12,3)
    p.apb(0,13);p.idle(wait+4)  # Both expire together.
    p.apb(3);p.apb(3,0xdead);p.apb(16,0xffffffff);p.apb(28)
    p.apb(0,15,abort=True)
    p.apb(4,1);p.apb(8,1);p.apb(12,3);p.apb(0,13);p.idle(3)
    p.cycle(rst=0);p.idle(2)
    return p.rows


def random_vectors(seed,iterations,width,wait):
    rng=random.Random(seed);p=Plan(width,wait);p.cycle(rst=0)
    maximum=(1<<width)-1
    for _ in range(iterations):
        if rng.randrange(20)==0:p.apb(0,rng.randrange(16),abort=True)
        elif rng.randrange(2):p.apb(rng.choice((0,4,8,12)),rng.choice((0,1,2,maximum,maximum-1,rng.getrandbits(32))))
        else:p.apb(rng.choice((0,4,8,12,16,20,24,28,3,32)))
        p.idle(rng.randrange(5))
    p.cycle(rst=0);p.idle(2)
    return p.rows


def totals(rows):
    return dict(completions=sum(r[6] for r in rows),errors=sum(r[7] for r in rows),
                waits=sum(bool(r[0] and r[1] and r[2] and not r[6]) for r in rows),
                timer_expiries=sum(r[14] for r in rows),watchdog_resets=sum(r[13] for r in rows))


def make_cases(args,parameters):
    width,wait=parameters['WIDTH'],parameters['WAIT_CYCLES']
    baseline=boundary_vectors(width,wait)
    result=[dict(id='boundaries',vectors=baseline,mutation=args.demo_bug,expected_failure=None,category='functional')]
    for seed in range(args.seed,args.seed+(3 if args.profile=='nightly' else 1)):
        result.append(dict(id=f'random-seed{seed}',seed=seed,vectors=random_vectors(seed,args.iterations,width,wait),
                           mutation=args.demo_bug,expected_failure=None,category='functional'))
    for m,label in ((1,'APB_TIMER_STATE'),(2,'APB_TIMER_IRQ'),(3,'APB_TIMER_STATE'),(4,'APB_TIMER_IRQ')):
        result.append(dict(id=f'detect-mutation{m}',vectors=baseline,mutation=m,expected_failure=label,category='mutation'))
    for case in result:case['counts']=totals(case['vectors'])
    return result


if __name__=='__main__':
    spec=importlib.util.spec_from_file_location('local_runner',HERE.parent/'local-common/runner.py')
    support=importlib.util.module_from_spec(spec);spec.loader.exec_module(support)
    sys.exit(support.main(sys.modules[__name__]))

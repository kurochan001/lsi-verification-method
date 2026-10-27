#!/usr/bin/env python3
"""Local timer/watchdog regression using enabled-clock deadlines as the oracle."""
import importlib.util
from pathlib import Path
import random
import sys

HERE=Path(__file__).resolve().parent
NAME='local-timer-watchdog'
TOP='timer_watchdog_tb'
CONFIGS={f'width{w}':dict(WIDTH=w) for w in (4,8)}
ITERATIONS={'smoke':200,'nightly':2000}
SOURCES=[HERE/'rtl/timer_watchdog.sv',HERE/'tb/timer_watchdog_tb.sv']


def stimulus(**kwargs):
    names=('rst_n','timer_enable','periodic','timer_load','timer_reload',
           'watchdog_enable','watchdog_load','watchdog_reload','kick','clear_irq')
    defaults=dict(rst_n=1,timer_enable=0,periodic=0,timer_load=0,timer_reload=0,
                  watchdog_enable=0,watchdog_load=0,watchdog_reload=0,kick=0,clear_irq=0)
    defaults.update(kwargs)
    return [defaults[n] for n in names]


def reference(inputs):
    """Model elapsed enabled clocks and deadlines; no RTL downcounter replication."""
    timer_tick=watchdog_tick=0
    timer_deadline=watchdog_deadline=None
    timer_saved=watchdog_saved=irq=0
    rows=[]
    for command in inputs:
        reset,te,periodic,tl,tr,we,wl,wr,kick,clear=command
        expired=request=0
        if not reset:
            timer_tick=watchdog_tick=0
            timer_deadline=watchdog_deadline=None
            timer_saved=watchdog_saved=irq=0
        else:
            timer_tick+=te
            watchdog_tick+=we
            if tl:
                timer_saved=tr
                timer_deadline=timer_tick+tr if tr else None
            elif te and timer_deadline is not None and timer_tick>=timer_deadline:
                expired=1
                timer_deadline=timer_tick+timer_saved if periodic and timer_saved else None
            if wl:
                watchdog_saved=wr
                watchdog_deadline=watchdog_tick+wr if wr else None
            elif we and kick:
                watchdog_deadline=watchdog_tick+watchdog_saved if watchdog_saved else None
            elif we and watchdog_deadline is not None and watchdog_tick>=watchdog_deadline:
                request=1
                watchdog_deadline=None
            irq=expired or (irq and not clear)
        tc=timer_deadline-timer_tick if timer_deadline is not None else 0
        wc=watchdog_deadline-watchdog_tick if watchdog_deadline is not None else 0
        rows.append([*command,tc,wc,int(irq),request,expired])
    return rows


def boundary_inputs(width):
    maximum=(1<<width)-1
    commands=[]
    def add(n=1,**kwargs):commands.extend([stimulus(**kwargs) for _ in range(n)])
    add(rst_n=0)
    add(timer_load=1,timer_reload=0,watchdog_load=1,watchdog_reload=0)
    add(3,timer_enable=1,periodic=1,watchdog_enable=1,kick=1)
    add(timer_load=1,timer_reload=1)
    add(timer_enable=1,clear_irq=1)  # expiry wins over clear
    add(clear_irq=1)
    add(3,timer_enable=1)
    add(timer_load=1,timer_reload=maximum)
    add(3)  # disabled holds maximum
    add(maximum,timer_enable=1)
    add(timer_load=1,timer_reload=1)
    add(4,timer_enable=1,periodic=1)  # expires on every enabled clock
    add(2,periodic=1)
    add(2,timer_enable=1,periodic=1)
    add(timer_load=1,timer_reload=3)
    add(10,timer_enable=1,periodic=1)
    add(timer_load=1,timer_reload=1)
    add(timer_load=1,timer_reload=maximum,timer_enable=1)  # load suppresses expiry
    add(watchdog_load=1,watchdog_reload=maximum)
    add(3,kick=1)  # disabled kick ignored
    add(maximum,watchdog_enable=1)
    add(3,watchdog_enable=1)  # no repeated reset request
    add(watchdog_load=1,watchdog_reload=1)
    add(watchdog_enable=1,kick=1)  # kick suppresses impending expiry
    add(watchdog_enable=1)
    add(watchdog_enable=1,kick=1)  # rearm after expiry
    add(watchdog_load=1,watchdog_reload=2,watchdog_enable=1,kick=1)
    add(watchdog_enable=1)
    add(2)  # freeze at one
    add(watchdog_enable=1)
    add(timer_load=1,timer_reload=1,watchdog_load=1,watchdog_reload=1)
    add(timer_enable=1,watchdog_enable=1)
    add(timer_load=1,timer_reload=3,watchdog_load=1,watchdog_reload=3)
    add(rst_n=0,timer_enable=1,watchdog_enable=1,kick=1,clear_irq=1)
    add(timer_load=1,timer_reload=1,watchdog_load=1,watchdog_reload=1)
    add(timer_enable=1,watchdog_enable=1)
    add(rst_n=0)
    add(2)
    return commands


def random_inputs(seed,iterations,width):
    rng=random.Random(seed)
    maximum=(1<<width)-1
    rows=[stimulus(rst_n=0)]
    for _ in range(iterations):
        reloads=[0,1,2,maximum,maximum-1,rng.randrange(maximum+1)]
        rows.append(stimulus(rst_n=int(rng.randrange(40)!=0),timer_enable=rng.randrange(2),
            periodic=rng.randrange(2),timer_load=int(rng.randrange(5)==0),timer_reload=rng.choice(reloads),
            watchdog_enable=rng.randrange(2),watchdog_load=int(rng.randrange(8)==0),
            watchdog_reload=rng.choice(reloads),kick=int(rng.randrange(4)==0),clear_irq=int(rng.randrange(3)==0)))
    return rows+[stimulus(rst_n=0),stimulus(),stimulus()]


def make_cases(args,parameters):
    width=parameters['WIDTH']
    baseline=reference(boundary_inputs(width))
    result=[dict(id='boundaries',vectors=baseline,mutation=args.demo_bug,expected_failure=None,category='functional')]
    for seed in range(args.seed,args.seed+(3 if args.profile=='nightly' else 1)):
        result.append(dict(id=f'random-seed{seed}',seed=seed,
            vectors=reference(random_inputs(seed,args.iterations,width)),mutation=args.demo_bug,
            expected_failure=None,category='functional'))
    for mutation,label in ((1,'TIMER_STATE'),(2,'TIMER_IRQ'),(3,'WDG_STATE'),(4,'TIMER_STATE')):
        result.append(dict(id=f'detect-mutation{mutation}',vectors=baseline,mutation=mutation,
            expected_failure=label,category='mutation'))
    for case in result:
        case['counts']=dict(timer_expiries=sum(r[14] for r in case['vectors']),
                            watchdog_resets=sum(r[13] for r in case['vectors']))
    return result


if __name__=='__main__':
    spec=importlib.util.spec_from_file_location('local_runner',HERE.parent/'local-common/runner.py')
    support=importlib.util.module_from_spec(spec);spec.loader.exec_module(support)
    sys.exit(support.main(sys.modules[__name__]))

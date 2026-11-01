#!/usr/bin/env python3
"""One-axis fixed-point PI closed loop with an actual-PWM-driven normalized motor plant."""
import importlib.util
from pathlib import Path
import sys
HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('axis_support',HERE.parent/'local-motion-io/support.py');S=importlib.util.module_from_spec(spec);spec.loader.exec_module(S)
E=S.E;C=S.load('axis_campaigns',HERE/'cases.py')
CONFIGS={'p16-sample64':dict(PERIOD=16,DEAD=2,FILTER=2,SAMPLE=64,LATENCY=3,SPEED_LIMIT=6),'p24-sample96':dict(PERIOD=24,DEAD=3,FILTER=3,SAMPLE=96,LATENCY=5,SPEED_LIMIT=8)}
SOURCES=[*sorted((HERE/'rtl').glob('*.sv')),*sorted((HERE.parent/'local-motion-io/rtl').glob('*.sv')),HERE/'tb/motion_axis_tb.sv']

def run(a):
    seeds=list(range(a.seed,a.seed+(3 if a.profile=='nightly' else 1)));names=[*C.NAMES,*[f'random-{s}' for s in seeds],*[f'mutation-{i}' for i in range(1,5)]]
    e=E.Evidence('local-motion-control',a,[Path(__file__),HERE/'cases.py',HERE/'model.py',HERE/'requirements.json',HERE.parent/'local-motion-io/support.py',HERE.parent/'local-motion-io/model.py',*SOURCES],dict(configurations=CONFIGS,seeds=seeds),['toolchain',*[cfg+'/'+n for cfg in CONFIGS for n in [*names,'coverage']],'source-freshness'])
    sim=S.Simulator(e,'motion_axis_tb',SOURCES);probes={n:E.P.execute([getattr(a,n),'-V'],e.out/(n+'-version.log'),a.timeout,e.out) for n in ('iverilog','vvp')};E.P.write_json(e.out/'tools.json',probes);e.check('toolchain',all(r['returncode']==0 and not r['error'] for r in probes.values()),probes)
    _,goals=E.C.catalog(HERE/'requirements.json');coverage={}
    for cfg,pars in CONFIGS.items():
        for name in C.NAMES:
            rows,expected,counts=C.make(name,pars,a.seed);sim.execute(cfg+'/'+name,pars,rows,expected,counts,a.seed)
        for seed in seeds:
            rows,expected,counts=C.make('random',pars,seed,6 if a.profile=='nightly' else 2);sim.execute(cfg+f'/random-{seed}',pars,rows,expected,counts,seed)
        for i,(name,label) in enumerate((('saturation','AXIS_PI'),('tracking','AXIS_PWM'),('deadline','AXIS_STATE'),('estop-rearm','AXIS_STATE')),1):
            rows,expected,counts=C.make(name,pars,a.seed);sim.execute(cfg+f'/mutation-{i}',pars,rows,expected,counts,a.seed,i,label)
        hits=set(g for r in sim.records if r['id'].startswith(cfg+'/') for g in r['coverage']);coverage[cfg]=dict(required=sorted(goals),hit=sorted(hits),missing=sorted(goals-hits));e.check(cfg+'/coverage',not goals-hits,coverage[cfg])
    sim.save();E.P.write_json(e.out/'coverage.json',coverage);S.fresh(e);return e.finish()

def main():
    p=E.parser(__doc__,'local-motion-control');a=p.parse_args();E.validate(p,a)
    try:return run(a)
    except (OSError,ValueError,KeyError,TypeError) as exc:print('RUNNER_ERROR',exc,file=sys.stderr);return 1
if __name__=='__main__':sys.exit(main())

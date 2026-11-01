#!/usr/bin/env python3
"""TMR limit register + SECDED store + watchdog: fault isolation, command cancellation and checked recovery."""
import importlib.util
from pathlib import Path
import sys
HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('fdir_support',HERE.parent/'local-tmr/support.py');S=importlib.util.module_from_spec(spec);spec.loader.exec_module(S)
E=S.E;C=S.load('fdir_campaigns',HERE/'cases.py')
CONFIGS={'depth4-wd5':dict(DEPTH=4,WD_LIMIT=5,TRIP=3),'depth8-wd9':dict(DEPTH=8,WD_LIMIT=9,TRIP=2)}
SOURCES=[*sorted((HERE/'rtl').glob('*.sv')),HERE.parent/'local-tmr/rtl/tmr_register.sv',HERE.parent/'local-ecc/rtl/secded.sv',HERE.parent/'local-timer-watchdog/rtl/timer_watchdog.sv',HERE/'tb/fdir_tb.sv']

def run(a):
    seeds=list(range(a.seed,a.seed+(3 if a.profile=='nightly' else 1)));names=[*C.NAMES,*[f'random-{s}' for s in seeds],*[f'mutation-{i}' for i in range(1,5)]]
    e=E.Evidence('local-fdir',a,[Path(__file__),HERE/'cases.py',HERE/'model.py',HERE/'requirements.json',HERE.parent/'local-tmr/support.py',HERE.parent/'local-tmr/model.py',*SOURCES],dict(configurations=CONFIGS,seeds=seeds),['toolchain',*[cfg+'/'+n for cfg in CONFIGS for n in [*names,'coverage']],'source-freshness'])
    sim=S.Simulator(e,'fdir_tb',SOURCES);probes={n:E.P.execute([getattr(a,n),'-V'],e.out/(n+'-version.log'),a.timeout,e.out) for n in ('iverilog','vvp')};E.P.write_json(e.out/'tools.json',probes);e.check('toolchain',all(r['returncode']==0 and not r['error'] for r in probes.values()),probes)
    _,goals=E.C.catalog(HERE/'requirements.json');coverage={}
    for cfg,pars in CONFIGS.items():
        for name in C.NAMES:
            rows,expected,counts=C.make(name,pars,a.seed);sim.execute(cfg+'/'+name,pars,rows,expected,counts,a.seed)
        for seed in seeds:
            rows,expected,counts=C.make('random',pars,seed,48 if a.profile=='nightly' else 16);sim.execute(cfg+f'/random-{seed}',pars,rows,expected,counts,seed)
        for i,(name,label) in enumerate((('watchdog','FDIR_CONTAIN'),('recovery-ecc','FDIR_STATE'),('watchdog','FDIR_STATE'),('watchdog','FDIR_STATE')),1):
            rows,expected,counts=C.make(name,pars,a.seed);sim.execute(cfg+f'/mutation-{i}',pars,rows,expected,counts,a.seed,i,label)
        hits=set(g for r in sim.records if r['id'].startswith(cfg+'/') for g in r['coverage']);coverage[cfg]=dict(required=sorted(goals),hit=sorted(hits),missing=sorted(goals-hits));e.check(cfg+'/coverage',not goals-hits,coverage[cfg])
    sim.save();E.P.write_json(e.out/'coverage.json',coverage);S.fresh(e);return e.finish()

def main():
    p=E.parser(__doc__,'local-fdir');a=p.parse_args();E.validate(p,a)
    try:return run(a)
    except (OSError,ValueError,KeyError,TypeError) as exc:print('RUNNER_ERROR',exc,file=sys.stderr);return 1
if __name__=='__main__':sys.exit(main())

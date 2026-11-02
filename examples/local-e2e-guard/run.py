#!/usr/bin/env python3
"""Executable automotive communication and supervised-command contracts."""
import importlib.util
from pathlib import Path
import sys
HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('automotive_vector_support',HERE.parent/'local-motion-io/support.py');S=importlib.util.module_from_spec(spec);spec.loader.exec_module(S)
E=S.E;C=S.load('automotive_cases',HERE/'cases.py')
CONFIGS={'id-a12f': {'DATA_ID': 41263}, 'id-35c9': {'DATA_ID': 13769}}
MUTATIONS=[('corruption-identity', 'E2E_STATUS'), ('corruption-identity', 'E2E_STATUS'), ('sequence', 'E2E_STATUS'), ('backpressure-reset', 'E2E_READY'), ('backpressure-reset', 'E2E_STATUS')]
SOURCES=[*sorted((HERE/'rtl').glob('*.sv')),HERE/'tb/e2e_guard_tb.sv']
def run(a):
    seeds=list(range(a.seed,a.seed+(3 if a.profile=='nightly' else 1)))
    names=[*C.NAMES,*[f'random-{seed}' for seed in seeds],*[f'mutation-{i}' for i in range(1,len(MUTATIONS)+1)]]
    e=E.Evidence('local-e2e-guard',a,[Path(__file__),HERE/'cases.py',HERE/'model.py',HERE/'requirements.json',HERE.parent/'local-motion-io/support.py',*SOURCES],dict(configurations=CONFIGS,seeds=seeds),['toolchain',*[cfg+'/'+n for cfg in CONFIGS for n in [*names,'coverage']],'source-freshness'])
    sim=S.Simulator(e,'e2e_guard_tb',SOURCES)
    probes={n:E.P.execute([getattr(a,n),'-V'],e.out/(n+'-version.log'),a.timeout,e.out) for n in ('iverilog','vvp')}
    E.P.write_json(e.out/'tools.json',probes);e.check('toolchain',all(not r['error'] and r['returncode']==0 for r in probes.values()),probes)
    _,goals=E.C.catalog(HERE/'requirements.json');coverage={}
    for cfg,pars in CONFIGS.items():
        for case in C.NAMES:
            rows,expected,counts=C.make(case,pars,a.seed);sim.execute(cfg+'/'+case,pars,rows,expected,counts,a.seed)
        for seed in seeds:
            rows,expected,counts=C.make('random',pars,seed,1500 if a.profile=='nightly' else 200);sim.execute(cfg+f'/random-{seed}',pars,rows,expected,counts,seed)
        for i,(case,label) in enumerate(MUTATIONS,1):
            rows,expected,counts=C.make(case,pars,a.seed);sim.execute(cfg+f'/mutation-{i}',pars,rows,expected,counts,a.seed,i,label)
        hit={g for r in sim.records if r['id'].startswith(cfg+'/') for g in r['coverage']};coverage[cfg]=dict(required=sorted(goals),hit=sorted(hit),missing=sorted(goals-hit));e.check(cfg+'/coverage',not goals-hit,coverage[cfg])
    sim.save();E.P.write_json(e.out/'coverage.json',coverage);S.fresh(e);return e.finish()
def main():
    p=E.parser(__doc__,'local-e2e-guard');a=p.parse_args();E.validate(p,a)
    try:return run(a)
    except (OSError,ValueError,KeyError,TypeError) as exc:print('RUNNER_ERROR',exc,file=sys.stderr);return 1
if __name__=='__main__':sys.exit(main())

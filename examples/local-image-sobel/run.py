#!/usr/bin/env python3
"""Two-line Sobel image IP: independent whole-frame oracle, streaming stalls and reset."""
import importlib.util
import json
from pathlib import Path
import sys

HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('sobel_support',HERE/'support.py');S=importlib.util.module_from_spec(spec);spec.loader.exec_module(S)
E=S.E
CONFIGS={'w5h4':dict(W=5,H=4),'w7h5':dict(W=7,H=5)}
SOURCES=[HERE.parent/'local-conv-window/rtl/conv_window.sv',HERE/'rtl/sobel_stream.sv',HERE/'tb/sobel_tb.sv']


def run(a):
    seeds=list(range(a.seed,a.seed+(3 if a.profile=='nightly' else 1)))
    names=['directed',*[f'random-{seed}' for seed in seeds],'reset',*[f'mutation-{i}' for i in range(1,5)]]
    ids=['toolchain',*[f'{cfg}/{n}' for cfg in CONFIGS for n in [*names,'coverage']],'source-freshness']
    e=E.Evidence('local-image-sobel',a,[Path(__file__),HERE/'support.py',HERE/'model.py',HERE/'requirements.json',*SOURCES],dict(configurations=CONFIGS,seeds=seeds),ids)
    sim=S.Simulator(e,'sobel_tb',SOURCES)
    probes={name:E.P.execute([getattr(a,name),'-V'],e.out/(name+'-version.log'),a.timeout,e.out) for name in ('iverilog','vvp')}
    E.P.write_json(e.out/'tools.json',probes);e.check('toolchain',all(not r['error'] and r['returncode']==0 for r in probes.values()),probes)
    _,goals=E.C.catalog(HERE/'requirements.json');coverage={}
    for cfg,parameters in CONFIGS.items():
        w,h=parameters['W'],parameters['H'];frames=S.MODEL.directed(w,h)
        sim.execute(cfg+'/directed',parameters,frames,a.seed)
        for seed in seeds:sim.execute(cfg+f'/random-{seed}',parameters,S.MODEL.random_frames(w,h,seed,12 if a.profile=='nightly' else 4),seed)
        sim.execute(cfg+'/reset',parameters,frames,a.seed,scenario=1)
        for mutation,label in ((1,'IMAGE_DATA'),(2,'IMAGE_DATA'),(3,'IMAGE_LAST'),(4,'IMAGE_HOLD')):
            sim.execute(cfg+f'/mutation-{mutation}',parameters,frames,a.seed,mutation=mutation,expected=label)
        hit=set(g for r in sim.records if r['id'].startswith(cfg+'/') for g in r['coverage'])
        coverage[cfg]=dict(required=sorted(goals),hit=sorted(hit),missing=sorted(goals-hit));e.check(cfg+'/coverage',not goals-hit,coverage[cfg])
    sim.save();E.P.write_json(e.out/'coverage.json',coverage);S.fresh(e);return e.finish()


def main():
    p=E.parser(__doc__,'local-image-sobel');a=p.parse_args();E.validate(p,a)
    if a.seed>2**31-4:p.error('seed must fit the three-seed signed 32-bit simulation range')
    try:return run(a)
    except (OSError,ValueError,KeyError,TypeError) as exc:print('RUNNER_ERROR',exc,file=sys.stderr);return 1
if __name__=='__main__':sys.exit(main())

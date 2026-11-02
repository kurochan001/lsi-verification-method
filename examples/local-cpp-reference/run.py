#!/usr/bin/env python3
"""Check a streaming FIR RTL against an independent transaction-level C++ model."""
import importlib.util
from pathlib import Path
import random
import sys
HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('cpp_native',HERE.parent/'local-native-common/runner.py');S=importlib.util.module_from_spec(spec);spec.loader.exec_module(S)
E=S.E
CONFIGS={'w8-lat1':dict(WIDTH=8,LATENCY=1),'w12-lat3':dict(WIDTH=12,LATENCY=3)}
RTL=[HERE/'rtl/saturating_fir.sv'];CPP=[HERE/'harness.cpp',HERE/'model/reference.cpp']

def samples(name,width,seed,count):
    hi=(1<<(width-1))-1;lo=-(1<<(width-1))
    fixed=[0,0,0,1,0,0,-1,0,0,2,-2,0,hi,lo,hi,lo,hi,lo,0,0,0]
    if name=='random':
        rng=random.Random(seed)
        return fixed+[rng.randrange(lo,hi+1) for _ in range(count)]
    return fixed*3 if name=='stalls' else fixed

def run(a):
    seeds=list(range(a.seed,a.seed+(3 if a.profile=='nightly' else 1)))
    names=['basic','stalls','reset',*[f'random-{s}' for s in seeds],*[f'detect-rtl-{m}' for m in range(1,5)],'detect-model']
    plan=['toolchain',*[f'{cfg}/{n}' for cfg in CONFIGS for n in [*names,'coverage']],'source-freshness']
    e=E.Evidence('local-cpp-reference',a,[Path(__file__),Path(S.__file__),*RTL,*CPP,HERE/'model/reference.hpp',HERE/'requirements.json'],dict(configurations=CONFIGS,seeds=seeds),plan)
    sim=S.Native(e,'saturating_fir',RTL,CPP);good,probes=sim.probes();e.check('toolchain',good,probes)
    _,goals=E.C.catalog(HERE/'requirements.json');coverage={}
    for cfg,parameters in CONFIGS.items():
        hits=set()
        for name in names:
            mutation=int(name[-1]) if name.startswith('detect-rtl-') else 0
            scenario='reset' if mutation==4 else 'stalls' if mutation==3 else 'basic' if name.startswith('detect-') else 'random' if name.startswith('random-') else name
            seed=int(name[7:]) if name.startswith('random-') else a.seed
            data=samples(scenario,parameters['WIDTH'],seed,256 if a.profile=='nightly' else 64)
            path=e.out/'vectors'/cfg/name/'vectors.txt';path.parent.mkdir(parents=True);path.write_text(''.join(str(v)+'\n' for v in data))
            build=sim.build(cfg,parameters,mutation,flags=['-I'+str(HERE/'model')])
            label='CPP_HOLD' if mutation==3 else 'CPP_DATA' if name.startswith('detect-') else None
            cancel=int(scenario=='reset')
            result=sim.execute(cfg+'/'+name,build,[scenario,seed,len(data),int(name=='detect-model'),path],dict(accepted=len(data)+cancel,retired=len(data),cancelled=cancel,resets=1+cancel),len(data),label,credited=label is None)
            hits.update(result['coverage'])
        coverage[cfg]=dict(required=sorted(goals),hit=sorted(hits),missing=sorted(goals-hits))
        e.check(cfg+'/coverage',not goals-hits,coverage[cfg])
    sim.save();E.P.write_json(e.out/'coverage.json',coverage);S.fresh(e);return e.finish()

def main():
    p=S.parser(__doc__,'local-cpp-reference');a=p.parse_args();S.validate(p,a)
    try:return run(a)
    except (OSError,ValueError,KeyError,TypeError) as err:print('RUNNER_ERROR',err,file=sys.stderr);return 1
if __name__=='__main__':sys.exit(main())

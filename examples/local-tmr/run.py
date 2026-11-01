#!/usr/bin/env python3
"""Three-replica register: majority, diagnosis, repair, collisions, and fault-model limits."""
import importlib.util
from pathlib import Path
import random
import sys
HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('tmr_support',HERE/'support.py');S=importlib.util.module_from_spec(spec);spec.loader.exec_module(S)
E=S.E;M=S.load('tmr_oracle',HERE/'model.py');CONFIGS={'bits8':dict(WIDTH=8),'bits16':dict(WIDTH=16)}
SOURCES=[HERE/'rtl/tmr_register.sv',HERE/'tb/tmr_tb.sv']

def stimuli(width,seed,count=32):
    rows=[[0,1,255,1,1,1,1],[1,1,0x55,0,0,0,0]]
    for lane in range(3):
        for bit in range(width):
            rows += [[1,1,0x55,0,0,0,0],[1,0,0,0,*[1<<bit if i==lane else 0 for i in range(3)]],[1,0,0,0,0,0,0],[1,0,0,1,0,0,0]]
    rows += [[1,0,0,0,1,0,0],[1,1,0xaa,1,0,0,0],[1,1,0x55,1,0,0,4],[1,0,0,1,0,0,0], # write wins over repair
             [1,1,0,0,0,0,0],[1,0,0,0,1,1,0],[1,0,0,1,0,0,0], # majority can repair to a wrong value
             [1,1,0,0,0,0,0],[1,0,0,0,2,2,2],[1,0,0,0,0,0,0], # common-mode upset is invisible
             [0,1,255,1,255,255,255],[1,1,0xaa,1,0,0,0]]
    rng=random.Random(seed)
    for _ in range(count):rows.append([1,int(rng.randrange(5)==0),rng.getrandbits(width),rng.randrange(2),*[rng.getrandbits(width) if rng.randrange(8)==0 else 0 for _ in range(3)]])
    rows.append([1,1,0x55,1,0,0,0]);return rows

def expected(rows,width):
    m=M.Register(width);values=[];counts=dict(rows=len(rows),injections=0,resets=0);old=0
    for row in rows:
        counts['resets']+=int(bool(old and not row[0]));old=row[0]
        counts['injections']+=int(bool(row[0] and any(row[4:])))
        values.append(m.step(row))
    return values,counts

def run(a):
    seeds=list(range(a.seed,a.seed+(3 if a.profile=='nightly' else 1)));names=[*[f'faults-{s}' for s in seeds],*[f'mutation-{i}' for i in range(1,5)]]
    e=E.Evidence('local-tmr',a,[Path(__file__),HERE/'support.py',HERE/'model.py',HERE/'requirements.json',*SOURCES],dict(configurations=CONFIGS,seeds=seeds),['toolchain',*[cfg+'/'+n for cfg in CONFIGS for n in [*names,'coverage']],'source-freshness'])
    sim=S.Simulator(e,'tmr_tb',SOURCES);probes={n:E.P.execute([getattr(a,n),'-V'],e.out/(n+'-version.log'),a.timeout,e.out) for n in ('iverilog','vvp')};E.P.write_json(e.out/'tools.json',probes);e.check('toolchain',all(r['returncode']==0 and not r['error'] for r in probes.values()),probes)
    _,goals=E.C.catalog(HERE/'requirements.json');coverage={}
    for cfg,pars in CONFIGS.items():
        for seed in seeds:
            rows=stimuli(pars['WIDTH'],seed,128 if a.profile=='nightly' else 32);oracle,counts=expected(rows,pars['WIDTH']);sim.execute(cfg+f'/faults-{seed}',pars,rows,oracle,counts,seed)
        for i,label in enumerate(('TMR_VOTE','TMR_STATUS','TMR_VOTE','TMR_STATUS'),1):
            rows=stimuli(pars['WIDTH'],a.seed,0);oracle,counts=expected(rows,pars['WIDTH']);sim.execute(cfg+f'/mutation-{i}',pars,rows,oracle,counts,a.seed,i,label)
        hits=set(g for r in sim.records if r['id'].startswith(cfg+'/') for g in r['coverage']);coverage[cfg]=dict(required=sorted(goals),hit=sorted(hits),missing=sorted(goals-hits));e.check(cfg+'/coverage',not goals-hits,coverage[cfg])
    sim.save();E.P.write_json(e.out/'coverage.json',coverage);S.fresh(e);return e.finish()

def main():
    p=E.parser(__doc__,'local-tmr');a=p.parse_args();E.validate(p,a)
    try:return run(a)
    except (OSError,ValueError,KeyError,TypeError) as exc:print('RUNNER_ERROR',exc,file=sys.stderr);return 1
if __name__=='__main__':sys.exit(main())

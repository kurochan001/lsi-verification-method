#!/usr/bin/env python3
"""Compare a sequential and a pipelined RTL of different latency with one untimed C++ model, by stream."""
import importlib.util
import json
from pathlib import Path
import random
import sys
HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('li_native',HERE.parent/'local-native-common/runner.py');S=importlib.util.module_from_spec(spec);spec.loader.exec_module(S)
E=S.E
CONFIGS={'seq':dict(IMPL=0,SPLIT=0),'pipe':dict(IMPL=1,SPLIT=0),'pipe-split':dict(IMPL=1,SPLIT=1)}
RTL=[HERE/'rtl/dot_seq.sv',HERE/'rtl/dot_pipe.sv',HERE/'rtl/li_dut.sv']
CPP=[HERE/'harness.cpp',HERE/'model/dot_model.cpp']
HEADERS=[HERE/'model/dot_model.hpp',HERE/'model/stream_compare.hpp']
REQUIREMENTS=HERE/'requirements.json'
# mutation: (configuration, scenario, expected label)
MUTANTS={1:('pipe','flow','LI_ORDER'),2:('pipe','flow','LI_DUP'),3:('pipe','flow','LI_DROP'),4:('pipe','flow','LI_WITHDRAW'),
         5:('pipe','reset','LI_EXTRA'),6:('pipe','flow','LI_DATA'),7:('pipe','flow','LI_HOLD'),
         8:('seq','flow','LI_DROP'),9:('seq','flow','LI_DATA')}
# Protocol errors that leave the delivered stream intact: with the monitor off they pass.
BLIND=(4,7)

def T(v):return 'T '+' '.join(map(str,v))
def txn(rng):return [rng.randrange(-128,128) for _ in range(8)]

def flow_steps():
    """Fixed list without resets: boundary values, gaps, long output stalls, alternate and back-to-back traffic."""
    rng=random.Random(1121)
    steps=['MODE on',T([1,2,3,4,5,6,7,8]),'IDLE 3',T([-128]*8),T([-128]*4+[127]*4),T([1,-1,2,-2,1,1,1,1]),
           T([0,0,0,-5,0,0,0,7]),T([0,0,0,5,0,0,0,-7]),'IDLE 2']
    steps+=['MODE burst',*[T(txn(rng)) for _ in range(14)]]
    steps+=['MODE alt',*[T(txn(rng)) for _ in range(8)]]
    steps+=['MODE on',*[T(txn(rng)) for _ in range(10)],'DRAIN']
    return steps

def reset_steps():
    """A reset with one result in flight, a reset with the design full, then traffic again."""
    rng=random.Random(2111)
    return ['MODE on',*[T(txn(rng)) for _ in range(3)],'DRAIN','RESETAFTER 1',T(txn(rng)),'FILL 6',*[T(txn(rng)) for _ in range(6)],
            'MODE burst',*[T(txn(rng)) for _ in range(6)],'DRAIN']

def random_steps(seed,count):
    rng=random.Random(seed);steps=['MODE rand']
    for _ in range(count):
        if rng.random()<0.2:steps.append(f'IDLE {rng.randrange(1,4)}')
        steps.append(T(txn(rng)))
    return steps+['DRAIN']

def expectations(steps):
    """Delivered transactions and scenario resets, from the list alone: what a reset cancels is never counted."""
    delivered=resets=skip=0
    for step in steps:
        word=step.split()[0]
        if word=='T':
            if skip:skip-=1
            else:delivered+=1
        elif word in ('RESETAFTER','FILL'):
            resets+=1;skip=1 if word=='RESETAFTER' else int(step.split()[1])
    if skip:raise ValueError('reset directive without its transactions')
    return delivered,resets

def required(catalog,cfg):
    return {g for r in catalog['requirements'] if cfg in r.get('configs',CONFIGS) for g in r['goals']}

def read_transfers(path):
    rows=path.read_text().splitlines()
    if not rows or rows[0]!='cycle,value':raise ValueError('bad transfer log '+str(path))
    return [tuple(map(int,line.split(','))) for line in rows[1:]]

def cycle_compare(a,b):
    """A cycle-locked comparison: the first position where (cycle, value) differ, or None."""
    for i,(x,y) in enumerate(zip(a,b)):
        if x!=y:return dict(index=i,first=x,second=y)
    return None if len(a)==len(b) else dict(index=min(len(a),len(b)),first=None,second=None)

def weak_check(expected,actual):
    """An order-blind check: the same number of results with the same sum."""
    return len(expected)==len(actual) and sum(expected)==sum(actual)

def plan_of(a):
    configs=CONFIGS if a.configuration=='all' else {a.configuration:CONFIGS[a.configuration]}
    seeds=list(range(a.seed,a.seed+(3 if a.profile=='nightly' else 1)))
    ids=['toolchain']
    for cfg in configs:
        ids+=[f'{cfg}/{n}' for n in ('flow','reset',*[f'random-{s}' for s in seeds])]
        ids+=[f'{cfg}/detect-m{m}' for m,v in MUTANTS.items() if v[0]==cfg]
        ids+=[f'{cfg}/blind-m{m}' for m in BLIND if MUTANTS[m][0]==cfg]
        ids.append(f'{cfg}/coverage')
    if len(configs)==len(CONFIGS):ids.append('diagnose-cycle-compare')
    if MUTANTS[1][0] in configs:ids.append('diagnose-weak-check')
    return configs,seeds,ids+['source-freshness']

def run(a):
    configs,seeds,ids=plan_of(a)
    count=120 if a.profile=='nightly' else 40
    e=E.Evidence('local-latency-insensitive-compare',a,[Path(__file__),Path(S.__file__),*RTL,*CPP,*HEADERS,REQUIREMENTS],
                 dict(configurations=configs,seeds=seeds,random_transactions=count,mutants={str(k):v for k,v in MUTANTS.items()}),ids)
    sim=S.Native(e,'li_dut',RTL,CPP);good,probes=sim.probes();e.check('toolchain',good,probes)
    catalog=json.loads(REQUIREMENTS.read_text());E.C.catalog(REQUIREMENTS)
    scenarios={'flow':flow_steps(),'reset':reset_steps(),**{f'random-{s}':random_steps(s,count) for s in seeds}}
    flags=['-I'+str(HERE/'model')]
    def case(cfg,name,scenario,mutation=0,label=None,monitor=1,credited=True):
        steps=scenarios[scenario];delivered,resets=expectations(steps)
        path=e.out/'vectors'/cfg/name/'vectors.txt';path.parent.mkdir(parents=True);path.write_text('\n'.join(steps)+'\n')
        seed=int(scenario[7:]) if scenario.startswith('random-') else a.seed
        build=sim.build(cfg,configs[cfg],mutation,flags=flags)
        return sim.execute(f'{cfg}/{name}',build,[scenario,seed,delivered,monitor,path],
                           dict(delivered=delivered,resets=resets,epochs=resets+1),delivered,label,credited=credited)
    coverage={}
    for cfg in configs:
        hits=set()
        for name in ('flow','reset',*[f'random-{s}' for s in seeds]):
            hits.update(case(cfg,name,name)['coverage'])
        for m,(owner,scenario,label) in MUTANTS.items():
            if owner==cfg:case(cfg,f'detect-m{m}',scenario,m,label,credited=False)
        for m in BLIND:
            if MUTANTS[m][0]==cfg:case(cfg,f'blind-m{m}',MUTANTS[m][1],m,None,monitor=0,credited=False)
        goals=required(catalog,cfg)
        coverage[cfg]=dict(required=sorted(goals),hit=sorted(hits&goals),missing=sorted(goals-hits))
        e.check(f'{cfg}/coverage',not goals-hits,coverage[cfg])
    if 'diagnose-cycle-compare' in ids:
        detail={};ok=True
        try:
            logs={cfg:read_transfers(e.out/cfg/'flow'/'transfers.csv') for cfg in configs}
            streams={cfg:[v for _,v in rows] for cfg,rows in logs.items()}
            ok=len({tuple(s) for s in streams.values()})==1 and len(streams['seq'])==expectations(scenarios['flow'])[0]
            names=list(configs)
            for i,x in enumerate(names):
                for y in names[i+1:]:
                    diff=cycle_compare(logs[x],logs[y]);detail[f'{x}~{y}']=diff;ok=ok and diff is not None
            detail['latency_first_result']={cfg:logs[cfg][0][0] for cfg in configs}
        except (OSError,ValueError,KeyError,IndexError) as err:ok=False;detail['error']=str(err)
        e.check('diagnose-cycle-compare',ok,detail)
    if 'diagnose-weak-check' in ids:
        try:
            d=e.out/MUTANTS[1][0]/'detect-m1'
            exp=[int(x) for x in (d/'stream-expected.txt').read_text().split()];act=[int(x) for x in (d/'stream-actual.txt').read_text().split()]
            ok=exp!=act and sorted(exp)==sorted(act) and weak_check(exp,act)
            detail=dict(results=len(exp),sum=sum(exp),first_difference=next((i for i,(x,y) in enumerate(zip(exp,act)) if x!=y),None))
        except (OSError,ValueError) as err:ok=False;detail=dict(error=str(err))
        e.check('diagnose-weak-check',ok,detail)
    sim.save();E.P.write_json(e.out/'coverage.json',coverage);S.fresh(e);return e.finish()

def main():
    p=S.parser(__doc__,'local-latency-insensitive-compare')
    p.add_argument('--configuration',choices=('all',*CONFIGS),default='all')
    a=p.parse_args();S.validate(p,a)
    try:return run(a)
    except (OSError,ValueError,KeyError,TypeError) as err:print('RUNNER_ERROR',err,file=sys.stderr);return 1
if __name__=='__main__':sys.exit(main())

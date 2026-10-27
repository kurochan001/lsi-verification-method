#!/usr/bin/env python3
"""Compare fixed random stimulus with feedback from observed functional coverage."""
import importlib.util
from pathlib import Path
import random
import sys
import time
HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('feedback_evidence',HERE.parent/'local-exploration-common/evidence.py');E=importlib.util.module_from_spec(spec);spec.loader.exec_module(E)
BATCH=128

def random_rows(plugin,seed,budget):
    rng=random.Random(seed);p=plugin.Plan(2);p.cycle(rst=0)
    while len(p.rows)<budget:
        n=rng.randint(1,5);p.packet([(rng.getrandbits(32),0 if rng.randrange(20)==0 else rng.choice((1,3,15))) for _ in range(n)],rng.randrange(5))
        if rng.randrange(32)==0:
            p.beat(rng.getrandbits(32),15,0);p.drain();p.cycle(rst=0);p.packet([(3,15)])
        if rng.randrange(32)==0:
            p.cycle(valid=1,data=4,keep=15,last=0,ready=0);p.cycle(rst=0);p.packet([(5,15)])
    return p.rows[:budget]

def target_rows(plugin,missing,seed,budget):
    rng=random.Random(seed);p=plugin.Plan(2);p.cycle(rst=0)
    for goal in missing:
        if goal=='reset/queued':
            p.cycle(valid=1,data=rng.getrandbits(32),keep=15,last=0,ready=0);p.cycle(rst=0);p.packet([(3,15)])
        elif goal in ('reset/partial-output','reset/recovery'):
            p.beat(3,15,0);p.drain();p.cycle(rst=0);p.packet([(4,15)])
        elif goal.startswith('handshake/'):
            for i in range(5):p.beat(i,15,int(i==4),4)
            p.drain()
        elif goal=='keep/null':p.packet([(1,0),(2,15)])
        elif goal=='keep/partial':p.packet([(3,5)])
        elif goal=='keep/full':p.packet([(4,15)])
        elif goal=='packet/multiple':p.packet([(5,15),(6,3)])
        elif goal=='packet/single':p.packet([(7,15)])
        else:raise ValueError('no stimulus recipe: '+goal)
    if len(p.rows)>budget:raise ValueError('target recipes exceed batch budget')
    while len(p.rows)<budget:p.packet([(rng.getrandbits(32),15)])
    # All target recipes must fit, otherwise truncation could conceal ineffective guidance.
    return p.rows[:budget]

def comparison(sim,policy,seed,batches,required):
    hits=set();decisions=[];start=time.monotonic();ok=True;checks=0
    for index in range(batches):
        missing=sorted(required-hits)
        use_feedback=policy=='feedback' and index>0 and bool(missing)
        rows=target_rows(sim.plugin,missing,seed+index,BATCH) if use_feedback else random_rows(sim.plugin,seed+index,BATCH)
        result=sim.execute(f'{policy}-seed{seed}-batch{index}',rows)
        ok &= result['status']=='pass';checks+=len(rows)
        if result['status']=='pass':hits.update(result['coverage'])
        decisions.append(dict(batch=index,missing_before=missing,mode='targeted' if use_feedback else 'random',
            actual_goals=result['coverage'],credited=result['status']=='pass',execution=result['id']))
    return dict(policy=policy,seed=seed,success=ok,checks=checks,budget=batches*BATCH,goals=sorted(required & hits),
        missing=sorted(required-hits),seconds=time.monotonic()-start,decisions=decisions)

def run(args):
    _,required=E.C.catalog(HERE.parent/'local-axis/requirements.json');batches=3 if args.profile=='smoke' else 6
    seeds=list(range(args.seed,args.seed+(1 if args.profile=='smoke' else 3)))
    checks=[f'seed{s}-{suffix}' for s in seeds for suffix in ('executions-complete','equal-cycle-budget','feedback-goals','first-batch-identical')]+[f'detect-mutation{m}' for m in range(1,5)]
    e=E.Evidence('local-coverage-feedback',args,[Path(__file__),*E.axis_inputs()],dict(batches=batches,cycles_per_batch=BATCH,seeds=seeds,required=sorted(required)),checks)
    sim=E.AxisSimulator(e);comparisons=[]
    for seed in seeds:
        pair=[comparison(sim,policy,seed,batches,required) for policy in ('random','feedback')];comparisons+=pair
        e.check(f'seed{seed}-executions-complete',all(r['success'] for r in pair),[r['missing'] for r in pair])
        e.check(f'seed{seed}-equal-cycle-budget',pair[0]['checks']==pair[1]['checks']==batches*BATCH,[r['checks'] for r in pair])
        e.check(f'seed{seed}-feedback-goals',not pair[1]['missing'],pair[1]['missing'])
        e.check(f'seed{seed}-first-batch-identical',(e.out/pair[0]['decisions'][0]['execution']/'vectors.txt').read_bytes()==(e.out/pair[1]['decisions'][0]['execution']/'vectors.txt').read_bytes(),'common initial exploration')
    for mutation,label in ((1,'AXIS_META'),(2,'AXIS_META'),(3,'AXIS_DATA'),(4,'AXIS_CONTROL')):
        r=sim.execute(f'detect-mutation{mutation}',sim.plugin.boundary_vectors(2),mutation,label)
        e.check(f'detect-mutation{mutation}',r['status']=='detected',r['message'])
    E.P.write_json(e.out/'coverage.json',dict(required=sorted(required),comparisons=comparisons,
        accounting='equal checked RTL cycles; rebuilds, wall time and diagnostic runs are recorded separately',native_covergroup=False))
    sim.save();return e.finish()

def main():
    p=E.parser(__doc__,'local-coverage-feedback');args=p.parse_args();E.validate(p,args)
    try:return run(args)
    except (OSError,ValueError,RuntimeError,KeyError) as exc:print('RUNNER_ERROR',exc,file=sys.stderr);return 1
if __name__=='__main__':sys.exit(main())

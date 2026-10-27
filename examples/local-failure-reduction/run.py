#!/usr/bin/env python3
"""Reduce a failing AXI4-Stream operation sequence, preserving the checker label."""
import importlib.util
from pathlib import Path
import random
import sys
HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('search_evidence',HERE.parent/'local-exploration-common/evidence.py');E=importlib.util.module_from_spec(spec);spec.loader.exec_module(E)

def ddmin(sequence,predicate):
    """Delete chunks, then certify single-action deletion minimality (not global optimality)."""
    current=list(sequence);n=2
    while len(current)>=2:
        width=(len(current)+n-1)//n;changed=False
        for start in range(0,len(current),width):
            candidate=current[:start]+current[start+width:]
            if predicate(candidate):current=candidate;n=max(2,n-1);changed=True;break
        if not changed:
            if n>=len(current):break
            n=min(len(current),n*2)
    return current

def operations(seed,n):
    rng=random.Random(seed);result=[]
    for _ in range(n):
        result.append(dict(op=rng.choice(('beat','beat','reset','idle')),data=rng.getrandbits(32),keep=rng.choice((0,1,5,15)),last=rng.randrange(2)))
    result.insert(n//2,dict(op='beat',data=0x12345678,keep=1,last=1));return result

def rows(plugin,actions):
    p=plugin.Plan(2);p.cycle(rst=0)
    for action in actions:
        if action['op']=='beat':p.beat(action['data'],action['keep'],action['last']);p.drain()
        elif action['op']=='reset':p.cycle(rst=0)
        elif action['op']=='idle':p.cycle()
        else:raise ValueError('unknown action')
    p.drain();return p.rows

def run(args):
    e=E.Evidence('local-failure-reduction',args,[Path(__file__),*E.axis_inputs()],dict(mutation=3,label='AXIS_DATA',algorithm='ddmin plus single-deletion certification'),['original-reproduces','same-checker-replay','original-rtl-passes','sequence-shortened','single-deletion-minimal','empty-sequence-is-clean'])
    sim=E.AxisSimulator(e);actions=operations(args.seed,24 if args.profile=='smoke' else 100);counter=0;cache={};trace=[]
    def fails(candidate):
        nonlocal counter
        key=repr(candidate)
        if key not in cache:
            result=sim.execute(f'trial-{counter:04d}',rows(sim.plugin,candidate),3,'AXIS_DATA',allow_clean=True);counter+=1
            if result['status'] not in ('pass','detected'):raise RuntimeError('invalid reduction oracle: '+result['message'])
            answer=result['status']=='detected'
            cache[key]=answer;trace.append(dict(actions=candidate,execution=result['id'],same_failure=answer))
        return cache[key]
    e.check('original-reproduces',fails(actions),len(actions))
    reduced=ddmin(actions,fails)
    # Value simplification is accepted only after reproducing the same RTL failure.
    for index,action in enumerate(list(reduced)):
        if action['op']=='beat':
            candidate=[dict(a) for a in reduced];candidate[index].update(data=0,keep=1,last=0)
            if fails(candidate):reduced=candidate
    # Re-run ddmin after simplification and force an uncached final replay.
    reduced=ddmin(reduced,fails)
    final=sim.execute('final-replay',rows(sim.plugin,reduced),3,'AXIS_DATA')
    fixed=sim.execute('original-rtl-replay',rows(sim.plugin,reduced))
    minimal=all(not fails(reduced[:i]+reduced[i+1:]) for i in range(len(reduced)))
    e.check('same-checker-replay',final['status']=='detected',final['message'])
    e.check('original-rtl-passes',fixed['status']=='pass',fixed['message'])
    e.check('sequence-shortened',len(reduced)<len(actions),dict(original=len(actions),reduced=len(reduced)))
    e.check('single-deletion-minimal',minimal and bool(reduced),'every one-action deletion checked')
    # Empty input must not be accepted merely because a tool failed or no output was produced.
    e.check('empty-sequence-is-clean',not fails([]),'no false reproducer')
    E.P.write_json(e.out/'original.json',actions);E.P.write_json(e.out/'reproducer.json',reduced)
    E.P.write_json(e.out/'search.json',dict(trace=trace,original_actions=len(actions),reduced_actions=len(reduced),rtl_executions=len(sim.runs),global_minimum_claimed=False))
    sim.save();return e.finish()

def main():
    p=E.parser(__doc__,'local-failure-reduction');args=p.parse_args();E.validate(p,args)
    try:return run(args)
    except (OSError,ValueError,RuntimeError,KeyError) as exc:print('RUNNER_ERROR',exc,file=sys.stderr);return 1
if __name__=='__main__':sys.exit(main())

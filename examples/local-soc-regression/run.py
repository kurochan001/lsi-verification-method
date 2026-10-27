#!/usr/bin/env python3
"""Seven local examples: native CRV/coverage, register generation, replay and SoC integration."""
import importlib.util
import json
from pathlib import Path
import sys
HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('soc_evidence',HERE.parent/'local-exploration-common/evidence.py');E=importlib.util.module_from_spec(spec);spec.loader.exec_module(E)
CORE=['local-priority-irq','local-descriptor-dma','local-credit-link','local-cache-dma']
TOOLS=['local-uvm-random','local-register-spec'];FORMAL=['local-formal-replay']
def child_success(summary):
    if not isinstance(summary,dict) or summary.get('success') is not True or summary.get('complete') is not True:return False
    planned=summary.get('planned');results=summary.get('results')
    if type(planned) is not int or planned<=0:return False
    if type(results) is int:return results==planned
    if not isinstance(results,list) or len(results)!=planned or not all(isinstance(r,dict) and r.get('status')=='pass' and isinstance(r.get('id'),str) and r['id'].strip() for r in results):return False
    return len({r['id'] for r in results})==len(results)
def run(args):
    names=(CORE if args.stage in ('all','core') else [])+(TOOLS if args.stage in ('all','tools') else [])+(FORMAL if args.stage in ('all','formal') else [])
    e=E.Evidence('local-soc-regression',args,[Path(__file__)],dict(children=names,parent_cases='child regression gates; child checks are separate'),names)
    for name in names:
        interpreter=args.rdl_python if name=='local-register-spec' else sys.executable
        command=[interpreter,str(HERE.parent/name/'run.py'),'--profile',args.profile,'--seed',str(args.seed),'--out',str(e.out/name)]
        if name in TOOLS:command+=['--uvm-home',str(args.uvm_home)]
        if name=='local-uvm-random':command+=['--solver',args.solver]
        if name=='local-formal-replay':command+=['--formal-python',args.formal_python]
        execution=E.P.execute(command,e.out/(name+'.log'),args.child_timeout,e.out);ok=False;detail=execution['error'] or execution['returncode']
        try:
            summary=json.loads((e.out/name/'summary.json').read_text());ok=not execution['error'] and execution['returncode']==0 and child_success(summary)
        except (OSError,ValueError,KeyError,TypeError) as exc:detail=str(exc)
        E.P.write_json(e.out/(name+'-execution.json'),execution);e.check(name,ok,detail)
    return e.finish()
def main():
    p=E.parser(__doc__,'local-soc-regression');p.add_argument('--stage',choices=('all','core','tools','formal'),default='all');p.add_argument('--uvm-home',type=Path);p.add_argument('--rdl-python',default=sys.executable);p.add_argument('--formal-python',default=sys.executable);p.add_argument('--solver',default='z3');p.add_argument('--child-timeout',type=float,default=1800)
    args=p.parse_args();E.validate(p,args)
    import math
    if not math.isfinite(args.child_timeout) or args.child_timeout<=0 or args.seed>2**31-4:p.error('invalid timeout/seed')
    if args.stage in ('all','tools') and args.uvm_home is None:p.error('--uvm-home required for tools stage')
    try:return run(args)
    except (OSError,ValueError,KeyError,TypeError) as exc:print('RUNNER_ERROR',exc,file=sys.stderr);return 1
if __name__=='__main__':sys.exit(main())

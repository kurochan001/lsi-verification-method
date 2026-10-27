#!/usr/bin/env python3
"""Run seven local workflow/integration examples; GitLab is not used."""
import importlib.util
import json
from pathlib import Path
import sys
HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('workflow_evidence',HERE.parent/'local-exploration-common/evidence.py');E=importlib.util.module_from_spec(spec);spec.loader.exec_module(E)
CORE=['local-failure-reduction','local-coverage-feedback','local-width-converter','local-access-control','local-ecc-memory','local-clock-reset']

def child_success(summary):
    if summary.get('success') is not True or summary.get('complete') is not True:return False
    planned=summary.get('planned');results=summary.get('results')
    if type(planned) is not int or planned<=0:return False
    if type(results) is int:return results==planned
    return isinstance(results,list) and len(results)==planned and all(r.get('status')=='pass' for r in results)

def run(args):
    names=(CORE if args.stage in ('all','core') else [])+(['local-uvm'] if args.stage in ('all','uvm') else [])
    e=E.Evidence('local-workflow-regression',args,[Path(__file__)],dict(children=names,parent_cases='child regression gates; child JUnit cases remain separate'),names)
    for name in names:
        command=[sys.executable,str(HERE.parent/name/'run.py'),'--profile',args.profile,'--seed',str(args.seed),'--out',str(e.out/name)]
        if name=='local-uvm':command+=['--uvm-home',str(args.uvm_home.resolve())]
        execution=E.P.execute(command,e.out/(name+'.log'),args.child_timeout,e.out);success=False;detail=execution['error'] or execution['returncode']
        try:
            summary=json.loads((e.out/name/'summary.json').read_text());success=not execution['error'] and execution['returncode']==0 and child_success(summary)
        except (OSError,ValueError,TypeError,KeyError) as exc:detail=str(exc)
        E.P.write_json(e.out/(name+'-execution.json'),execution);e.check(name,success,detail)
    return e.finish()

def main():
    p=E.parser(__doc__,'local-workflow-regression');p.add_argument('--stage',choices=('all','core','uvm'),default='all');p.add_argument('--uvm-home',type=Path);p.add_argument('--child-timeout',type=float,default=1800)
    args=p.parse_args();E.validate(p,args)
    import math
    if not math.isfinite(args.child_timeout) or args.child_timeout<=0:p.error('finite positive child timeout required')
    if args.stage in ('all','uvm') and args.uvm_home is None:p.error('--uvm-home required for UVM; use --stage core for the other six examples')
    try:return run(args)
    except (OSError,ValueError,RuntimeError,KeyError) as exc:print('RUNNER_ERROR',exc,file=sys.stderr);return 1
if __name__=='__main__':sys.exit(main())

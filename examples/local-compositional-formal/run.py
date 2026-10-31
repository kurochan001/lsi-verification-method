#!/usr/bin/env python3
"""Execute actual induction proofs, then reject incomplete/stale/cyclic proof claims."""
import copy
import importlib.util
import json
import math
from pathlib import Path
import sys
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1]
def load(name,path):
    s=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
E=load('contract_evidence',HERE.parent/'local-exploration-common/evidence.py')
D=load('contract_dependencies',HERE/'dependencies.py');F=load('contract_tasks',HERE/'formal_tasks.py')
DIAGNOSTICS=['missing','duplicate','failed','bmc-only','stale-source','cycle','orphan']
def run(a):
    plan=json.loads((HERE/'plan.json').read_text());ids=['formal-tasks','dependencies',*DIAGNOSTICS]
    e=E.Evidence('local-compositional-formal',a,[Path(__file__),HERE/'plan.json',HERE/'dependencies.py',HERE/'formal_tasks.py',*F.SOURCES,HERE.parent/'local-formal-common/runner.py'],dict(dependencies=plan,proofs=F.PROOFS),ids)
    r=E.P.execute([a.formal_python,str(HERE/'formal_tasks.py'),'--timeout',str(a.timeout),'--out',str(e.out/'tasks')],e.out/'tasks.log',a.child_timeout,e.out)
    e.check('formal-tasks',not r['error'] and r['returncode']==0,r)
    manifest=json.loads((e.out/'tasks/manifest.json').read_text()) if (e.out/'tasks/manifest.json').exists() else {}
    summary=json.loads((e.out/'tasks/summary.json').read_text()) if (e.out/'tasks/summary.json').exists() else {}
    rows=[r for r in summary.get('results',[]) if r.get('id') in {'chain-'+v for v in F.PROOFS.values()}]
    sources=json.loads((e.out/'manifest.json').read_text())['source_sha256']|manifest.get('source_sha256',{})
    for name in ['dependencies',*DIAGNOSTICS]:
        p=copy.deepcopy(plan);rs=copy.deepcopy(rows);ss=dict(sources)
        if name=='missing' and rs:rs.pop()
        if name=='duplicate' and rs:rs.append(copy.deepcopy(rs[0]))
        if name=='failed' and rs:rs[0]['outcome']='fail'
        if name=='bmc-only' and rs:rs[0]['mode']='bmc'
        if name=='stale-source':ss[next(iter(ss))]='0'*64
        if name=='cycle':p['nodes'][0]['requires']=['integration']
        if name=='orphan':p['nodes'][-1]['requires']=['consumer']
        report=D.audit(p,rs,ss,ROOT,F.PROOFS)
        E.P.write_json(e.out/(name+'.json'),report)
        e.check(name,summary.get('success') is True and report['success'] is (name=='dependencies'),report)
    return e.finish()
def main():
    p=E.parser(__doc__,'local-compositional-formal');p.set_defaults(timeout=1800);p.add_argument('--formal-python',default=sys.executable);p.add_argument('--child-timeout',type=float,default=7200)
    a=p.parse_args();E.validate(p,a)
    if not math.isfinite(a.child_timeout) or a.child_timeout<=0:p.error('finite positive child timeout required')
    try:return run(a)
    except (OSError,ValueError,KeyError,TypeError) as exc:print('RUNNER_ERROR',exc,file=sys.stderr);return 1
if __name__=='__main__':sys.exit(main())

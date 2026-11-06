#!/usr/bin/env python3
"""Execute actual induction proofs, then reject incomplete/stale/cyclic/undischarged proof claims."""
import copy
import hashlib
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
# Each diagnostic must be rejected for its own reason, not merely rejected.
DIAGNOSTICS={'missing':'missing/duplicate','duplicate':'missing/duplicate','failed':'unproven','bmc-only':'unproven','stale-source':'stale source','cycle':'cyclic','orphan':'orphan',
             'forged-inventory':'property inventory','relabelled-diagnostic':'property inventory','wrong-parameters':'proof configuration','partial-sources':'source inventory',
             'undischarged':'undischarged','unjustified-edge':'dependency without','diverged-statement':'not one statement'}
PARAMETERS=('ROLE','MUTATION','ASSUME_HOLD','LOCK_RESET')
def with_model(record,tasks):
    """Attach what was actually compiled; a record without a compiled model cannot satisfy the audit."""
    path=tasks/record['id']/'task/model/inventory.json';record=copy.deepcopy(record)
    if path.is_file():
        model=json.loads(path.read_text());top=model['modules'][F.TOP]['parameter_default_values']
        record['compiled']=dict(parameters={k:int(top[k],2) for k in PARAMETERS},properties=D.compiled_properties(model))
    return record
def run(a):
    plan=json.loads((HERE/'plan.json').read_text());ids=['formal-tasks','dependencies',*DIAGNOSTICS]
    e=E.Evidence('local-compositional-formal',a,[Path(__file__),HERE/'plan.json',HERE/'dependencies.py',HERE/'formal_tasks.py',*F.SOURCES,HERE.parent/'local-formal-common/runner.py'],dict(dependencies=plan,proofs=F.PROOFS),ids)
    r=E.P.execute([a.formal_python,str(HERE/'formal_tasks.py'),'--timeout',str(a.timeout),'--out',str(e.out/'tasks')],e.out/'tasks.log',a.child_timeout,e.out)
    e.check('formal-tasks',not r['error'] and r['returncode']==0,r)
    manifest=json.loads((e.out/'tasks/manifest.json').read_text()) if (e.out/'tasks/manifest.json').exists() else {}
    summary=json.loads((e.out/'tasks/summary.json').read_text()) if (e.out/'tasks/summary.json').exists() else {}
    results={r.get('id'):r for r in summary.get('results',[])};cases={c['id']:c for c in F.plan(F.BOUND,0)}
    rows=[with_model(results['chain-'+v],e.out/'tasks') for v in F.PROOFS.values() if 'chain-'+v in results]
    sources=json.loads((e.out/'manifest.json').read_text())['source_sha256']|manifest.get('source_sha256',{})
    required=[str(p.relative_to(ROOT)) for p in F.SOURCES]
    for name in ['dependencies',*DIAGNOSTICS]:
        p=copy.deepcopy(plan);rs=copy.deepcopy(rows);ss=dict(sources);consumer=next((r for r in rs if r['id']=='chain-consumer-guarantee'),None)
        if name=='missing' and rs:rs.pop()
        if name=='duplicate' and rs:rs.append(copy.deepcopy(rs[0]))
        if name=='failed' and rs:rs[0]['outcome']='fail'
        if name=='bmc-only' and rs:rs[0]['mode']='bmc'
        if name=='stale-source':ss[next(iter(ss))]='0'*64
        if name=='cycle':p['nodes'][0]['requires']=['consumer']
        if name=='orphan':p['target']='connection'
        if name=='forged-inventory' and consumer:consumer['inventory']['assert']=['ap_reset']
        if name=='relabelled-diagnostic' and consumer and 'chain-overconstrained-proof' in results:
            consumer.clear();consumer.update(with_model(results['chain-overconstrained-proof'],e.out/'tasks'),id='chain-consumer-guarantee',category='normal')
        if name=='wrong-parameters' and consumer and 'compiled' in consumer:consumer['compiled']['parameters']['LOCK_RESET']=1
        if name=='partial-sources':ss={'LICENSE':hashlib.sha256((ROOT/'LICENSE').read_bytes()).hexdigest()}
        if name=='undischarged':p['contracts'].pop()
        if name=='unjustified-edge':next(n for n in p['nodes'] if n['id']=='consumer')['requires'].append('producer')
        if name=='diverged-statement' and consumer and 'compiled' in consumer:consumer['compiled']['properties']['ag_sink_hold'][1]='contract_formal.sv:1.1-1.2'
        report=D.audit(p,rs,ss,ROOT,F.PROOFS,cases,F.properties,required)
        E.P.write_json(e.out/(name+'.json'),report)
        expected=name=='dependencies' or DIAGNOSTICS[name] in ';'.join(report['errors'])
        e.check(name,summary.get('success') is True and report['success'] is (name=='dependencies') and expected,report)
    return e.finish()
def main():
    p=E.parser(__doc__,'local-compositional-formal');p.set_defaults(timeout=1800);p.add_argument('--formal-python',default=sys.executable);p.add_argument('--child-timeout',type=float,default=7200)
    a=p.parse_args();E.validate(p,a)
    if not math.isfinite(a.child_timeout) or a.child_timeout<=0:p.error('finite positive child timeout required')
    try:return run(a)
    except (OSError,ValueError,KeyError,TypeError) as exc:print('RUNNER_ERROR',exc,file=sys.stderr);return 1
if __name__=='__main__':sys.exit(main())

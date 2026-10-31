#!/usr/bin/env python3
"""Run real IRQ SVA, adapt native observations, and reject broken traceability."""
import copy
import importlib.util
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent; ROOT = HERE.parents[1]
def load(name, path):
    spec=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
E=load('plan_evidence',HERE.parent/'local-exploration-common/evidence.py')
V=load('portable_plan',ROOT/'tools/verification_plan.py')
SVA=load('plan_sva',HERE.parent/'local-sva/run.py')
PLAN=HERE/'plan.json'
DIAGNOSTICS={'missing-test':'TEST_INVENTORY','duplicate-test':'duplicate results','zero-comparisons':'ZERO_COMPARISONS',
             'checker-off':'UNMET_ITEM','missing-goal':'UNMET_ITEM','stale-plan':'STALE_PLAN',
             'stale-source':'STALE_SOURCE','wrong-configuration':'WRONG_CONFIGURATION','unmapped-requirement':'UNMAPPED_REQUIREMENT',
             'stale-artifact':'STALE_ARTIFACT','unpaired-goal':'UNMET_ITEM'}


def verify_snapshot(snapshot,root=ROOT):
    for name,digest in snapshot.items():
        if V.digest(root/name)!=digest:raise ValueError('input changed during execution: '+name)


def normalize(child, plan):
    manifest=json.loads((child/'manifest.json').read_text()); summary=json.loads((child/'summary.json').read_text())
    if (not summary.get('success') or not summary.get('complete') or
            type(summary.get('planned')) is not int or type(summary.get('results')) is not int or
            summary['planned']!=len(manifest['cases']) or summary['results']!=summary['planned']):
        raise ValueError('child did not complete its fixed plan')
    build=json.loads((child/'build.json').read_text())
    if build.get('error') or build.get('returncode')!=0 or '--assert' not in build['command']:
        raise ValueError('native assertions were not built successfully')
    expected_sources=set(plan['sources'])-{'examples/local-plan-traceability/spec.md','examples/local-plan-traceability/run.py','tools/verification_plan.py'}
    if set(manifest['source_sha256'])!=expected_sources:raise ValueError('child source inventory differs')
    for source,digest in manifest['source_sha256'].items():
        if V.digest(ROOT/source)!=digest:raise ValueError('child source changed')
    goals={g:0 for g in SVA.load_catalog(HERE.parent/'local-sva/requirements.json')[1]}; comparisons=0
    artifacts={str(child/n):V.digest(child/n) for n in ('manifest.json','summary.json','build.json','coverage.json','requirements.json')}
    for case in manifest['cases']:
        directory=child/case['id'];record=json.loads((directory/'result.json').read_text())
        for name in ('result.json','simulation.log','coverage.dat'):
            artifacts[str(directory/name)]=V.digest(directory/name)
        counts=SVA.native_counts(directory/'coverage.dat',set(goals))
        status,_=SVA.classify(case,record,(directory/'simulation.log').read_text(),counts)
        expected_status='detected' if case['expected_failure'] else 'pass'
        if (record.get('id')!=case['id'] or record.get('category')!=case['category'] or
                status!=expected_status or record['status']!=expected_status):raise ValueError('invalid child case execution')
        if case['category']!='functional':continue
        if case['mutation']!=0 or case['selftest']!=0:raise ValueError('mutations cannot supply normal evidence')
        comparisons+=case['checks']
        for goal,count in counts.items():goals[goal]+=count
    checkers={checker:min(goals[g] for g in covers) for checker,covers in SVA.ASSERTION_COVERS.items()}
    return dict(schema_version=1,plan_id=plan['id'],plan_sha256=V.digest(PLAN),
                source_sha256={p:V.digest(ROOT/p) for p in plan['sources']},artifacts=artifacts,
                adapter='IRQ SVA: successful native assert run plus paired native cover completions',
                results=[dict(id='sva-functional',configuration='irq1',status='pass',complete=True,
                              comparisons=comparisons,checkers=checkers,goals=goals)])


def run(args):
    plan=json.loads(PLAN.read_text()); ids=['irq-regression','adapter','plan']+list(DIAGNOSTICS)
    e=E.Evidence('local-plan-traceability',args,[PLAN,*[ROOT/p for p in plan['sources']]],dict(items=plan['items'],child='local-sva'),ids)
    command=[sys.executable,str(SVA.HERE/'run.py'),'--profile',args.profile,'--seed',str(args.seed),
             '--verilator',args.verilator,'--timeout',str(args.timeout),'--out',str(e.out/'irq')]
    result=E.P.execute(command,e.out/'irq.log',args.child_timeout,e.out)
    ok=not result['error'] and result['returncode']==0;e.check('irq-regression',ok,result)
    evidence=None
    try:
        if not ok:raise ValueError('IRQ regression failed')
        evidence=normalize(e.out/'irq',plan)
        verify_snapshot(json.loads((e.out/'manifest.json').read_text())['source_sha256'])
        E.P.write_json(e.out/'evidence.json',evidence)
        e.check('adapter',True,dict(comparisons=evidence['results'][0]['comparisons']))
    except (OSError,ValueError,KeyError,TypeError) as exc:e.check('adapter',False,str(exc))
    for name in ['plan',*DIAGNOSTICS]:
        if evidence is None:e.check(name,False,'no valid underlying execution');continue
        p=copy.deepcopy(plan);data=copy.deepcopy(evidence);directory=e.out/name;directory.mkdir()
        row=data['results'][0]
        if name=='missing-test':data['results']=[]
        elif name=='duplicate-test':data['results'].append(copy.deepcopy(row))
        elif name=='zero-comparisons':row['comparisons']=0
        elif name=='checker-off':row['checkers']['ap_set_wins']=0
        elif name=='missing-goal':row['goals']['cp_set_wins_done']=0
        elif name=='stale-plan':data['plan_sha256']='0'*64
        elif name=='stale-source':data['source_sha256'][plan['sources'][0]]='0'*64
        elif name=='wrong-configuration':row['configuration']='another-instance'
        elif name=='unmapped-requirement':p['requirements'].append(dict(id='NEW-REQ',source=plan['sources'][0],anchor='S01'))
        elif name=='stale-artifact':data['artifacts'][next(iter(data['artifacts']))]='0'*64
        elif name=='unpaired-goal':
            point=p['items'][0];checker=point['checkers'][0]
            extra=copy.deepcopy(row);extra['id']='unchecked-observation';extra['checkers'][checker]=0
            for goal in point['goals']:row['goals'][goal]=0
            p['tests'].append(dict(id=extra['id'],configuration=row['configuration']))
            point['tests'].append(extra['id']);data['results'].append(extra)
        E.P.write_json(directory/'plan.json',p)
        # Re-serialization intentionally gets its own reviewed plan digest.
        if name!='stale-plan':data['plan_sha256']=V.digest(directory/'plan.json')
        E.P.write_json(directory/'evidence.json',data)
        execution=E.P.execute([sys.executable,str(ROOT/'tools/verification_plan.py'),'--plan',str(directory/'plan.json'),
                              '--evidence',str(directory/'evidence.json'),'--root',str(ROOT),'--out',str(directory/'report')],
                             directory/'audit.log',args.timeout,directory)
        report=json.loads((directory/'report/report.json').read_text()) if (directory/'report/report.json').exists() else {}
        good=(not execution['error'] and execution['returncode']==(0 if name=='plan' else 1) and
              report.get('success') is (name=='plan') and
              (name=='plan' or DIAGNOSTICS[name] in ';'.join(report.get('errors',[]))))
        e.check(name,good,dict(execution=execution,report=report))
    return e.finish()


def main():
    p=E.parser(__doc__,'local-plan-traceability');p.add_argument('--verilator',default='verilator');p.add_argument('--child-timeout',type=float,default=600)
    a=p.parse_args();E.validate(p,a)
    import math
    if not math.isfinite(a.child_timeout) or a.child_timeout<=0:p.error('positive finite child timeout required')
    try:return run(a)
    except (OSError,ValueError,KeyError,TypeError) as exc:print('RUNNER_ERROR',exc,file=sys.stderr);return 1
if __name__=='__main__':sys.exit(main())

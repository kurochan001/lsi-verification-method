#!/usr/bin/env python3
"""Audit a current execution plan and chronological campaigns without hiding failures."""
import argparse
import hashlib
import html
import importlib.util
import json
import math
from pathlib import Path
import sys
from types import SimpleNamespace
import xml.etree.ElementTree as ET
ROOT=Path(__file__).resolve().parents[1]
S=importlib.util.spec_from_file_location('report_campaign',ROOT/'tools/run_regression.py');R=importlib.util.module_from_spec(S);S.loader.exec_module(R)
LIMITS={'--timeout','--simulation-timeout','--formal-timeout','--child-timeout','--build-timeout'}

def digest(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def signature(job):
    command=job.get('command')
    if not isinstance(command,list) or not command or any(not isinstance(x,str) or not x for x in command):raise ValueError('invalid job command')
    semantic=[];limits={};out=None;i=0
    while i<len(command):
        flag=command[i]
        if flag=='--out' or flag in LIMITS:
            if i+1==len(command):raise ValueError('missing command argument')
            value=command[i+1];i+=2
            if flag=='--out':
                if out is not None:raise ValueError('duplicate output argument')
                out=value
            else:
                number=float(value)
                if flag in limits or not math.isfinite(number) or number<=0:raise ValueError('invalid command limit')
                limits[flag]=number
        else:semantic.append(flag);i+=1
    if out is None or Path(out).resolve()!=Path(job['out']).resolve():raise ValueError('job output argument differs')
    return dict(example=job['example'],configuration=job['configuration'],command=semantic),limits

def jobs_index(rows):
    if not isinstance(rows,list) or not rows or any(not isinstance(r,dict) or not isinstance(r.get('id'),str) or not r['id'] for r in rows):raise ValueError('invalid job inventory')
    result={r['id']:r for r in rows}
    if len(result)!=len(rows):raise ValueError('duplicate job ID')
    return result

def sources(record,root,expected_keys=None):
    hashes=record.get('source_sha256')
    if not isinstance(hashes,dict) or not hashes or (expected_keys is not None and hashes.keys()!=expected_keys):raise ValueError('source inventory differs')
    for name,value in hashes.items():
        if digest(root/name)!=value:raise ValueError('stale source: '+name)
    return hashes

def validate_plan(plan,root):
    if not isinstance(plan,dict) or type(plan.get('schema_version')) is not int or plan['schema_version']!=1:raise ValueError('unsupported plan schema')
    options=plan['options'];args=SimpleNamespace(**options)
    args.out=Path(args.out);args.registry=Path(args.registry)
    if args.uvm_home is not None:args.uvm_home=Path(args.uvm_home)
    if plan.get('profile')!=args.profile or plan.get('suite')!=args.suite or plan.get('seed')!=args.seed:raise ValueError('plan options differ')
    registry_key=str(args.registry.relative_to(root) if args.registry.is_relative_to(root) else args.registry)
    expected={str(path.relative_to(root) if path.is_relative_to(root) else path) for path in R.plan_inputs(args,plan['jobs'],root)}
    sources(plan,root,expected)
    entries=R.load_registry(args.registry,root);generated=R.make_plan(entries,args,root)
    jobs=jobs_index(plan['jobs'])
    if plan['jobs']!=generated or ('planned' in plan and plan['planned']!=len(jobs)):raise ValueError('plan does not match current registry/options')
    for job in jobs.values():signature(job)
    return entries,jobs

def build_report(plan,campaigns,root=ROOT):
    """The last declared attempt owns each job, including failed/unstarted attempts."""
    entries,jobs=validate_plan(plan,root);history={j:[] for j in jobs};raw=[];inputs={};errors=[]
    resolved=[Path(c).resolve() for c in campaigns]
    if not resolved or len(set(resolved))!=len(resolved):raise ValueError('missing/duplicate campaign directory')
    for directory in resolved:
        manifest_path=directory/'manifest.json';manifest=json.loads(manifest_path.read_text());inputs[str(manifest_path)]=digest(manifest_path)
        attempted=jobs_index(manifest['jobs'])
        if attempted.keys()-jobs.keys():raise ValueError('campaign has jobs outside the selected plan')
        problem=None
        try:
            if manifest.get('profile')!=plan['profile']:raise ValueError('campaign profile differs')
            sources(manifest,root,plan['source_sha256'].keys())
        except (ValueError,OSError,KeyError,TypeError) as exc:problem=str(exc)
        summary_path=directory/'summary.json'
        summary=json.loads(summary_path.read_text()) if summary_path.is_file() else {}
        if summary_path.is_file():inputs[str(summary_path)]=digest(summary_path)
        rows=summary.get('results',[])
        if not isinstance(rows,list) or any(not isinstance(r,dict) or not isinstance(r.get('id'),str) for r in rows):raise ValueError('invalid campaign results')
        by_id={r['id']:r for r in rows}
        if len(rows)!=len(by_id) or by_id.keys()-attempted.keys():raise ValueError('duplicate/unplanned campaign results')
        if summary and (type(summary.get('planned')) is not int or summary['planned']!=len(attempted)):raise ValueError('campaign completion plan differs')
        if summary.get('success') is True and (summary.get('complete') is not True or len(rows)!=len(attempted) or any(r.get('success') is not True for r in rows)):raise ValueError('contradictory campaign success')
        if summary:
            junit=directory/'junit.xml';xml=ET.parse(junit).getroot();cases=list(xml.iter('testcase'));names=[c.get('name') for c in cases]
            if xml.tag!='testsuite' or len(names)!=len(set(names)) or set(names)!=set(by_id)|{'campaign-integrity'} or int(xml.get('tests','-1'))!=len(names) or list(xml.iter('error')) or list(xml.iter('skipped')):raise ValueError('campaign JUnit inventory differs')
            for case in cases:
                if case.get('name') in by_id and bool(case.find('failure') is not None)==(by_id[case.get('name')].get('success') is True):raise ValueError('campaign JUnit result contradicts summary')
            inputs[str(junit)]=digest(junit)
            integrity=summary.get('integrity_error')
            transient={'campaign incomplete','job inventory differs from plan'}
            if integrity and any(message not in transient for message in integrity.split('; ')):problem='campaign integrity failed: '+integrity
        raw.append(dict(campaign=str(directory),success=summary.get('success') is True,complete=summary.get('complete') is True,planned=len(attempted),recorded=len(rows),source_error=problem))
        for identity,job in attempted.items():
            expected,_=signature(jobs[identity]);actual,limits=signature(job);row=by_id.get(identity,{})
            record=dict(campaign=str(directory),out=job['out'],limits=limits,job_timeout=manifest.get('options',{}).get('job_timeout'),campaign_complete=summary.get('complete') is True,recorded=identity in by_id,returncode=row.get('returncode'),raw_success=row.get('success') is True,success=False,reason='not completed')
            try:
                # Outputs belong to the declared campaign, not an unrelated passing run.
                if Path(job['out']).resolve()!=directory/'runs'/identity:raise ValueError('job output outside its campaign')
                if expected!=actual:raise ValueError('job inputs/configuration differ from current plan')
                if problem:raise ValueError(problem)
                if row.get('success') is not True or type(row.get('returncode')) is not int or row['returncode']!=0:raise ValueError(row.get('message','job not completed successfully'))
                info=R.inspect_output(Path(job['out']),entries[job['example']],entries,root,plan['profile'])
                record.update(success=True,reason='current plan, completion, JUnit and sources verified',**info)
                for filename in ('manifest.json','summary.json','junit.xml','uvm-source.json','oss-source.json'):
                    for path in Path(job['out']).rglob(filename):inputs[str(path)]=digest(path)
            except (OSError,ValueError,KeyError,TypeError,ET.ParseError) as exc:record['reason']=str(exc)
            history[identity].append(record)
    results=[]
    for identity,job in jobs.items():
        attempts=history[identity];chosen=attempts[-1] if attempts else None
        results.append(dict(id=identity,example=job['example'],configuration=job['configuration'],status='pass' if chosen and chosen['success'] else 'fail',history=attempts,selected=chosen if chosen and chosen['success'] else None,reason=chosen['reason'] if chosen else 'no execution supplied'))
    # Catch edits while collecting the report; never repair old evidence in place.
    for name,value in inputs.items():
        if digest(name)!=value:errors.append('execution artifact changed while reporting: '+name)
    sources(plan,root,plan['source_sha256'].keys())
    for result in results:
        if result['selected']:
            try:R.inspect_output(Path(result['selected']['out']),entries[result['example']],entries,root,plan['profile'])
            except (OSError,ValueError,KeyError,TypeError,ET.ParseError) as exc:result.update(status='fail',selected=None,reason='final audit: '+str(exc))
    return dict(schema_version=1,success=not errors and all(r['status']=='pass' for r in results),complete=all(r['history'] and r['history'][-1]['recorded'] for r in results),planned=len(jobs),results=results,campaigns=raw,errors=errors,input_sha256=inputs,plan_source_sha256=plan['source_sha256'],
        policy='Chronological order is explicit. The last declared attempt owns the job. Failed attempts remain visible; reports never execute jobs or approve signoff.')

def write_report(out,report):
    out.mkdir(parents=True,exist_ok=False)
    (out/'summary.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    suite=ET.Element('testsuite',name='regression-report',tests=str(len(report['results'])+1),failures=str(sum(r['status']!='pass' for r in report['results'])+int(bool(report['errors']))),errors='0')
    gate=ET.SubElement(suite,'testcase',name='report-integrity')
    if report['errors']:ET.SubElement(gate,'failure',message='; '.join(report['errors']))
    for row in report['results']:
        case=ET.SubElement(suite,'testcase',name=row['id'])
        if row['status']!='pass':ET.SubElement(case,'failure',message=row['reason'])
    ET.indent(suite);ET.ElementTree(suite).write(out/'junit.xml',encoding='utf-8',xml_declaration=True)
    h=html.escape;body=[]
    for row in report['results']:
        attempts=''.join('<li>'+h(a['campaign'])+': '+('PASS' if a['success'] else 'FAIL')+' — '+h(a['reason'])+'</li>' for a in row['history'])
        body.append('<tr><td>'+h(row['id'])+'</td><td>'+h(row['status'])+'</td><td><ol>'+attempts+'</ol></td><td>'+h(row['reason'])+'</td></tr>')
    page='<!doctype html><html lang="ja"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>リグレッション照合結果</title><style>body{font:16px system-ui;margin:2rem;line-height:1.6;color:#17212b}table{border-collapse:collapse;width:100%}td,th{border:1px solid #bcc8d2;padding:.6rem;text-align:left;vertical-align:top;overflow-wrap:anywhere}ol{margin:0;padding-left:1.4rem}h1{font-size:1.5rem}.scroll{overflow:auto}</style><h1>リグレッション照合結果：'+('PASS' if report['success'] else 'FAIL')+'</h1><p>入力で指定した順に履歴を評価し、各ジョブの最後の試行を判定します。初回の失敗は保持します。人のサインオフ承認は含みません。</p><div class="scroll"><table><thead><tr><th>ジョブ</th><th>採用判定</th><th>全試行（古い順）</th><th>理由</th></tr></thead><tbody>'+''.join(body)+'</tbody></table></div></html>'
    (out/'report.html').write_text(page)

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--plan',type=Path,required=True);p.add_argument('--campaign',type=Path,action='append',required=True);p.add_argument('--out',type=Path,required=True)
    a=p.parse_args()
    if a.out.exists():p.error('output exists; choose a new --out')
    runtime={str(path):digest(path) for path in (Path(__file__),Path(R.__file__),ROOT/'examples/local-irq-cdc/run.py')}
    before=None
    try:
        before=digest(a.plan)
        report=build_report(json.loads(a.plan.read_text()),a.campaign)
        if digest(a.plan)!=before:report['errors'].append('plan changed while reporting');report['success']=False
    except (OSError,ValueError,KeyError,TypeError,AttributeError,ET.ParseError) as exc:report=dict(success=False,complete=False,planned=0,results=[],campaigns=[],errors=[str(exc)],input_sha256={})
    for name,value in runtime.items():
        if digest(name)!=value:report['errors'].append('report implementation changed during execution');report['success']=False
    write_report(a.out,report)
    hashes=dict(runtime)
    if before is not None:hashes[str(a.plan.resolve())]=before
    hashes.update(report['input_sha256'])
    hashes.update({str(ROOT/name):value for name,value in report.get('plan_source_sha256',{}).items()})
    (a.out/'manifest.json').write_text(json.dumps(dict(source_sha256=hashes,policy=report.get('policy'),plan_sha256=before),indent=2)+'\n')
    print('Regression report:','PASS' if report['success'] else 'FAIL');return 0 if report['success'] else 1
if __name__=='__main__':sys.exit(main())

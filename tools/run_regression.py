#!/usr/bin/env python3
"""Run the repository's registered example matrices with explicit tool preflight."""
import argparse
import concurrent.futures
from datetime import datetime, timezone
import hashlib
import importlib.util
import itertools
import json
import math
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
import xml.etree.ElementTree as ET

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('campaign_process',ROOT/'examples/local-irq-cdc/run.py')
P=importlib.util.module_from_spec(spec);spec.loader.exec_module(P)
REDUCTION_GATES={'learning','selection','comparison'}|{f'{kind}/normal' for kind in ('full','coverage_only','guarded')}|{f'{kind}/mutation{i}' for kind in ('full','coverage_only','guarded') for i in range(1,5)}


def load_registry(path,root=ROOT):
    data=json.loads(path.read_text());entries=data.get('examples')
    if type(data.get('schema_version')) is not int or data['schema_version']!=1 or not isinstance(entries,list) or not entries:raise ValueError('invalid registry')
    result={}
    for entry in entries:
        if not isinstance(entry,dict):raise ValueError('invalid registry entry')
        name=entry.get('id')
        if not isinstance(name,str) or not re.fullmatch(r'local-[a-z0-9-]+',name) or name in result:raise ValueError('invalid/duplicate example id')
        script=(root/entry['script']).resolve()
        if not script.is_relative_to(root.resolve()) or not script.is_file():raise ValueError('missing/outside-root script: '+name)
        if entry.get('kind') not in ('simulation','formal','sta','aggregate'):raise ValueError('unknown kind: '+name)
        if not isinstance(entry.get('tools'),list) or not isinstance(entry.get('options'),list):raise ValueError('missing capabilities: '+name)
        matrix=entry.get('matrix',{})
        if not isinstance(matrix,dict) or any(not re.fullmatch(r'[a-z][a-z0-9-]*',k) or not isinstance(v,list) or not v or
                any(type(x) not in (int,str) or not re.fullmatch(r'[A-Za-z0-9_-]+',str(x)) for x in v) or len(v)!=len(set(map(str,v))) for k,v in matrix.items()):raise ValueError('invalid matrix: '+name)
        result[name]=entry
    actual={str(p.relative_to(root)) for p in (root/'examples').glob('*/run.py')}
    registered={e['script'] for e in entries if e['script'].endswith('/run.py')}
    if actual!=registered:raise ValueError('unregistered or stale run.py entries: '+str(sorted(actual^registered)))
    def visit(name,trail):
        if name in trail:raise ValueError('aggregate cycle: '+name)
        for child in result[name].get('children',{}):
            if child not in result:raise ValueError('unknown child: '+child)
            visit(child,trail|{name})
    for name in result:visit(name,set())
    return result


def descendants(name,entries):
    found=set()
    for child in entries[name].get('children',{}):found.add(child);found.update(descendants(child,entries))
    return found


def make_plan(entries,args,root=ROOT):
    selected=set(args.example or entries)
    if selected-entries.keys():raise ValueError('unknown examples: '+','.join(sorted(selected-entries.keys())))
    if args.suite=='formal':selected={n for n in selected if entries[n]['kind']=='formal'}
    elif args.suite=='simulation':selected={n for n in selected if entries[n]['kind'] in ('simulation','sta')}
    # Aggregates only run in the all suite. A child already owned by a selected
    # parent is executed once through that parent, with its own evidence retained.
    owned=set().union(*(descendants(n,entries) for n in selected)) if selected else set()
    selected-=owned
    if not selected:raise ValueError('empty execution plan')
    jobs=[]
    for name in sorted(selected,key=lambda n:(entries[n]['kind']!='aggregate',n)):
        e=entries[name];matrix=e.get('matrix',{})
        for values in itertools.product(*matrix.values()):
            configuration=dict(zip(matrix,values));identity=name+''.join('-'+k+str(v) for k,v in configuration.items())
            target=args.out.resolve()/'runs'/identity
            interpreter=args.formal_python if e['kind']=='formal' or name=='local-system-regression' else args.python
            if name=='local-register-spec':interpreter=args.rdl_python
            command=[interpreter,str(root/e['script']),'--out',str(target)]
            if e.get('profile'):command+=['--profile',args.profile,'--seed',str(args.seed)]
            for key,value in configuration.items():command+=['--'+key,str(value)]
            bindings={'uvm-home':args.uvm_home,'python':args.python,'formal-python':args.formal_python,
                      'rdl-python':args.rdl_python,'cocotb-python':args.cocotb_python}
            if name=='local-system-regression':bindings['python']=args.formal_python
            if name=='local-cocotb':bindings['python']=args.cocotb_python
            for key,value in bindings.items():
                if key in e['options'] and value is not None:command+=['--'+key,str(value)]
            for key,value in [('formal-timeout',args.formal_timeout),('child-timeout',args.child_timeout),('build-timeout',args.build_timeout)]:
                if key in e['options'] and value is not None:command+=['--'+key,str(value)]
            if args.formal_timeout is not None and e['kind']=='formal':command+=['--timeout',str(args.formal_timeout)]
            if args.command_timeout is not None and e['kind']=='simulation' and 'timeout' in e['options']:command+=['--timeout',str(args.command_timeout)]
            if args.command_timeout is not None and 'simulation-timeout' in e['options']:command+=['--simulation-timeout',str(args.command_timeout)]
            jobs.append(dict(id=identity,example=name,configuration=configuration,command=command,out=str(target)))
    return jobs


def plan_document(args,jobs):
    """Use the same reproducible input snapshot for --list and actual execution."""
    return dict(schema_version=1,profile=args.profile,suite=args.suite,seed=args.seed,jobs=jobs,
        options={k:([str(p) for p in v] if k=='tool_bin' else str(v) if isinstance(v,Path) else v) for k,v in vars(args).items()},
        source_sha256={str(p.relative_to(ROOT) if p.is_relative_to(ROOT) else p):hashlib.sha256(p.read_bytes()).hexdigest()
                       for p in [Path(__file__),args.registry,ROOT/'examples/local-irq-cdc/run.py']})


def environment(args):
    env=dict(os.environ);bins=[str(p.resolve()) for p in args.tool_bin]
    bins += [str(Path(p).absolute().parent) for p in (args.formal_python,args.python,args.rdl_python,args.cocotb_python)]
    env['PATH']=os.pathsep.join(dict.fromkeys(bins+[env.get('PATH','')]))
    env['COCOTB_PYTHON']=args.cocotb_python
    return env


def preflight(jobs,entries,args,env):
    required=set();packages={};errors=[];tools={}
    closure=set().union(*({j['example']}|descendants(j['example'],entries) for j in jobs))
    for name in closure:
        entry=entries[name];required.update(entry['tools'])
        for interpreter,modules in entry.get('packages',{}).items():packages.setdefault(interpreter,set()).update(modules)
        if 'uvm-home' in entry['options'] and (args.uvm_home is None or not (args.uvm_home/'src/uvm_pkg.sv').is_file()):errors.append('UVM library required: '+name)
    for command in sorted(required):
        resolved=shutil.which(command,path=env['PATH']);tools[command]=resolved
        if not resolved:errors.append('missing executable: '+command)
    for binding,modules in packages.items():
        interpreter=getattr(args,binding.replace('-','_'));code='import importlib; '+ '; '.join('importlib.import_module('+repr(m)+')' for m in sorted(modules))
        try:
            probe=subprocess.run([interpreter,'-c',code],capture_output=True,text=True,env=env,timeout=30)
            if probe.returncode:errors.append(binding+' missing/unusable packages: '+','.join(sorted(modules))+'\n'+probe.stderr[-1000:])
        except (OSError,subprocess.TimeoutExpired) as exc:errors.append(binding+': '+str(exc))
    return dict(success=not errors,errors=errors,tools=tools,packages={k:sorted(v) for k,v in packages.items()},examples=sorted(closure))


def validate_summary(data,kind='planned'):
    if not isinstance(data,dict) or data.get('success') is not True or data.get('complete') is False:raise ValueError('unsuccessful/incomplete summary')
    if kind=='reduction':
        rows=data.get('gates')
        if not isinstance(rows,dict) or rows.keys()!=REDUCTION_GATES or any(r.get('status')!='pass' for r in rows.values()):raise ValueError('reduction gates incomplete')
        return set(rows)
    rows=data.get('results');planned=data.get('planned')
    if kind!='bus-validation' and (type(planned) is not int or planned<1):raise ValueError('missing/empty plan')
    if type(rows) is int:
        if rows!=planned or data.get('complete') is not True:raise ValueError('completion count differs')
        return set()
    if not isinstance(rows,list) or not rows or (kind!='bus-validation' and len(rows)!=planned):raise ValueError('result plan differs')
    ids=[]
    for row in rows:
        if not isinstance(row,dict) or not isinstance(row.get('id'),str) or not row['id'].strip():raise ValueError('invalid result id')
        states=[row[k] for k in ('status','outcome') if k in row]
        if not states or any(state not in ('pass','detected') for state in states) or row.get('success') is False or row.get('complete') is False:raise ValueError('failed/incomplete child result')
        ids.append(row['id'])
    if len(ids)!=len(set(ids)):raise ValueError('duplicate result id')
    return set(ids)


def inspect_output(directory,entry,entries,root=ROOT,profile=None):
    manifest=json.loads((directory/'manifest.json').read_text())
    if not isinstance(manifest.get('source_sha256'),dict) or not manifest['source_sha256']:raise ValueError('missing root source manifest')
    if profile is not None and entry.get('profile') and manifest.get('profile')!=profile:raise ValueError('execution profile differs from plan')
    data=json.loads((directory/'summary.json').read_text());ids=validate_summary(data,entry.get('summary','planned'))
    # Count-only summaries cannot identify a missing/replaced JUnit case. Use
    # the frozen manifest, and also prevent list summaries shrinking check_ids.
    if type(data.get('results')) is int or 'check_ids' in manifest:
        planned=manifest.get('cases') if type(data.get('results')) is int else manifest['check_ids']
        if not isinstance(planned,list) or not planned:raise ValueError('missing manifest check plan')
        expected=[row.get('id') if isinstance(row,dict) else row for row in planned]
        if any(not isinstance(name,str) or not name.strip() for name in expected) or len(set(expected))!=len(expected):raise ValueError('invalid/duplicate manifest check id')
        if len(expected)!=data['planned'] or (ids and ids!=set(expected)):raise ValueError('summary differs from manifest check plan')
        ids=set(expected)
    xml=ET.parse(directory/'junit.xml').getroot();cases=list(xml.iter('testcase'))
    keys=[(c.get('classname',''),c.get('name')) for c in cases]
    if (not cases or len(keys)!=len(set(keys)) or any(not name for _,name in keys) or
            list(xml.iter('error')) or list(xml.iter('failure')) or list(xml.iter('skipped'))):raise ValueError('JUnit incomplete, duplicate, skipped or failed')
    for suite in xml.iter('testsuite'):
        if int(suite.get('tests','-1'))!=len(suite.findall('testcase')):raise ValueError('JUnit test count differs')
    for node in (n for n in xml.iter() if n.tag in ('testsuite','testsuites')):
        if any(int(node.get(key,'0'))!=0 for key in ('failures','errors','skipped')):raise ValueError('JUnit reports failed/skipped tests')
        if node.tag=='testsuites' and 'tests' in node.attrib and int(node.get('tests'))!=len(list(node.iter('testcase'))):raise ValueError('JUnit total test count differs')
    if ids-{c.get('name') for c in cases}:raise ValueError('summary case missing from JUnit')
    for child,relative in entry.get('children',{}).items():inspect_output(directory/relative,entries[child],entries,root,profile)
    count=0
    for manifest in directory.rglob('manifest.json'):
        for name,expected in json.loads(manifest.read_text()).get('source_sha256',{}).items():
            path=root/name
            if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest()!=expected:raise ValueError('stale source: '+name)
            count+=1
    snapshots=list(directory.rglob('uvm-source.json'))
    if 'uvm-home' in entry.get('options',[]) and not snapshots:raise ValueError('missing UVM source snapshot')
    for snapshot in snapshots:
        record=json.loads(snapshot.read_text())
        hashes=record.get('source_sha256',record.get('sha256',{}))
        if not isinstance(hashes,dict) or not hashes:raise ValueError('empty/invalid UVM source snapshot')
        for name,expected in hashes.items():
            path=Path(record['root'])/name
            if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest()!=expected:raise ValueError('stale UVM source: '+str(path))
    if count==0:raise ValueError('missing source manifest')
    return dict(junit=len(cases),source_hashes=count)


def stop_tree(process):
    """Include detached child sessions created by the example runners."""
    rows=subprocess.check_output(['ps','-axo','pid,ppid,pgid'],text=True).splitlines()[1:]
    table=[tuple(map(int,row.split())) for row in rows]
    owned={process.pid}
    while True:
        expanded=owned|{pid for pid,parent,_ in table if parent in owned}
        if expanded==owned:break
        owned=expanded
    groups={group for pid,_,group in table if pid in owned}-{os.getpgrp()}
    # Stop the root first, before it can launch another child.
    for group in [process.pid,*sorted(groups-{process.pid})]:
        try:os.killpg(group,signal.SIGTERM)
        except ProcessLookupError:pass
    time.sleep(.2)
    process.poll()
    rows=subprocess.check_output(['ps','-axo','pid,pgid,stat'],text=True).splitlines()[1:]
    live_groups={int(row.split()[1]) for row in rows if int(row.split()[0]) in owned and not row.split()[2].startswith('Z')}
    for group in groups & live_groups:
        try:os.killpg(group,signal.SIGKILL)
        except ProcessLookupError:pass
    process.wait(timeout=5)


def save(out,jobs,results,complete,preflight_ok,integrity_error=None):
    errors=[integrity_error] if integrity_error else []
    if not complete:errors.append('campaign incomplete')
    if not preflight_ok:errors.append('preflight failed')
    planned=[j['id'] for j in jobs];actual=[r['id'] for r in results]
    if len(set(planned))!=len(planned) or len(set(actual))!=len(actual) or set(actual)!=set(planned):errors.append('job inventory differs from plan')
    integrity_error='; '.join(errors) or None
    success=not integrity_error and all(r['success'] for r in results)
    P.write_json(out/'summary.json',dict(success=success,complete=complete,planned=len(jobs),results=sorted(results,key=lambda r:r['id']),
        integrity_error=integrity_error,
        counting='Parent JUnit contains job gates plus campaign integrity; individual checks remain in runs/. Do not sum both as requirements.'))
    suite=ET.Element('testsuite',name='repository-regression',tests=str(len(results)+1),failures=str(sum(not r['success'] for r in results)+int(bool(integrity_error))),errors='0')
    gate=ET.SubElement(suite,'testcase',name='campaign-integrity')
    if integrity_error:ET.SubElement(gate,'failure',message=integrity_error)
    for result in sorted(results,key=lambda r:r['id']):
        case=ET.SubElement(suite,'testcase',name=result['id'],time=str(result.get('seconds',0)))
        if not result['success']:ET.SubElement(case,'failure',message=result['message'])
    ET.indent(suite);ET.ElementTree(suite).write(out/'junit.xml',encoding='utf-8',xml_declaration=True)
    return success


def run(args,entries,jobs):
    out=args.out.resolve();out.mkdir(parents=True,exist_ok=False);(out/'runs').mkdir()
    env=environment(args)
    P.write_json(out/'manifest.json',plan_document(args,jobs))
    check=preflight(jobs,entries,args,env);P.write_json(out/'preflight.json',check)
    if not check['success']:
        results=[dict(id=j['id'],success=False,message='preflight failed; job not started') for j in jobs]
        save(out,jobs,results,False,False)
        for error in check['errors']:print(error,file=sys.stderr)
        return 1
    if args.check_tools:
        P.write_json(out/'preflight-only.json',dict(success=True,executed_jobs=0,planned_jobs=len(jobs)))
        print('Tool preflight: PASS; no example was executed');return 0
    results=[];active=set();lock=threading.Lock();cancel=threading.Event()
    def execute(job):
        started=time.monotonic();process=None;message='';ok=False;details={};code=None
        with lock:active.add(job['id'])
        try:
            with (out/(job['id']+'.log')).open('w') as log:
                if cancel.is_set():raise ValueError('cancelled before execution')
                process=subprocess.Popen(job['command'],cwd=ROOT,env=env,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
                while process.poll() is None:
                    if cancel.is_set() or time.monotonic()-started>args.job_timeout:
                        stop_tree(process);raise ValueError('cancelled' if cancel.is_set() else 'job timeout')
                    try:process.wait(timeout=.5)
                    except subprocess.TimeoutExpired:pass
                code=process.returncode
            if code!=0:raise ValueError('runner exit '+str(code))
            details=inspect_output(Path(job['out']),entries[job['example']],entries,profile=args.profile);ok=True;message='planned execution, JUnit and source hashes valid'
        except (OSError,ValueError,KeyError,TypeError,ET.ParseError) as exc:message=str(exc)
        finally:
            with lock:active.discard(job['id'])
        return dict(id=job['id'],example=job['example'],success=ok,message=message,returncode=code,seconds=round(time.monotonic()-started,3),**details)
    def interrupted(signum,_frame):
        if not cancel.is_set():cancel.set();raise P.RunInterrupted(signum)
    previous={sig:signal.signal(sig,interrupted) for sig in (signal.SIGTERM,signal.SIGINT)}
    pool=concurrent.futures.ThreadPoolExecutor(max_workers=args.jobs);futures={pool.submit(execute,j) for j in jobs};exit_code=None
    try:
        while futures:
            done,futures=concurrent.futures.wait(futures,timeout=10,return_when=concurrent.futures.FIRST_COMPLETED)
            for future in done:
                result=future.result();results.append(result);print('PASS' if result['success'] else 'FAIL',result['id'],result['message'],flush=True)
            with lock:running=sorted(active)
            P.write_json(out/'progress.json',dict(completed=len(results),planned=len(jobs),active=running))
            save(out,jobs,results,False,True)
            if not done:print('Progress:',len(results),'/',len(jobs),'active:',','.join(running),flush=True)
    except P.RunInterrupted as exc:exit_code=128+exc.signum;cancel.set()
    finally:
        pool.shutdown(wait=True,cancel_futures=True)
        for sig,handler in previous.items():signal.signal(sig,handler)
    if exit_code is not None:
        completed={r['id'] for r in results}
        results += [dict(id=j['id'],success=False,message='interrupted; no completed evidence') for j in jobs if j['id'] not in completed]
        P.write_json(out/'progress.json',dict(completed=len(completed),planned=len(jobs),active=[],interrupted=True))
        save(out,jobs,results,False,True);return exit_code
    integrity_error=None
    try:
        load_registry(args.registry)
        for name,expected in json.loads((out/'manifest.json').read_text())['source_sha256'].items():
            if hashlib.sha256((ROOT/name).read_bytes()).hexdigest()!=expected:raise ValueError('campaign source changed: '+name)
        by_id={j['id']:j for j in jobs}
        for result in results:
            if not result['success']:continue
            job=by_id[result['id']]
            try:inspect_output(Path(job['out']),entries[job['example']],entries,profile=args.profile)
            except (OSError,ValueError,KeyError,TypeError,ET.ParseError) as exc:result.update(success=False,message='final audit: '+str(exc))
    except (OSError,ValueError,KeyError,TypeError) as exc:integrity_error=str(exc)
    ok=save(out,jobs,results,True,True,integrity_error);print('Artifacts:',out,'\nRepository regression:','PASS' if ok else 'FAIL');return 0 if ok else 1


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--profile',choices=('smoke','nightly'),default='smoke');p.add_argument('--suite',choices=('all','simulation','formal'),default='all')
    p.add_argument('--example',action='append');p.add_argument('--list',action='store_true');p.add_argument('--check-tools',action='store_true')
    p.add_argument('--registry',type=Path,default=ROOT/'tools/regressions.json');p.add_argument('--seed',type=int,default=17)
    p.add_argument('--jobs',type=int,default=1);p.add_argument('--job-timeout',type=float,default=10800)
    for name in ('command-timeout','formal-timeout','child-timeout','build-timeout'):p.add_argument('--'+name,type=float)
    for name in ('python','formal-python','rdl-python','cocotb-python'):p.add_argument('--'+name,default=sys.executable)
    p.add_argument('--tool-bin',type=Path,action='append',default=[]);p.add_argument('--uvm-home',type=Path)
    p.add_argument('--out',type=Path,default=ROOT/'artifacts'/datetime.now(timezone.utc).strftime('regression-%Y%m%dT%H%M%S%fZ'))
    args=p.parse_args()
    args.registry=args.registry.resolve()
    if os.name!='posix' or args.seed<0 or args.seed>2**31-4 or args.jobs<1:p.error('requires POSIX, 1+ jobs and seed 0..2^31-4')
    if any(value is not None and (not math.isfinite(value) or value<=0) for value in [args.job_timeout,args.command_timeout,args.formal_timeout,args.child_timeout,args.build_timeout]):p.error('finite positive timeouts required')
    for name in ('python','formal_python','rdl_python','cocotb_python'):
        found=shutil.which(getattr(args,name))
        if found is None:p.error('Python executable missing: '+getattr(args,name))
        setattr(args,name,os.path.abspath(found))
    if args.uvm_home is not None:args.uvm_home=args.uvm_home.resolve()
    try:
        entries=load_registry(args.registry);jobs=make_plan(entries,args)
        if args.list:
            print(json.dumps(dict(plan_document(args,jobs),planned=len(jobs)),indent=2));return 0
        if args.out.exists():p.error('output exists; choose a new --out')
        return run(args,entries,jobs)
    except (OSError,ValueError,KeyError,TypeError) as exc:print('RUNNER_ERROR',exc,file=sys.stderr);return 1
if __name__=='__main__':sys.exit(main())

"""Strict local SBY evidence runner shared by system-level teaching examples."""
import argparse
from collections import Counter
from datetime import datetime,timezone
import hashlib
import importlib.metadata
import importlib.util
import json
import math
import os
from pathlib import Path
import re
import shutil
import signal
import sys
import xml.etree.ElementTree as ET
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1]
PROCESS_PATH=HERE.parent/'local-irq-cdc/run.py'
spec=importlib.util.spec_from_file_location('system_formal_process',PROCESS_PATH)
P=importlib.util.module_from_spec(spec);spec.loader.exec_module(P)

def inventory(path,plugin,parameters,case):
    data=json.loads(path.read_text());top=data['modules'][getattr(plugin,'PARAMETER_MODULE',plugin.TOP)]
    expected={**parameters,**case['parameters']}
    if any(int(top['parameter_default_values'][k],2)!=v for k,v in expected.items()):raise ValueError('compiled parameters differ')
    found={k:Counter() for k in ('assert','assume','cover')}
    for module in data['modules'].values():
        for name,cell in module.get('cells',{}).items():
            if cell['type']=='$check' and cell['parameters']['FLAVOR'] in found:
                found[cell['parameters']['FLAVOR']][name.rsplit('.',1)[-1]]+=1
    required=plugin.properties(parameters,case)
    if any(found[k]!=Counter(required[k]) for k in found):raise ValueError(f'compiled property inventory differs: {found}')
    return {k:sorted(v.elements()) for k,v in found.items()}

def observed(log):
    def names(pattern):return {s.rsplit('.',1)[-1] for s in re.findall(pattern,log)}
    return (names(r'Reached cover statement in step \d+ at [\w.]+: ([\w.]+)'),
            names(r'Unreached cover statement at [\w.]+: ([\w.]+)'),
            names(r'Assert failed in [\w.]+: ([\w.]+)'))

def witnessed_traces(engine,out):
    """Counterexample and cover traces, each with its witness. An induction-step trace starts
    from an arbitrary state, so it is kept on disk but is neither required nor counted."""
    traces=[]
    for trace in sorted(engine.glob('*.vcd')):
        if trace.name.startswith('trace_induct'):continue
        if '$enddefinitions' not in trace.read_text(errors='replace') or not trace.with_suffix('.yw').exists() or not trace.with_suffix('.yw').stat().st_size:raise ValueError('incomplete counterexample/witness')
        traces.append(str(trace.relative_to(out)))
    return traces

def judge(case,execution,status,log,traces,properties):
    if execution['error']:return 'error',execution['error']
    if status not in ('PASS','FAIL') or execution['returncode']!=(0 if status=='PASS' else 2):return 'error','incomplete task or inconsistent status/exit'
    if status!=case['expect']:return 'fail',f"expected {case['expect']}, got {status}"
    reached,unreached,failed=observed(log)
    if status=='PASS':
        if failed:return 'error','PASS includes assertion violation'
        if case['mode']=='prove' and 'successful proof by k-induction' not in log:return 'error','induction not completed'
        if case['mode']=='bmc' and 'Status: passed' not in log:return 'error','bounded engine not completed'
        if case['mode']=='cover' and (reached!=set(properties['cover']) or unreached or not traces):return 'error','incomplete covers or witnesses'
        return 'pass','induction proof completed' if case['mode']=='prove' else 'all covers reached' if case['mode']=='cover' else f"checked through configured depth {case['depth']}"
    if case['category'] in ('mutation','counterexample') and case['failure'] in failed and failed<=set(properties['assert']) and traces:
        return 'detected','counterexample confirms '+case['failure']
    if case['category']=='diagnostic' and case['mode']=='cover' and unreached==set(properties['cover']) and not reached and not failed and not traces:
        return 'detected','permanent reset blocks all normal goals within bound'
    return 'error','FAIL lacks intended property and trace evidence'

def run(plugin,args):
    out=args.out.resolve();out.mkdir(parents=True,exist_ok=False)
    configs=plugin.CONFIGS if args.configuration=='all' else {args.configuration:plugin.CONFIGS[args.configuration]}
    cases=[c for c in plugin.plan(args.bound,args.demo_bug) if args.task=='all' or c['id']==args.task];inputs=[Path(__file__),Path(plugin.__file__),PROCESS_PATH,*plugin.SOURCES,
        HERE.parent/'local-bus-formal/tools-requirements.txt',HERE.parent/'local-fifo-formal/tools-requirements.txt']
    versions={}
    for name in ('yowasp-yosys','z3-solver','yowasp-runtime','wasmtime'):
        try:versions[name]=importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:versions[name]='not installed in runner environment'
    P.write_json(out/'manifest.json',dict(schema_version=1,created_at=datetime.now(timezone.utc).isoformat(),python=sys.version,
        configurations=configs,cases=cases,scope=plugin.SCOPE,packages=versions,timeout=args.timeout,
        source_sha256={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs}))
    tools={}
    for name,command in [('yosys',[args.yosys,'-V']),('sby',[args.sby,'--version']),('z3',['z3','--version'])]:tools[name]=P.execute(command,out/(name+'-version.log'),args.timeout,out)
    P.write_json(out/'tools.json',tools)
    results=[];coverage={}
    for config,parameters in configs.items():
        for case in cases:
            directory=out/(config+'-'+case['id']);directory.mkdir()
            for source in plugin.SOURCES:shutil.copy2(source,directory/source.name)
            properties=plugin.properties(parameters,case)
            commands=''.join(f'chparam -set {k} {v} {plugin.TOP}\n' for k,v in {**parameters,**case['parameters']}.items())
            reading=plugin.prepare(parameters,case) if hasattr(plugin,'prepare') else 'read -formal -sv '+' '.join(p.name for p in plugin.SOURCES)+'\n'+commands
            text=(f"[options]\nmode {case['mode']}\ndepth {case['depth']}\ntimeout {max(1,int(args.timeout)-5)}\n"+
                ('cover_assert on\n' if case['mode']=='cover' else '')+
                '\n[engines]\nsmtbmc z3\n\n[script]\n'+reading+
                f'prep -top {plugin.TOP}\nopt_clean\nopt_expr\nwrite_json ../model/inventory.json\nasync2sync\nmemory_map\nopt -full\n\n[files]\n'+'\n'.join(p.name for p in plugin.SOURCES)+'\n')
            (directory/'task.sby').write_text(text)
            execution=P.execute([args.sby,'--yosys',args.yosys,'--smtbmc',args.smtbmc,'--witness',args.witness,'task.sby'],directory/'console.log',args.timeout,directory)
            work=directory/'task';status_file=work/'status';status=status_file.read_text().split()[0] if status_file.exists() and status_file.read_text().strip() else 'MISSING'
            log=(work/'logfile.txt').read_text(errors='replace') if (work/'logfile.txt').exists() else ''
            traces=[];inv=None
            try:
                traces=witnessed_traces(work/'engine_0',out)
                if status in ('PASS','FAIL') and not execution['error']:inv=inventory(work/'model/inventory.json',plugin,parameters,case)
                outcome,message=judge(case,execution,status,log,traces,properties)
            except (OSError,ValueError,KeyError,TypeError) as exc:outcome,message='error','invalid evidence: '+str(exc)
            record=dict(id=directory.name,configuration=config,category=case['category'],mode=case['mode'],outcome=outcome,
                message=message,formal_status=status,inventory=inv,traces=traces,**execution)
            P.write_json(directory/'result.json',record);results.append(record)
            if case['id']=='scenario-cover':
                reached,_,_=observed(log);credited=reached if outcome=='pass' else set()
                coverage[config]=dict(success=credited==set(properties['cover']),hit=sorted(credited),missing=sorted(set(properties['cover'])-credited))
            print(outcome.upper(),record['id'],message,flush=True)
    success=len(results)==len(configs)*len(cases) and all(r['outcome'] in ('pass','detected') for r in results) and all(c['success'] for c in coverage.values())
    P.write_json(out/'coverage.json',coverage);P.write_json(out/'summary.json',dict(success=success,planned=len(configs)*len(cases),results=results))
    suite=ET.Element('testsuite',name=plugin.TOP,tests=str(len(results)),failures=str(sum(r['outcome']=='fail' for r in results)),errors=str(sum(r['outcome']=='error' for r in results)))
    for r in results:
        node=ET.SubElement(suite,'testcase',name=r['id'],classname=plugin.TOP+'.'+r['configuration'],time=f"{r['seconds']:.6f}")
        if r['outcome'] in ('error','fail'):ET.SubElement(node,'error' if r['outcome']=='error' else 'failure',message=r['message'])
    ET.indent(suite);ET.ElementTree(suite).write(out/'junit.xml',encoding='utf-8',xml_declaration=True)
    print('Artifacts:',out,'\nFormal:', 'PASS' if success else 'FAIL');return 0 if success else 1

def main(plugin):
    p=argparse.ArgumentParser(description=plugin.__doc__);p.add_argument('--configuration',choices=('all',*plugin.CONFIGS),default='all')
    p.add_argument('--task',choices=('all',*[c['id'] for c in plugin.plan(plugin.BOUND,0)]),default='all')
    p.add_argument('--bound',type=int,default=plugin.BOUND);p.add_argument('--timeout',type=float,default=getattr(plugin,'TIMEOUT',120))
    p.add_argument('--demo-bug',type=int,choices=range(5),default=0)
    for name,default in [('sby','yowasp-sby'),('yosys','yowasp-yosys'),('smtbmc','yowasp-yosys-smtbmc'),('witness','yowasp-yosys-witness')]:p.add_argument('--'+name,default=default)
    p.add_argument('--out',type=Path,default=Path('artifacts')/datetime.now(timezone.utc).strftime(plugin.TOP+'-%Y%m%dT%H%M%S%fZ'))
    args=p.parse_args()
    P.resolve_tools(args)
    if os.name!='posix' or not 8<=args.bound<=64 or not math.isfinite(args.timeout) or args.timeout<=0:p.error('requires POSIX, bound 8..64 and finite positive timeout')
    if args.out.exists():p.error('output exists; choose a new directory')
    previous=signal.signal(signal.SIGTERM,P.interrupted)
    try:return run(plugin,args)
    except P.RunInterrupted as exc:return 128+exc.signum
    except KeyboardInterrupt:return 130
    except (OSError,ValueError,KeyError,TypeError) as exc:print('RUNNER_ERROR',exc,file=sys.stderr);return 1
    finally:signal.signal(signal.SIGTERM,previous)

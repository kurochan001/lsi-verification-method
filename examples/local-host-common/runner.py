"""Strict evidence for locally compiled software/co-simulation/differential examples."""
import argparse
from datetime import datetime,timezone
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import re
import signal
import sys
import xml.etree.ElementTree as ET
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1]
def module(name,path):
    spec=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
COMMON=module('host_catalog',HERE.parent/'local-common/runner.py');P=COMMON.PROCESS

def evaluate(case,execution,log):
    status,message=P.classify(case,execution,log)
    counts={}
    if status=='pass':
        pairs=re.findall(r'^COUNT ([a-z_]+)=(\d+)$',log,re.M);counts={k:int(v) for k,v in pairs}
        if len(pairs)!=len(counts) or counts!=case['counts']:return 'error','missing/duplicate/incorrect counts',counts
        message=f"completed planned checks: {case['checks']}"
    return status,message,counts

def run(plugin,args):
    requirements,goals=COMMON.catalog(Path(plugin.__file__).parent/'requirements.json')
    cases=plugin.cases(args);out=args.out.resolve();out.mkdir(parents=True,exist_ok=False)
    if not cases or len({c['id'] for c in cases})!=len(cases):raise ValueError('empty/duplicate case plan')
    inputs=[Path(__file__),Path(plugin.__file__),Path(COMMON.__file__),COMMON.PROCESS_PATH,
            Path(plugin.__file__).parent/'requirements.json',*plugin.INPUTS]
    P.write_json(out/'manifest.json',dict(created_at=datetime.now(timezone.utc).isoformat(),python=sys.version,
        profile=args.profile,seed=args.seed,iterations=args.iterations,cases=cases,
        source_sha256={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs}))
    P.write_json(out/'requirements.json',requirements)
    tools={}
    for name,command in plugin.probes(args).items():
        tools[name]=P.execute(command,out/(name+'-version.log'),args.timeout,out)
    P.write_json(out/'tools.json',tools)
    context=plugin.prepare(args,out);results=[];hits={name:{} for name in plugin.CONFIGS}
    for case in cases:
        d=out/case['id'];d.mkdir();P.write_json(d/'case.json',case)
        execution=plugin.execute(args,out,d,case,context);log=(d/'simulation.log').read_text(errors='replace')
        status,message,counts=evaluate(case,execution,log)
        observed=sorted(set(re.findall(r'^COVER (\S+)$',log,re.M)))
        credited=observed if status=='pass' and case['category']=='functional' else []
        for goal in credited:hits[case['configuration']].setdefault(goal,[]).append(case['id'])
        result=dict(id=case['id'],configuration=case['configuration'],category=case['category'],outcome=status,
                    message=message,counts=counts,observed_coverage=observed,credited_coverage=credited,**execution)
        P.write_json(d/'result.json',result);results.append(result);print(status.upper(),case['id'],message,flush=True)
    coverage={name:dict(success=goals<=observed.keys(),missing=sorted(goals-observed.keys()),hit=len(goals & observed.keys()),required=len(goals),hits=observed) for name,observed in hits.items()}
    success=len(results)==len(cases) and all(r['outcome'] in ('pass','detected') for r in results) and all(c['success'] for c in coverage.values())
    P.write_json(out/'coverage.json',coverage);P.write_json(out/'summary.json',dict(success=success,planned=len(cases),results=results))
    suite=ET.Element('testsuite',name=plugin.NAME,tests=str(len(results)+len(coverage)),failures=str(sum(r['outcome']=='fail' for r in results)+sum(not c['success'] for c in coverage.values())),errors=str(sum(r['outcome']=='error' for r in results)))
    for r in results:
        n=ET.SubElement(suite,'testcase',name=r['id'],classname=plugin.NAME+'.'+r['configuration'],time=f"{r['seconds']:.6f}")
        if r['outcome'] in ('error','fail'):ET.SubElement(n,'error' if r['outcome']=='error' else 'failure',message=r['message'])
    for name,c in coverage.items():
        n=ET.SubElement(suite,'testcase',name=name+'-coverage',classname=plugin.NAME+'.gate')
        if not c['success']:ET.SubElement(n,'failure',message='missing required goals').text=', '.join(c['missing'])
    ET.indent(suite);ET.ElementTree(suite).write(out/'junit.xml',encoding='utf-8',xml_declaration=True)
    print('Artifacts:',out,'\nRegression:', 'PASS' if success else 'FAIL');return 0 if success else 1

def main(plugin):
    p=argparse.ArgumentParser(description=plugin.__doc__);p.add_argument('--profile',choices=('smoke','nightly'),default='smoke');p.add_argument('--seed',type=int,default=17)
    p.add_argument('--iterations',type=int);p.add_argument('--timeout',type=float,default=120);p.add_argument('--build-timeout',type=float,default=180)
    p.add_argument('--iverilog',default='iverilog');p.add_argument('--vvp',default='vvp');p.add_argument('--verilator',default='verilator');p.add_argument('--cc',default='cc')
    p.add_argument('--out',type=Path,default=Path('artifacts')/datetime.now(timezone.utc).strftime(plugin.NAME+'-%Y%m%dT%H%M%S%fZ'))
    args=p.parse_args()
    if args.iterations is None:args.iterations=plugin.ITERATIONS[args.profile]
    if os.name!='posix' or args.seed<0 or not 1<=args.iterations<=10000 or any(not math.isfinite(n) or n<=0 for n in (args.timeout,args.build_timeout)):p.error('invalid environment, seed, count or timeout')
    if args.out.exists():p.error('output exists; choose a new directory')
    previous=signal.signal(signal.SIGTERM,P.interrupted)
    try:return run(plugin,args)
    except P.RunInterrupted as exc:return 128+exc.signum
    except KeyboardInterrupt:return 130
    except (OSError,ValueError,KeyError,TypeError,ImportError) as exc:print('RUNNER_ERROR',exc,file=sys.stderr);return 1
    finally:signal.signal(signal.SIGTERM,previous)

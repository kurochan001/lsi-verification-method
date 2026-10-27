#!/usr/bin/env python3
"""Run the seven advanced local verification examples; no GitLab, CI edits or automatic installs."""
import argparse
from datetime import datetime,timezone
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import signal
import sys
import xml.etree.ElementTree as ET
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1]
SUPPORT_PATH=HERE.parent/'gitlab-regression/run.py'
spec=importlib.util.spec_from_file_location('system_regression_process',SUPPORT_PATH)
P=importlib.util.module_from_spec(spec);spec.loader.exec_module(P)
SIMULATIONS=['local-axis','local-c-driver','local-memory-order','local-dsp','local-cocotb','local-differential']
FORMALS=['local-progress']

def child_success(summary):
    if summary.get('success') is not True or type(summary.get('planned')) is not int or summary['planned']<=0:return False
    results=summary.get('results')
    if isinstance(results,list):return len(results)==summary['planned'] and all(r.get('outcome') in ('pass','detected') for r in results)
    return type(results) is int and results==summary['planned'] and summary.get('complete') is True

def run(args):
    out=args.out.resolve();out.mkdir(parents=True,exist_ok=False)
    examples=(SIMULATIONS if args.stage in ('all','simulation') else [])+(FORMALS if args.stage in ('all','formal') else [])
    P.write_json(out/'manifest.json',dict(created_at=datetime.now(timezone.utc).isoformat(),examples=examples,
        profile=args.profile,seed=args.seed,python=args.python,timeout=args.timeout,formal_timeout=args.formal_timeout,cocotb_python=args.cocotb_python,formal_python=args.formal_python,
        source_sha256={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in (Path(__file__),SUPPORT_PATH)},
        child_evidence='Each child has its own source manifest, JUnit and detailed results. Parent cases are child regression gates.'))
    results=[]
    for name in examples:
        interpreter=args.cocotb_python if name=='local-cocotb' else args.formal_python if name in FORMALS else args.python
        command=[interpreter,str(HERE.parent/name/'run.py'),'--out',str(out/name)]
        if name in SIMULATIONS:command+=['--profile',args.profile,'--seed',str(args.seed)]
        else:command+=['--timeout',str(args.formal_timeout)]
        if name in FORMALS:command=[interpreter,str(Path(__file__).resolve()),'--formal-child',*command[1:]]
        execution=P.execute(command,out/(name+'.log'),args.timeout,out)
        summary_path=out/name/'summary.json';ok=False;message='child execution or summary failed'
        try:
            if not execution['error'] and execution['returncode']==0 and summary_path.exists():ok=child_success(json.loads(summary_path.read_text()))
        except (OSError,ValueError,KeyError,TypeError) as exc:message='invalid child evidence: '+str(exc)
        record=dict(id=name,status='pass' if ok else 'error',message='child regression complete' if ok else message,**execution)
        results.append(record);print(record['status'].upper(),name,flush=True)
    success=len(results)==len(examples) and all(r['status']=='pass' for r in results)
    P.write_json(out/'summary.json',dict(success=success,planned=len(examples),results=results))
    suite=ET.Element('testsuite',name='local.advanced-regression',tests=str(len(results)),failures='0',errors=str(sum(r['status']=='error' for r in results)))
    for result in results:
        n=ET.SubElement(suite,'testcase',name=result['id'],classname='local.advanced-regression',time=f"{result['seconds']:.6f}")
        if result['status']=='error':ET.SubElement(n,'error',message=result['message'])
    ET.indent(suite);ET.ElementTree(suite).write(out/'junit.xml',encoding='utf-8',xml_declaration=True)
    print('Artifacts:',out,'\nAdvanced regression:', 'PASS' if success else 'FAIL');return 0 if success else 1

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--stage',choices=('all','simulation','formal'),default='all')
    p.add_argument('--profile',choices=('smoke','nightly'),default='smoke');p.add_argument('--seed',type=int,default=17)
    p.add_argument('--cocotb-python',default=sys.executable);p.add_argument('--formal-python',default=sys.executable)
    p.add_argument('--python',default=sys.executable);p.add_argument('--timeout',type=float,default=1800);p.add_argument('--formal-timeout',type=float,default=300)
    p.add_argument('--out',type=Path,default=Path('artifacts')/datetime.now(timezone.utc).strftime('advanced-regression-%Y%m%dT%H%M%S%fZ'))
    args=p.parse_args()
    if os.name!='posix' or args.seed<0 or any(not math.isfinite(n) or n<=0 for n in (args.timeout,args.formal_timeout)):p.error('requires POSIX, nonnegative seed and finite positive timeouts')
    if args.out.exists():p.error('output exists; choose a new directory')
    previous=signal.signal(signal.SIGTERM,P.interrupted)
    try:return run(args)
    except P.RunInterrupted as exc:return 128+exc.signum
    except KeyboardInterrupt:return 130
    except (OSError,ValueError,KeyError,TypeError) as exc:print('RUNNER_ERROR',exc,file=sys.stderr);return 1
    finally:signal.signal(signal.SIGTERM,previous)
if __name__=='__main__':
    if len(sys.argv)>1 and sys.argv[1]=='--formal-child':
        os.environ['PATH']=str(Path(sys.executable).parent)+os.pathsep+os.environ.get('PATH','')
        os.execv(sys.executable,[sys.executable,*sys.argv[2:]])
    sys.exit(main())

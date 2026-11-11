#!/usr/bin/env python3
"""Run an explicit inventory of local unittest groups; reject skips and zero tests."""
import argparse
import concurrent.futures
from datetime import datetime,timezone
import math
from pathlib import Path
import re
import signal
import subprocess
import sys
import threading
import time
import quality_common as Q
def groups(root,scope):return ([root/'tools/tests'] if scope=='tools' else sorted((root/'examples').glob('*/tests'))+[root/'tools/tests'])
def repository_inputs(root,out):
    data=subprocess.check_output(['git','-C',str(root),'ls-files','-z','--cached','--others','--exclude-standard'])
    paths={root/p.decode() for p in data.split(b'\0') if p}
    return sorted(p for p in paths if p.is_file() and not p.resolve().is_relative_to(out.resolve()))
def execute(command,log,timeout,cwd,cancel):
    """Like the shared helper, but a worker thread cannot see the signal, so it watches for a cancellation."""
    started=time.monotonic();code=error=None
    with log.open('w',encoding='utf-8') as stream:
        process=subprocess.Popen(command,cwd=cwd,stdout=stream,stderr=subprocess.STDOUT,start_new_session=True)
        while code is None and error is None:
            try:code=process.wait(timeout=.2)
            except subprocess.TimeoutExpired:
                if cancel.is_set():error='cancelled'
                elif time.monotonic()-started>timeout:error='command timeout'
        if error:
            cleanup=Q.P.stop_process_group(process)
            if cleanup:error+='; '+cleanup
            stream.write(f'\nRUNNER_ERROR {error}\n')
    return dict(command=command,returncode=code,error=error,seconds=time.monotonic()-started)
def evaluate(execution,log):
    counts=re.findall(r'^Ran (\d+) tests? in ',log,re.M)
    skips=re.findall(r"^.*?\.\.\. skipped (.+)$",log,re.M)
    good=not execution['error'] and execution['returncode']==0 and len(counts)==1 and int(counts[0])>0 and re.findall(r'^OK[ \t]*$',log,re.M)==['OK'] and not skips
    return dict(success=good,tests=int(counts[0]) if len(counts)==1 else 0,skips=skips,execution=execution)
def run(a):
    selected=groups(Q.ROOT,a.scope);names=[p.parent.name if p.parent.name!='tools' else 'tools' for p in selected]
    if len(names)!=len(set(names)):raise ValueError('duplicate unittest group')
    files=[p for path in selected for p in sorted(path.rglob('*.py'))];inputs=repository_inputs(Q.ROOT,a.out)
    report=Q.Report('selftests',a.out,[Path(__file__),*inputs,*files],['inventory',*names,'source-freshness'],dict(groups=[str(p.relative_to(Q.ROOT)) for p in selected],python=a.python,scope=a.scope))
    report.check('inventory',bool(names),dict(groups=len(names),test_files=len(files)))
    cancel=threading.Event()
    def group(item):
        name,path=item;r=execute([a.python,'-m','unittest','discover','-s',str(path),'-v'],report.out/(name+'.log'),a.timeout,Q.ROOT,cancel)
        return name,evaluate(r,(report.out/(name+'.log')).read_text(errors='replace'))
    results=[]
    with concurrent.futures.ThreadPoolExecutor(max_workers=a.jobs) as pool:
        try:
            for name,result in pool.map(group,zip(names,selected)):
                results.append(dict(id=name,**result));report.check(name,result['success'],result);print('PASS' if result['success'] else 'FAIL',name,flush=True)
        except Q.P.RunInterrupted:
            # Leaving the block waits for the workers, which now stop their process groups.
            cancel.set();pool.shutdown(wait=False,cancel_futures=True);raise
    changed=report.fresh()
    current=groups(Q.ROOT,a.scope)
    if current!=selected or [p for path in current for p in sorted(path.rglob('*.py'))]!=files:changed.append('unittest inventory changed')
    if repository_inputs(Q.ROOT,a.out)!=inputs:changed.append('repository input inventory changed')
    report.check('source-freshness',not changed,changed)
    Q.write(report.out/'tests.json',dict(groups=len(results),tests=sum(r['tests'] for r in results),results=results));return report.finish()
def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--scope',choices=('tools','all'),default='all');p.add_argument('--python',default=sys.executable);p.add_argument('--jobs',type=int,default=2);p.add_argument('--timeout',type=float,default=600);p.add_argument('--out',type=Path,default=Q.ROOT/'artifacts'/datetime.now(timezone.utc).strftime('selftests-%Y%m%dT%H%M%S%fZ'))
    a=p.parse_args()
    if not 1<=a.jobs<=16 or not math.isfinite(a.timeout) or a.timeout<=0 or a.out.exists():p.error('valid jobs, finite positive timeout and fresh --out required')
    a.python=Q.executable(a.python)
    previous={sig:signal.signal(sig,Q.P.interrupted) for sig in (signal.SIGTERM,signal.SIGINT)}
    try:return run(a)
    except Q.P.RunInterrupted as exc:return 128+exc.signum
    except (OSError,ValueError,KeyError,TypeError,subprocess.SubprocessError) as exc:print('SELFTEST_ERROR',exc,file=sys.stderr);return 1
    finally:
        for sig,handler in previous.items():signal.signal(sig,handler)
if __name__=='__main__':sys.exit(main())

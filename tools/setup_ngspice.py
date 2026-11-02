#!/usr/bin/env python3
"""Build or check the pinned ngspice shared library in an isolated directory."""
import argparse
from datetime import datetime,timezone
import json
import math
import os
from pathlib import Path
import sys
import ngspice as N
import quality_common as Q

def run(a):
    phases=['clone','fetch','checkout','revision','patch','generate','configure','build','install']
    checks=['installation','probe','source-freshness'] if a.check else [*phases,'installation','probe','source-freshness']
    config=N.spec();report=Q.Report('ngspice-setup',a.out,[Path(__file__),Path(N.__file__),N.CONFIG,Q.ROOT/N.spec()['patch']['file']],checks,dict(spec=config,tool_bin=[str(p) for p in a.tool_bin],check=str(a.check)))
    os.environ['PATH']=os.pathsep.join([*map(lambda p:str(p.resolve()),a.tool_bin),os.environ.get('PATH','')])
    good=True;executions=[];home=a.check.resolve() if a.check else report.out/'install'
    if not a.check:
        source=report.out/'src';build=report.out/'build';build.mkdir();logs=report.out/'logs';logs.mkdir()
        def execute(phase,command,cwd=report.out):
            nonlocal good
            r=Q.P.execute(command,logs/(phase+'.log'),a.timeout,cwd) if good else dict(command=command,error='prerequisite failed',returncode=None)
            ok=not r['error'] and r['returncode']==0
            if phase=='revision' and ok:ok=(logs/(phase+'.log')).read_text().strip()==config['commit']
            executions.append(dict(phase=phase,**r));good=report.check(phase,ok,r) and good
        execute('clone',['git','clone','--depth=1','--no-checkout',config['repository'],str(source)])
        execute('fetch',['git','-C',str(source),'fetch','--depth=1','origin',config['commit']])
        execute('checkout',['git','-C',str(source),'checkout','--detach',config['commit']])
        execute('revision',['git','-C',str(source),'rev-parse','HEAD'])
        patch=config['patch'];patch_file=Q.ROOT/patch['file']
        if good and (N.digest(patch_file)!=patch['sha256'] or N.digest(source/patch['target'])!=patch['original_sha256']):good=False
        execute('patch',['git','-C',str(source),'apply',str(patch_file)])
        if good and N.digest(source/patch['target'])!=patch['patched_sha256']:raise ValueError('ngspice patch result differs')
        execute('generate',['sh','autogen.sh'],source)
        execute('configure',[str(source/'configure'),'--prefix='+str(home),*config['configure']],build)
        execute('build',['make','-j'+str(a.jobs)],build)
        execute('install',['make','install'],build)
    record={}
    try:
        if not good:raise ValueError('ngspice build failed')
        record=N.snapshot(home) if a.check else N.record_install(home,source)
        report.check('installation',True,record)
    except (OSError,ValueError,KeyError,TypeError) as err:good=False;report.check('installation',False,str(err))
    Q.write(report.out/'ngspice-source.json',record);Q.write(report.out/'builds.json',executions)
    result={}
    try:
        if not good:raise ValueError('installation unavailable')
        result=N.probe(home);report.check('probe',True,result)
    except (OSError,ValueError,KeyError,TypeError,AttributeError) as err:report.check('probe',False,str(err))
    Q.write(report.out/'probe.json',result)
    changed=report.fresh()
    if record:
        try:N.verify(record)
        except (OSError,ValueError,KeyError,TypeError) as err:changed.append(str(err))
    report.check('source-freshness',not changed,changed)
    print('ngspice bin:',home/'bin');return report.finish()

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--check',type=Path);p.add_argument('--jobs',type=int,default=2);p.add_argument('--timeout',type=float,default=1800)
    p.add_argument('--tool-bin',type=Path,action='append',default=[])
    p.add_argument('--out',type=Path,default=Q.ROOT/'artifacts/toolchains'/datetime.now(timezone.utc).strftime('ngspice-%Y%m%dT%H%M%S%fZ'))
    a=p.parse_args()
    if a.out.exists() or not 1<=a.jobs<=16 or not math.isfinite(a.timeout) or a.timeout<=0:p.error('fresh output, jobs 1..16 and positive finite timeout required')
    try:return run(a)
    except (OSError,ValueError,KeyError,TypeError) as err:print('NGSPICE_SETUP_ERROR',err,file=sys.stderr);return 1
if __name__=='__main__':sys.exit(main())

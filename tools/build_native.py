#!/usr/bin/env python3
"""Build pinned native EDA sources into a fresh prefix (Ubuntu CI reference)."""
import argparse
from datetime import datetime,timezone
import json
import math
from pathlib import Path
import sys
import quality_common as Q
HERE=Path(__file__).resolve().parent
def run(a):
    config=json.loads((HERE/'environment.json').read_text());names=['iverilog','verilator']+(['cudd','opensta'] if a.profile=='full' else [])
    phases=['clone','fetch','checkout','revision','generate','configure','build','install'];ids=[n+'/'+p for n in names for p in phases]+['source-freshness']
    report=Q.Report('native-build',a.out,[Path(__file__),HERE/'environment.json'],ids,dict(profile=a.profile,jobs=a.jobs,timeout=a.timeout,native_sources={n:config['native_sources'][n] for n in names}))
    prefix=report.out/'install';records={}
    for name in names:
        spec=config['native_sources'][name];src=report.out/'src'/name;src.parent.mkdir(exist_ok=True);directory=report.out/'logs'/name;directory.mkdir(parents=True)
        good=True;records[name]=dict(**spec,executions=[])
        def execute(phase,command,cwd=report.out):
            nonlocal good
            if good:r=Q.P.execute(command,directory/(phase+'.log'),a.timeout,cwd)
            else:r=dict(command=command,returncode=None,error='prerequisite failed')
            ok=not r['error'] and r['returncode']==0
            if phase=='revision' and ok:ok=(directory/(phase+'.log')).read_text().strip()==spec['commit']
            records[name]['executions'].append(dict(phase=phase,**r));report.check(name+'/'+phase,ok,r);good=good and ok;print('PASS' if ok else 'FAIL',name+'/'+phase,flush=True)
        execute('clone',['git','clone','--depth=1','--filter=blob:none','--no-checkout',spec['repository'],str(src)])
        execute('fetch',['git','-C',str(src),'fetch','--depth=1','origin',spec['commit']])
        execute('checkout',['git','-C',str(src),'checkout','--detach',spec['commit']])
        execute('revision',['git','-C',str(src),'rev-parse','HEAD'])
        if name=='opensta':
            # OpenSTA's own CMake project has no generated configure script.
            execute('generate',['cmake','--version'])
            build=report.out/'opensta-build'
            execute('configure',['cmake','-S',str(src),'-B',str(build),'-G','Ninja','-DCMAKE_BUILD_TYPE=Release','-DCMAKE_INSTALL_PREFIX='+str(prefix),'-DCUDD_DIR='+str(prefix/'cudd'),'-DUSE_TCL_READLINE=OFF'])
            execute('build',['cmake','--build',str(build),'--parallel',str(a.jobs)])
            execute('install',['cmake','--install',str(build)])
        else:
            execute('generate',['sh','autoconf.sh'] if name=='iverilog' else ['autoconf'] if name=='verilator' else ['test','-x',str(src/'configure')],src)
            target=prefix/'cudd' if name=='cudd' else prefix
            command=['./configure','--prefix='+str(target)]+(['--enable-static','--disable-shared'] if name=='cudd' else [])
            execute('configure',command,src);execute('build',['make','-j'+str(a.jobs)],src);execute('install',['make','install'],src)
    Q.write(report.out/'native-sources.json',records)
    changed=report.fresh();report.check('source-freshness',not changed,changed);print('Native bin:',prefix/'bin');return report.finish()
def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--profile',choices=('smoke','full'),default='full');p.add_argument('--jobs',type=int,default=2);p.add_argument('--timeout',type=float,default=1800);p.add_argument('--out',type=Path,default=Q.ROOT/'artifacts/toolchains'/datetime.now(timezone.utc).strftime('native-%Y%m%dT%H%M%S%fZ'))
    a=p.parse_args()
    if not 1<=a.jobs<=16 or not math.isfinite(a.timeout) or a.timeout<=0 or a.out.exists():p.error('valid jobs, finite positive timeout and fresh --out required')
    try:return run(a)
    except (OSError,ValueError,KeyError,TypeError) as exc:print('NATIVE_BUILD_ERROR',exc,file=sys.stderr);return 1
if __name__=='__main__':sys.exit(main())

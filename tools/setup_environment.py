#!/usr/bin/env python3
"""Prepare isolated Python environments, pinned docs packages and official UVM."""
import argparse
from datetime import datetime,timezone
import json
import math
from pathlib import Path
import shlex
import sys
import quality_common as Q
import oss_cad as O
HERE=Path(__file__).resolve().parent
def run(a):
    ids=['python-venv','python-packages']
    if a.profile in ('docs','full'):ids+=['docs-packages']
    if a.profile=='full':ids+=['formal-venv','formal-packages','uvm-library','oss-cad-suite']
    ids+=['diagnosis','source-freshness']
    report=Q.Report('environment-setup',a.out,[Path(__file__),HERE/'check_environment.py',HERE/'environment.json',HERE/'uvm-source-sha256.json',HERE/'docs-requirements.txt',HERE/'simulation-requirements.txt',HERE/'docs/package.json',HERE/'docs/package-lock.json',HERE/'docs/check_mermaid.mjs',Q.ROOT/'examples/local-fifo-formal/tools-requirements.txt',Q.ROOT/'examples/local-uvm/setup_uvm.py',HERE/'setup_oss_cad.py',Path(O.__file__),O.CONFIG],ids,dict(profile=a.profile,python=a.python,tool_bin=[str(p) for p in a.tool_bin]))
    def execute(name,command,ready=True):
        if ready:r=Q.P.execute(command,report.out/(name+'.log'),a.timeout, Q.ROOT)
        else:r=dict(command=command,returncode=None,error='prerequisite failed')
        good=not r['error'] and r['returncode']==0
        if good and name=='diagnosis':
            try:
                child=json.loads((report.out/'diagnosis/summary.json').read_text())
                good=child['success'] is True and child['complete'] is True and child['planned']==len(child['results']) and bool(child['results']) and all(x['status']=='pass' for x in child['results'])
            except (OSError,ValueError,KeyError,TypeError):good=False
        report.check(name,good,r);return good
    py=report.out/'python/bin/python';formal=report.out/'formal/bin/python'
    ok=execute('python-venv',[a.python,'-m','venv',str(report.out/'python')])
    reqs=[]
    if a.profile in ('docs','full'):reqs+=['-r',str(HERE/'docs-requirements.txt')]
    if a.profile=='full':reqs+=['-r',str(HERE/'simulation-requirements.txt')]
    if reqs:ok=execute('python-packages',[str(py),'-m','pip','install','--disable-pip-version-check',*reqs],ok)
    else:report.check('python-packages',ok,'smoke uses the Python standard library')
    if a.profile in ('docs','full'):ok=execute('docs-packages',[a.npm,'ci','--prefix',str(HERE/'docs'),'--ignore-scripts','--no-audit','--no-fund'],ok)
    if a.profile=='full':
        f=execute('formal-venv',[a.python,'-m','venv',str(report.out/'formal')])
        f=execute('formal-packages',[str(formal),'-m','pip','install','--disable-pip-version-check','-r',str(Q.ROOT/'examples/local-fifo-formal/tools-requirements.txt')],f)
        u=execute('uvm-library',[a.python,str(Q.ROOT/'examples/local-uvm/setup_uvm.py'),'--out',str(report.out/'uvm')])
        oss_home=getattr(a,'oss_home',None) or report.out/'oss/oss-cad-suite'
        oss_command=[a.python,str(HERE/'setup_oss_cad.py'),'--out',str(report.out/'oss-check' if getattr(a,'oss_home',None) else report.out/'oss')]
        if getattr(a,'oss_home',None):oss_command+=['--check',str(oss_home)]
        o=execute('oss-cad-suite',oss_command);ok=ok and f and u and o
    command=[str(py),str(HERE/'check_environment.py'),'--profile',a.profile,'--python',str(py),'--out',str(report.out/'diagnosis')]
    if a.profile=='full':command+=['--formal-python',str(formal),'--uvm-home',str(report.out/'uvm/1800.2-2020.3.2'),'--oss-home',str(oss_home)]
    for path in a.tool_bin:command+=['--tool-bin',str(path.absolute())]
    execute('diagnosis',command,ok)
    changed=report.fresh();report.check('source-freshness',not changed,changed)
    command[command.index('--out')+1]=str(report.out.parent/(report.out.name+'-recheck'))
    (report.out/'next-command.txt').write_text(shlex.join(command)+'\n')
    print('Dedicated environment:',report.out);return report.finish()
def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--profile',choices=('docs','smoke','full'),default='full');p.add_argument('--python',default=sys.executable);p.add_argument('--npm',default='npm');p.add_argument('--tool-bin',type=Path,action='append',default=[]);p.add_argument('--timeout',type=float,default=600);p.add_argument('--out',type=Path,default=Q.ROOT/'artifacts/toolchains'/datetime.now(timezone.utc).strftime('quality-%Y%m%dT%H%M%S%fZ'))
    p.add_argument('--oss-home',type=Path,help='reuse an existing pinned OSS CAD Suite; otherwise install in the new environment')
    a=p.parse_args()
    if a.oss_home is not None:a.oss_home=a.oss_home.absolute()
    if not math.isfinite(a.timeout) or a.timeout<=0 or a.out.exists():p.error('positive finite timeout and fresh --out required')
    for name in ('python','npm'):setattr(a,name,Q.executable(getattr(a,name)))
    try:return run(a)
    except (OSError,ValueError,KeyError,TypeError) as exc:print('SETUP_ERROR',exc,file=sys.stderr);return 1
if __name__=='__main__':sys.exit(main())

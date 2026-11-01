#!/usr/bin/env python3
"""Install or check the pinned open-source tools for mutation and liveness examples."""
import argparse
from datetime import datetime,timezone
import json
import math
from pathlib import Path
import sys
import tarfile
import oss_cad as O
import quality_common as Q

def run(a):
    O.prepare_environment()
    data,key,spec=O.config();checks=['archive','extract','inventory','yosys','sby','mcy','source-freshness']
    report=Q.Report('oss-cad-setup',a.out,[Path(__file__),Path(O.__file__),O.CONFIG],checks,dict(platform=key,release=data['release'],url=spec['url']))
    archive=a.archive.absolute() if a.archive else report.out/'archive.tgz'
    if a.archive:
        download=dict(returncode=0,error=None,command=[],source=str(archive))
    else:
        code='import shutil,sys,urllib.request; r=urllib.request.urlopen(sys.argv[1],timeout=30); f=open(sys.argv[2],"wb"); shutil.copyfileobj(r,f); f.close();r.close()'
        download=Q.P.execute([sys.executable,'-c',code,spec['url'],str(archive)],report.out/'download.log',a.timeout,report.out)
    good=not download['error'] and download['returncode']==0 and archive.is_file() and O.digest(archive)==spec['sha256']
    report.check('archive',good,dict(expected=spec['sha256'],execution=download))
    home=report.out/'oss-cad-suite';error=None
    try:
        if not good:raise ValueError('archive verification failed')
        O.extract(archive,report.out)
    except (OSError,ValueError,EOFError,tarfile.TarError) as exc:
        error=str(exc)
    report.check('extract',error is None,error)
    snapshot={}
    try:
        if error is not None:raise ValueError('extraction failed')
        snapshot=O.verify(home);good=True
    except (OSError,ValueError,RuntimeError) as exc:good=False;snapshot=dict(error=str(exc))
    report.check('inventory',good,snapshot);Q.write(report.out/'oss-source.json',snapshot)
    for name,flags in [('yosys',['-V']),('sby',['--version']),('mcy',['--help'])]:
        r=Q.P.execute([str(home/'bin'/name),*flags],report.out/(name+'.log'),a.timeout,report.out) if good else dict(returncode=None,error='toolchain not verified')
        report.check(name,not r['error'] and r['returncode']==0,r)
    changed=report.fresh();report.check('source-freshness',not changed,changed)
    print('OSS CAD home:',home);return report.finish()

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--archive',type=Path);p.add_argument('--check',type=Path);p.add_argument('--timeout',type=float,default=600);p.add_argument('--out',type=Path,default=Q.ROOT/'artifacts/toolchains'/datetime.now(timezone.utc).strftime('oss-%Y%m%dT%H%M%S%fZ'))
    a=p.parse_args()
    if not math.isfinite(a.timeout) or a.timeout<=0:p.error('finite positive timeout required')
    try:
        if a.check:print(json.dumps(O.verify(a.check),indent=2));return 0
        if a.out.exists():p.error('fresh output required')
        return run(a)
    except (OSError,ValueError,RuntimeError) as exc:print('OSS_CAD_ERROR',exc,file=sys.stderr);return 1
if __name__=='__main__':sys.exit(main())

#!/usr/bin/env python3
"""Run real failed/repaired FIFO campaigns and audit their complete attempt history."""
import importlib.util
import json
import math
from pathlib import Path
import sys
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1]
S=importlib.util.spec_from_file_location('report_demo_evidence',HERE.parent/'local-exploration-common/evidence.py');E=importlib.util.module_from_spec(S);S.loader.exec_module(E)
def run(a):
    inputs=[Path(__file__),ROOT/'tools/run_regression.py',ROOT/'tools/regression_report.py',ROOT/'tools/regressions.json',HERE.parent/'local-fifo/run.py',HERE.parent/'local-fifo/rtl/sync_fifo.sv',HERE.parent/'local-fifo/tb/fifo_tb.sv',HERE.parent/'local-fifo/requirements.json']
    e=E.Evidence('local-regression-report',a,inputs,dict(child='local-fifo',matrix='all six depth/width configurations',failure='root job timeout',policy='last declared attempt owns the job'),['failed-campaign','repaired-campaign','report','failed-only','latest-failed','duplicate-campaign'])
    for name,extra,expected in [('failed-campaign',['--job-timeout','0.000001'],1),('repaired-campaign',[],0)]:
        command=[sys.executable,str(ROOT/'tools/run_regression.py'),'--example','local-fifo','--profile',a.profile,'--seed',str(a.seed),'--command-timeout',str(a.timeout),'--out',str(e.out/name),*extra]
        execution=E.P.execute(command,e.out/(name+'.log'),a.child_timeout,e.out)
        path=e.out/name/'summary.json';summary=json.loads(path.read_text()) if path.is_file() else {}
        ok=not execution['error'] and execution['returncode']==expected and summary.get('success') is (expected==0) and summary.get('complete') is True
        if expected:ok &= len(summary.get('results',[]))==6 and all('job timeout' in r.get('message','') for r in summary.get('results',[]))
        e.check(name,bool(ok),dict(execution=execution,summary=summary))
    for name,campaigns,expected in [('report',['failed-campaign','repaired-campaign'],0),('failed-only',['failed-campaign'],1),('latest-failed',['repaired-campaign','failed-campaign'],1),('duplicate-campaign',['repaired-campaign','repaired-campaign'],1)]:
        command=[sys.executable,str(ROOT/'tools/regression_report.py'),'--plan',str(e.out/'repaired-campaign/manifest.json'),'--out',str(e.out/name)]
        for campaign in campaigns:command+=['--campaign',str(e.out/campaign)]
        execution=E.P.execute(command,e.out/(name+'.log'),a.child_timeout,e.out)
        path=e.out/name/'summary.json';report=json.loads(path.read_text()) if path.is_file() else {}
        ok=not execution['error'] and execution['returncode']==expected and report.get('success') is (expected==0)
        if name=='report':ok &= report.get('planned')==6 and all(len(r['history'])==2 and not r['history'][0]['success'] and r['history'][1]['success'] for r in report.get('results',[]))
        e.check(name,bool(ok),dict(execution=execution,report=report))
    return e.finish()
def main():
    p=E.parser(__doc__,'local-regression-report');p.add_argument('--child-timeout',type=float,default=600);a=p.parse_args();E.validate(p,a)
    if not math.isfinite(a.child_timeout) or a.child_timeout<=0 or a.seed>2**31-4:p.error('finite positive child limit and valid seed required')
    try:return run(a)
    except (OSError,ValueError,KeyError,TypeError) as exc:print('RUNNER_ERROR',exc,file=sys.stderr);return 1
if __name__=='__main__':sys.exit(main())

#!/usr/bin/env python3
"""Run common DUT lint plus deliberate diagnostic and policy failures."""
import copy
import importlib.util
import json
import math
from pathlib import Path
import sys
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1]
def load(name,path):
    s=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
L=load('lint_common',ROOT/'tools/run_lint.py');E=L.E
def run(a):
    fixtures={'width':'WIDTHTRUNC','latch':'LATCH','implicit':'IMPLICIT','unconnected':'PINMISSING'}
    policies=['new','resolved','stale','unreviewed','malformed'];ids=['targets',*fixtures,*['policy/'+p for p in policies],'missing-tool','timeout']
    e=E.Evidence('local-lint',a,[Path(__file__),ROOT/'tools/run_lint.py',ROOT/'tools/lint_targets.json',ROOT/'tools/lint_baseline.json',*sorted((HERE/'fixtures').glob('*.sv'))],dict(fixtures=fixtures,policies=policies),ids)
    r=E.P.execute([sys.executable,str(ROOT/'tools/run_lint.py'),'--verilator',a.verilator,'--timeout',str(a.timeout),'--out',str(e.out/'targets')],e.out/'targets.log',a.child_timeout,e.out)
    child=json.loads((e.out/'targets/summary.json').read_text()) if (e.out/'targets/summary.json').is_file() else {}
    e.check('targets',not r['error'] and r['returncode']==0 and child.get('success') is True and child.get('complete') is True,dict(execution=r,summary=child))
    executions=[]
    for name,rule in fixtures.items():
        r=E.P.execute([a.verilator,'--lint-only','--Wall','-Wno-fatal','--top-module',name,str(HERE/'fixtures'/(name+'.sv'))],e.out/(name+'.log'),a.timeout,e.out)
        ds=L.diagnostics((e.out/(name+'.log')).read_text());ok=not r['error'] and r['returncode']==0 and not any(d['severity']=='Error' for d in ds) and any(d['severity']=='Warning' and d['rule']==rule for d in ds)
        executions.append(dict(id=name,execution=r,diagnostics=ds));e.check(name,ok,executions[-1])
    d=dict(severity='Warning',rule='WIDTH',file='fixture.sv',line=2,column=1,message='width mismatch')
    item=dict(diagnostic=d,count=1,disposition='waived',reason='synthetic policy test',impact='no design use',reviewer='test fixture',method='deterministic self-test',expires='source/tool/configuration change')
    b=dict(source_sha256={'fixture.sv':'old'},diagnostics=[item]);sha=b['source_sha256']
    delta=L.changes([d],dict(source_sha256=sha,diagnostics=[]),sha);e.check('policy/new',bool(delta['new']),delta)
    delta=L.changes([],b,sha);e.check('policy/resolved',bool(delta['resolved']),delta)
    delta=L.changes([d],b,{'fixture.sv':'new'});e.check('policy/stale',delta['source_changed'],delta)
    invalid=copy.deepcopy(b);invalid['diagnostics'][0]['reason']='REVIEW REQUIRED'
    try:L.changes([d],invalid,sha);rejected=False
    except ValueError:rejected=True
    e.check('policy/unreviewed',rejected,'unreviewed candidate must not be an accepted baseline')
    try:L.diagnostics('%Warning-this is malformed');rejected=False
    except ValueError:rejected=True
    e.check('policy/malformed',rejected,'unrecognized diagnostic must not become zero warnings')
    # Tool faults go through the real lint gate: every target must fail, for the injected reason.
    stalled=e.out/'stalled-verilator';stalled.write_text('#!/bin/sh\ncase "$1" in --version) echo "Verilator 5.052 2026-09-05 rev fixture";; *) exec sleep 60;; esac\n');stalled.chmod(0o755)
    targets=[t['id'] for t in json.loads((ROOT/'tools/lint_targets.json').read_text())['targets']]
    for name,verilator,limit,reason in [('missing-tool',e.out/'nonexistent-verilator',a.timeout,'No such file or directory'),('timeout',stalled,min(a.timeout,0.05),'command timeout')]:
        r=E.P.execute([sys.executable,str(ROOT/'tools/run_lint.py'),'--verilator',str(verilator),'--timeout',str(limit),'--out',str(e.out/name)],e.out/(name+'.log'),a.child_timeout,e.out)
        child=json.loads((e.out/name/'summary.json').read_text()) if (e.out/name/'summary.json').is_file() else {}
        rows={x['id']:x for x in child.get('results',[])}
        faulted=sorted(t for t in targets if rows.get(t,{}).get('status')=='fail' and reason in str(rows[t]['detail']['execution']['error']))
        e.check(name,not r['error'] and r['returncode']==1 and child.get('success') is False and child.get('complete') is True and faulted==sorted(targets),dict(execution=r,targets=len(targets),faulted=len(faulted)))
    E.P.write_json(e.out/'fixture-executions.json',executions);return e.finish()
def main():
    p=E.parser(__doc__,'local-lint');p.add_argument('--verilator',default='verilator');p.add_argument('--child-timeout',type=float,default=600)
    a=p.parse_args();E.validate(p,a)
    if not math.isfinite(a.child_timeout) or a.child_timeout<=0:p.error('positive finite child timeout required')
    try:return run(a)
    except (OSError,ValueError,KeyError,TypeError,RuntimeError) as exc:print('RUNNER_ERROR',exc,file=sys.stderr);return 1
if __name__=='__main__':sys.exit(main())

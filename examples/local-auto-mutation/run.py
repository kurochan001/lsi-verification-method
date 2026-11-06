#!/usr/bin/env python3
"""Automatic MCY mutations, independent functional tests, and unbounded equivalence."""
import importlib.util
import json
import math
from contextlib import closing
import os
from pathlib import Path
import shlex
import sqlite3
import sys
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1]
sys.path.insert(0,str(HERE));sys.path.insert(0,str(ROOT/'tools'))
import oss_cad as O
import quality_common as Q
from task import compare
spec=importlib.util.spec_from_file_location('auto_mutation_evidence',ROOT/'examples/local-exploration-common/evidence.py');E=importlib.util.module_from_spec(spec);spec.loader.exec_module(E)
LOGIC='''w=result("weak");s=result("strong");e=result("equiv")
if any(x not in ("PASS","FAIL") for x in (w,s,e)):
    tag("INCOMPLETE")
elif e=="PASS":
    tag("EQUIVALENT" if w==s=="PASS" else "ORACLE_CONFLICT")
else:
    tag("WEAK_COVERED" if w=="FAIL" else "WEAK_UNCOVERED")
    tag("STRONG_COVERED" if s=="FAIL" else "STRONG_UNCOVERED")
'''
# MCY always adds one unchanged design. It checks the three evaluations; it is not a candidate.
NO_OP='mutate -mode none'

def configuration(size,seed,python):
    result=f'[options]\nsize {size}\nseed {seed}\n[script]\nread_verilog -sv irq_regs.sv\nprep -top irq_regs\n[files]\nirq_regs.sv\n[logic]\n'+LOGIC+'\n[report]\nprint("AUTOMUTATION_COMPLETE total=%d" % tags())\n'
    for kind in ('weak','strong','equiv'):
        # OSS CAD's launcher sets PYTHONEXECUTABLE for its own interpreter.
        # The project adapter must use its explicitly chosen Python instead.
        command=['env','-u','PYTHONEXECUTABLE','-u','PYTHONHOME','-u','PYTHONPATH','-u','__PYVENV_LAUNCHER__',python,str(HERE/'task.py'),kind]
        result+='[test '+kind+']\nmaxbatchsize 1\nexpect PASS FAIL ERROR TIMEOUT\nrun '+shlex.join(command)+'\n'
    return result

def tags_for(weak,strong,equiv):
    if any(s not in ('PASS','FAIL') for s in (weak,strong,equiv)):return {'INCOMPLETE'}
    if equiv=='PASS':return {'EQUIVALENT'} if weak==strong=='PASS' else {'ORACLE_CONFLICT'}
    return {'WEAK_COVERED' if weak=='FAIL' else 'WEAK_UNCOVERED','STRONG_COVERED' if strong=='FAIL' else 'STRONG_UNCOVERED'}

def audit(project,size):
    with closing(sqlite3.connect(project/'database/db.sqlite3')) as db:
        mutations=db.execute('select mutation_id,mutation from mutations order by mutation_id').fetchall()
        tests=db.execute('select mutation_id,test,result from results').fetchall();tags=db.execute('select mutation_id,tag from tags').fetchall()
        queued=db.execute('select count(*) from queue').fetchone()[0]
    if len(mutations)!=size or len({m for _,m in mutations})!=size or len(tests)!=3*size or queued:raise ValueError('mutation/task inventory incomplete')
    by_test={(i,t):s for i,t,s in tests}
    if len(by_test)!=len(tests):raise ValueError('duplicate test result')
    rows=[];control=None;counts={k:0 for k in ('EQUIVALENT','ORACLE_CONFLICT','INCOMPLETE','WEAK_COVERED','WEAK_UNCOVERED','STRONG_COVERED','STRONG_UNCOVERED')}
    for identity,mutation in mutations:
        observed={t:by_test[(identity,t)] for t in ('weak','strong','equiv')};expected=tags_for(*[observed[t] for t in ('weak','strong','equiv')]);actual=[t for i,t in tags if i==identity]
        if len(actual)!=len(set(actual)) or set(actual)!=expected:raise ValueError('MCY tags differ from raw outcomes')
        for t in observed:
            directory=project/'evidence'/str(identity)/t;record=json.loads((directory/'result.json').read_text());source=directory.parent/'mutated.v'
            if record['status']!=observed[t] or record['mutated_sha256']!=Q.digest(source):raise ValueError('task evidence differs from database or generated input')
            if observed[t] in ('PASS','FAIL') and t!='equiv' and record.get('checks',0)<=0:raise ValueError('simulation performed no comparisons')
        if mutation==NO_OP:
            if set(actual)!={'EQUIVALENT'}:raise ValueError('no-op control is not equivalent')
            control=dict(id=identity,outcomes=observed,mutated_sha256=Q.digest(project/'evidence'/str(identity)/'mutated.v'));continue
        for tag in actual:counts[tag]+=1
        rows.append(dict(id=identity,mutation=mutation,outcomes=observed,tags=sorted(actual),mutated_sha256=Q.digest(project/'evidence'/str(identity)/'mutated.v')))
    if control is None:raise ValueError('no-op control missing')
    denominator=size-1-counts['EQUIVALENT']-counts['INCOMPLETE']-counts['ORACLE_CONFLICT']
    return dict(total=size,candidates=size-1,no_op_control=control,counts=counts,changed_mutations=denominator,weak_score=counts['WEAK_COVERED']/denominator if denominator else None,strong_score=counts['STRONG_COVERED']/denominator if denominator else None,mutations=rows,note='functional equivalence observes pending and irq; debug_hint is unspecified; execution failures are not detections')

def run(a):
    O.prepare_environment();size=32 if a.profile=='smoke' else 96
    ids=['toolchain','baseline/weak','baseline/strong','mutation-init','mutation-run','classification','no-op-control','improvement','missing-compiler-control','source-freshness']
    sources=[Path(__file__),HERE/'task.py',HERE/'vectors.py',HERE/'rtl/irq_regs.sv',HERE/'tb.sv',HERE/'miter.sv',ROOT/'examples/local-formal-common/runner.py',Path(Q.__file__),Path(O.__file__),O.CONFIG]
    e=E.Evidence('local-auto-mutation',a,sources,dict(size=size,seed=a.seed,logic=LOGIC,observed_outputs=['pending','irq'],unobserved=['debug_hint']),ids)
    try:snapshot=O.verify(a.oss_home);ready=True
    except (OSError,ValueError,RuntimeError) as exc:snapshot=dict(error=str(exc));ready=False
    E.P.write_json(e.out/'oss-source.json',snapshot);e.check('toolchain',ready,snapshot)
    os.environ.update(MCY_SBY=str(a.oss_home/'bin/sby'),MCY_IVERILOG=a.iverilog,MCY_VVP=a.vvp)
    project=e.out/'project';project.mkdir();source=HERE/'rtl/irq_regs.sv';(project/'irq_regs.sv').write_bytes(source.read_bytes())
    (project/'config.mcy').write_text(configuration(size,a.seed,sys.executable))
    baseline=True
    for kind in ('weak','strong'):
        if ready:status=compare(kind,source,e.out/('baseline-'+kind),project)
        else:status='ERROR'
        e.check('baseline/'+kind,status=='PASS',dict(status=status));baseline &= status=='PASS'
    for name,command in [('mutation-init',['init']),('mutation-run',['run','-j',str(a.jobs)])]:
        r=E.P.execute([str(a.oss_home/'bin/mcy'),*command],e.out/(name+'.log'),a.child_timeout,project) if ready and baseline else dict(returncode=None,error='original design or toolchain did not pass')
        ok=not r['error'] and r['returncode']==0;e.check(name,ok,r);baseline &= ok
    result={};problem=None
    try:
        if not baseline:raise ValueError('campaign did not finish')
        result=audit(project,size)
        if result['counts']['INCOMPLETE'] or result['counts']['ORACLE_CONFLICT']:raise ValueError('incomplete analysis or contradictory oracle')
    except (OSError,ValueError,KeyError,TypeError,sqlite3.Error) as exc:problem=str(exc)
    E.P.write_json(e.out/'mutation-report.json',dict(result,success=problem is None,error=problem))
    e.check('classification',problem is None,problem or result['counts'])
    e.check('no-op-control',problem is None and bool(result.get('no_op_control')),result.get('no_op_control',problem))
    improvement=problem is None and result['changed_mutations']>0 and result['counts']['EQUIVALENT']>0 and result['counts']['WEAK_UNCOVERED']>0 and result['counts']['STRONG_UNCOVERED']==0
    e.check('improvement',improvement,result.get('counts',problem))
    status=compare('strong',source,e.out/'missing-compiler',project,compiler=str(e.out/'missing-iverilog'))
    e.check('missing-compiler-control',status=='ERROR',dict(status=status,note='execution error is not a detected mutation'))
    changed=[n for n,h in json.loads((e.out/'manifest.json').read_text())['source_sha256'].items() if not (ROOT/n).is_file() or Q.digest(ROOT/n)!=h]
    try:
        if O.verify(a.oss_home)!=snapshot:changed.append('toolchain changed')
    except (OSError,ValueError,RuntimeError):changed.append('toolchain changed')
    e.check('source-freshness',not changed,changed);return e.finish()

def main():
    p=E.parser(__doc__,'local-auto-mutation');p.add_argument('--oss-home',type=Path,required=True);p.add_argument('--jobs',type=int,default=2);p.add_argument('--child-timeout',type=float,default=1800)
    a=p.parse_args();E.validate(p,a);a.oss_home=a.oss_home.absolute()
    if not 1<=a.jobs<=8 or not math.isfinite(a.child_timeout) or a.child_timeout<=0 or not 0<=a.seed<2**31:p.error('valid jobs, seed and finite timeout required')
    try:return run(a)
    except (OSError,ValueError,KeyError,TypeError,RuntimeError,sqlite3.Error) as exc:print('MUTATION_ERROR',exc,file=sys.stderr);return 1
if __name__=='__main__':sys.exit(main())

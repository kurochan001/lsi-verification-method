#!/usr/bin/env python3
"""Native UVM constraints/randomize plus native coverpoint/cross bin evidence."""
import hashlib
import importlib.util
import os
from pathlib import Path
import re
import shlex
import sys
HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('crv_evidence',HERE.parent/'local-exploration-common/evidence.py');E=importlib.util.module_from_spec(spec);spec.loader.exec_module(E)
BASE=HERE.parent/'local-uvm'
SOURCES=[BASE/'tb/apb_if.sv',BASE/'tb/uvm_apb_pkg.sv',HERE/'tb/random_pkg.sv',HERE.parent/'gitlab-apb/rtl/apb_regs.sv',HERE/'tb/top.sv']
EXPECTED_BINS=({f'__vlAnonCG_bus_cg.a.{n}' for n in ('cfg','idreg','pending','invalid')}|
 {f'__vlAnonCG_bus_cg.w.{n}' for n in ('read','write')}|{f'__vlAnonCG_bus_cg.e.{n}' for n in ('okay','error')}|
 {f'__vlAnonCG_bus_cg.aw.{a}_x_{w}' for a in ('cfg','idreg','pending','invalid') for w in ('read','write')}|
 {f'__vlAnonCG_collision_cg.{point}.{n}' for point in ('e','c') for n in ('absent','present')}|
 {f'__vlAnonCG_collision_cg.ec.{a}_x_{c}' for a in ('absent','present') for c in ('absent','present')})
def native(path):
    bins={}
    for line in path.read_text().splitlines():
        if not line or line.startswith('#'):continue
        m=re.fullmatch(r"C '([^']*)' (\d+)",line)
        if not m:raise ValueError('malformed native coverage')
        meta=dict(field.split('\x02',1) for field in m[1].split('\x01') if field)
        if meta.get('t')=='covergroup' and Path(meta.get('f','')).resolve()==(HERE/'tb/random_pkg.sv').resolve():
            name=meta['h']
            if name in bins:raise ValueError('duplicate native bin')
            bins[name]=int(m[2])
    if bins.keys()!=EXPECTED_BINS or any(v<=0 for v in bins.values()):raise ValueError('native bin inventory/hits differ from fixed plan')
    return bins

def random_trace(log,n):
    records=re.findall(r'^RANDOM addr=(\d+) write=([01]) data=([0-9a-f]{8}) events=(\d+)$',log,re.M)
    if len(records)!=n:raise ValueError('randomized operation count differs')
    rows=[[int(a),int(w),int(d,16),int(ev)] for a,w,d,ev in records]
    if any(a not in (0,4,8,12) or ev not in (0,1,3,15) or (a==8 and d>15) for a,w,d,ev in rows):raise ValueError('generated stimulus violates constraints')
    return rows

def run(args):
    home=args.uvm_home.resolve();library=home/'src/uvm_pkg.sv'
    n=16 if args.profile=='smoke' else 100;seeds=list(range(args.seed,args.seed+(1 if args.profile=='smoke' else 3)))
    names=['build']+[f'wait{w}-{name}' for w in (0,2) for name in [*[f'random-seed{s}' for s in seeds],'repeat-seed','detect-mutation1','detect-mutation2','detect-mutation3','bad-constraint','cover-off','native-bins']]
    e=E.Evidence('local-uvm-random',args,[Path(__file__),HERE/'sim_main.cpp',*SOURCES],dict(iterations=n,seeds=seeds,expected_bins=sorted(EXPECTED_BINS)),names)
    E.P.write_json(e.out/'uvm-source.json',dict(root=str(home),sha256={str(p.relative_to(home)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted((home/'src').rglob('*')) if p.is_file()}))
    E.P.write_json(e.out/'tools.json',{name:E.P.execute(command,e.out/(name+'-version.log'),args.timeout,e.out) for name,command in [('verilator',[args.verilator,'--version']),('solver',[args.solver,'--version'])]})
    os.environ['VERILATOR_SOLVER']=shlex.quote(args.solver)+' --in'
    build_dir=e.out/'build';build=E.P.execute([args.verilator,'--cc','--exe','--build','--timing','--trace','--coverage-user','--assert','-Wno-fatal','-j','4','--top-module','top','--Mdir',str(build_dir),'-I'+str(home/'src'),'-I'+str(BASE/'tb'),'+define+UVM_NO_DPI',str(library),*map(str,SOURCES),str(HERE/'sim_main.cpp')],e.out/'build.log',args.build_timeout,e.out)
    E.P.write_json(e.out/'build.json',build);built=not build['error'] and build['returncode']==0;e.check('build',built,build)
    executions=[]
    for wait in (0,2):
        observed=[];first_trace=None
        plans=([(f'random-seed{s}',s,n,0,0,0,None) for s in seeds]+[('repeat-seed',args.seed,n,0,0,0,None)]+
              [(f'detect-mutation{m}',args.seed,1,m,0,0,label) for m,label in ((1,'UVM_CONFIG'),(2,'UVM_PENDING'),(3,'UVM_CONFIG'))]+[
              ('bad-constraint',args.seed,1,0,1,0,'CRV_RANDOMIZE'),('cover-off',args.seed,1,0,0,1,'CRV_COVERAGE')])
        for name,seed,count,mutation,bad,off,label in plans:
            identity=f'wait{wait}-{name}';d=e.out/identity;d.mkdir()
            case=dict(checks=12+count,expected_failure=label)
            if built:ex=E.P.execute([str(build_dir/'Vtop'),f'+WAIT_CYCLES={wait}',f'+MUTATION={mutation}',f'+ITERATIONS={count}',f'+SEED={seed}',f'+BAD_CONSTRAINT={bad}',f'+COVER_OFF={off}',f'+WAVE={d/"wave.vcd"}'],d/'simulation.log',args.timeout,d)
            else:ex=dict(error='build failed',returncode=None);(d/'simulation.log').write_text('build failed\n')
            log=(d/'simulation.log').read_text(errors='replace');status,message=E.P.classify(case,ex,log);ok=status==('detected' if label else 'pass');bins={};trace=[]
            try:
                if ok and not label:
                    trace=random_trace(log,count);bins=native(d/'coverage.dat')
                    pairs=re.findall(r'^COUNT ([a-z_]+)=(\d+)$',log,re.M);writes=8+sum(r[1] for r in trace)
                    expected=dict(randomizations=count,transactions=12+count,reads=12+count-writes,writes=writes,errors=3+sum(a==12 or (a==4 and w) for a,w,data,ev in trace))
                    if len(pairs)!=len(dict(pairs)) or {k:int(v) for k,v in pairs}!=expected:raise ValueError('completion counts differ')
                    for severity,value in [('ERROR','0'),('FATAL','0'),('WARNING','2')]:
                        if re.findall(r'^UVM_'+severity+r'\s*:\s*(\d+)\s*$',log,re.M)!=[value]:raise ValueError('native UVM report differs')
                    if sorted(re.findall(r'^UVM_WARNING .*?\[([^]]+)\]',log,re.M))!=['NO_DPI_USED','NO_VISIT_CHECK']:raise ValueError('unexpected UVM warning')
                    if first_trace is None:first_trace=trace
                    if name=='repeat-seed' and trace!=first_trace:raise ValueError('same seed did not reproduce randomized inputs')
                    observed.append(bins)
                if ok and (not (d/'wave.vcd').is_file() or '$enddefinitions' not in (d/'wave.vcd').read_text()):raise ValueError('wave missing')
            except (OSError,ValueError,KeyError) as exc:ok=False;message=str(exc)
            record=dict(id=identity,success=ok,message=message,mutation=mutation,expected_failure=label,random_trace=trace,native_bins=bins,**ex)
            E.P.write_json(d/'result.json',record);executions.append(record);e.check(identity,ok,message)
        e.check(f'wait{wait}-native-bins',len(observed)==len(seeds)+1 and all(b.keys()==EXPECTED_BINS for b in observed),dict(bins=24,normal_runs=len(observed)))
    E.P.write_json(e.out/'executions.json',executions);return e.finish()

def main():
    p=E.parser(__doc__,'local-uvm-random');p.add_argument('--uvm-home',type=Path,required=True);p.add_argument('--solver',default='z3');p.add_argument('--verilator',default='verilator');p.add_argument('--build-timeout',type=float,default=300)
    args=p.parse_args();E.validate(p,args)
    import math
    if args.seed>2**31-4 or not math.isfinite(args.build_timeout) or args.build_timeout<=0:p.error('seed/build timeout out of range')
    try:return run(args)
    except (OSError,ValueError,KeyError,TypeError) as exc:print('RUNNER_ERROR',exc,file=sys.stderr);return 1
if __name__=='__main__':sys.exit(main())

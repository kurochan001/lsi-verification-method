#!/usr/bin/env python3
"""Reuse two passive IP environments beneath a native UVM hierarchical RAL map."""
from collections import Counter
import hashlib
import importlib.util
import math
from pathlib import Path
import re
import sys
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1]
def load(name,path):
    s=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
E=load('hierarchy_evidence',HERE.parent/'local-exploration-common/evidence.py')
BASE=HERE.parent/'local-uvm';HARNESS=HERE.parent/'local-uvm-random/sim_main.cpp'
SOURCES=[BASE/'tb/apb_if.sv',BASE/'tb/uvm_apb_pkg.sv',HERE/'tb/hierarchy_pkg.sv',HERE.parent/'local-apb/rtl/apb_regs.sv',HERE/'tb/top.sv']
GOALS={f'hierarchy/b{b}/{g}' for b in (0,1) for g in ('readback','pending','reset')}|{'hierarchy/unmapped'}
COVERS={'cp_leaf0','cp_leaf1','cp_reset'}

def native(path,log):
    counts={}
    for line in path.read_text().splitlines():
        if not line or line.startswith('#'):continue
        match=re.fullmatch(r"C '([^']*)' (\d+)",line)
        if not match:raise ValueError('malformed native coverage')
        meta=dict(p.split('\x02',1) for p in match[1].split('\x01') if p)
        if meta.get('t')!='user':continue
        label=meta.get('o')
        if label not in COVERS or label in counts or meta.get('h')!='TOP.top.'+label or Path(meta.get('f','')).resolve()!=(HERE/'tb/top.sv').resolve():raise ValueError('native cover source/inventory differs')
        counts[label]=int(match[2])
    logged=Counter(re.findall(r'^HIER_COVER (\w+)$',log,re.M))
    if counts.keys()!=COVERS or set(logged)!=COVERS or any(n<=0 or logged[k]!=n for k,n in counts.items()):raise ValueError('native cover hits/actions differ')
    return counts

def evaluate(case,execution,log):
    status,message=E.P.classify(case,execution,log)
    if status not in ('pass','detected'):return False,message
    if case['expected_failure']:return status=='detected',message
    n=case['iterations']
    if log.count(f'HIER_COMPLETE bank0={3*n+6} bank1={3*n+6}\n')!=1:return False,'leaf transaction counts differ'
    if log.count('HIER_OWNERSHIP active_drivers=1 passive_children=2\n')!=1:return False,'driver ownership differs'
    if log.count('Accellera:1800.2:UVM:2020.3.2')!=1:return False,'UVM version differs'
    if sorted(re.findall(r'^UVM_WARNING .*?\[([^]]+)\]',log,re.M))!=['NO_DPI_USED','NO_VISIT_CHECK']:return False,'unexpected warning'
    for severity,value in [('WARNING','2'),('ERROR','0'),('FATAL','0')]:
        if re.findall(r'^UVM_'+severity+r'\s*:\s*(\d+)\s*$',log,re.M)!=[value]:return False,'native UVM summary differs'
    if not GOALS<=set(re.findall(r'^COVER (\S+)$',log,re.M)):return False,'missing verified hierarchy goal'
    return True,'hierarchy comparisons and native UVM completed'

def run(args):
    seeds=list(range(args.seed,args.seed+(3 if args.profile=='nightly' else 1)));n=20 if args.profile=='nightly' else 4
    diags=[('checker-off','HIER_COUNTS',{'CHECKER_OFF':1}),('bad-map','HIER_MAP',{'BAD_MAP':1}),('sva-fault','HIER_STABILITY',{'SVA_FAULT':1})]
    ids=['build']+[f'layout{l}/seed{s}' for l in (0,1) for s in seeds]+[f'layout{l}/mutation{m}' for l in (0,1) for m in (1,2,3)]+[f'layout{l}/{d}' for l in (0,1) for d,_,_ in diags]+['coverage']
    e=E.Evidence('local-uvm-hierarchy',args,[Path(__file__),HARNESS,*SOURCES],dict(layouts=[0,1],seeds=seeds,iterations=n,goals=sorted(GOALS),sva_covers=sorted(COVERS)),ids)
    home=args.uvm_home.resolve()
    E.P.write_json(e.out/'uvm-source.json',dict(root=str(home),source_sha256={str(p.relative_to(home)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted((home/'src').rglob('*')) if p.is_file()}))
    E.P.write_json(e.out/'tools.json',dict(verilator=E.P.execute([args.verilator,'--version'],e.out/'verilator-version.log',args.timeout,e.out)))
    build=E.P.execute([args.verilator,'--cc','--exe','--build','--timing','--trace','--coverage-user','--assert','-Wno-fatal','-j',str(args.jobs),'--top-module','top','--Mdir',str(e.out/'build'),'-I'+str(home/'src'),'+define+UVM_NO_DPI',str(home/'src/uvm_pkg.sv'),*map(str,SOURCES),str(HARNESS)],e.out/'build.log',args.build_timeout,e.out)
    E.P.write_json(e.out/'build.json',build);built=not build['error'] and build['returncode']==0;e.check('build',built,build)
    records=[]
    def execute(identity,layout,seed,mutation=0,label=None,**flags):
        d=e.out/identity;d.mkdir(parents=True)
        case=dict(id=identity,iterations=n,checks=2*n+9,expected_failure=label)
        command=[str(e.out/'build/Vtop'),f'+LAYOUT={layout}',f'+MUTATION={mutation}',f'+SEED={seed}',f'+ITERATIONS={n}',f'+WAVE={d/"wave.vcd"}',f'+SVA_OFF={int(args.sva_off)}',*[f'+{k}={v}' for k,v in flags.items()]]
        if built:r=E.P.execute(command,d/'simulation.log',args.timeout,d)
        else:r=dict(error='build failed',returncode=None);(d/'simulation.log').write_text('build failed\n')
        log=(d/'simulation.log').read_text(errors='replace');ok,message=evaluate(case,r,log);counts={}
        try:
            if ok and label is None:counts=native(d/'coverage.dat',log)
            if ok and (not (d/'wave.vcd').is_file() or '$enddefinitions' not in (d/'wave.vcd').read_text()):raise ValueError('waveform missing')
        except (ValueError,OSError,KeyError) as exc:ok=False;message=str(exc)
        record=dict(case,layout=layout,seed=seed,mutation=mutation,success=ok,message=message,native=counts,execution=r)
        records.append(record);E.P.write_json(d/'result.json',record);e.check(identity,ok,record)
    for l in (0,1):
        for s in seeds:execute(f'layout{l}/seed{s}',l,s,args.demo_bug)
        for m,label in [(1,'UVM_CONFIG'),(2,'UVM_PENDING'),(3,'HIER_READ')]:execute(f'layout{l}/mutation{m}',l,seeds[0],m,label)
        for name,label,flags in diags:execute(f'layout{l}/{name}',l,seeds[0],label=label,**flags)
    normal=[r for r in records if r['expected_failure'] is None]
    e.check('coverage',len(normal)==2*len(seeds) and all(r['success'] and set(r['native'])==COVERS for r in normal),dict(goals=sorted(GOALS),normal_runs=len(normal)))
    E.P.write_json(e.out/'executions.json',records);return e.finish()

def main():
    p=E.parser(__doc__,'local-uvm-hierarchy');p.add_argument('--uvm-home',type=Path,required=True);p.add_argument('--verilator',default='verilator');p.add_argument('--jobs',type=int,default=2);p.add_argument('--build-timeout',type=float,default=600);p.add_argument('--demo-bug',type=int,choices=range(4),default=0);p.add_argument('--sva-off',action='store_true')
    a=p.parse_args();E.validate(p,a)
    if not (a.uvm_home/'src/uvm_pkg.sv').is_file() or not 1<=a.jobs<=32 or not math.isfinite(a.build_timeout) or a.build_timeout<=0 or a.seed>2**31-4:p.error('prepared UVM, valid seed and positive build limit/jobs required')
    try:return run(a)
    except (OSError,ValueError,KeyError,TypeError,RuntimeError) as exc:print('RUNNER_ERROR',exc,file=sys.stderr);return 1
if __name__=='__main__':sys.exit(main())

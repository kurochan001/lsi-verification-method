#!/usr/bin/env python3
"""Native SystemVerilog UVM agent, independent scoreboard and RAL frontdoor example."""
import hashlib
import importlib.util
from pathlib import Path
import re
import sys
HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('uvm_evidence',HERE.parent/'local-exploration-common/evidence.py');E=importlib.util.module_from_spec(spec);spec.loader.exec_module(E)
SOURCES=[HERE/'tb/apb_if.sv',HERE/'tb/uvm_apb_pkg.sv',HERE.parent/'gitlab-apb/rtl/apb_regs.sv',HERE/'tb/top.sv']
_,GOALS=E.C.catalog(HERE/'requirements.json')

def evaluate(case,execution,log):
    status,message=E.P.classify(case,execution,log)
    pairs=re.findall(r'^COUNT ([a-z_]+)=(\d+)$',log,re.M)
    if status=='pass':
        expected=dict(transactions=case['checks'],reads=6+case['iterations'],writes=4+case['iterations'],errors=2)
        if len(pairs)!=len(dict(pairs)) or {k:int(v) for k,v in pairs}!=expected:return False,'completion counts differ'
        if log.count('Accellera:1800.2:UVM:2020.3.2')!=1:return False,'unexpected UVM library version'
        warning_ids=re.findall(r'^UVM_WARNING .*?\[([^]]+)\]',log,re.M)
        if sorted(warning_ids)!=['NO_DPI_USED','NO_VISIT_CHECK']:return False,'unexpected/missing UVM warnings'
        if re.findall(r'^UVM_WARNING\s*:\s*(\d+)\s*$',log,re.M)!=['2']:return False,'warning summary differs'
        for severity in ('ERROR','FATAL'):
            if re.findall(r'^UVM_'+severity+r'\s*:\s*(\d+)\s*$',log,re.M)!=['0']:return False,'native UVM summary differs'
    return status in ('pass','detected'),message

def run(args):
    home=args.uvm_home.resolve();library=home/'src/uvm_pkg.sv'
    if not library.is_file():raise ValueError('--uvm-home must contain src/uvm_pkg.sv (UVM 2020-3.2)')
    n=8 if args.profile=='smoke' else 50;seeds=list(range(args.seed,args.seed+(1 if args.profile=='smoke' else 3)))
    checks=['uvm-build']+[f'wait{w}-{name}' for w in (0,2) for name in [*[f'random-seed{s}' for s in seeds],*[f'detect-mutation{m}' for m in (1,2,3)],'detect-bad-expectation','coverage']]
    e=E.Evidence('local-uvm',args,[Path(__file__),HERE/'setup_uvm.py',HERE/'requirements.json',*SOURCES],dict(waits=[0,2],seeds=seeds,iterations=n,goals=sorted(GOALS),mutants=[1,2,3],bad_expectation=True),checks)
    library_files=sorted(p for p in (home/'src').rglob('*') if p.is_file())
    E.P.write_json(e.out/'uvm-source.json',dict(root=str(home),source_sha256={str(p.relative_to(home)):hashlib.sha256(p.read_bytes()).hexdigest() for p in library_files}))
    E.P.write_json(e.out/'tools.json',dict(verilator=E.P.execute([args.verilator,'--version'],e.out/'verilator-version.log',args.timeout,e.out)))
    build_dir=e.out/'build'
    build=E.P.execute([args.verilator,'--binary','--timing','--trace','--assert','-Wno-fatal','-j',str(args.jobs),'--top-module','top','--Mdir',str(build_dir),'-I'+str(home/'src'),'-I'+str(HERE/'tb'),'+define+UVM_NO_DPI',str(library),*map(str,SOURCES)],e.out/'build.log',args.build_timeout,e.out)
    E.P.write_json(e.out/'build.json',build);build_ok=not build['error'] and build['returncode']==0 and (build_dir/'Vtop').is_file()
    e.check('uvm-build',build_ok,build['error'] or build['returncode']);cases=[]
    for wait in (0,2):
        config_hits=set()
        plans=[(f'random-seed{s}',s,n,0,0,None) for s in seeds]
        plans += [(f'detect-mutation{m}',args.seed,0,m,0,label) for m,label in ((1,'UVM_CONFIG'),(2,'UVM_PENDING'),(3,'UVM_CONFIG'))]
        plans += [('detect-bad-expectation',args.seed,0,0,1,'UVM_EXPECTATION')]
        for name,seed,iterations,mutation,bad,label in plans:
            identity=f'wait{wait}-{name}';d=e.out/identity;d.mkdir()
            case=dict(id=identity,wait=wait,seed=seed,iterations=iterations,mutation=mutation,bad_expectation=bad,checks=10+2*iterations,expected_failure=label)
            if build_ok:
                execution=E.P.execute([str(build_dir/'Vtop'),f'+WAIT_CYCLES={wait}',f'+MUTATION={mutation}',f'+BAD_EXPECTED={bad}',f'+ITERATIONS={iterations}',f'+SEED={seed}',f'+WAVE={d/"wave.vcd"}'],d/'simulation.log',args.timeout,d)
            else:
                execution=dict(error='UVM build failed',returncode=None,seconds=0);(d/'simulation.log').write_text('UVM build failed\n')
            log=(d/'simulation.log').read_text(errors='replace');ok,message=evaluate(case,execution,log)
            if ok and (not (d/'wave.vcd').exists() or '$enddefinitions' not in (d/'wave.vcd').read_text()):ok=False;message='wave missing'
            observed=sorted(set(re.findall(r'^COVER (\S+)$',log,re.M)))
            credited=observed if ok and label is None else []
            config_hits.update(credited)
            record=dict(case,success=ok,message=message,observed_coverage=observed,credited_coverage=credited,**execution)
            E.P.write_json(d/'result.json',record);cases.append(record);e.check(identity,ok,message)
        e.check(f'wait{wait}-coverage',GOALS<=config_hits,dict(required=sorted(GOALS),missing=sorted(GOALS-config_hits)))
    E.P.write_json(e.out/'executions.json',cases);return e.finish()

def main():
    p=E.parser(__doc__,'local-uvm');p.add_argument('--uvm-home',type=Path,required=True);p.add_argument('--verilator',default='verilator');p.add_argument('--jobs',type=int,default=4);p.add_argument('--build-timeout',type=float,default=300)
    args=p.parse_args();E.validate(p,args)
    import math
    if not 1<=args.jobs<=32 or not math.isfinite(args.build_timeout) or args.build_timeout<=0:p.error('invalid jobs or build timeout')
    try:return run(args)
    except (OSError,ValueError,RuntimeError,KeyError) as exc:print('RUNNER_ERROR',exc,file=sys.stderr);return 1
if __name__=='__main__':sys.exit(main())

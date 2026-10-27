#!/usr/bin/env python3
"""Generate APB RTL/RAL, connect actual UVM frontdoor and an independent scoreboard."""
import hashlib,importlib.util,json,re,sys
from pathlib import Path
HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('generated_front_evidence',HERE.parent/'local-exploration-common/evidence.py');E=importlib.util.module_from_spec(spec);spec.loader.exec_module(E)
BASE=HERE.parent/'local-uvm';RDL=HERE.parent/'local-register-spec'
GOALS={'reset/mirror','config/write','config/mirror','id/read','pending/event','pending/event-wins','pending/clear','access/error','reset/recovery'}
SOURCES=[BASE/'tb/apb_if.sv',BASE/'tb/uvm_apb_pkg.sv',HERE/'tb/front_pkg.sv',HERE/'tb/top.sv',HERE/'sim_main.cpp']
def native_counts(log,n):
    pairs=re.findall(r'^COUNT ([a-z_]+)=(\d+)$',log,re.M)
    if len(pairs)!=len(dict(pairs)) or {k:int(v) for k,v in pairs}!=dict(transactions=12+2*n,reads=8+n,writes=4+n,errors=2):return False
    if not GOALS<=set(re.findall(r'^COVER (\S+)$',log,re.M)):return False
    for severity,value in [('ERROR','0'),('FATAL','0'),('WARNING','5')]:
        if re.findall(r'^UVM_'+severity+r'\s*:\s*(\d+)\s*$',log,re.M)!=[value]:return False
    return sorted(re.findall(r'^UVM_WARNING .*?\[([^]]+)\]',log,re.M))==sorted(['NO_DPI_USED','NO_VISIT_CHECK']+['UVM/FLD/GET_MIRRORED_VAL/VOL']*3)
def run(args):
    n=12 if args.profile=='smoke' else 80;seeds=list(range(args.seed,args.seed+(1 if args.profile=='smoke' else 3)))
    names=['generate','independent-contract','build']+[f'wait{w}-{part}' for w in (0,2) for part in [*[f'seed{s}' for s in seeds],'mutation1','mutation2','mutation3','bad-mirror','coverage']]
    e=E.Evidence('local-generated-ral',args,[Path(__file__),*SOURCES,RDL/'generate.py',RDL/'registers.rdl',RDL/'contract.json',RDL/'tools-requirements.txt'],dict(seeds=seeds,iterations=n,goals=sorted(GOALS)),names)
    g=e.out/'generated';x=E.P.execute([args.rdl_python,str(RDL/'generate.py'),str(RDL/'registers.rdl'),'--out',str(g)],e.out/'generate.log',args.timeout,e.out);generated=not x['error'] and x['returncode']==0;e.check('generate',generated,x)
    if not generated:return e.finish()
    e.check('independent-contract',json.loads((g/'model.json').read_text())==json.loads((RDL/'contract.json').read_text()),'separate specification contract')
    home=args.uvm_home.resolve();E.P.write_json(e.out/'uvm-source.json',dict(root=str(home),sha256={str(p.relative_to(home)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted((home/'src').rglob('*')) if p.is_file()}))
    build=e.out/'build';x=E.P.execute([args.verilator,'--cc','--exe','--build','--timing','--trace','--assert','-Wno-fatal','-j','4','--top-module','top','--Mdir',str(build),'-I'+str(home/'src'),'+define+UVM_NO_DPI',str(home/'src/uvm_pkg.sv'),str(BASE/'tb/apb_if.sv'),str(BASE/'tb/uvm_apb_pkg.sv'),str(g/'rdl_regs.sv'),str(g/'rdl_pkg.sv'),str(HERE/'tb/front_pkg.sv'),str(HERE/'tb/top.sv'),str(HERE/'sim_main.cpp')],e.out/'build.log',args.build_timeout,e.out);built=not x['error'] and x['returncode']==0;e.check('build',built,x)
    for wait in (0,2):
        covered=[]
        plans=[(f'seed{s}',s,0,0,None) for s in seeds]+[(f'mutation{m}',args.seed,m,0,label) for m,label in [(1,'FRONT_STATE'),(2,'FRONT_STATE'),(3,'FRONT_PENDING')]]+[('bad-mirror',args.seed,0,1,'FRONT_REPORT')]
        for name,seed,mutation,bad,label in plans:
            d=e.out/f'wait{wait}-{name}';d.mkdir();logpath=d/'simulation.log'
            if built:x=E.P.execute([str(build/'Vtop'),f'+ITERATIONS={n}',f'+SEED={seed}',f'+WAIT_CYCLES={wait}',f'+MUTATION={mutation}',f'+BAD_MIRROR={bad}',f'+WAVE={d/"wave.vcd"}'],logpath,args.timeout,d)
            else:x=dict(error='build failed',returncode=None);logpath.write_text('build failed\n')
            log=logpath.read_text(errors='replace');status,message=E.P.classify(dict(checks=12+2*n,expected_failure=label),x,log);ok=status==('detected' if label else 'pass')
            if ok and not label:
                ok=native_counts(log,n);covered.append(ok)
                if not ok:message='native counts, coverage goals or UVM reports differ'
            if ok:ok=(d/'wave.vcd').is_file() and '$enddefinitions' in (d/'wave.vcd').read_text()
            E.P.write_json(d/'result.json',dict(success=ok,message=message,expected_failure=label,**x));e.check(f'wait{wait}-{name}',ok,message)
        e.check(f'wait{wait}-coverage',len(covered)==len(seeds) and all(covered),'each normal run reaches all nine goals')
    E.P.write_json(e.out/'generated-sha256.json',{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in g.iterdir() if p.is_file()})
    E.P.write_json(e.out/'tools.json',{name:E.P.execute(cmd,e.out/(name+'-version.log'),args.timeout,e.out) for name,cmd in [('verilator',[args.verilator,'--version']),('rdl',[args.rdl_python,'-m','pip','freeze'])]})
    return e.finish()
def main():
    p=E.parser(__doc__,'local-generated-ral');p.add_argument('--uvm-home',type=Path,required=True);p.add_argument('--rdl-python',default=sys.executable);p.add_argument('--verilator',default='verilator');p.add_argument('--build-timeout',type=float,default=300)
    a=p.parse_args();E.validate(p,a)
    import math
    if not math.isfinite(a.build_timeout) or a.build_timeout<=0 or a.seed>2**31-4:p.error('invalid build timeout/seed')
    try:return run(a)
    except (OSError,ValueError,TypeError,KeyError) as exc:print('RUNNER_ERROR',exc,file=sys.stderr);return 1
if __name__=='__main__':sys.exit(main())

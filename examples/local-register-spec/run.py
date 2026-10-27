#!/usr/bin/env python3
"""Compile SystemRDL and check generated RTL, C and native UVM RAL against a separate contract."""
import importlib.util
import json
from pathlib import Path
import random
import sys
HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('rdl_evidence',HERE.parent/'local-exploration-common/evidence.py');E=importlib.util.module_from_spec(spec);spec.loader.exec_module(E)
def operations(seed,n):
    fixed=[[0,0,0,0,0],[4,0,0,0,0],[0,1,0x12345678,0,0],[0,0,0,0,0],[8,1,3,3,3],[8,0,0,0,0],[8,1,15,0,0],[8,0,0,0,0],[4,1,1,0,0],[12,0,0,0,0]]
    rng=random.Random(seed);return fixed+[[rng.choice((0,4,8,12)),rng.randrange(2),rng.getrandbits(32),rng.randrange(16),rng.randrange(16)] for _ in range(n)]
def same_contract(model,contract):return sorted(model,key=lambda r:r['name'])==sorted(contract,key=lambda r:r['name'])
def run(args):
    n=24 if args.profile=='smoke' else 150;seeds=list(range(args.seed,args.seed+(1 if args.profile=='smoke' else 3)))
    names=['generate','independent-contract','reject-shared-spec-error','ral-build','header','bad-header','ral','bad-ral']+[f'wait{w}-{name}' for w in (0,2) for name in [*[f'random-seed{s}' for s in seeds],'mutation1','mutation2','mutation3']]
    e=E.Evidence('local-register-spec',args,[Path(__file__),HERE/'generate.py',HERE/'registers.rdl',HERE/'contract.json',HERE/'rtl_tb.sv',HERE/'ral_tb.sv',HERE/'check_header.c',HERE/'tools-requirements.txt'],dict(seeds=seeds,operations=n,views=['RTL','C','RAL']),names)
    generated=e.out/'generated';gen=E.P.execute([sys.executable,str(HERE/'generate.py'),str(HERE/'registers.rdl'),'--out',str(generated)],e.out/'generate.log',args.timeout,e.out)
    generated_ok=not gen['error'] and gen['returncode']==0;e.check('generate',generated_ok,gen)
    if not generated_ok:return e.finish()
    contract=json.loads((HERE/'contract.json').read_text());model=json.loads((generated/'model.json').read_text());e.check('independent-contract',same_contract(model,contract),model)
    # Change the source spec, regenerate ALL views, then reject their shared wrong reset.
    wrong=e.out/'wrong.rdl';wrong.write_text((HERE/'registers.rdl').read_text().replace("reset=8'h12","reset=8'h13"))
    bad=E.P.execute([sys.executable,str(HERE/'generate.py'),str(wrong),'--out',str(e.out/'wrong-generated')],e.out/'wrong-generate.log',args.timeout,e.out)
    e.check('reject-shared-spec-error',not bad['error'] and bad['returncode']==0 and not same_contract(json.loads((e.out/'wrong-generated/model.json').read_text()),contract),'separate handwritten contract rejects common source error')
    for corrupt in (0,1):
        name='bad-header' if corrupt else 'header';d=e.out/name;d.mkdir();binary=d/'check'
        b=E.P.execute([args.cc,'-std=c11','-Wall','-Wextra','-Werror','-I'+str(generated),*(['-DBAD_HEADER'] if corrupt else []),str(HERE/'check_header.c'),'-o',str(binary)],d/'build.log',args.timeout,d)
        x=E.P.execute([str(binary)],d/'simulation.log',args.timeout,d) if not b['error'] and b['returncode']==0 else dict(error='C build failed',returncode=None)
        log=(d/'simulation.log').read_text() if (d/'simulation.log').exists() else ''
        status,message=E.P.classify(dict(checks=1,expected_failure='RDL_HEADER' if corrupt else None),x,log)
        if status=='pass' and log.count('COUNT views=1\n')!=1:status='error';message='view count missing or duplicated'
        e.check(name,status==('detected' if corrupt else 'pass'),message)
    home=args.uvm_home.resolve();ral=e.out/'ral-build'
    import hashlib
    E.P.write_json(e.out/'uvm-source.json',dict(root=str(home),sha256={str(p.relative_to(home)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted((home/'src').rglob('*')) if p.is_file()}))
    b=E.P.execute([args.verilator,'--binary','--timing','-Wno-fatal','-j','4','--top-module','ral_tb','--Mdir',str(ral),'-I'+str(home/'src'),'+define+UVM_NO_DPI',str(home/'src/uvm_pkg.sv'),str(generated/'rdl_pkg.sv'),str(HERE/'ral_tb.sv')],e.out/'ral-build.log',args.build_timeout,e.out)
    e.check('ral-build',not b['error'] and b['returncode']==0,b)
    for corrupt in (0,1):
        name='bad-ral' if corrupt else 'ral';d=e.out/name;d.mkdir()
        x=E.P.execute([str(ral/'Vral_tb'),f'+BAD_RAL={corrupt}'],d/'simulation.log',args.timeout,d) if not b['error'] and b['returncode']==0 else dict(error='RAL build failed',returncode=None)
        log=(d/'simulation.log').read_text() if (d/'simulation.log').exists() else ''
        status,message=E.P.classify(dict(checks=1,expected_failure='RDL_RAL' if corrupt else None),x,log)
        if status=='pass' and log.count('COUNT views=1\n')!=1:status='error';message='view count missing or duplicated'
        e.check(name,status==('detected' if corrupt else 'pass'),message)
    for wait in (0,2):
        binaries={}
        for mutation in range(4):
            binary=e.out/f'wait{wait}-m{mutation}.vvp'
            b=E.P.execute([args.iverilog,'-g2012','-s','rtl_tb',f'-Prtl_tb.WAIT_CYCLES={wait}',f'-Prtl_tb.MUTATION={mutation}','-o',str(binary),str(generated/'rdl_regs.sv'),str(HERE/'rtl_tb.sv')],e.out/f'wait{wait}-m{mutation}-build.log',args.timeout,e.out);binaries[mutation]=(binary,b)
        for name,seed,mutation in [(f'random-seed{s}',s,0) for s in seeds]+[(f'mutation{m}',args.seed,m) for m in (1,2,3)]:
            identity=f'wait{wait}-{name}';d=e.out/identity;d.mkdir();rows=operations(seed,n if not mutation else 0)
            vectors=d/'vectors.txt';vectors.write_text(''.join(' '.join(format(v,'x') for v in r)+'\n' for r in rows));binary,b=binaries[mutation]
            x=E.P.execute([args.vvp,str(binary),'+VECTORS='+str(vectors),'+WAVE='+str(d/'wave.vcd')],d/'simulation.log',args.timeout,d) if not b['error'] and b['returncode']==0 else dict(error='RTL build failed',returncode=None)
            log=(d/'simulation.log').read_text() if (d/'simulation.log').exists() else '';status,message=E.P.classify(dict(checks=len(rows),expected_failure='RDL_READ' if mutation else None),x,log)
            if status=='pass' and re_counts(log)!=len(rows):status='error';message='operation counts differ'
            if status in ('pass','detected') and (not (d/'wave.vcd').exists() or '$enddefinitions' not in (d/'wave.vcd').read_text()):status='error';message='wave missing'
            e.check(identity,status==('detected' if mutation else 'pass'),message);E.P.write_json(d/'result.json',dict(status=status,message=message,**x))
    E.P.write_json(e.out/'tools.json',{k:E.P.execute(cmd,e.out/(k+'-version.log'),args.timeout,e.out) for k,cmd in [('compiler',[sys.executable,'-m','pip','freeze']),('verilator',[args.verilator,'--version']),('cc',[args.cc,'--version'])]})
    E.P.write_json(e.out/'generated-sha256.json',{p.name:__import__('hashlib').sha256(p.read_bytes()).hexdigest() for p in generated.iterdir() if p.is_file()})
    return e.finish()
def re_counts(log):
    import re
    pairs=re.findall(r'^COUNT operations=(\d+)$',log,re.M);return int(pairs[0]) if len(pairs)==1 else -1

def main():
    p=E.parser(__doc__,'local-register-spec');p.add_argument('--uvm-home',type=Path,required=True);p.add_argument('--verilator',default='verilator');p.add_argument('--cc',default='cc');p.add_argument('--build-timeout',type=float,default=300)
    args=p.parse_args();E.validate(p,args)
    import math
    if not math.isfinite(args.build_timeout) or args.build_timeout<=0:p.error('positive build timeout required')
    try:return run(args)
    except (OSError,ValueError,KeyError,TypeError) as exc:print('RUNNER_ERROR',exc,file=sys.stderr);return 1
if __name__=='__main__':sys.exit(main())

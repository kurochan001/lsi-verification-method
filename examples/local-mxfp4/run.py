#!/usr/bin/env python3
"""Pinned MXFP4 RTL: upstream regression plus an independent rational oracle."""
import argparse
from datetime import datetime, timezone
import importlib.util
import json
import math
from pathlib import Path
import re
import signal
import sys

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
UP=HERE/'upstream'
sys.path.insert(0,str(HERE))
from vectors import make_vectors, expected_counts

spec=importlib.util.spec_from_file_location('mxfp4_evidence',HERE.parent/'local-exploration-common/evidence.py')
E=importlib.util.module_from_spec(spec);spec.loader.exec_module(E)
CORE=['mxfp4_pkg','e2m1_decode','elem_mul','scale_add','reduce_tree','mxfp4_i2f',
      'mxfp4_fp32_add_core','mxfp4_lza','mxfp4_fp32_add_nearfar','mxfp4_bdp']
ENC=['mxfp4_pkg','e2m1_quantize','amax_tree32','quant_encoder']
ADD=['mxfp4_pkg','mxfp4_fp32_add_core']
NF=['mxfp4_pkg','mxfp4_fp32_add_core','mxfp4_lza','mxfp4_fp32_add_nearfar']
BENCHES={
    'add':('tb_fp32_add',ADD,[],[]),
    'bdp':('tb_mxfp4_bdp',CORE,[],['tb/mxfp4_bdp_sva.sv']),
    'encoder':('tb_quant_encoder',ENC,[],[]),
    'gemm':('tb_mxfp4_gemm_top',CORE+['gemm_ctrl_fsm','mxfp4_gemm_top'],['+define+MXFP4_ASSERT'],['tb/mxfp4_bdp_sva.sv']),
    'gemm-k1':('tb_mxfp4_gemm_top',CORE+['gemm_ctrl_fsm','mxfp4_gemm_top'],['+define+MXFP4_ASSERT','-GKBLK=1'],['tb/mxfp4_bdp_sva.sv']),
    'gemm-rect-k3':('tb_mxfp4_gemm_top',CORE+['gemm_ctrl_fsm','mxfp4_gemm_top'],['+define+MXFP4_ASSERT','-GROWS=2','-GCOLS=3','-GKBLK=3'],['tb/mxfp4_bdp_sva.sv']),
    'class':('tb_top',list(dict.fromkeys(CORE+ENC)),[],['tb/mxfp4_bdp_sva.sv']),
    'flow':('tb_bdp_flow',CORE+['mxfp4_fifo','mxfp4_bdp_fifo'],['+define+MXFP4_ASSERT'],['tb/mxfp4_bdp_sva.sv']),
    'scale34':('tb_quant_q34',ENC,[],[]),
    'gradual':('tb_gradual_uf',CORE,[],['tb/mxfp4_bdp_sva.sv']),
    'nearfar':('tb_nearfar',NF,[],[]),
    'bdp-nearfar':('tb_mxfp4_bdp',CORE,['-GUSE_NEARFAR=1'],['tb/mxfp4_bdp_sva.sv']),
}
WARN=['DECLFILENAME','PINCONNECTEMPTY','UNUSEDPARAM','UNUSEDSIGNAL','TIMESCALEMOD','SYNCASYNCNET','WIDTHTRUNC','WIDTHEXPAND']
MP_CHECKS=['mp-lint','mp-bdp','mp-encoder','mp-gemm','mp-gemm-k1','mp-gemm-rect-k3','mp-reject-oracle']
LOCAL_TOPS={'tb_multiprecision','tb_mp_encoder','tb_mp_gemm'}


def upstream_result(execution, log, top):
    summaries=re.findall(r'^ '+re.escape(top)+r' : (\d+) checks, (\d+) errors$',log,re.M)
    return (not execution['error'] and execution['returncode']==0 and len(summaries)==1
            and int(summaries[0][0])>0 and summaries[0][1]=='0'
            and log.count('*** PASS ***')==1 and not re.search(r'\[FAIL\]|\[ERROR\]|\[TIMEOUT\]|%Error|\*\*\* FAIL',log))


def scoped_requirements(catalog, selected):
    known=set(BENCHES)|set(MP_CHECKS)|{'rational-ftz','rational-nearfar','rational-gradual','rational-scale34'}
    seen=set();included=[];outside=[]
    if catalog.get('schema_version')!=1 or not catalog.get('requirements'):
        raise ValueError('invalid requirement catalogue')
    for item in catalog['requirements']:
        if item['id'] in seen or not item['checks'] or not set(item['checks'])<=known:
            raise ValueError('duplicate requirement or unknown/empty check family')
        seen.add(item['id'])
        if set(item['checks'])<=set(selected):included.append(item)
        else:outside.append(item['id'])
    if not included:raise ValueError('no requirements in selected stage')
    return included,outside


def compile_tb(args, out, name, top, modules, extra=(), auxiliary=()):
    obj=out/(name+'-build')
    warnings=WARN[:-2] if top in LOCAL_TOPS else WARN
    command=[args.verilator,'--binary','--timing','--assert','--trace','--timescale','1ns/1ps','-j',str(args.jobs),'-Wall',
             *['-Wno-'+w for w in warnings],*extra,'--top-module',top,'--Mdir',str(obj),'-o','simulation']
    command += [str(UP/'rtl'/(m+'.sv')) for m in modules]
    if top in LOCAL_TOPS:
        command += [str(HERE/'rtl'/(name+'.sv')) for name in ['mp_pkg','mp_add','mp_bdp','mp_encoder','mp_gemm']]
        command += [str(HERE/'tb'/(top+'.sv'))]
    elif top=='tb_rational':
        command += [str(HERE/'tb/tb_rational.sv')]
    else:
        command += [str(UP/'tb/mxfp4_ref_pkg.sv'),*[str(UP/p) for p in auxiliary],str(UP/'tb'/(top+'.sv'))]
    result=E.P.execute(command,out/(name+'-build.log'),args.build_timeout,out)
    return obj/'simulation',result


def run(args):
    rational_configs={'rational-ftz':(0,0,0),'rational-nearfar':(0,1,0),'rational-gradual':(1,0,0),'rational-scale34':(0,0,1)}
    core_ids=['lint',*BENCHES,*rational_configs,'reject-corrupt-oracle']
    check_ids=(core_ids if args.stage=='core' else MP_CHECKS if args.stage=='multiprecision' else core_ids+MP_CHECKS)+['requirements']
    inputs=[UP/'Makefile']+[p for p in HERE.rglob('*') if p.is_file() and p.suffix in ('.py','.sv','.svh','.json') and '__pycache__' not in p.parts]
    evidence=E.Evidence('local-mxfp4',args,inputs,dict(upstream=json.loads((HERE/'upstream.json').read_text())['commit'],stage=args.stage,benches=list(BENCHES),rational_configs=rational_configs),check_ids)
    executions={}
    tool=E.P.execute([args.verilator,'--version'],evidence.out/'verilator-version.log',args.timeout,evidence.out)
    E.P.write_json(evidence.out/'tools.json',{'verilator':tool})
    if args.stage!='multiprecision':
        lint=E.P.execute(['make','-C',str(UP),'lint','VERILATOR='+args.verilator],evidence.out/'lint.log',args.build_timeout,evidence.out)
        evidence.check('lint',not lint['error'] and lint['returncode']==0 and not tool['error'] and tool['returncode']==0,lint)
    sizes=(dict(N_ADD=2000,N_R1=256,N_R2A=32,N_R2E=8,N_R3=16,N_GEMM=8,N_SERIES=32,N_ENC=16,N_FLOW=100,N_Q34=64,N_GUF=500,N_NF=2000)
           if args.profile=='smoke' else dict(N_ADD=300000,N_R1=100000,N_R2A=20000,N_R2E=200,N_R3=20000,N_GEMM=500,N_SERIES=5000,N_ENC=1000,N_FLOW=1000,N_Q34=20000,N_GUF=50000,N_NF=200000))
    seed_args=['+verilator+seed+'+str(args.seed),*[f'+{k}={v}' for k,v in sizes.items()]]
    passed=set()
    for name,(top,modules,options,auxiliary) in (BENCHES if args.stage!='multiprecision' else {}).items():
        binary,build=compile_tb(args,evidence.out,name,top,modules,options,auxiliary)
        if build['error'] or build['returncode']!=0:
            evidence.check(name,False,{'build':build});continue
        execution=E.P.execute([str(binary),*seed_args],evidence.out/(name+'.log'),args.timeout,evidence.out)
        ok=upstream_result(execution,(evidence.out/(name+'.log')).read_text(),top)
        evidence.check(name,ok,execution);executions[name]=execution
        if ok: passed.add(name)
    rational_out={}
    for name,(gradual,nearfar,scale34) in (rational_configs if args.stage!='multiprecision' else {}).items():
        rows=make_vectors(args.seed,args.iterations,gradual,scale34)
        path=evidence.out/(name+'.txt');path.write_text(''.join(' '.join(format(x,'x') for x in row)+'\n' for row in rows))
        binary,build=compile_tb(args,evidence.out,name,'tb_rational',list(dict.fromkeys(CORE+ENC)),
                               [f'-GGRADUAL_UF={gradual}',f'-GUSE_NEARFAR={nearfar}',f'-GSCALE34={scale34}'])
        if build['error'] or build['returncode']!=0:
            evidence.check(name,False,{'build':build});continue
        command=[str(binary),'+VECTORS='+str(path),'+WAVE='+str(evidence.out/(name+'.vcd'))]
        execution=E.P.execute(command,evidence.out/(name+'.log'),args.timeout,evidence.out)
        log=(evidence.out/(name+'.log')).read_text()
        counts=expected_counts(rows)
        expected=f"RATIONAL PASS checks={counts['checks']} bdp={counts['bdp']} encoder={counts['encoder']}"
        ok=not execution['error'] and execution['returncode']==0 and log.count(expected)==1
        evidence.check(name,ok,dict(expected_counts=counts,execution=execution));executions[name]=execution
        if ok: passed.add(name)
        if name=='rational-ftz': rational_out=dict(rows=rows,binary=binary)
    if rational_out:
        rows=[list(r) for r in rational_out['rows']];rows[0][-1]^=1
        path=evidence.out/'corrupt-oracle.txt';path.write_text(''.join(' '.join(format(x,'x') for x in row)+'\n' for row in rows))
        execution=E.P.execute([str(rational_out['binary']),'+VECTORS='+str(path),'+WAVE='+str(evidence.out/'corrupt-oracle.vcd')],evidence.out/'corrupt-oracle.log',args.timeout,evidence.out)
        log=(evidence.out/'corrupt-oracle.log').read_text()
        evidence.check('reject-corrupt-oracle',not execution['error'] and execution['returncode']!=0 and 'BDP_DATA' in log,execution)
    if args.stage!='core':
        import multiprecision
        multiprecision.execute(sys.modules[__name__],evidence,args,passed,executions)
    requirements=json.loads((HERE/'requirements.json').read_text())
    included,outside=scoped_requirements(requirements,check_ids)
    coverage=[dict(item,passed=set(item['checks'])<=passed) for item in included]
    E.P.write_json(evidence.out/'coverage.json',{'requirements':coverage,'outside_selected_stage':outside,'note':'reviewed test families, not source or native covergroup coverage'})
    evidence.check('requirements',all(item['passed'] for item in coverage),coverage)
    E.P.write_json(evidence.out/'executions.json',executions)
    return evidence.finish()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--profile',choices=('smoke','nightly'),default='smoke')
    parser.add_argument('--stage',choices=('all','core','multiprecision'),default='all')
    parser.add_argument('--seed',type=int,default=17)
    parser.add_argument('--iterations',type=int)
    parser.add_argument('--verilator',default='verilator')
    parser.add_argument('--jobs',type=int,default=4)
    parser.add_argument('--timeout',type=float,default=120)
    parser.add_argument('--build-timeout',type=float,default=300)
    parser.add_argument('--out',type=Path,default=Path('artifacts')/datetime.now(timezone.utc).strftime('local-mxfp4-%Y%m%dT%H%M%S%fZ'))
    args=parser.parse_args()
    E.P.resolve_tools(args)
    if args.iterations is None: args.iterations=64 if args.profile=='smoke' else 1024
    if args.out.exists():parser.error('output already exists')
    if args.seed<0 or not 1<=args.iterations<=10000 or not 1<=args.jobs<=32 or any(not math.isfinite(v) or v<=0 for v in [args.timeout,args.build_timeout]):parser.error('invalid seed, iterations, jobs or timeout')
    previous=signal.signal(signal.SIGTERM,E.P.interrupted)
    try:return run(args)
    except E.P.RunInterrupted as exc:return 128+exc.signum
    except KeyboardInterrupt:return 130
    except (OSError,ValueError,KeyError) as exc:print('RUNNER_ERROR',exc,file=sys.stderr);return 1
    finally:signal.signal(signal.SIGTERM,previous)


if __name__=='__main__':sys.exit(main())

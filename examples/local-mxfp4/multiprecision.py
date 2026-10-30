"""Execution and evidence for the Appendix B implementation."""
import re
from pathlib import Path
from vectors_mp import bdp_vectors, encoder_vectors, gemm_vectors


def write_vectors(path, rows):
    path.write_text(''.join(' '.join(format(value,'x') for value in row)+'\n' for row in rows))


def bdp_counts(rows):
    mode=None;results=0;x0=0
    for row in rows:
        if row[1]:mode=row[0]
        if row[2]:
            results+=1;x0+=int(mode==2)
    # A stalled result is held on the cycle out_valid rises and for `stall` more cycles.
    held=sum(row[8]+1 for row in rows if row[2] and row[8])
    return dict(beats=len(rows),results=results,sums=sum(row[10] for row in rows),x0=x0,held=held)


def encoder_counts(rows):
    # Each output beat i is parked for stall+(i%2) cycles before it is consumed.
    return dict(vectors=len(rows),beats=sum(row[2] for row in rows),x0=sum(row[0]==2 for row in rows),
                held=sum(row[2]*row[4]+row[2]//2 for row in rows))


def execute(runner,evidence,args,passed,executions):
    out=evidence.out
    modules=list(dict.fromkeys(runner.CORE+runner.ENC+['gemm_ctrl_fsm','mxfp4_gemm_top']))
    sources=[str(runner.UP/'rtl'/(name+'.sv')) for name in modules]
    sources += [str(runner.HERE/'rtl'/(name+'.sv')) for name in ['mp_pkg','mp_add','mp_bdp','mp_encoder','mp_gemm']]
    lint_records=[]
    for top in ['mp_bdp','mp_encoder','mp_gemm']:
        command=[args.verilator,'--lint-only','--assert','-Wall',*['-Wno-'+w for w in runner.WARN[:-2]],'--top-module',top,*sources]
        lint_records.append(runner.E.P.execute(command,out/(top+'-lint.log'),args.build_timeout,out))
    evidence.check('mp-lint',all(not r['error'] and r['returncode']==0 for r in lint_records),lint_records)
    specs=[('mp-bdp','tb_multiprecision',{}),('mp-encoder','tb_mp_encoder',{}),
           ('mp-gemm','tb_mp_gemm',dict(ROWS=4,COLS=4,KBLK=4)),
           ('mp-gemm-k1','tb_mp_gemm',dict(ROWS=4,COLS=4,KBLK=1)),
           ('mp-gemm-rect-k3','tb_mp_gemm',dict(ROWS=2,COLS=3,KBLK=3))]
    bdp_binary=None;bdp_rows=None
    for name,top,config in specs:
        binary,build=runner.compile_tb(args,out,name,top,modules,[f'-G{k}={v}' for k,v in config.items()])
        if build['error'] or build['returncode']!=0:
            evidence.check(name,False,dict(build=build));continue
        if name=='mp-bdp':
            rows=bdp_vectors(args.seed,args.iterations,args.profile=='nightly')
            expected=bdp_counts(rows)
            pattern=r'^MP PASS beats=(\d+) results=(\d+) sums=(\d+) x0=(\d+) held=(\d+)$'
        elif name=='mp-encoder':
            rows=encoder_vectors(args.seed,min(args.iterations,128 if args.profile=='nightly' else 16),args.profile=='nightly')
            expected=encoder_counts(rows)
            pattern=r'^MP_ENCODER PASS vectors=(\d+) beats=(\d+) x0=(\d+) held=(\d+)$'
        else:
            rows=gemm_vectors(args.seed,min(args.iterations,32 if args.profile=='nightly' else 4),config['ROWS'],config['COLS'],config['KBLK'])
            # Every pre-done C hold check, final value, compatibility value,
            # reset-abort value and rejected-start value must be observed.
            comparisons=sum(1+config['KBLK']*{0:4,1:2,2:1}[row[1]]+(6 if row[1]==2 else 8)+(row[1]==2)
                            for row in rows if row[0] in (2,3))
            comparisons+=10*sum(row[0]==3 for row in rows)+sum(row[0]==4 for row in rows)
            expected=dict(runs=sum(row[0] in (2,3) for row in rows),checks=config['ROWS']*config['COLS']*comparisons,
                          x0=sum(row[0] in (2,3) and row[1]==2 for row in rows),aborted=sum(row[0]==3 for row in rows))
            pattern=r'^MP_GEMM PASS runs=(\d+) checks=(\d+) x0=(\d+) aborted=(\d+)$'
        path=out/(name+'.txt');write_vectors(path,rows)
        command=[str(binary),'+VECTORS='+str(path),'+WAVE='+str(out/(name+'.vcd'))]
        execution=runner.E.P.execute(command,out/(name+'.log'),args.timeout,out)
        log=(out/(name+'.log')).read_text()
        matches=re.findall(pattern,log,re.M)
        counts={}
        if len(matches)==1:
            counts=dict(zip(expected,map(int,matches[0])))
        ok=not execution['error'] and execution['returncode']==0 and all(counts.get(k)==v for k,v in expected.items()) and len(matches)==1
        evidence.check(name,ok,dict(expected_counts=expected,counts=counts,execution=execution))
        executions[name]=dict(execution,counts=counts)
        if ok:passed.add(name)
        if name=='mp-bdp':bdp_binary=binary;bdp_rows=rows
    if bdp_binary is not None:
        corrupt=[list(row) for row in bdp_rows[:1]];corrupt[0][5]^=1
        path=out/'mp-corrupt-oracle.txt';write_vectors(path,corrupt)
        result=runner.E.P.execute([str(bdp_binary),'+VECTORS='+str(path),'+WAVE='+str(out/'mp-corrupt-oracle.vcd')],out/'mp-corrupt-oracle.log',args.timeout,out)
        log=(out/'mp-corrupt-oracle.log').read_text()
        evidence.check('mp-reject-oracle',not result['error'] and result['returncode']!=0 and 'MP_RESULT' in log,result)

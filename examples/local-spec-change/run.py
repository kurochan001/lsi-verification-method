#!/usr/bin/env python3
"""Reverify an APB/IRQ priority specification change with identical saved stimuli."""
from collections import Counter
import copy
import importlib.util
import json
import math
from pathlib import Path
import re
import sys
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1]
def load(name,path):
    s=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
E=load('change_evidence',HERE.parent/'local-exploration-common/evidence.py')
A=load('change_apb',HERE.parent/'local-apb-irq/run.py');V=load('change_plan',ROOT/'tools/verification_plan.py')
REGS=HERE.parent/'local-apb/rtl/apb_regs.sv';RTL=HERE.parent/'local-apb-irq/rtl/apb_irq.sv';TB=HERE.parent/'local-apb-irq/tb/apb_irq_tb.sv'
RTL_OLD="pending <= (pending & ~(clear_pending ? pwdata[3:0] : 4'b0)) | events;"
RTL_NEW="pending <= (pending | events) & ~(clear_pending ? pwdata[3:0] : 4'b0);"
MODEL_OLD='          if (accepted && pwrite && paddr == 8 && pwdata[b]) model_pending[b] = 0;\n          if (events[b]) model_pending[b] = 1;'
MODEL_NEW='          if (events[b]) model_pending[b] = 1;\n          if (accepted && pwrite && paddr == 8 && pwdata[b]) model_pending[b] = 0;'
GOALS={f'cross/bit{b}/mask{m}/clear1/event1' for b in range(4) for m in (0,1)}
NATIVE_COVERS={f'cp_collision{b}' for b in range(4)}|{'cp_reset','cp_masked','cp_unmasked'}
HARNESS=HERE.parent/'local-uvm-random/sim_main.cpp'

def replace_once(text,before,after):
    if text.count(before)!=1:raise ValueError('upstream source changed; review the revision adapter')
    return text.replace(before,after)

def prepared(revision,old_checker=False):
    regs=REGS.read_text();tb=TB.read_text()
    if revision==2:regs=replace_once(regs,RTL_OLD,RTL_NEW)
    if revision==2 and not old_checker:tb=replace_once(tb,MODEL_OLD,MODEL_NEW)
    return regs,tb

def native_counts(path,log,regs_path):
    covers={};lines=[]
    for line in path.read_text().splitlines():
        if not line or line.startswith('#'):continue
        match=re.fullmatch(r"C '([^']*)' (\d+)",line)
        if not match:raise ValueError('malformed native coverage DB')
        meta=dict(p.split('\x02',1) for p in match[1].split('\x01') if p);count=int(match[2])
        if meta.get('t')=='user':
            label=meta.get('o')
            if label not in NATIVE_COVERS or label in covers or meta.get('h')!='TOP.apb_irq_tb.contract.'+label or Path(meta.get('f','')).resolve()!=(HERE/'capstone_checker.sv').resolve():raise ValueError('native SVA inventory differs')
            covers[label]=count
        if meta.get('t')=='line' and Path(meta.get('f','')).resolve()==regs_path.resolve():lines.append(dict(line=meta.get('l'),hits=count))
    logged=Counter(re.findall(r'^CAP_COVER (\w+)$',log,re.M))
    if covers.keys()!=NATIVE_COVERS or set(logged)-NATIVE_COVERS or any(logged[k]!=v for k,v in covers.items()):raise ValueError('native covers/actions differ')
    if not lines:raise ValueError('APB register RTL line coverage is missing')
    return dict(sva=covers,line=dict(total=len(lines),hit=sum(p['hits']>0 for p in lines),unhit=[p for p in lines if p['hits']==0]))

def run(a):
    seeds=list(range(a.seed,a.seed+(3 if a.profile=='nightly' else 1)));transactions=500 if a.profile=='nightly' else 50
    groups={}
    for w in (0,1,3):
        args=type('Options',(),dict(wait=w,profile=a.profile,seed=a.seed,transactions=transactions,demo_bug=0))()
        groups[w]=[c for c in A.make_plan(args) if c['category']=='functional']
    ids=[f'r{r}/wait{w}/build' for r in (1,2) for w in groups]+[f'r2/wait{w}/old-checker-build' for w in groups]
    ids += [f'r{r}/wait{w}/{c["id"]}' for r in (1,2) for w,cs in groups.items() for c in cs]+[f'r2/wait{w}/old-checker' for w in groups]+[f'native/r{r}/{c}' for r in (1,2) for c in ('build','normal','disabled','old-property')]+['traceability','stale-evidence']
    plan=json.loads((HERE/'plan.json').read_text())
    e=E.Evidence('local-spec-change',a,[HERE/'plan.json',HARNESS,*[ROOT/p for p in plan['sources']]],dict(revisions=[1,2],waits=list(groups),seeds=seeds,transactions=transactions,cases=groups),ids)
    artifacts={};results=[]
    def remember(path):artifacts[str(path)]=V.digest(path)
    for revision in (1,2):
        for wait,cases in groups.items():
            prefix=f'r{revision}/wait{wait}';d=e.out/prefix;d.mkdir(parents=True)
            regs,tb=prepared(revision);(d/'apb_regs.sv').write_text(regs);(d/'apb_irq_tb.sv').write_text(tb)
            for p in (d/'apb_regs.sv',d/'apb_irq_tb.sv'):remember(p)
            def build(name,tb_path,binary):
                execution=E.P.execute([a.iverilog,'-g2012','-s','apb_irq_tb',f'-Papb_irq_tb.WAIT_CYCLES={wait}','-o',str(binary),str(d/'apb_regs.sv'),str(RTL),str(tb_path)],d/(name+'.log'),a.timeout,e.out)
                ok=not execution['error'] and execution['returncode']==0;e.check(prefix+'/'+name,ok,execution);return ok
            built=build('build',d/'apb_irq_tb.sv',d/'normal.vvp');counts=Counter();comparisons=0;all_ok=True
            for case in cases:
                cd=d/case['id'];cd.mkdir();vp=cd/'vectors.txt';vp.write_text(''.join(f'{r} {s} {en} {wr} {addr:x} {value:x} {event:x}\n' for r,s,en,wr,addr,value,event in case['vectors']))
                if built:ex=E.P.execute([a.vvp,str(d/'normal.vvp'),f'+VECTORS={vp}',f'+WAVE={cd/"wave.vcd"}',f'+TRACE={cd/"trace.log"}'],cd/'simulation.log',a.timeout,cd)
                else:ex=dict(error='build failed',returncode=None);(cd/'simulation.log').write_text('build failed\n')
                log=(cd/'simulation.log').read_text(errors='replace');status,message=E.P.classify(case,ex,log);ok=status=='pass'
                trace=(cd/'trace.log').read_text() if (cd/'trace.log').is_file() else ''
                observed=[line for line in trace.splitlines() if line.startswith('OBS ')];checked=[line for line in trace.splitlines() if line.startswith('OK ')]
                ok &= len(observed)==len(checked)==case['checks'] and checked==[f'OK {i}' for i in range(1,case['checks']+1)]
                ok &= (cd/'wave.vcd').is_file() and '$enddefinitions' in (cd/'wave.vcd').read_text()
                record=dict(id=case['id'],success=bool(ok),checks=case['checks'],message=message,execution=ex);E.P.write_json(cd/'result.json',record)
                for p in (vp,cd/'simulation.log',cd/'result.json'):
                    remember(p)
                if (cd/'trace.log').is_file():remember(cd/'trace.log')
                e.check(prefix+'/'+case['id'],bool(ok),record);all_ok &= ok
                if ok:
                    comparisons+=case['checks'];counts.update(g for g in log.splitlines() if g.startswith('COVER '))
            results.append(dict(id=f'r{revision}-wait{wait}',configuration=f'wait{wait}',status='pass' if all_ok else 'fail',complete=bool(all_ok),comparisons=comparisons,checkers={'cycle-reference':comparisons},goals={g:counts['COVER '+g] for g in GOALS}))
            if revision==2:
                (d/'old_checker.sv').write_text(prepared(2,True)[1]);remember(d/'old_checker.sv')
                bad_built=build('old-checker-build',d/'old_checker.sv',d/'old.vvp')
                vp=d/cases[0]['id']/'vectors.txt'
                if bad_built:ex=E.P.execute([a.vvp,str(d/'old.vvp'),f'+VECTORS={vp}',f'+WAVE={d/"old.vcd"}'],d/'old-checker.log',a.timeout,d)
                else:ex=dict(error='build failed',returncode=None);(d/'old-checker.log').write_text('build failed\n')
                status,message=E.P.classify(dict(cases[0],expected_failure='APB_IRQ_PENDING'),ex,(d/'old-checker.log').read_text())
                e.check(prefix+'/old-checker',status=='detected',dict(execution=ex,message=message));remember(d/'old-checker.log')
    for revision in (1,2):
        d=e.out/f'native/r{revision}';d.mkdir(parents=True);regs,tb=prepared(revision)
        (d/'apb_regs.sv').write_text(regs)
        instance=f'capstone_checker #(.REVISION({revision})) contract(clk,rst_n,psel,penable,pwrite,pready,pslverr,paddr,pwdata,config_value,events,pending,irq);\n'
        # The native run uses REGISTER_MUTATION=0; Verilator rejects the legacy
        # defparam overriding an explicitly connected child parameter.
        tb=replace_once(tb,'  defparam dut.regs.MUTATION = REGISTER_MUTATION;','')
        (d/'native_tb.sv').write_text(replace_once(tb,'endmodule',instance+'endmodule'))
        rows=[row for c in groups[1] for row in c['vectors']]+[[1,0,0,0,0,0,0]]*2
        vectors=d/'vectors.txt';vectors.write_text(''.join(f'{r} {s} {en} {wr} {addr:x} {value:x} {event:x}\n' for r,s,en,wr,addr,value,event in rows))
        for p in (d/'apb_regs.sv',d/'native_tb.sv',vectors):remember(p)
        build=E.P.execute([a.verilator,'--cc','--exe','--build','--timing','--trace','--assert','--coverage-user','--coverage-line','-Wno-fatal','-j','2','--prefix','Vtop','--top-module','apb_irq_tb','-GWAIT_CYCLES=1','--Mdir',str(d/'build'),str(d/'apb_regs.sv'),str(RTL),str(HERE/'capstone_checker.sv'),str(d/'native_tb.sv'),str(HARNESS)],d/'build.log',a.build_timeout,d)
        built=not build['error'] and build['returncode']==0;e.check(f'native/r{revision}/build',built,build)
        for mode,flags,label in [('normal',[],None),('disabled',['+CAP_SVA_OFF=1'],None),('old-property',[f'+CAP_EXPECTED_REV={3-revision}'],'CAP_PRIORITY')]:
            cd=d/mode;cd.mkdir()
            if built:ex=E.P.execute([str(d/'build/Vtop'),f'+VECTORS={vectors}',f'+WAVE={cd/"wave.vcd"}',*flags],cd/'simulation.log',a.timeout,cd)
            else:ex=dict(error='build failed',returncode=None);(cd/'simulation.log').write_text('build failed\n')
            log=(cd/'simulation.log').read_text(errors='replace');status,message=E.P.classify(dict(checks=len(rows),expected_failure=label),ex,log);ok=status==('detected' if label else 'pass');measured={}
            try:
                if ok and not label:
                    measured=native_counts(cd/'coverage.dat',log,d/'apb_regs.sv')
                    ok &= all(v>0 for v in measured['sva'].values()) if mode=='normal' else all(v==0 for v in measured['sva'].values())
                    remember(cd/'coverage.dat')
                if ok:ok &= (cd/'wave.vcd').is_file() and '$enddefinitions' in (cd/'wave.vcd').read_text()
            except (OSError,ValueError,KeyError) as exc:ok=False;message=str(exc)
            E.P.write_json(cd/'result.json',dict(success=bool(ok),execution=ex,coverage=measured,message=message));remember(cd/'result.json');remember(cd/'simulation.log')
            e.check(f'native/r{revision}/{mode}',bool(ok),dict(execution=ex,coverage=measured,message=message))
    snapshot=json.loads((e.out/'manifest.json').read_text())['source_sha256']
    evidence=dict(schema_version=1,plan_id=plan['id'],plan_sha256=V.digest(HERE/'plan.json'),source_sha256={p:snapshot[p] for p in plan['sources']},artifacts=artifacts,results=results)
    E.P.write_json(e.out/'evidence.json',evidence)
    report=V.audit(plan,evidence,ROOT,V.digest(HERE/'plan.json'),e.out);V.write_report(e.out/'traceability',report)
    e.check('traceability',report['success'],report)
    old=copy.deepcopy(evidence);old['plan_sha256']='0'*64;rejected=V.audit(plan,old,ROOT,V.digest(HERE/'plan.json'),e.out)
    E.P.write_json(e.out/'stale-evidence.json',rejected);e.check('stale-evidence',not rejected['success'] and any('STALE_PLAN' in s for s in rejected['errors']),rejected)
    return e.finish()
def main():
    p=E.parser(__doc__,'local-spec-change');p.add_argument('--verilator',default='verilator');p.add_argument('--build-timeout',type=float,default=300);a=p.parse_args();E.validate(p,a)
    if a.seed>2**31-4 or not math.isfinite(a.build_timeout) or a.build_timeout<=0:p.error('valid seed and finite positive build timeout required')
    try:return run(a)
    except (OSError,ValueError,KeyError,TypeError) as exc:print('RUNNER_ERROR',exc,file=sys.stderr);return 1
if __name__=='__main__':sys.exit(main())

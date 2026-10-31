#!/usr/bin/env python3
"""Coordinate three native UVM agents and reconcile acceptance-time GAIN results."""
from collections import Counter
import hashlib
import importlib.util
import math
from pathlib import Path
import random
import re
import sys
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1]
def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
E=load('coord_evidence',HERE.parent/'local-exploration-common/evidence.py')
BASE=HERE.parent/'local-uvm';HARNESS=HERE.parent/'local-uvm-random/sim_main.cpp'
SOURCES=[BASE/'tb/apb_if.sv',HERE/'tb/stream_if.sv',BASE/'tb/uvm_apb_pkg.sv',HERE/'tb/coord_pkg.sv',HERE.parent/'local-apb/rtl/apb_regs.sv',HERE/'rtl/gain_pipe.sv',HERE/'tb/top.sv']
GAINS=('zero','one','multi','maximum');OPERANDS=('zero','one','wide_value')
BINS=({f'__vlAnonCG_measured.cp_gain.{g}' for g in GAINS}|{f'__vlAnonCG_measured.cp_operand.{x}' for x in OPERANDS}|
      {f'__vlAnonCG_measured.{p}.{b}' for p in ('cp_saturation','cp_overlap') for b in ('absent','present')}|
      {f'__vlAnonCG_measured.gain_operand.{g}_x_{x}' for g in GAINS for x in OPERANDS})
COVERS={'cp_overlap','cp_stall','cp_reset_pending','cp_reset_done'}


def model(rows):
    gain=0;pending=None;accepted=produced=cancelled=0;records=[]
    for edge,row in enumerate(rows,1):
        r,s,e,w,a,d,v,x,ready=row
        input_ready=int(pending is None or ready);out_valid=int(pending is not None);out_data=pending
        if not r:
            cancelled+=int(pending is not None);gain=0;pending=None
        else:
            if pending is not None and ready:produced+=1;pending=None
            if v and input_ready:pending=min(255,x*gain);accepted+=1
            if s and e and w and a==0:gain=d&255
        records.append([edge,input_ready,out_valid,out_data if out_valid else None,int(pending is not None),pending,gain])
    return records,dict(accepted=accepted,produced=produced,cancelled=cancelled,pending=int(pending is not None))


def vectors(seed,operations):
    rows=[]
    def add(r=1,s=0,e=0,w=0,a=0,d=0,v=0,x=0,ready=1):rows.append([r,s,e,w,a,d,v,x,ready])
    def write(gain):add(s=1,w=1,d=gain);add(s=1,e=1,w=1,d=gain);add()
    add(r=0);add(r=0);add()
    for gain in (0,1,3,255):
        write(gain)
        for x in (0,1,255):add(v=1,x=x);add()
    write(3);add(s=1,w=1,d=5);add(s=1,e=1,w=1,d=5,v=1,x=7);add(v=1,x=7);add()
    add(v=1,x=9,ready=0)
    for _ in range(3):add(v=1,x=4,ready=0)
    add(v=1,x=4);add();add(v=1,x=11,ready=0);add(r=0,ready=0);add(r=0);add()
    rng=random.Random(seed);held=None;pending=False
    def random_row(**bus):
        nonlocal held,pending
        r=bus.get('r',1);ready=int(rng.randrange(4)!=0);valid=int(rng.randrange(4)!=0);x=rng.randrange(256)
        if held is not None:valid=1;x=held
        if not r:valid=0
        can_accept=not pending or ready
        add(v=valid,x=x,ready=ready,**bus)
        held=x if r and valid and not can_accept else None
        pending=(bool(valid) if can_accept else pending) if r else False
    for _ in range(operations):
        choice=rng.randrange(12)
        if choice==0:random_row(r=0)
        elif choice<4:
            gain=rng.choice((0,1,3,255));random_row(s=1,w=1,d=gain);random_row(s=1,e=1,w=1,d=gain)
        else:random_row()
    if held is not None:add(v=1,x=held)
    add();add();add()
    return rows


def observed_trace(output,rows):
    lines=[line for line in output.splitlines() if line.startswith('COORD_SAMPLE')]
    records=[]
    for line in lines:
        m=re.fullmatch(r'COORD_SAMPLE (\d+) ([01]) ([01]) (\d+) ([01]) (\d+) (\d+)',line)
        if not m:raise ValueError('malformed/unknown observed cycle')
        record=list(map(int,m.groups()))
        if record[3]>255 or record[5]>255 or record[6]>255:raise ValueError('signal width exceeded')
        records.append(record)
    expected,counts=model(rows)
    if len(records)!=len(expected):raise ValueError('observed cycle count differs')
    for actual,reference in zip(records,expected):
        if any(want is not None and value!=want for value,want in zip(actual,reference)):
            raise ValueError(f'Python expectation differs at edge {reference[0]}: {actual} != {reference}')
    # Canonicalize invalid data; its value is not specified by the interface.
    normalized=[[v if expected[i][j] is not None else None for j,v in enumerate(row)] for i,row in enumerate(records)]
    marker=f"COORD_COMPLETE cycles={len(rows)} accepted={counts['accepted']} produced={counts['produced']} cancelled={counts['cancelled']} pending=0\n"
    if counts['pending'] or counts['accepted']!=counts['produced']+counts['cancelled'] or output.count(marker)!=1:raise ValueError('completion or cancellation accounting differs')
    return normalized,counts


def native(path,output):
    bins={};covers={}
    for line in path.read_text().splitlines():
        if not line or line.startswith('#'):continue
        m=re.fullmatch(r"C '([^']*)' (\d+)",line)
        if not m:raise ValueError('malformed native DB')
        meta=dict(p.split('\x02',1) for p in m[1].split('\x01') if p);count=int(m[2])
        if meta.get('t')=='covergroup':
            if Path(meta.get('f','')).resolve()!=(HERE/'tb/coord_pkg.sv').resolve() or meta['h'] in bins:raise ValueError('unexpected source/duplicate native bin')
            bins[meta['h']]=count
        elif meta.get('t')=='user':
            label=meta.get('o')
            if label not in COVERS or label in covers or meta.get('h')!='TOP.top.'+label or Path(meta.get('f','')).resolve()!=(HERE/'tb/top.sv').resolve():raise ValueError('unexpected native SVA counter')
            covers[label]=count
    logged=Counter(re.findall(r'^COORD_COVER (\w+)$',output,re.M))
    if bins.keys()!=BINS or any(n<=0 for n in bins.values()):raise ValueError('native functional bin inventory/hits differ')
    if covers.keys()!=COVERS or set(logged)-COVERS or any(n<=0 or logged[k]!=n for k,n in covers.items()):raise ValueError('native SVA covers and actions differ')
    return dict(bins=bins,sva=covers)


def normal_report(output):
    if output.count('Accellera:1800.2:UVM:2020.3.2')!=1 or output.count('COORD_OWNERSHIP config=1 data=1 ready=1\n')!=1:raise ValueError('UVM version/driver ownership differs')
    for severity,value in [('ERROR','0'),('FATAL','0'),('WARNING','2')]:
        if re.findall(r'^UVM_'+severity+r'\s*:\s*(\d+)\s*$',output,re.M)!=[value]:raise ValueError('UVM severity summary differs')
    if sorted(re.findall(r'^UVM_WARNING .*?\[([^]]+)\]',output,re.M))!=['NO_DPI_USED','NO_VISIT_CHECK']:raise ValueError('unexpected native UVM warning')


def run(args):
    seeds=list(range(args.seed,args.seed+(3 if args.profile=='nightly' else 1)));operations=2000 if args.profile=='nightly' else 200
    diagnostics=[('checker-off','COORD_COUNTS',dict(CHECKER_OFF=1)),('dropped-edge','COORD_COUNTS',dict(DROP_CFG=1)),
                 ('cover-off','COORD_COVERAGE',dict(COVER_OFF=1)),('sva-fault','COORD_STABILITY',dict(SVA_FAULT=1))]
    checks=['build']+[f'order{o}/seed{s}' for s in seeds for o in (0,1)]+[f'order-invariance/seed{s}' for s in seeds]+[f'order{o}/mutation{m}' for o in (0,1) for m in (1,2,3)]+[f'order{o}/{name}' for o in (0,1) for name,_,_ in diagnostics]+['coverage-inventory']
    plans={s:vectors(s,operations) for s in seeds}
    e=E.Evidence('local-uvm-coordination',args,[Path(__file__),HARNESS,*SOURCES],dict(seeds=seeds,operations=operations,vectors=plans,expected_bins=sorted(BINS),sva_covers=sorted(COVERS)),checks)
    home=args.uvm_home.resolve();E.P.write_json(e.out/'uvm-source.json',dict(root=str(home),source_sha256={str(p.relative_to(home)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted((home/'src').rglob('*')) if p.is_file()}))
    E.P.write_json(e.out/'tools.json',dict(verilator=E.P.execute([args.verilator,'--version'],e.out/'verilator-version.log',args.timeout,e.out)))
    build=E.P.execute([args.verilator,'--cc','--exe','--build','--timing','--trace','--coverage-user','--assert','-Wno-fatal','-j',str(args.jobs),'--top-module','top','--Mdir',str(e.out/'build'),'-I'+str(home/'src'),'+define+UVM_NO_DPI',str(home/'src/uvm_pkg.sv'),*map(str,SOURCES),str(HARNESS)],e.out/'build.log',args.build_timeout,e.out)
    e.check('build',not build['error'] and build['returncode']==0,build);E.P.write_json(e.out/'build.json',build)
    traces={};evidence=[]
    def execute(identity,order,rows,mutation=0,label=None,**flags):
        d=e.out/identity;d.mkdir(parents=True);file=d/'vectors.txt';file.write_text(''.join(f'{r} {s} {en} {w} {a:x} {value:x} {v} {x:x} {ready}\n' for r,s,en,w,a,value,v,x,ready in rows))
        command=[str(e.out/'build/Vtop'),f'+VECTORS={file}',f'+CHECKS={len(rows)}',f'+MONITOR_ORDER={order}',f'+MUTATION={mutation}',f'+SVA_OFF={int(args.sva_off)}',f'+WAVE={d/"wave.vcd"}',*[f'+{k}={v}' for k,v in flags.items()]]
        result=E.P.execute(command,d/'simulation.log',args.timeout,d);output=(d/'simulation.log').read_text(errors='replace')
        status,message=E.P.classify(dict(checks=len(rows),expected_failure=label),result,output);ok=status==('detected' if label else 'pass');trace=None;counts={};coverage={}
        try:
            if ok and not label:
                normal_report(output);trace,counts=observed_trace(output,rows);coverage=native(d/'coverage.dat',output)
                if not (d/'wave.vcd').is_file() or '$enddefinitions' not in (d/'wave.vcd').read_text():raise ValueError('waveform missing')
        except (ValueError,OSError,KeyError) as exc:ok=False;message=str(exc)
        record=dict(id=identity,success=ok,message=message,mutation=mutation,expected_failure=label,counts=counts,native=coverage,execution=result)
        E.P.write_json(d/'result.json',record)
        if trace is not None:E.P.write_json(d/'normalized-trace.json',trace)
        evidence.append(record);e.check(identity,ok,record);return trace if ok else None
    for seed,rows in plans.items():
        for order in (0,1):traces[seed,order]=execute(f'order{order}/seed{seed}',order,rows,args.demo_bug)
        e.check(f'order-invariance/seed{seed}',traces[seed,0] is not None and traces[seed,0]==traces[seed,1],dict(seed=seed,cycles=len(rows)))
    for order in (0,1):
        for mutation in (1,2,3):execute(f'order{order}/mutation{mutation}',order,plans[seeds[0]],mutation,'COORD_RESET' if mutation==3 else 'COORD_DATA')
        for name,label,flags in diagnostics:execute(f'order{order}/{name}',order,plans[seeds[0]],label=label,**flags)
    positives=[r for r in evidence if r['expected_failure'] is None]
    e.check('coverage-inventory',len(positives)==2*len(seeds) and all(r['success'] and set(r['native']['bins'])==BINS and set(r['native']['sva'])==COVERS for r in positives),dict(functional_bins=len(BINS),sva_covers=len(COVERS),normal_executions=len(positives)))
    E.P.write_json(e.out/'executions.json',evidence);return e.finish()


def main():
    p=E.parser(__doc__,'local-uvm-coordination');p.add_argument('--uvm-home',type=Path,required=True);p.add_argument('--verilator',default='verilator');p.add_argument('--build-timeout',type=float,default=600);p.add_argument('--jobs',type=int,default=2);p.add_argument('--demo-bug',type=int,choices=range(4),default=0);p.add_argument('--sva-off',action='store_true')
    a=p.parse_args();E.validate(p,a)
    if not (a.uvm_home/'src/uvm_pkg.sv').is_file() or a.jobs<=0 or not math.isfinite(a.build_timeout) or a.build_timeout<=0 or a.seed>2**31-4:p.error('prepared UVM library, positive build time/jobs and valid seed required')
    try:return run(a)
    except (OSError,ValueError,KeyError,TypeError) as exc:print('RUNNER_ERROR',exc,file=sys.stderr);return 1
if __name__=='__main__':sys.exit(main())

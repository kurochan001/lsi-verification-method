#!/usr/bin/env python3
"""Native UVM mailbox with independent clocks, resets and cancellation epochs."""
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
E=load('multiclock_evidence',HERE.parent/'local-exploration-common/evidence.py')
BASE=HERE.parent/'local-uvm';HARNESS=HERE.parent/'local-uvm-random/sim_main.cpp'
SOURCES=[BASE/'tb/apb_if.sv',BASE/'tb/uvm_apb_pkg.sv',HERE/'tb/mc_if.sv',HERE/'tb/mc_pkg.sv',HERE/'rtl/reset_mailbox.sv',HERE/'tb/top.sv']
COVERS={'cp_'+s for s in ('source','destination','stall','src_reset','dst_reset','both_reset','src_up','dst_up','recovery','release_wait')}
MUTANTS=((1,'MC_DATA'),(2,'MC_STALE'),(3,'MC_RELEASE'),(4,'MC_CHANNEL'),(5,'MC_CHANNEL'))
# The receiver's own release delay shows at the pins only when the source is much faster.
PAIRS=(0,1,2);FAST_SOURCE=2;RECEIVER_MUTANT=(6,'MC_CHANNEL')

def ledger(log,n):
    """Reconstruct the contract from raw monitor records and return the order the scoreboard actually used."""
    issued=[tuple(map(int,p)) for p in re.findall(r'^MC_ISSUED id=(\d+) data=(\d+)$',log,re.M)]
    if len(issued)!=sum(l.startswith('MC_ISSUED') for l in log.splitlines()) or [p[0] for p in issued]!=list(range(1,n+22)):raise ValueError('issued ID inventory differs')
    stimulus=dict(issued);events=[tuple(map(int,p)) for p in re.findall(r'^MC_OBS kind=(\d+) t=(\d+) id=(\d+) data=(\d+) mask=(\d+)$',log,re.M)]
    if len(events)!=sum(l.startswith('MC_OBS') for l in log.splitlines()) or any(not 0<=p[2]<65536 or not 0<=p[3]<256 or (p[0]!=2 and p[4]!=0) for p in events):raise ValueError('malformed monitor observation')
    if len(events)!=len(set((p[0],p[1]) for p in events)):raise ValueError('duplicate clock/reset observation')
    events.sort(key=lambda p:(p[1],{2:0,0:1,1:2}.get(p[0],3)))
    pending={};seen=set();epoch=accepted=produced=cancelled=0;last_mask=3;reset_masks=[]
    for kind,stamp,identity,data,mask in events:
        if kind==2:
            if mask not in range(4) or mask==last_mask:raise ValueError('invalid reset transition')
            if mask & ~last_mask:epoch+=1;cancelled+=len(pending);pending.clear()
            last_mask=mask;reset_masks.append(mask)
        elif kind==0:
            if last_mask or identity in seen or stimulus.get(identity)!=data:raise ValueError('invalid source acceptance')
            seen.add(identity);pending[identity]=(data^0x3c,epoch,stamp);accepted+=1
            if len(pending)>1:raise ValueError('more than one outstanding request')
        elif kind==1:
            if last_mask or identity not in pending:raise ValueError('unknown/cancelled response')
            expected,generation,when=pending.pop(identity)
            if data!=expected or generation!=epoch or stamp<=when:raise ValueError('response contract differs')
            produced+=1
        else:raise ValueError('unknown event kind')
        if accepted!=produced+cancelled+len(pending):raise ValueError('transaction ledger differs')
    if reset_masks!=[2,0,1,0,2,0,3,2,0,3,1,0,1,0,2,0]:raise ValueError('reset/release sequence differs')
    if (accepted,produced,cancelled,epoch,len(pending))!=(21+n,16+n,5,6,0) or seen!=set(stimulus):raise ValueError('incomplete transaction ledger')
    processed=[tuple(map(int,p)) for p in re.findall(r'^MC_PROCESS kind=(\d+) t=(\d+) id=(\d+) data=(\d+) mask=(\d+)$',log,re.M)]
    if len(processed)!=sum(l.startswith('MC_PROCESS') for l in log.splitlines()) or processed!=events:raise ValueError('scoreboard order differs from observation time order')
    arrivals=[tuple(map(int,p)) for p in re.findall(r'^MC_ARRIVE kind=(\d+) t=(\d+) at=(\d+)$',log,re.M)]
    if len(arrivals)!=sum(l.startswith('MC_ARRIVE') for l in log.splitlines()) or sorted(a[:2] for a in arrivals)!=sorted(e[:2] for e in events):raise ValueError('notification inventory differs')
    # Without these inversions the time ordering above would be tested by nothing.
    inverted={(a[0],b[0]) for a,b in zip(arrivals,arrivals[1:]) if b[1]<a[1]}
    if not {(2,0),(2,1)}<=inverted:raise ValueError('reset notification never overtook an earlier acceptance and completion')
    return processed

def native(path,log):
    counts={}
    for line in path.read_text().splitlines():
        if not line or line.startswith('#'):continue
        match=re.fullmatch(r"C '([^']*)' (\d+)",line)
        if not match:raise ValueError('malformed native coverage')
        meta=dict(p.split('\x02',1) for p in match[1].split('\x01') if p)
        if meta.get('t')!='user':continue
        label=meta.get('o')
        if label not in COVERS or label in counts or meta.get('h')!='TOP.top.'+label or Path(meta.get('f','')).resolve()!=(HERE/'tb/top.sv').resolve():raise ValueError('native cover inventory differs')
        counts[label]=int(match[2])
    logged=Counter(re.findall(r'^MC_COVER (\w+)$',log,re.M))
    if counts.keys()!=COVERS or set(logged)!=COVERS or any(v<=0 or logged[k]!=v for k,v in counts.items()):raise ValueError('cover hits/actions differ')
    return counts

def evaluate(case,execution,log):
    status,message=E.P.classify(case,execution,log)
    if case['expected_failure']:return status=='detected',message,[]
    if status!='pass':return False,message,[]
    n=case['iterations']
    if log.count(f'MC_COMPLETE accepted={21+n} produced={16+n} cancelled=5 epoch=6 pending=0\n')!=1:return False,'completion count differs',[]
    if log.count('MC_OWNERSHIP source=1 destination=1 resets=1\n')!=1 or log.count('Accellera:1800.2:UVM:2020.3.2')!=1:return False,'ownership/UVM version differs',[]
    if sorted(re.findall(r'^UVM_WARNING .*?\[([^]]+)\]',log,re.M))!=['NO_DPI_USED','NO_VISIT_CHECK']:return False,'unexpected warning',[]
    for severity,value in [('WARNING','2'),('ERROR','0'),('FATAL','0')]:
        if re.findall(r'^UVM_'+severity+r'\s*:\s*(\d+)\s*$',log,re.M)!=[value]:return False,'UVM summary differs',[]
    try:return True,'independent ledger and UVM completed',ledger(log,n)
    except ValueError as exc:return False,str(exc),[]

def run(args):
    seeds=list(range(args.seed,args.seed+(3 if args.profile=='nightly' else 1)));n=160 if args.profile=='nightly' else 40
    diags=[('source-off','MC_STALE',{'CHECKER_OFF':1}),('reset-off','MC_COUNTS',{'CHECKER_OFF':2}),('sva-fault','MC_DST_HOLD',{'SVA_FAULT':1}),
           ('arrival-order','MC_STALE',{'ARRIVAL_ORDER':1}),('arrival-order-acceptance','MC_COUNTS',{'ARRIVAL_ORDER':1,'GUIDED_SWAP':1})]
    ids=['build']+[f'pair{p}/order{o}/seed{s}' for p in PAIRS for o in (0,1) for s in seeds]+[f'pair{p}/seed{s}/order-invariance' for p in PAIRS for s in seeds]+[f'pair{p}/order{o}/mutation{m}' for p in PAIRS for o in (0,1) for m,_ in MUTANTS]+[f'pair{FAST_SOURCE}/order{o}/mutation{RECEIVER_MUTANT[0]}' for o in (0,1)]+[f'pair{p}/order{o}/{d}' for p in PAIRS for o in (0,1) for d,_,_ in diags]+['coverage']
    e=E.Evidence('local-uvm-multiclock',args,[Path(__file__),HARNESS,*SOURCES],dict(clock_pairs=list(PAIRS),monitor_orders=[0,1],seeds=seeds,iterations=n,sva_covers=sorted(COVERS)),ids)
    home=args.uvm_home.resolve()
    E.P.write_json(e.out/'uvm-source.json',dict(root=str(home),source_sha256={str(p.relative_to(home)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted((home/'src').rglob('*')) if p.is_file()}))
    E.P.write_json(e.out/'tools.json',dict(verilator=E.P.execute([args.verilator,'--version'],e.out/'verilator-version.log',args.timeout,e.out)))
    build=E.P.execute([args.verilator,'--cc','--exe','--build','--timing','--trace','--coverage-user','--assert','-Wno-fatal','-j',str(args.jobs),'--top-module','top','--Mdir',str(e.out/'build'),'-I'+str(home/'src'),'+define+UVM_NO_DPI',str(home/'src/uvm_pkg.sv'),*map(str,SOURCES),str(HARNESS)],e.out/'build.log',args.build_timeout,e.out)
    E.P.write_json(e.out/'build.json',build);built=not build['error'] and build['returncode']==0;e.check('build',built,build)
    records=[];traces={}
    def execute(identity,pair,order,seed,mutation=0,label=None,**flags):
        d=e.out/identity;d.mkdir(parents=True);case=dict(id=identity,iterations=n,checks=21+n,expected_failure=label)
        command=[str(e.out/'build/Vtop'),f'+CLOCK_PAIR={pair}',f'+MONITOR_ORDER={order}',f'+MUTATION={mutation}',f'+SEED={seed}',f'+ITERATIONS={n}',f'+WAVE={d/"wave.vcd"}',f'+SVA_OFF={int(args.sva_off)}',*[f'+{k}={v}' for k,v in flags.items()]]
        if built:r=E.P.execute(command,d/'simulation.log',args.timeout,d)
        else:r=dict(error='build failed',returncode=None);(d/'simulation.log').write_text('build failed\n')
        log=(d/'simulation.log').read_text(errors='replace');ok,message,events=evaluate(case,r,log);counts={}
        try:
            if ok and label is None:counts=native(d/'coverage.dat',log)
            if ok and (not (d/'wave.vcd').is_file() or '$enddefinitions' not in (d/'wave.vcd').read_text()):raise ValueError('waveform missing')
        except (OSError,ValueError,KeyError) as exc:ok=False;message=str(exc)
        record=dict(case,clock_pair=pair,monitor_order=order,seed=seed,mutation=mutation,success=ok,message=message,native=counts,execution=r)
        records.append(record);E.P.write_json(d/'result.json',record);e.check(identity,ok,record)
        if label is None:traces[pair,order,seed]=events if ok else None
    for p in PAIRS:
        for o in (0,1):
            for s in seeds:execute(f'pair{p}/order{o}/seed{s}',p,o,s,args.demo_bug)
            for m,label in MUTANTS+((RECEIVER_MUTANT,) if p==FAST_SOURCE else ()):execute(f'pair{p}/order{o}/mutation{m}',p,o,seeds[0],m,label)
            for name,label,flags in diags:execute(f'pair{p}/order{o}/{name}',p,o,seeds[0],label=label,**flags)
        for s in seeds:e.check(f'pair{p}/seed{s}/order-invariance',traces[p,0,s] is not None and traces[p,0,s]==traces[p,1,s],dict(clock_pair=p,seed=s))
    normal=[r for r in records if r['expected_failure'] is None]
    e.check('coverage',len(normal)==2*len(PAIRS)*len(seeds) and all(r['success'] and set(r['native'])==COVERS for r in normal),dict(normal_runs=len(normal),covers=sorted(COVERS)))
    E.P.write_json(e.out/'executions.json',records);return e.finish()

def main():
    p=E.parser(__doc__,'local-uvm-multiclock');p.add_argument('--uvm-home',type=Path,required=True);p.add_argument('--verilator',default='verilator');p.add_argument('--jobs',type=int,default=2);p.add_argument('--build-timeout',type=float,default=600);p.add_argument('--demo-bug',type=int,choices=range(6),default=0);p.add_argument('--sva-off',action='store_true')
    a=p.parse_args();E.validate(p,a)
    if not (a.uvm_home/'src/uvm_pkg.sv').is_file() or not 1<=a.jobs<=32 or not math.isfinite(a.build_timeout) or a.build_timeout<=0 or a.seed>2**31-4:p.error('prepared UVM, valid seed and positive build limit/jobs required')
    try:return run(a)
    except (OSError,ValueError,KeyError,TypeError,RuntimeError) as exc:print('RUNNER_ERROR',exc,file=sys.stderr);return 1
if __name__=='__main__':sys.exit(main())

#!/usr/bin/env python3
"""Native UVM tagged outstanding transactions, reordering, ID reuse and cancellation."""
from collections import Counter
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import re
import sys
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1]
spec=importlib.util.spec_from_file_location('outstanding_evidence',HERE.parent/'local-exploration-common/evidence.py');E=importlib.util.module_from_spec(spec);spec.loader.exec_module(E)
HARNESS=HERE.parent/'local-uvm-random/sim_main.cpp'
SOURCES=[HERE/'tb/oo_if.sv',HERE/'tb/oo_pkg.sv',HERE/'rtl/tagged_reorder.sv',HERE/'tb/top.sv']
COVERS={'cp_'+s for s in ('accept','response','stall','full','reuse','ooo','reset','recovery','busy','concurrent','stall_accept')}
MUTANTS={1:'OO_DATA',2:'OO_TOKEN',3:'OO_UNKNOWN',4:'OO_UNKNOWN',5:'OO_BUSY',6:'OO_TOKEN',7:'OO_LATENCY',8:'OO_HOLD'}
# Requests per round: full batch 4, while draining 6, latency probe 1, stalled pair and busy retry 3, same-edge pair 2.
PER_ROUND=16

def ledger(log,rounds,seed):
    issued=[tuple(map(int,p)) for p in re.findall(r'^OO_ISSUED id=(\d+) token=(\d+) data=(\d+)$',log,re.M)]
    total=PER_ROUND*rounds+4
    if len(issued)!=sum(l.startswith('OO_ISSUED') for l in log.splitlines()) or len(issued)!=total:raise ValueError('issued inventory differs')
    state=seed;planned={}
    for i,(identity,token,data) in enumerate(issued):
        state=(state*1664525+1013904223)&0xffffffff
        # The seed fixes the upper data bits; directed requests choose their own ID and delay bits.
        if identity not in range(4) or token!=i+1 or data>>3!=(state>>19)&31:raise ValueError('declared seed/issued fields differ')
        planned[token]=(identity,data)
    events=[]
    for kind,cycle,identity,token,data in re.findall(r'^OO_OBS kind=(\d+) cycle=(\d+) id=(\d+) token=(\d+) data=(\d+)$',log,re.M):events.append((int(cycle),int(kind)+1,int(identity),int(token),int(data)))
    resets=[(int(c),0,int(r),0,0) for c,r in re.findall(r'^OO_RESET cycle=(\d+) rst=(\d+)$',log,re.M)];events+=resets
    if len(events)!=sum(l.startswith(('OO_OBS','OO_RESET')) for l in log.splitlines()) or len({e[:2] for e in events})!=len(events):raise ValueError('malformed/duplicate observations')
    events.sort();pending={};seen_tokens=set();seen_ids=set();accepted=produced=cancelled=epoch=peak=overtakes=reused=draining=tight=delay_overtakes=0;reset=0;reset_values=[]
    accept_cycles=set();complete_cycles=set();period_accepts=[];period_replies=[];full=False;batch_orders=set();reply_orders=set()
    for cycle,kind,identity,token,data in events:
        if kind==0:
            if identity not in (0,1) or reset==identity:raise ValueError('invalid reset transition')
            reset=identity;reset_values.append(reset)
            if not reset:epoch+=1;cancelled+=len(pending);pending.clear();period_accepts=[];period_replies=[];full=False
        elif kind==1:
            if not reset or identity not in range(4) or identity in pending or token in seen_tokens or planned.get(token)!=(identity,data):raise ValueError('invalid acceptance/ID reuse')
            reused+=int(identity in seen_ids);seen_ids.add(identity);seen_tokens.add(token);accept_cycles.add(cycle)
            if pending and period_replies:draining+=1
            if not pending:period_accepts=[];period_replies=[];full=False
            pending[identity]=dict(token=token,value=(3*data+identity)%256,delay=data&7,epoch=epoch,cycle=cycle,ordinal=accepted);accepted+=1;peak=max(peak,len(pending));period_accepts.append(identity)
            if len(pending)==4 and not period_replies:full=True
            if peak>4:raise ValueError('outstanding limit exceeded')
        elif kind==2:
            if not reset or identity not in pending:raise ValueError('unknown, duplicate or cancelled completion')
            expected=pending[identity];latency=cycle-expected['cycle'];complete_cycles.add(cycle)
            if token!=expected['token'] or data!=expected['value'] or epoch!=expected['epoch'] or latency<expected['delay']+2:raise ValueError('completion transaction/value differs')
            tight+=int(expected['delay']>0 and latency==expected['delay']+2)
            overtaking=expected['ordinal']!=min(p['ordinal'] for p in pending.values());overtakes+=int(overtaking);delay_overtakes+=int(overtaking and not full)
            pending.pop(identity);produced+=1;period_replies.append(identity)
            if not pending and full:batch_orders.add(tuple(period_accepts));reply_orders.add(tuple(period_replies))
        else:raise ValueError('unknown observation kind')
        if accepted!=produced+cancelled+len(pending):raise ValueError('transaction ledger differs')
    summary=dict(accepted=accepted,produced=produced,cancelled=cancelled,epoch=epoch,peak=peak,overtakes=overtakes,reused=reused,pending=len(pending))
    result=dict(summary,draining=draining,concurrent=len(accept_cycles&complete_cycles),tight_latency=tight,delay_overtakes=delay_overtakes,batch_orders=len(batch_orders),reply_orders=len(reply_orders))
    orders=min(rounds,4)
    if reset_values!=[1,0,1] or (accepted,produced,cancelled,epoch,peak,reused,len(pending))!=(total,PER_ROUND*rounds,4,1,4,PER_ROUND*rounds,0) or overtakes<3*rounds or seen_tokens!=planned.keys():raise ValueError('incomplete transaction/reordering goals')
    if draining<rounds or result['concurrent']<rounds or tight<rounds or delay_overtakes<rounds or len(batch_orders)<orders or len(reply_orders)<orders:raise ValueError('incomplete ID-order, draining, same-edge or latency goals')
    expected_line='OO_COMPLETE '+' '.join(k+'='+str(summary[k]) for k in summary)
    if log.count(expected_line+'\n')!=1:raise ValueError('UVM and independent ledger differ')
    return result

def native(path,log,counts,rounds):
    observed={}
    for line in path.read_text().splitlines():
        if not line or line.startswith('#'):continue
        m=re.fullmatch(r"C '([^']*)' (\d+)",line)
        if not m:raise ValueError('malformed native coverage')
        meta=dict(p.split('\x02',1) for p in m[1].split('\x01') if p)
        if meta.get('t')!='user':continue
        name=meta.get('o')
        if name not in COVERS or name in observed or meta.get('h')!='TOP.top.'+name or Path(meta.get('f','')).resolve()!=(HERE/'tb/top.sv').resolve():raise ValueError('native cover identity differs')
        observed[name]=int(m[2])
    logged=Counter(re.findall(r'^OO_COVER (\w+)$',log,re.M))
    if observed.keys()!=COVERS or logged.keys()!=COVERS or any(n<=0 or logged[k]!=n for k,n in observed.items()):raise ValueError('SVA covers missing or action/DB counts differ')
    exact=dict(cp_accept=counts['accepted'],cp_response=counts['produced'],cp_reuse=counts['reused'],cp_ooo=counts['overtakes'],cp_reset=1,cp_recovery=PER_ROUND*(rounds-rounds//2),cp_concurrent=counts['concurrent'])
    if any(observed[k]!=v for k,v in exact.items()):raise ValueError('native covers and independent observations differ')
    return observed

def evaluate(case,execution,log):
    status,message=E.P.classify(case,execution,log)
    if case['expected_failure']:return status=='detected',message,{}
    if status!='pass':return False,message,{}
    if log.count('Accellera:1800.2:UVM:2020.3.2')!=1:return False,'unexpected UVM library',{}
    if sorted(re.findall(r'^UVM_WARNING .*?\[([^]]+)\]',log,re.M))!=['NO_DPI_USED','NO_VISIT_CHECK']:return False,'unexpected warnings',{}
    for name,value in [('WARNING','2'),('ERROR','0'),('FATAL','0')]:
        if re.findall(r'^UVM_'+name+r'\s*:\s*(\d+)\s*$',log,re.M)!=[value]:return False,'UVM summary differs',{}
    try:return True,'independent transaction ledger completed',ledger(log,case['rounds'],case['seed'])
    except ValueError as exc:return False,str(exc),{}

def run(a):
    rounds=12 if a.profile=='nightly' else 4;seeds=list(range(a.seed,a.seed+(3 if a.profile=='nightly' else 1)))
    checks=['build',*['seed'+str(s) for s in seeds],*['mutation'+str(m) for m in MUTANTS],'source-monitor-off','scoreboard-off','coverage','source-freshness']
    e=E.Evidence('local-uvm-outstanding',a,[Path(__file__),HARNESS,*SOURCES],dict(slots=4,id_bits=2,token_bits=16,rounds=rounds,seeds=seeds,native_covers=sorted(COVERS)),checks)
    home=a.uvm_home.resolve();E.P.write_json(e.out/'uvm-source.json',dict(root=str(home),source_sha256={str(p.relative_to(home)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted((home/'src').rglob('*')) if p.is_file()}))
    version=E.P.execute([a.verilator,'--version'],e.out/'verilator-version.log',a.timeout,e.out);E.P.write_json(e.out/'tools.json',dict(verilator=version))
    command=[a.verilator,'--cc','--exe','--build','--timing','--trace','--coverage-user','--assert','-Wno-fatal','-j',str(a.jobs),'--top-module','top','--Mdir',str(e.out/'build'),'-I'+str(home/'src'),'+define+UVM_NO_DPI',str(home/'src/uvm_pkg.sv'),*map(str,SOURCES),str(HARNESS)]
    build=E.P.execute(command,e.out/'build.log',a.build_timeout,e.out);built=not build['error'] and build['returncode']==0 and not version['error'] and version['returncode']==0;e.check('build',built,build)
    records=[]
    def execute(name,seed,mutation=0,label=None,off=0):
        d=e.out/name;d.mkdir();case=dict(id=name,checks=PER_ROUND*rounds+4,rounds=rounds,seed=seed,expected_failure=label)
        cmd=[str(e.out/'build/Vtop'),f'+SEED={seed}',f'+ROUNDS={rounds}',f'+MUTATION={mutation}',f'+CHECKER_OFF={off}',f'+SVA_OFF={int(a.sva_off)}','+WAVE='+str(d/'trace.vcd')]
        if built:r=E.P.execute(cmd,d/'simulation.log',a.timeout,d)
        else:r=dict(error='build failed',returncode=None);(d/'simulation.log').write_text('build failed\n')
        log=(d/'simulation.log').read_text(errors='replace');ok,message,counts=evaluate(case,r,log);covers={}
        try:
            if ok and label is None:covers=native(d/'coverage.dat',log,counts,rounds)
            if ok and (not (d/'trace.vcd').is_file() or '$enddefinitions' not in (d/'trace.vcd').read_text()):raise ValueError('waveform missing')
        except (OSError,ValueError,KeyError) as exc:ok=False;message=str(exc)
        record=dict(case,mutation=mutation,success=ok,message=message,ledger=counts,native=covers,execution=r);records.append(record);E.P.write_json(d/'result.json',record);e.check(name,ok,record)
    for seed in seeds:execute('seed'+str(seed),seed,a.demo_bug)
    for mutation,label in MUTANTS.items():execute('mutation'+str(mutation),seeds[0],mutation,label)
    execute('source-monitor-off',seeds[0],label='OO_UNKNOWN',off=1);execute('scoreboard-off',seeds[0],label='OO_COUNTS',off=2)
    normal=[r for r in records if r['expected_failure'] is None];e.check('coverage',len(normal)==len(seeds) and all(r['success'] and r['native'].keys()==COVERS for r in normal),dict(runs=len(normal),covers=sorted(COVERS)))
    E.P.write_json(e.out/'executions.json',records)
    changed=[n for n,h in json.loads((e.out/'manifest.json').read_text())['source_sha256'].items() if not (ROOT/n).is_file() or hashlib.sha256((ROOT/n).read_bytes()).hexdigest()!=h]
    e.check('source-freshness',not changed,changed);return e.finish()

def main():
    p=E.parser(__doc__,'local-uvm-outstanding');p.add_argument('--uvm-home',type=Path,required=True);p.add_argument('--verilator',default='verilator');p.add_argument('--jobs',type=int,default=2);p.add_argument('--build-timeout',type=float,default=600);p.add_argument('--demo-bug',type=int,choices=range(9),default=0);p.add_argument('--sva-off',action='store_true')
    a=p.parse_args();E.validate(p,a)
    if not (a.uvm_home/'src/uvm_pkg.sv').is_file() or not 1<=a.jobs<=8 or not math.isfinite(a.build_timeout) or a.build_timeout<=0 or a.seed>2**31-4:p.error('prepared UVM, valid jobs/seed and finite build limit required')
    try:return run(a)
    except (OSError,ValueError,KeyError,TypeError,RuntimeError) as exc:print('UVM_OUTSTANDING_ERROR',exc,file=sys.stderr);return 1
if __name__=='__main__':sys.exit(main())

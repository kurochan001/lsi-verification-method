#!/usr/bin/env python3
"""Layer packet sequences over a bus sequencer and check lock, grab and priority with native UVM."""
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import random
import re
import sys
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1]
def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
E=load('layering_evidence',HERE.parent/'local-exploration-common/evidence.py')
HARNESS=HERE.parent/'local-uvm-random/sim_main.cpp';REQUIREMENTS=HERE/'requirements.json'
SOURCES=[HERE/'tb/layer_if.sv',HERE/'tb/layer_pkg.sv',HERE/'rtl/frame_port.sv',HERE/'tb/top.sv']
CTRL,DATA,INDEX,VALUE,STATUS,ENABLE=range(6)
FRAME,STATS,HOLD,LATE,ISR,SETUP=range(6)
BACKLOG,HAZARD,CONTEND,W1C_LATE,W1C_SAME,MIX=range(1,7)
LATENCY_BOUND=5
GOALS=('cycle_model','both_ports','mixed_traffic','backlog_priority','lock_delays_isr','gap_protected','isr_inside_frame',
       'grab_overtakes_lock','alarm_serviced','done_serviced','w1c_late','w1c_same')
MUTANTS={1:'LAYER_DATA',2:'LAYER_IRQ',3:'LAYER_VALUE',4:'LAYER_IRQ'}
DIAGNOSTICS=(('lock-off','LAYER_ATOMIC','LOCK_OFF'),('isr-uses-lock','LAYER_LATENCY','ISR_LOCK'),
             ('fifo-arbitration','LAYER_PRIORITY','ARB_FIFO'),('no-layering','LAYER_FRAME','FLAT'))


def plan(seed,mixes):
    """Packets per port and the ordered steps; every packet is used by exactly one step."""
    rng=random.Random(seed);packets={0:[],1:[]};steps=[]
    def packet(port,gap=0,payload=None):
        payload=payload if payload is not None else [rng.randrange(256) for _ in range(rng.randint(1,4))]
        packets[port].append(dict(port=port,seq=len(packets[port])%128,payload=payload,gap=gap))
    def step(kind,*fields):steps.append([kind,*fields]+[0]*(8-len(fields)))
    for payload in ([0x11,0x22],[0x33],[0x44,0x55,0x66]):packet(1,payload=payload)
    for payload in ([0x77],[0x88,0x99,0xaa,0xbb],[0xcc,0xdd]):packet(0,payload=payload)
    step(BACKLOG,3,3);step(HAZARD,2,6);step(CONTEND)
    packet(0,payload=[0x5a,0xa5]);step(W1C_LATE)
    step(W1C_SAME)
    for _ in range(mixes):
        urgent,bulk=rng.randint(1,4),rng.randint(1,4)
        for _ in range(urgent):packet(1,gap=rng.randrange(7))
        for _ in range(bulk):packet(0,gap=rng.randrange(7))
        step(MIX,urgent,bulk,rng.randint(1,4),rng.randint(1,3),rng.randrange(100))
    urgent,bulk=rng.randint(1,3),rng.randint(1,3)
    for _ in range(urgent):packet(1)
    for _ in range(bulk):packet(0)
    step(BACKLOG,urgent,bulk)
    return dict(packets=packets,steps=steps)


def plan_text(p):
    rows=[[0,x['port'],x['seq'],len(x['payload']),*(x['payload']+[0]*4)[:4],x['gap']] for port in (0,1) for x in p['packets'][port]]
    return ''.join(' '.join(map(str,row))+'\n' for row in rows+p['steps'])


def expected_frames(p):
    """Frames each step must deliver: (kind, urgent list, bulk list); a frame is the head byte followed by the payload."""
    queues={port:[[(port<<7)|x['seq'],*x['payload']] for x in p['packets'][port]] for port in (0,1)};result=[]
    for row in p['steps']:
        urgent,bulk={BACKLOG:(row[1],row[2]),MIX:(row[1],row[2]),W1C_LATE:(0,1)}.get(row[0],(0,0))
        result.append((row[0],[queues[1].pop(0) for _ in range(urgent)],[queues[0].pop(0) for _ in range(bulk)]))
    if queues[0] or queues[1]:raise ValueError('plan leaves packets unused')
    return result


class Port:
    """Cycle model of the register port, written from the README and not from the RTL."""
    def __init__(self):self.reset()
    def reset(self):
        self.ack=self.rdata=self.valid=self.out_head=self.out_len=self.out_sum=0
        self.in_frame=self.count=self.sum=self.head=self.index=0;self.table=[0,0,0,0];self.status=self.enable=0
    def outputs(self):return [self.ack,self.rdata,int(bool(self.status&self.enable)),self.valid,self.out_head,self.out_len,self.out_sum]
    def edge(self,rst,req,write,addr,wdata,alarm):
        if not rst:self.reset();return
        reads=[self.in_frame,self.count,self.index,self.table[self.index],self.status,self.enable,0,0]
        self.ack=req;self.rdata=reads[addr] if req and not write else 0;self.valid=0
        events=2 if alarm else 0;cleared=0
        if req and write:
            if addr==CTRL and wdata&1:
                if self.in_frame:events|=4
                self.in_frame=1;self.count=self.sum=0
            elif addr==CTRL and wdata&2:
                if self.in_frame:
                    self.in_frame=0;self.table[0]=self.out_len=self.count;self.table[1]=self.out_sum=self.sum;self.out_head=self.head
                    self.table[2]=(self.table[2]+1)&255;self.valid=1;events|=1
                else:events|=4
            elif addr==DATA:
                if self.in_frame:
                    if self.count==0:self.head=wdata
                    self.count=(self.count+1)&255;self.sum=(self.sum+wdata)&255
                else:events|=4
            elif addr==INDEX:self.index=wdata&3
            elif addr==STATUS:cleared=wdata&7
            elif addr==ENABLE:self.enable=wdata&7
        if events&4:self.table[3]=(self.table[3]+1)&255
        self.status=(self.status&~cleared)|events


def parse(output):
    """Samples, transfers and step markers in log order."""
    events=[];samples=[];transfers=[]
    for line in output.splitlines():
        if line.startswith('LAYER_SAMPLE'):
            m=re.fullmatch(r'LAYER_SAMPLE'+r' (\d+)'*14,line)
            if not m:raise ValueError('malformed or unknown sample')
            row=list(map(int,m.groups()))
            if row[0]!=len(samples)+1:raise ValueError('sample numbering differs')
            samples.append(row);events.append(('sample',len(samples)-1))
        elif line.startswith('LAYER_XFER'):
            m=re.fullmatch(r'LAYER_XFER'+r' (\d+)'*6,line)
            if not m:raise ValueError('malformed transfer')
            row=list(map(int,m.groups()))
            if row[0]!=len(transfers)+1 or row[1]>SETUP:raise ValueError('transfer numbering or source differs')
            transfers.append(row);events.append(('transfer',len(transfers)-1))
        elif line.startswith('LAYER_STEP'):
            m=re.fullmatch(r'LAYER_STEP (\d+) (\d+) (begin|end)',line)
            if not m:raise ValueError('malformed step marker')
            events.append((m[3],int(m[1]),int(m[2])))
    return events,samples,transfers


def analyse(output,p):
    """Check one normal run against the plan and the cycle model; return counts and the goals that were reached."""
    events,samples,logged=parse(output);port=Port();bus=[]
    if not samples or samples[0][1]!=0:raise ValueError('recording must start in reset')
    for index,row in enumerate(samples):
        if row[7:]!=port.outputs():raise ValueError(f'cycle model differs at sample {row[0]}: {row[7:]} != {port.outputs()}')
        if row[1] and row[2]:bus.append(dict(cycle=index,write=row[3],addr=row[4],wdata=row[5],irq=row[9]))
        port.edge(*row[1:7])
    if len(bus)!=len(logged):raise ValueError('driver log and observed transfers differ in number')
    for t,row in zip(bus,logged):
        response=samples[t['cycle']+1] if t['cycle']+1<len(samples) else None
        if response is None or response[7]!=1:raise ValueError('transfer without acknowledge')
        t.update(src=row[1],rdata=response[8])
        if [row[2],row[3]]!=[t['write'],t['addr']] or (t['write'] and row[4]!=t['wdata']) or (not t['write'] and row[5]!=t['rdata']):
            raise ValueError(f'driver log differs from the pins at transfer {row[0]}')
    # Attribute transfers to steps by log order.
    step=None;closed=[];expected=expected_frames(p)
    for event in events:
        if event[0]=='begin':
            if step is not None or event[1]!=len(closed) or event[2]!=p['steps'][event[1]][0]:raise ValueError('step order differs')
            step=event[1]
        elif event[0]=='end':
            if step!=event[1]:raise ValueError('step end differs')
            closed.append(step);step=None
        elif event[0]=='transfer':bus[event[1]]['step']=step
    if step is not None or len(closed)!=len(p['steps']):raise ValueError('steps did not complete')
    goals=set();frames=[];current=None;owner=None;streak=0;last_index=None;pairs=[]
    for number,t in enumerate(bus):
        if t['irq'] and t['src']!=ISR:
            streak+=1
            if streak>LATENCY_BOUND:raise ValueError('interrupt service waited behind too many transfers')
            if t['src'] in (STATS,HOLD):goals.add('lock_delays_isr')
        else:streak=0
        if t['src']==ISR and current is not None:goals.add('isr_inside_frame')
        if t['write'] and t['addr']==CTRL and t['wdata']&1:
            if current is not None or t['src']!=FRAME:raise ValueError('frame started inside a frame')
            current=dict(step=t['step'],bytes=[])
        elif t['write'] and t['addr']==CTRL and t['wdata']&2:
            if current is None or t['src']!=FRAME or current['step']!=t['step']:raise ValueError('frame end without start')
            frames.append(current);current=None
        elif t['write'] and t['addr']==DATA:
            if current is None or t['src']!=FRAME:raise ValueError('byte outside a frame')
            current['bytes'].append(t['wdata'])
        elif t['write'] and t['addr']==INDEX:owner=t['src'];last_index=number
        elif not t['write'] and t['addr']==VALUE:
            if owner!=t['src'] or last_index!=number-1:raise ValueError('index and value were separated')
            pairs.append((bus[last_index],t))
            if t['src']==STATS and t['irq'] and t['cycle']-bus[last_index]['cycle']>=4:goals.add('gap_protected')
    if current is not None:raise ValueError('frame left open')
    outputs=[row[11:14] for row in samples if row[10]]
    if outputs!=[[f['bytes'][0],len(f['bytes']),sum(f['bytes'])&255] for f in frames]:raise ValueError('DUT frames differ from the bytes on the bus')
    for number,(kind,urgent,bulk) in enumerate(expected):
        seen=[f['bytes'] for f in frames if f['step']==number]
        if [f for f in seen if f[0]&128]!=urgent or [f for f in seen if not f[0]&128]!=bulk:raise ValueError(f'step {number} delivered other packets or another order within a port')
        if kind==BACKLOG:
            if seen!=urgent+bulk:raise ValueError(f'step {number} did not deliver the waiting high-priority packets first')
            if urgent and bulk:goals.add('backlog_priority')
        sources=[t['src'] for t in bus if t['step']==number]
        if kind==MIX and urgent and bulk and STATS in sources and any(samples[t['cycle']][6] for t in bus if t['step']==number):goals.add('mixed_traffic')
        if kind==CONTEND:
            order=[s for i,s in enumerate(sources) if s in (HOLD,ISR,LATE) and (i==0 or sources[i-1]!=s)]
            if order==[HOLD,ISR,LATE]:goals.add('grab_overtakes_lock')
            else:raise ValueError('grab was not served before the queued lock')
        if kind in (W1C_LATE,W1C_SAME):
            status=[t for t in bus if t['step']==number and t['src']==ISR and t['addr']==STATUS]
            alarms=[i for i,row in enumerate(samples) if row[6] and status and status[0]['cycle']<=i<=status[-1]['cycle']]
            if len(status)!=4 or len(alarms)!=1 or status[0]['rdata']!=(1 if kind==W1C_LATE else 2) or status[2]['rdata']!=2:raise ValueError('second interrupt cause was not kept')
            if kind==W1C_LATE and status[0]['cycle']<alarms[0]<status[1]['cycle']:goals.add('w1c_late')
            if kind==W1C_SAME and alarms[0]==status[1]['cycle']:goals.add('w1c_same')
    if any(f['bytes'][0]&128 for f in frames) and any(not f['bytes'][0]&128 for f in frames):goals.add('both_ports')
    reads=[t['rdata'] for t in bus if t['src']==ISR and t['addr']==STATUS and not t['write']]
    counts=dict(steps=len(p['steps']),transfers=len(bus),frames=len(frames),alarms=sum(row[6] for row in samples),
                served_done=sum(r&1 for r in reads),served_alarm=sum(r>>1&1 for r in reads),services=len(reads))
    if counts['served_alarm']!=counts['alarms'] or counts['served_done']!=counts['frames'] or any(r&4 for r in reads):raise ValueError('interrupt causes and services differ')
    if counts['alarms']:goals.add('alarm_serviced')
    if counts['frames']:goals.add('done_serviced')
    goals.add('cycle_model')
    marker='LAYER_COMPLETE '+' '.join(f'{k}={v}' for k,v in counts.items())+'\n'
    if output.count(marker)!=1 or output.count('LAYER_COMPLETE')!=1:raise ValueError('completion counts differ from the log')
    return dict(counts,cycles=len(samples),pairs=len(pairs)),sorted(goals)


def normal_report(output):
    if output.count('Accellera:1800.2:UVM:2020.3.2')!=1:raise ValueError('UVM version differs')
    for severity,value in [('ERROR','0'),('FATAL','0'),('WARNING','2')]:
        if re.findall(r'^UVM_'+severity+r'\s*:\s*(\d+)\s*$',output,re.M)!=[value]:raise ValueError('UVM severity summary differs')
    if sorted(re.findall(r'^UVM_WARNING .*?\[([^]]+)\]',output,re.M))!=['NO_DPI_USED','NO_VISIT_CHECK']:raise ValueError('unexpected native UVM warning')


def requirements():
    data=json.loads(REQUIREMENTS.read_text());listed=[g for r in data['requirements'] for g in r['goals']]
    if len({r['id'] for r in data['requirements']})!=len(data['requirements']) or sorted(listed)!=sorted(GOALS):raise ValueError('requirements and goals differ')
    return data


def run(args):
    seeds=list(range(args.seed,args.seed+(3 if args.profile=='nightly' else 1)));mixes=12 if args.profile=='nightly' else 3
    checks=['build']+[f'seed{s}' for s in seeds]+[f'mutation{m}' for m in MUTANTS]+[name for name,_,_ in DIAGNOSTICS]+['requirements-and-coverage']
    plans={s:plan(s,mixes) for s in seeds};catalog=requirements()
    e=E.Evidence('local-uvm-layering',args,[Path(__file__),HARNESS,REQUIREMENTS,*SOURCES],dict(seeds=seeds,mixes=mixes,plans=plans,goals=GOALS,latency_bound=LATENCY_BOUND),checks)
    home=args.uvm_home.resolve();E.P.write_json(e.out/'uvm-source.json',dict(root=str(home),source_sha256={str(p.relative_to(home)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted((home/'src').rglob('*')) if p.is_file()}))
    E.P.write_json(e.out/'tools.json',dict(verilator=E.P.execute([args.verilator,'--version'],e.out/'verilator-version.log',args.timeout,e.out)))
    build=E.P.execute([args.verilator,'--cc','--exe','--build','--timing','--trace','--coverage-user','--assert','-Wno-fatal','-j',str(args.jobs),'--top-module','top','--Mdir',str(e.out/'build'),'-I'+str(home/'src'),'+define+UVM_NO_DPI',str(home/'src/uvm_pkg.sv'),*map(str,SOURCES),str(HARNESS)],e.out/'build.log',args.build_timeout,e.out)
    e.check('build',not build['error'] and build['returncode']==0,build);E.P.write_json(e.out/'build.json',build)
    evidence=[]
    def execute(identity,p,mutation=0,label=None,flag=None):
        d=e.out/identity;d.mkdir(parents=True);file=d/'plan.txt';file.write_text(plan_text(p))
        command=[str(e.out/'build/Vtop'),f'+PLAN={file}',f'+CHECKS={len(p["steps"])}',f'+MUTATION={mutation}',f'+WAVE={d/"wave.vcd"}']+([f'+{flag}=1'] if flag else [])
        result=E.P.execute(command,d/'simulation.log',args.timeout,d);output=(d/'simulation.log').read_text(errors='replace')
        status,message=E.P.classify(dict(checks=len(p['steps']),expected_failure=label),result,output);ok=status==('detected' if label else 'pass');counts={};goals=[]
        try:
            if ok and not label:
                normal_report(output);counts,goals=analyse(output,p)
                if not (d/'wave.vcd').is_file() or '$enddefinitions' not in (d/'wave.vcd').read_text():raise ValueError('waveform missing')
        except (ValueError,OSError,KeyError,IndexError) as exc:ok=False;message=str(exc)
        record=dict(id=identity,success=ok,message=message,mutation=mutation,flag=flag,expected_failure=label,counts=counts,goals=goals,execution=result)
        E.P.write_json(d/'result.json',record);evidence.append(record);e.check(identity,ok,record)
    for seed,p in plans.items():execute(f'seed{seed}',p,args.demo_bug)
    first=plans[seeds[0]]
    for mutation,label in MUTANTS.items():execute(f'mutation{mutation}',first,mutation,label)
    for name,label,flag in DIAGNOSTICS:execute(name,first,label=label,flag=flag)
    normal=[r for r in evidence if r['expected_failure'] is None]
    missing={r['id']:sorted(set(GOALS)-set(r['goals'])) for r in normal if set(r['goals'])!=set(GOALS)}
    coverage=dict(requirements=[dict(id=r['id'],goals=r['goals'],covered=not missing) for r in catalog['requirements']],goals=len(GOALS),missing=missing,normal_executions=len(normal))
    E.P.write_json(e.out/'coverage.json',coverage)
    e.check('requirements-and-coverage',len(normal)==len(seeds) and all(r['success'] for r in normal) and not missing,coverage)
    E.P.write_json(e.out/'executions.json',evidence);return e.finish()


def main():
    p=E.parser(__doc__,'local-uvm-layering');p.add_argument('--uvm-home',type=Path,required=True);p.add_argument('--verilator',default='verilator');p.add_argument('--build-timeout',type=float,default=600);p.add_argument('--jobs',type=int,default=2);p.add_argument('--demo-bug',type=int,choices=range(5),default=0)
    a=p.parse_args();E.validate(p,a)
    if not (a.uvm_home/'src/uvm_pkg.sv').is_file() or a.jobs<=0 or not math.isfinite(a.build_timeout) or a.build_timeout<=0 or a.seed>2**31-4:p.error('prepared UVM library, positive build time/jobs and valid seed required')
    try:return run(a)
    except (OSError,ValueError,KeyError,TypeError) as exc:print('RUNNER_ERROR',exc,file=sys.stderr);return 1
if __name__=='__main__':sys.exit(main())

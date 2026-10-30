#!/usr/bin/env python3
"""Port checkers, explicit crosses, reset/X, throughput and native code coverage; local only."""
import argparse
from collections import Counter
from datetime import datetime,timezone
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import re
import signal
import sys
import xml.etree.ElementTree as ET

HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1]
SUPPORT_PATH=HERE.parent/'local-irq-cdc/run.py'
def module(name,path):
    spec=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
SUPPORT=module('bus_process_support',SUPPORT_PATH)
AHB=module('ahb_vectors',HERE.parent/'local-ahb/run.py');AXI=module('axi_vectors',HERE.parent/'local-axi/run.py')
CHECKERS=[HERE/'checkers/ahb_protocol_checker.sv',HERE/'checkers/axi_lite_protocol_checker.sv']
WAIVERS={'WIDTHEXPAND':'intentional parameter/integer arithmetic and address/data extension; functional checks remain enabled',
         'WIDTHTRUNC':'intentional field/byte selection; functional checks remain enabled',
         'UNUSEDSIGNAL':'subset interface attributes/unused address bits retained at ports',
         'UNUSEDPARAM':'subset interface configuration retained',
         'DECLFILENAME':'teaching file/module naming'}


def cross_plan(bus):
    if bus=='ahb':return {f'ahb/op{op}/size{s}/resp{r}' for op in (0,1) for s in range(3) for r in (0,1)}
    return ({f'axi/order{o}/strobe{s}/stall{b}' for o in range(3) for s in range(3) for b in (0,1)} |
            {f'axi/read/resp{r}/stall{s}' for r in (0,2) for s in (0,1)})


def cases(bus,parameters,args):
    n=args.transfers
    plugin=AHB if bus=='ahb' else AXI
    if bus=='ahb':
        wait=parameters['WAIT_CYCLES'];p=AHB.Plan(wait);p.cycle(rst=0)
        requests=[]
        for op in (0,1):
            for size in range(3):
                requests += [AHB.request(0,bool(op),0x96a55a69,size=size),AHB.request(32,bool(op),0x12345678,size=size)]
        p.pipeline(requests);p.cycle(rst=0);p.cycle();crosses=p.rows
        p=AHB.Plan(wait);p.cycle(rst=0)
        p.pipeline([AHB.request((i%4)*4,True,(0x12340000+i)&0xffffffff) for i in range(n)]+
                   [AHB.request((i%4)*4) for i in range(n)])
        p.cycle(rst=0);p.cycle();stress=p.rows
        random_rows=AHB.random_vectors(args.seed,32 if args.profile=='smoke' else 500,wait)
        baseline=AHB.boundary_vectors(wait)
        recovery=[]
    else:
        delay=parameters['RESP_DELAY'];p=AXI.Plan(delay);p.cycle(rst=0)
        for order in range(3):
            for strobe in (0,5,15):
                for stall in (0,3):
                    p.write(0,0x12345678,strobe,0 if order!=1 else 4,0 if order!=0 else 4,stall)
        for address in (0,32):
            for stall in (0,3):p.read(address,stall)
        p.cycle(rst=0);p.idle(2);crosses=p.rows
        p=AXI.Plan(delay);p.cycle(rst=0)
        for i in range(n):p.write((i%4)*4,(0x12340000+i)&0xffffffff)
        for i in range(n):p.read((i%4)*4)
        p.cycle(rst=0);p.idle(2);stress=p.rows
        p=AXI.Plan(delay);p.cycle(rst=0);p.write(0,0xa5a55a5a,b_stall=64);p.read(0,stall=64);p.write(0,0x12345678);p.read(0)
        p.cycle(rst=0);p.idle(2);recovery=p.rows
        random_rows=AXI.random_vectors(args.seed,32 if args.profile=='smoke' else 300,delay)
        baseline=AXI.boundary_vectors(delay)
    result=[dict(id='boundaries',vectors=baseline),dict(id='crosses',vectors=crosses),
            dict(id='throughput',vectors=stress),dict(id='random',vectors=random_rows)]
    if recovery:result.append(dict(id='stall-recovery',vectors=recovery))
    for c in result:c.update(checks=len(c['vectors']),counts=plugin.totals(c['vectors']),expected_failure=None)
    return result


def native(path,checker,bus,rtl):
    user={};code=[]
    for line in path.read_text().splitlines():
        if not line or line.startswith('#'):continue
        match=re.fullmatch(r"C '([^']*)' (\d+)",line)
        if not match:raise ValueError('malformed native coverage record')
        meta=dict(field.split('\x02',1) for field in match[1].split('\x01') if field)
        source=Path(meta.get('f','')).resolve();page=meta.get('page','');count=int(match[2])
        if source==checker.resolve() and (meta.get('t')=='user' or page.startswith('v_user/')):
            label=meta.get('o')
            if label in user:raise ValueError('duplicate native user cover')
            user[label]=count
        if source==rtl.resolve() and (page.startswith('v_line/') or page.startswith('v_toggle/')):
            code.append(dict(kind='line' if page.startswith('v_line/') else 'toggle',count=count,metadata=meta))
    expected=({'cp_address_wait','cp_error','cp_pipeline'} if bus=='ahb' else
              {'cp_aw_wait','cp_w_wait','cp_ar_wait','cp_b_wait','cp_r_wait'})
    if user.keys()!=expected:raise ValueError('native checker cover inventory differs from fixed plan')
    if not code or not any(c['kind']=='line' for c in code) or not any(c['kind']=='toggle' for c in code):
        raise ValueError('RTL line/toggle instrumentation missing')
    return dict(user=user,code=code)


def performance(log,bus,parameters,case,transfers):
    observations=[(m[1],int(m[2]),int(m[3])) for m in re.finditer(r'^PERF (\S+) latency=(\d+) cycle=(\d+)$',log,re.M)]
    expected_count=(case['counts']['reads']+case['counts']['writes']+case['counts']['errors'] if bus=='ahb' else
                    case['counts']['b']+case['counts']['r'])
    allowed={'ahb'} if bus=='ahb' else {'axi-write','axi-read'}
    if not observations or len(observations)!=expected_count or any(label not in allowed for label,_,_ in observations):
        raise ValueError('performance completion inventory mismatch')
    totals=re.findall(r'^PERF_TOTAL (\S+) first=(-?\d+) last=(-?\d+) completed=(\d+)$',log,re.M)
    if len(totals)!=1:raise ValueError('missing or duplicate performance totals')
    name,first,last,completed=totals[0];first,last,completed=int(first),int(last),int(completed)
    if name!=bus or completed!=len(observations) or not 0<=first<=last or last!=observations[-1][2]:
        raise ValueError('performance totals mismatch')
    if any(b[2]<a[2] for a,b in zip(observations,observations[1:])):raise ValueError('nonmonotonic completion clocks')
    result=dict(completed=len(observations),histogram=dict(Counter(lat for _,lat,_ in observations)),
                max_latency=max(lat for _,lat,_ in observations),first_request=first,
                first_completion=observations[0][2],last_completion=last,
                window_completions_per_cycle=len(observations)/(last-first+1))
    if case['id']=='throughput':
        expected_latency=parameters['WAIT_CYCLES']+1 if bus=='ahb' else parameters['RESP_DELAY']+2
        expected_spacing=parameters['WAIT_CYCLES']+1 if bus=='ahb' else parameters['RESP_DELAY']+3
        if len(observations)!=2*transfers or any(lat!=expected_latency for _,lat,_ in observations):
            raise ValueError('throughput latency contract failed')
        if any(b[2]-a[2]!=expected_spacing for a,b in zip(observations,observations[1:])):
            raise ValueError('throughput completion spacing failed')
        result['steady_completions_per_cycle']=1/expected_spacing
    return result


def build(args,out,top,sources,parameters,native_build):
    out.mkdir()
    if native_build:
        command=[args.verilator,'--cc','--exe','--build','-j','2','--timing','--assert','--autoflush',
                 '--coverage-user','--coverage-line','--coverage-toggle','--trace','-Wno-fatal',
                 '-DBUS_VALIDATION','-DNATIVE_SVA','--prefix','Vbus_model','--top-module',top,'--Mdir',str(out/'obj')]
        command += [f'-G{k}={v}' for k,v in parameters.items()]+[str(p) for p in sources]+[str(HERE/'sim_main.cpp')]
        binary=[str(out/'obj/Vbus_model')]
    else:
        command=[args.iverilog,'-g2012','-s',top,'-o',str(out/'sim.vvp')]
        command += [f'-P{top}.{k}={v}' for k,v in parameters.items()]+[str(p) for p in sources]
        binary=[args.vvp,str(out/'sim.vvp')]
    execution=SUPPORT.execute(command,out/'build.log',args.build_timeout,out)
    SUPPORT.write_json(out/'build.json',execution)
    return execution,binary


def run_bus(args,out,results):
    report={}
    for bus,plugin in [('ahb',AHB),('axi',AXI)]:
        rtl=plugin.SOURCES[0];checker=CHECKERS[0 if bus=='ahb' else 1]
        lint=SUPPORT.execute([args.verilator,'--lint-only','--Wall','-Wno-fatal','--top-module',
            'ahb_regs' if bus=='ahb' else 'axi_lite_regs',str(rtl)],out/f'lint-{bus}.log',args.build_timeout,out)
        warnings=[dict(code=m[1],message=m[2]) for m in re.finditer(r'^%Warning-([A-Z0-9_]+): (.*)$',(out/f'lint-{bus}.log').read_text(),re.M)]
        lint_ok=not lint['error'] and lint['returncode']==0 and all(w['code'] in WAIVERS for w in warnings)
        SUPPORT.write_json(out/f'lint-{bus}.json',dict(success=lint_ok,warnings=warnings,waivers=WAIVERS,**lint))
        results.append(dict(id='lint-'+bus,status='pass' if lint_ok else 'error',message='RTL lint audit',seconds=lint['seconds']))
        for config,parameters in plugin.CONFIGS.items():
            name=bus+'-'+config;directory=out/name;directory.mkdir()
            execution,binary=build(args,directory/'build',plugin.TOP,[*plugin.SOURCES,checker],parameters,True)
            hits=set();native_hits=Counter();code_hits={};metrics={}
            for case in cases(bus,parameters,args):
                d=directory/case['id'];d.mkdir();vectors=d/'vectors.txt'
                vectors.write_text(''.join(' '.join(format(v,'x') for v in row)+'\n' for row in case['vectors']))
                command=[*binary,f'+VECTORS={vectors}',f'+WAVE={d/"wave.vcd"}']
                if execution['error'] or execution['returncode']!=0:
                    e=dict(returncode=None,error='build failed',seconds=0,command=command);(d/'simulation.log').write_text('build failed\n')
                else:e=SUPPORT.execute(command,d/'simulation.log',args.timeout,d)
                log=(d/'simulation.log').read_text(errors='replace');status,message=SUPPORT.classify(case,e,log)
                audit=None
                if status=='pass':
                    try:
                        counts=re.findall(r'^COUNT ([a-z_]+)=(\d+)$',log,re.M)
                        if len(counts)!=len(dict(counts)) or {k:int(v) for k,v in counts}!=case['counts']:raise ValueError('completion counts mismatch')
                        audit=native(d/'coverage.dat',checker,bus,rtl)
                        metrics[case['id']]=performance(log,bus,parameters,case,args.transfers)
                        hits.update(re.findall(r'^CROSS (\S+)$',log,re.M));native_hits.update(audit['user'])
                        for c in audit['code']:
                            key=json.dumps(c['metadata'],sort_keys=True);code_hits[key]=code_hits.get(key,0)+c['count']
                    except (OSError,ValueError,KeyError) as exc:status,message='error',str(exc)
                record=dict(id=name+'-'+case['id'],status=status,message=message,seconds=e['seconds'],execution=e)
                SUPPORT.write_json(d/'result.json',record);results.append(record);print(status.upper(),record['id'],message,flush=True)
            required=cross_plan(bus)
            expected_native=({'cp_error','cp_pipeline'} if bus=='ahb' and parameters['WAIT_CYCLES']==0 else
                              {'cp_address_wait','cp_error','cp_pipeline'} if bus=='ahb' else
                              {'cp_aw_wait','cp_w_wait','cp_ar_wait','cp_b_wait','cp_r_wait'})
            success=required<=hits and all(native_hits[c]>0 for c in expected_native)
            results.append(dict(id=name+'-cross-and-sva-gate',status='pass' if success else 'fail',message='required cross/native goals',seconds=0))
            report[name]=dict(success=success,required=sorted(required),hit=sorted(required & hits),missing=sorted(required-hits),
                native_counts=native_hits,native_required=sorted(expected_native),
                excluded_native={'cp_address_wait':'zero-wait configuration has no ordinary wait'} if bus=='ahb' and parameters['WAIT_CYCLES']==0 else {},
                metrics=metrics,code_counters=[dict(metadata=json.loads(k),count=v) for k,v in code_hits.items()],
                code_summary={kind:dict(total=sum(json.loads(k).get('page','').startswith('v_'+kind+'/') for k in code_hits),
                    hit=sum(json.loads(k).get('page','').startswith('v_'+kind+'/') and v>0 for k,v in code_hits.items())) for kind in ('line','toggle')})
    SUPPORT.write_json(out/'bus-report.json',report)


def run_fixtures(args,out,results):
    for native_build in (False,True):
        for bus in (0,1):
            name=('sva' if native_build else 'four-state')+('-ahb' if bus==0 else '-axi')
            execution,binary=build(args,out/(name+'-build'),'checker_tb',[*CHECKERS,HERE/'tb/checker_tb.sv'],{'BUS':bus},native_build)
            fixtures=([(1,'PROTO_AHB_ERROR'),(2,'PROTO_AHB_ADDRESS'),(3,'PROTO_AHB_DATA'),(7,'PROTO_AHB_ERROR')] if bus==0 else
                      [(1,'PROTO_AXI_AW'),(2,'PROTO_AXI_W'),(3,'PROTO_AXI_AR'),(4,'PROTO_AXI_B'),(5,'PROTO_AXI_R'),(6,'PROTO_AXI_CAUSALITY'),(10,'PROTO_AXI_CREDIT'),(11,'PROTO_AXI_CAUSALITY')])
            if not native_build:fixtures += [(4,'PROTO_AHB_X'),(5,None)] if bus==0 else [(7,'PROTO_AXI_X'),(8,None)]
            fixtures += [(6 if bus==0 else 9,None)]
            for scenario,label in fixtures:
                d=out/(name+f'-scenario{scenario}');d.mkdir()
                e=SUPPORT.execute([*binary,f'+SCENARIO={scenario}',f'+WAVE={d/"wave.vcd"}'],d/'simulation.log',args.timeout,d) if not execution['error'] and execution['returncode']==0 else dict(error='build failed',returncode=None,seconds=0)
                log=(d/'simulation.log').read_text(errors='replace') if (d/'simulation.log').exists() else ''
                checks=5 if bus==0 and scenario==6 else 4
                status,message=SUPPORT.classify(dict(checks=checks,expected_failure=label),e,log)
                record=dict(id=d.name,status=status,message=message,seconds=e['seconds']);results.append(record);SUPPORT.write_json(d/'result.json',record)
                print(status.upper(),d.name,message,flush=True)
    execution,binary=build(args,out/'reset-build','reset_tb',[AHB.SOURCES[0],AXI.SOURCES[0],*CHECKERS,HERE/'tb/reset_tb.sv'],{},False)
    d=out/'actual-async-reset';d.mkdir()
    e=SUPPORT.execute([*binary,f'+WAVE={d/"wave.vcd"}'],d/'simulation.log',args.timeout,d) if not execution['error'] and execution['returncode']==0 else dict(error='build failed',returncode=None,seconds=0)
    log=(d/'simulation.log').read_text(errors='replace') if (d/'simulation.log').exists() else ''
    status,message=SUPPORT.classify(dict(checks=3,expected_failure=None),e,log)
    if status=='pass' and set(re.findall(r'^COVER reset/(\S+)$',log,re.M))!={'offset1','offset2','offset6'}:status,message='error','reset phase goals missing'
    results.append(dict(id=d.name,status=status,message=message,seconds=e['seconds']))


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--stage',choices=('all','bus','fixtures','bridges','axi4'),default='all')
    p.add_argument('--profile',choices=('smoke','nightly'),default='smoke');p.add_argument('--seed',type=int,default=17)
    p.add_argument('--transfers',type=int);p.add_argument('--verilator',default='verilator');p.add_argument('--iverilog',default='iverilog');p.add_argument('--vvp',default='vvp')
    p.add_argument('--timeout',type=float,default=30);p.add_argument('--build-timeout',type=float,default=180)
    p.add_argument('--out',type=Path,default=Path('artifacts')/datetime.now(timezone.utc).strftime('bus-validation-%Y%m%dT%H%M%S%fZ'))
    args=p.parse_args()
    if args.transfers is None:args.transfers=4096 if args.profile=='nightly' else 512
    if args.out.exists():p.error('output exists; choose a new directory')
    if os.name!='posix' or args.seed<0 or not 2<=args.transfers<=50000 or any(not math.isfinite(n) or n<=0 for n in (args.timeout,args.build_timeout)):p.error('invalid seed/count/timeout')
    out=args.out.resolve();out.mkdir(parents=True);results=[]
    sources=[Path(__file__),SUPPORT_PATH,*CHECKERS,HERE/'sim_main.cpp',*HERE.glob('tb/*.sv'),
             Path(AHB.__file__),*AHB.SOURCES,Path(AXI.__file__),*AXI.SOURCES]
    SUPPORT.write_json(out/'manifest.json',dict(profile=args.profile,stage=args.stage,seed=args.seed,transfers=args.transfers,
        source_sha256={str(f.relative_to(ROOT)):hashlib.sha256(f.read_bytes()).hexdigest() for f in sources}))
    versions={}
    for name in (('verilator','iverilog','vvp') if args.stage in ('all','fixtures') else ('verilator',) if args.stage=='bus' else ()):
        e=SUPPORT.execute([getattr(args,name),'--version' if name=='verilator' else '-V'],out/(name+'-version.log'),args.timeout,out)
        versions[name]=dict(e,output=(out/(name+'-version.log')).read_text(errors='replace'))
    SUPPORT.write_json(out/'tools.json',versions)
    try:
        if args.stage in ('all','bus'):run_bus(args,out,results)
        if args.stage in ('all','fixtures'):run_fixtures(args,out,results)
        for stage,directory in [('bridges','local-bus-bridge'),('axi4','local-axi4')]:
            if args.stage in ('all',stage):
                command=[sys.executable,str(HERE.parent/directory/'run.py'),'--profile',args.profile,'--seed',str(args.seed),'--iverilog',args.iverilog,'--vvp',args.vvp,'--timeout',str(args.timeout),'--out',str(out/stage)]
                e=SUPPORT.execute(command,out/(stage+'.log'),args.build_timeout*4,out)
                child=out/stage/'summary.json'
                ok=not e['error'] and e['returncode']==0 and child.exists() and json.loads(child.read_text())['success']
                results.append(dict(id=stage,status='pass' if ok else 'error',message='child regression',seconds=e['seconds']))
    except (OSError,ValueError,KeyError,TypeError) as exc:results.append(dict(id='runner',status='error',message=str(exc),seconds=0))
    success=bool(results) and all(r['status'] in ('pass','detected') for r in results)
    SUPPORT.write_json(out/'summary.json',dict(success=success,results=results,scope=args.stage))
    suite=ET.Element('testsuite',name='bus.validation',tests=str(len(results)),failures=str(sum(r['status']=='fail' for r in results)),errors=str(sum(r['status']=='error' for r in results)))
    for r in results:
        n=ET.SubElement(suite,'testcase',name=r['id'],classname='bus.validation',time=f"{r['seconds']:.6f}")
        if r['status'] in ('fail','error'):ET.SubElement(n,'failure' if r['status']=='fail' else 'error',message=r['message'])
    ET.indent(suite);ET.ElementTree(suite).write(out/'junit.xml',encoding='utf-8',xml_declaration=True)
    print('Artifacts:',out,'\nValidation:', 'PASS' if success else 'FAIL');return 0 if success else 1

if __name__=='__main__':
    previous=signal.signal(signal.SIGTERM,SUPPORT.interrupted)
    try:sys.exit(main())
    except SUPPORT.RunInterrupted as exc:sys.exit(128+exc.signum)
    except KeyboardInterrupt:sys.exit(130)
    finally:signal.signal(signal.SIGTERM,previous)

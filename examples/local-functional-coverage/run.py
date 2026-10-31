#!/usr/bin/env python3
"""Native coverpoint/cross coverage for DRAM, SHA-256 and packet switching."""
import importlib.util
from pathlib import Path
import math
import re
import sys
from types import SimpleNamespace
HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('native_evidence',HERE.parent/'local-exploration-common/evidence.py')
E=importlib.util.module_from_spec(spec);spec.loader.exec_module(E)
EXAMPLES={'dram':'local-dram','sha256':'local-sha256','packet-switch':'local-packet-switch'}
SCHEMAS={
 'dram':{'commands':({'bank_id':('zero','one'),'operation':('activate','read_data','write_data','precharge')},
                     {'bank_command':('bank_id','operation')}),
         'refreshes':({'response':('free','held')},{}),'responses':({'ready_state':('held','accepted')},{})},
 'sha256':{'lengths':({'length':('empty','short_message','end_one','start_two','partial','full_block','above_block','maximum','rejected')},{}),
           'responses':({'result':('okay','rejected'),'ready_state':('held','accepted')},{'result_ready':('result','ready_state')})},
 'packet-switch':{'flits':({'port_id':('zero','one'),'tail':('body','tail'),'ready_state':('held','accepted')},
                          {'port_tail_ready':('port_id','tail','ready_state')})}}

def inventory(example):
    from itertools import product
    result={}
    for group,(points,crosses) in SCHEMAS[example].items():
        for point,bins in points.items():
            result.update({f'{group}.{point}.{name}':False for name in bins})
        for cross,point_names in crosses.items():
            result.update({f'{group}.{cross}.'+ '_x_'.join(names):True for names in product(*(points[p] for p in point_names))})
    return result

def expected_bins(example,rows):
    counts=dict.fromkeys(inventory(example),0)
    def sample(group,**values):
        points,crosses=SCHEMAS[example][group]
        if values.keys()!=points.keys():raise ValueError('sample schema differs')
        for point,name in values.items():counts[f'{group}.{point}.{name}']+=1
        for cross,point_names in crosses.items():counts[f'{group}.{cross}.'+'_x_'.join(values[p] for p in point_names)]+=1
    opened=[None,None];pending=None
    for r in rows:
        if not r[0]:opened=[None,None];pending=None;continue
        if example=='sha256':
            if r[1] and r[6]:
                n=r[2];name=('empty' if n==0 else 'short_message' if n<55 else 'end_one' if n==55 else
                  'start_two' if n==56 else 'partial' if n<64 else 'full_block' if n==64 else
                  'above_block' if n<119 else 'maximum' if n==119 else 'rejected')
                sample('lengths',length=name)
            if r[8]:sample('responses',result='rejected' if r[9] else 'okay',ready_state='accepted' if r[5] else 'held')
        elif example=='packet-switch':
            for o in range(2):
                if r[7]>>o&1:sample('flits',port_id='one' if o else 'zero',tail='tail' if r[8]>>o&1 else 'body',ready_state='accepted' if r[5]>>o&1 else 'held')
        else:
            cmd=r[11]
            if 1<=cmd<=4:
                b=pending[1] if pending is not None else next(i for i in range(2) if opened[i] is not None)
                sample('commands',bank_id='one' if b else 'zero',operation={1:'activate',2:'read_data',3:'write_data',4:'precharge'}[cmd])
                if cmd==1:opened[b]=pending[2]
                elif cmd==4:opened[b]=None
                if cmd in (2,3):pending=None
            if cmd==5:sample('refreshes',response='held' if r[9] and not r[7] else 'free')
            if r[9]:sample('responses',ready_state='accepted' if r[7] else 'held')
            if r[1] and r[8]:pending=tuple(r[2:7])
    return counts

def native(path,example):
    expected=inventory(example);bins={};source=(HERE/'tb'/f'{example}.sv').resolve()
    for line in path.read_text().splitlines():
        if not line or line.startswith('#'):continue
        match=re.fullmatch(r"C '([^']*)' (\d+)",line)
        if not match:raise ValueError('NATIVE_FORMAT: malformed counter')
        fields=[field.split('\x02',1) for field in match[1].split('\x01') if field]
        if any(len(f)!=2 for f in fields) or len(dict(fields))!=len(fields):raise ValueError('NATIVE_FORMAT: metadata')
        meta=dict(fields)
        if meta.get('t')!='covergroup' or Path(meta.get('f','')).resolve()!=source:raise ValueError('NATIVE_IDENTITY: type/source')
        name=meta.get('h')
        if name not in expected or name in bins:raise ValueError('NATIVE_INVENTORY: unexpected/duplicate bin')
        if (meta.get('cross')=='1')!=expected[name]:raise ValueError('NATIVE_IDENTITY: cross type')
        bins[name]=int(match[2])
    if bins.keys()!=expected.keys():raise ValueError('NATIVE_INVENTORY: missing bin')
    return bins

def validate_bins(example,bins,expected):
    if bins.keys()!=inventory(example).keys() or expected.keys()!=bins.keys():raise ValueError('NATIVE_INVENTORY')
    if any(v<=0 for v in bins.values()):raise ValueError('NATIVE_COVERAGE: required bins not hit')
    if bins!=expected:raise ValueError('NATIVE_COUNTS: samples differ from independent event tally')

def plans(example,plugin,args,parameters):
    cases=plugin.make_cases(SimpleNamespace(profile=args.profile,seed=args.seed,iterations=plugin.ITERATIONS[args.profile],demo_bug=0),parameters)
    rows=[(c['id'],c['vectors']) for c in cases if c['category']=='functional']
    if example=='packet-switch':
        # Fill the legal output x tail x readiness cross on both output ports.
        p=plugin.Plan(parameters['WIDTH']);p.cycle(rst=0)
        p.streams([plugin.packet(1,[101,102]),plugin.packet(0,[201,202])],[0,0,3,0,3])
        rows=[(name,p.rows+vectors) for name,vectors in rows]
    return rows

def partial(example,plugin,parameters):
    if example=='sha256':p=plugin.Plan(parameters['ROUNDS']);p.cycle(rst=0);p.message(b'abc')
    elif example=='dram':p=plugin.Plan(parameters);p.cycle(rst=0);p.access(0,0,0,0)
    else:p=plugin.Plan(parameters['WIDTH']);p.cycle(rst=0);p.streams([plugin.packet(0,[1]),[]])
    return p.rows

def checked_execution(execution,log,rows,wave):
    status,message=E.P.classify(dict(checks=len(rows),expected_failure=None),execution,log)
    pairs=re.findall(r'^COUNT ([a-z_]+)=(\d+)$',log,re.M)
    if status!='pass':raise ValueError('FUNCTIONAL: '+message)
    if pairs!=[('steps',str(len(rows)))]:raise ValueError('FUNCTIONAL: completion count')
    if not wave.is_file() or '$enddefinitions' not in wave.read_text():raise ValueError('FUNCTIONAL: waveform')

def run(args):
    selected=list(EXAMPLES) if args.example=='all' else [args.example]
    plugins={name:E.load('fc_'+name,HERE.parent/EXAMPLES[name]/'run.py') for name in selected}
    jobs=[(name,plugin,cfg,params,plans(name,plugin,args,params)) for name,plugin in plugins.items() for cfg,params in plugin.CONFIGS.items()]
    inputs=[Path(__file__),HERE/'sim_main.cpp',*[HERE/'tb'/f'{name}.sv' for name in selected]]
    for plugin in plugins.values():inputs += [Path(plugin.__file__),plugin.HERE/'requirements.json',*plugin.SOURCES]
    checks=[f'{name}-{cfg}-{step}' for name,plugin,cfg,params,cases in jobs for step in ['build',*[n for n,rows in cases],'reject-partial','reject-disabled','native-bins']]
    e=E.Evidence('local-functional-coverage',args,inputs,dict(examples=selected,native_bins={n:inventory(n) for n in selected}),checks)
    E.P.write_json(e.out/'tools.json',{'verilator':E.P.execute([args.verilator,'--version'],e.out/'verilator-version.log',args.timeout,e.out)})
    records=[]
    for name,plugin,cfg,params,cases in jobs:
        identity=f'{name}-{cfg}';build=e.out/(identity+'-build')
        command=[args.verilator,'--cc','--exe','--build','--timing','--trace','--coverage-user','--timescale','1ns/1ps','-j',str(args.jobs),
          '--top-module','native_top','--Mdir',str(build),*[f'-G{k}={v}' for k,v in params.items()],str(HERE/'tb'/f'{name}.sv'),*map(str,plugin.SOURCES),str(HERE/'sim_main.cpp')]
        result=E.P.execute(command,e.out/(identity+'-build.log'),args.build_timeout,e.out);E.P.write_json(e.out/(identity+'-build.json'),result)
        built=not result['error'] and result['returncode']==0;e.check(identity+'-build',built,result)
        credited=[]
        executions=[(n,r,False,False) for n,r in cases]+[('reject-partial',partial(name,plugin,params),True,False),('reject-disabled',cases[0][1],True,True)]
        for case_name,rows,diagnostic,off in executions:
            case_id=identity+'-'+case_name;d=e.out/case_id;d.mkdir();vectors=d/'vectors.txt';wave=d/'wave.vcd'
            vectors.write_text(''.join(' '.join(format(v,'x') for v in row)+'\n' for row in rows))
            if built:ex=E.P.execute([str(build/'Vnative_top'),f'+VECTORS={vectors}',f'+WAVE={wave}',f'+COVER_OFF={int(off)}'],d/'simulation.log',args.timeout,d)
            else:ex=dict(error='build failed',returncode=None);(d/'simulation.log').write_text('build failed\n')
            ok=False;message='';bins={};expected=expected_bins(name,rows)
            try:
                checked_execution(ex,(d/'simulation.log').read_text(errors='replace'),rows,wave)
                bins=native(d/'coverage.dat',name)
                if diagnostic:
                    if bins!=(dict.fromkeys(expected,0) if off else expected):raise ValueError('NATIVE_COUNTS: diagnostic tally')
                    try:validate_bins(name,bins,expected)
                    except ValueError as exc:
                        if not str(exc).startswith('NATIVE_COVERAGE:'):raise
                        ok=True;message=str(exc)
                    else:message='coverage diagnostic unexpectedly passed'
                else:validate_bins(name,bins,expected);ok=True;credited.append(case_id)
            except (OSError,ValueError,KeyError,TypeError) as exc:message=str(exc)
            record=dict(id=case_id,success=ok,diagnostic=diagnostic,credited=ok and not diagnostic,counts=bins,expected_counts=expected,message=message,**ex)
            E.P.write_json(d/'result.json',record);records.append(record);e.check(case_id,ok,message)
        e.check(identity+'-native-bins',len(credited)==len(cases),dict(required_bins=len(inventory(name)),normal_cases=credited))
    E.P.write_json(e.out/'executions.json',records);return e.finish()

def main():
    p=E.parser(__doc__,'local-functional-coverage');p.add_argument('--example',choices=['all',*EXAMPLES],default='all')
    p.add_argument('--verilator',default='verilator');p.add_argument('--build-timeout',type=float,default=180);p.add_argument('--jobs',type=int,default=4)
    args=p.parse_args();E.validate(p,args)
    if not math.isfinite(args.build_timeout) or args.build_timeout<=0 or args.jobs<1:p.error('positive build timeout/jobs required')
    try:return run(args)
    except (OSError,ValueError,KeyError,TypeError,StopIteration) as exc:print('RUNNER_ERROR',exc,file=sys.stderr);return 1
if __name__=='__main__':sys.exit(main())

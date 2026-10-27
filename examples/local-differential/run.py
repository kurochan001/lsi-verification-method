#!/usr/bin/env python3
"""Replay identical DSP/AXI-Stream vectors on Icarus and Verilator and compare qualified traces."""
import importlib.util
from pathlib import Path
import re
import sys
HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('host_runner',HERE.parent/'local-host-common/runner.py');H=importlib.util.module_from_spec(spec);spec.loader.exec_module(H)
DSP=H.module('diff_dsp',HERE.parent/'local-dsp/run.py');AXIS=H.module('diff_axis',HERE.parent/'local-axis/run.py')
NAME='local-differential';ITERATIONS={'smoke':32,'nightly':300}
CONFIGS={**{'dsp-'+k:(DSP,v) for k,v in DSP.CONFIGS.items()},**{'axis-'+k:(AXIS,v) for k,v in AXIS.CONFIGS.items()}}
INPUTS=[HERE/'sim_main.cpp',Path(DSP.__file__),*DSP.SOURCES,Path(AXIS.__file__),*AXIS.SOURCES]
def cases(args):
    result=[]
    for config,(plugin,parameters) in CONFIGS.items():
        for source in plugin.make_cases(type('A',(),dict(profile=args.profile,seed=args.seed,iterations=args.iterations,demo_bug=0))(),parameters):
            if source['category']!='functional':continue
            result.append(dict(id=config+'-'+source['id'],configuration=config,kind='equal',vectors=source['vectors'],checks=len(source['vectors']),expected_failure=None,category='functional',reference_counts=source['counts'],counts=dict(cycles=len(source['vectors']),backends=2)))
        if plugin is DSP:
            baseline=result[-2 if args.profile=='smoke' else -4].copy();baseline.update(id=config+'-inactive-X',inactive_x=True);result.append(baseline)
    baseline=next(c for c in result if c['configuration']==next(iter(CONFIGS)))
    result += [dict(baseline,id='detect-backend-difference',kind='different',category='diagnostic',expected_failure='DIFFERENTIAL_MISMATCH'),
               dict(baseline,id='four-state-active-X',kind='active-x',category='diagnostic',expected_failure='DSP_DATA')]
    return result
def probes(args):return {'iverilog':[args.iverilog,'-V'],'verilator':[args.verilator,'--version']}
def build(args,d,plugin,params,backend,mutation=0,check=1):
    d.mkdir();parameters=dict(params,MUTATION=mutation)
    if plugin is DSP:parameters['CHECK_EXPECTATIONS']=check
    if backend=='icarus':
        cmd=[args.iverilog,'-g2012','-s',plugin.TOP,'-o',str(d/'sim.vvp'),*[f'-P{plugin.TOP}.{k}={v}' for k,v in parameters.items()],*[str(p) for p in plugin.SOURCES]];binary=[args.vvp,str(d/'sim.vvp')]
    else:
        cmd=[args.verilator,'--cc','--exe','--build','-j','2','--timing','--trace','--assert','--autoflush','-Wno-fatal','--prefix','Vbus_model','--top-module',plugin.TOP,'--Mdir',str(d/'obj'),*[f'-G{k}={v}' for k,v in parameters.items()],*[str(p) for p in plugin.SOURCES],str(HERE/'sim_main.cpp')];binary=[str(d/'obj/Vbus_model')]
    e=H.P.execute(cmd,d/'build.log',args.build_timeout,d);H.P.write_json(d/'build.json',e);return e,binary

def prepare(args,out):
    context={}
    for config,(plugin,params) in CONFIGS.items():
        for backend in ('icarus','verilator'):
            print('BUILD',config,backend,flush=True);context[config,backend,'normal']=build(args,out/(config+'-'+backend),plugin,params,backend)
    config=next(iter(CONFIGS));plugin,params=CONFIGS[config]
    for backend,mutation in [('icarus',0),('verilator',4)]:context[config,backend,'different']=build(args,out/('difference-'+backend),plugin,params,backend,mutation,0)
    return context

def traces(log,checks):
    lines=re.findall(r'^OBS .+$',log,re.M)
    patterns=(r'OBS (?:DSP|AXIS) cycle=(\d+) ready=[01] valid=0',
              r'OBS DSP cycle=(\d+) ready=[01] valid=1 data=[0-9a-f]{2} clipped=[01]',
              r'OBS AXIS cycle=(\d+) ready=[01] valid=1 data=[0-9a-f]{8} keep=[0-9a-f] last=[01]')
    clocks=[]
    for line in lines:
        match=next((m for pattern in patterns if (m:=re.fullmatch(pattern,line))),None)
        if match is None:raise ValueError('unknown-valued or malformed qualified trace')
        clocks.append(int(match[1]))
    if clocks!=list(range(checks)):raise ValueError('missing/duplicate/reordered trace clocks')
    return lines

def execute(args,out,d,case,context):
    vectors=d/'vectors.txt';vectors.write_text(''.join(' '.join(format(v,'x') for v in row)+'\n' for row in case['vectors']))
    logs=[];seconds=0
    for backend in (('icarus',) if case['kind']=='active-x' else ('icarus','verilator')):
        directory=d/backend;directory.mkdir();build,binary=context[case['configuration'],backend,'different' if case['kind']=='different' else 'normal']
        command=[*binary,f'+VECTORS={vectors}',f'+WAVE={directory/"wave.vcd"}']
        if case.get('inactive_x'):command+=['+INVALID_X']
        if case['kind']=='active-x':command+=['+ACTIVE_X']
        if build['error'] or build['returncode']!=0:
            (d/'simulation.log').write_text('backend build failed\n');return dict(error='backend build failed',returncode=None,seconds=0,command=command)
        execution=H.P.execute(command,directory/'simulation.log',args.timeout,directory);seconds+=execution['seconds'];log=(directory/'simulation.log').read_text(errors='replace')
        if case['kind']=='active-x':(d/'simulation.log').write_text(log);return execution
        expected=dict(case,expected_failure=None,counts=case['reference_counts'])
        status,message,_=H.evaluate(expected,execution,log)
        if status!='pass':(d/'simulation.log').write_text(log);return dict(execution,error='backend oracle/completion failed: '+message)
        try:logs.append(traces(log,case['checks']))
        except ValueError as exc:(d/'simulation.log').write_text(str(exc)+'\n');return dict(execution,error=str(exc))
    mismatch=logs[0]!=logs[1]
    H.P.write_json(d/'comparison.json',dict(equal=not mismatch,first_mismatch=next((i for i,(a,b) in enumerate(zip(*logs)) if a!=b),None)))
    if case['kind']=='different':text='CHECK_FAIL DIFFERENTIAL_MISMATCH\n' if mismatch else f"RESULT PASS checks={case['checks']}\n";rc=int(mismatch)
    elif mismatch:text='CHECK_FAIL DIFFERENTIAL_UNEXPECTED\n';rc=1
    else:text=f"COUNT cycles={case['checks']}\nCOUNT backends=2\nCOVER trace/complete\nCOVER backend/equivalent\nCOVER oracle/both\nRESULT PASS checks={case['checks']}\n";rc=0
    (d/'simulation.log').write_text(text);return dict(command=['compare-qualified-traces'],returncode=rc,error=None,seconds=seconds)
if __name__=='__main__':sys.exit(H.main(sys.modules[__name__]))

#!/usr/bin/env python3
"""Generate fresh FIFO counterexamples, replay only top-level inputs and retain regressions."""
from collections import deque
import importlib.util
import json
import os
from pathlib import Path
import sys
HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('replay_evidence',HERE.parent/'local-exploration-common/evidence.py');E=importlib.util.module_from_spec(spec);spec.loader.exec_module(E)
FORMAL=HERE.parent/'local-equivalence';RTL=FORMAL/'rtl/fifo_pair.sv'

def witness_inputs(document):
    if document.get('format')!='Yosys Witness Trace':raise ValueError('unsupported witness format')
    if document.get('clocks')!=[dict(path=['\\clk'],edge='posedge',offset=0)]:raise ValueError('single positive clock required')
    signals=document['signals'];required={'rst_n':1,'valid':1,'ready':1,'data':4};rows=[]
    for index,step in enumerate(document['steps']):
        active=[s for s in signals if index==0 or not s.get('init_only',False)]
        bits=step['bits'][::-1]
        if len(bits)!=sum(s['width'] for s in active):raise ValueError('incomplete witness step')
        cursor=0;values={}
        for signal in active:
            width=signal['width'];raw=bits[cursor:cursor+width][::-1];cursor+=width
            path=signal['path']
            if len(path)==1 and path[0].lstrip('\\') in required:
                name=path[0].lstrip('\\')
                if name in values or signal['offset']!=0 or width!=required[name] or any(b not in '01' for b in raw):raise ValueError('unknown/duplicate/split top input')
                values[name]=int(raw,2)
        if values.keys()!=required.keys():raise ValueError('top-level inputs missing')
        rows.append([values[n] for n in ('rst_n','valid','ready','data')])
    if len(rows)<2 or rows[0][0]!=0:raise ValueError('trace must begin with reset and reach a checked state')
    return rows

def oracle(inputs,depth):
    queue=deque();rows=[]
    for reset,valid,ready,data in inputs:
        ir=int(len(queue)<depth);ov=int(bool(queue));value=queue[0] if queue else 0
        rows.append([reset,valid,ready,data,ir,ov,value])
        if not reset:queue.clear()
        else:
            if ready and ov:queue.popleft()
            if valid and ir:queue.append(data)
    return rows

def run(args):
    inputs=[Path(__file__),HERE/'replay_tb.sv',RTL,FORMAL/'run.py',FORMAL/'equivalence_formal.sv',HERE.parent/'local-formal-common/runner.py']
    names=[f'depth{d}-mutation{m}-{part}' for d in (2,4) for m in (1,2,3,4) for part in ('formal','replay','fixed')]
    e=E.Evidence('local-formal-replay',args,inputs,dict(depths=[2,4],mutations=[1,2,3,4],drive='top inputs only; no internal state forcing'),names)
    os.environ['PATH']=str(Path(args.formal_python).absolute().parent)+os.pathsep+os.environ.get('PATH','')
    for depth in (2,4):
        for mutation in (1,2,3,4):
            name=f'depth{depth}-mutation{mutation}';out=e.out/name;out.mkdir()
            child=out/'formal';command=[args.formal_python,str(FORMAL/'run.py'),'--configuration',f'depth{depth}','--task',f'detect-mutation{mutation}','--out',str(child)]
            execution=E.P.execute(command,out/'formal.log',args.formal_timeout,out);valid=False;record=None;trace=None
            try:
                summary=json.loads((child/'summary.json').read_text());record=summary['results'][0]
                valid=execution['error'] is None and execution['returncode']==0 and summary['success'] is True and summary['planned']==len(summary['results'])==1 and record['outcome']=='detected'
                candidates=sorted((child/record['id']/'task/engine_0').glob('trace*.yw'))
                if len(candidates)!=1:raise ValueError('expected one bounded counterexample witness')
                trace=candidates[0];rows=oracle(witness_inputs(json.loads(trace.read_text())),depth)
            except (OSError,ValueError,KeyError,TypeError,IndexError) as exc:valid=False;record=str(exc)
            e.check(name+'-formal',valid,record)
            if not valid:
                e.check(name+'-replay',False,'no valid formal trace');e.check(name+'-fixed',False,'no valid formal trace');continue
            E.P.write_json(out/'reproducer.json',dict(depth=depth,source_witness=str(trace.relative_to(e.out)),inputs=[r[:4] for r in rows],rows=rows))
            vectors=out/'vectors.txt';vectors.write_text(''.join(' '.join(format(v,'x') for v in r)+'\n' for r in rows))
            for label,bug in [('replay',mutation),('fixed',0)]:
                directory=out/label;directory.mkdir();binary=directory/'sim.vvp'
                build=E.P.execute([args.iverilog,'-g2012','-s','replay_tb',f'-Preplay_tb.DEPTH={depth}',f'-Preplay_tb.MUTATION={bug}','-o',str(binary),str(RTL),str(HERE/'replay_tb.sv')],directory/'build.log',args.timeout,directory)
                if build['error'] or build['returncode']!=0:
                    result=dict(error='build failed',returncode=None);(directory/'simulation.log').write_text('build failed\n')
                else:result=E.P.execute([args.vvp,str(binary),'+VECTORS='+str(vectors),'+WAVE='+str(directory/'wave.vcd')],directory/'simulation.log',args.timeout,directory)
                case=dict(checks=len(rows),expected_failure=('ap_control' if mutation in (1,3) else 'ap_data') if bug else None)
                log=(directory/'simulation.log').read_text();status,message=E.P.classify(case,result,log)
                ok=status==('detected' if bug else 'pass')
                if ok and (not (directory/'wave.vcd').exists() or '$enddefinitions' not in (directory/'wave.vcd').read_text()):ok=False
                E.P.write_json(directory/'result.json',dict(status=status,message=message,build=build,**result));e.check(name+'-'+label,ok,message)
    return e.finish()

def main():
    p=E.parser(__doc__,'local-formal-replay');p.add_argument('--formal-python',required=True);p.add_argument('--formal-timeout',type=float,default=300);args=p.parse_args();E.validate(p,args)
    import math
    if not math.isfinite(args.formal_timeout) or args.formal_timeout<=0:p.error('positive formal timeout required')
    try:return run(args)
    except (OSError,ValueError,KeyError,TypeError) as exc:print('RUNNER_ERROR',exc,file=sys.stderr);return 1
if __name__=='__main__':sys.exit(main())

#!/usr/bin/env python3
"""Arithmetic, dual-clock FIFO, streaming video, and fixed-timing display regression."""
import importlib.util
import json
import math
from pathlib import Path
import random
import re
import sys

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
spec=importlib.util.spec_from_file_location('video_evidence',HERE.parent/'local-exploration-common/evidence.py')
E=importlib.util.module_from_spec(spec);spec.loader.exec_module(E)
M=E.load('video_image_model',HERE/'model.py')
C=E.load('video_image_compare',HERE/'compare.py')
RTL=sorted((HERE/'rtl').glob('*.sv'))
CHECKER=HERE/'tb/video_fifo_checker.sv'
PIPELINE_SOURCES=[*RTL,CHECKER,HERE/'tb/pipeline_tb.sv']
FIFO_SOURCES=[HERE/'rtl/video_reset_sync.sv',HERE/'rtl/video_async_fifo.sv',CHECKER,HERE/'tb/fifo_tb.sv']
ARITH_SOURCES=[HERE/'rtl'/f'video_{name}.sv' for name in ('key','csc','blend')]+[HERE/'tb/arithmetic_tb.sv']
CASE_NAMES=('arithmetic','fifo-fast','fifo-slow','fifo-phase','fifo-fractional','fifo-same-edge',
    'stream-random','stream-small','stream-ratios','stream-reset','display-normal','display-slow',
    'display-clock-change','display-starve','display-clock-underflow','display-reset','display-tiny')


def scenario_goals(case):
    if case['kind']=='arithmetic':return {'math/key','math/csc','math/blend'}
    if case['kind']=='fifo':
        return {'fifo/order','fifo/backpressure','fifo/wrap'}|({'fifo/same-edge'} if case['id']=='fifo-same-edge' else set())
    p=case['parameters'];goals={'stream/metadata'}
    if p.get('STALLS'):goals.add('stream/stalls')
    if p.get('DISPLAY'):goals.update(('display/fixed','display/prefill'))
    if case['id']=='display-slow':goals.add('display/slow')
    if p.get('CHANGE_OK'):goals.add('clock/change-safe')
    if p.get('UNDERFLOW_KIND'):goals.add('display/underflow')
    if p.get('RESET_TEST') or p.get('UNDERFLOW_KIND'):goals.add('reset/busy')
    return goals


def plans(a):
    cases=[]
    def add(name,kind,**kw):
        if not a.case or name in a.case:cases.append(dict(id=name,kind=kind,seed=a.seed,**kw))
    add('arithmetic','arithmetic')
    for name,depth,periods,phases in (
        ('fifo-fast',4,(10,17),(0,0)),('fifo-slow',8,(17,10),(1,3)),
        ('fifo-phase',4,(10,10),(0,3)),('fifo-fractional',8,(13,17),(0.5,2)),
        ('fifo-same-edge',4,(10,10),(0,0))):
        add(name,'fifo',parameters=dict(DEPTH=depth),periods=periods,phases=phases)
    base=dict(W=a.width,H=a.height,FRAMES=a.frames,D0=a.depth0,D1=a.depth1,D2=a.depth2,PREFILL=a.prefill,
              H_FP=a.h_fp,H_SYNC=a.h_sync,H_BP=a.h_bp,V_FP=a.v_fp,V_SYNC=a.v_sync,V_BP=a.v_bp)
    clocks=(a.key_ns,a.csc_ns,a.blend_ns,a.pix_ns)
    phases=(a.key_phase,a.csc_phase,a.blend_phase,a.pix_phase)
    def pipe(name,parameters=None,periods=None,offsets=None):
        add(name,'pipeline',parameters=dict(base,**(parameters or {})),periods=periods or clocks,phases=offsets or phases)
    if not a.case or 'stream-random' in a.case:
        for seed in range(a.seed,a.seed+(3 if a.profile=='nightly' else 1)):
            rng=random.Random(seed)
            periods=clocks if seed==a.seed else tuple(rng.randrange(8,30) for _ in range(4))
            cases.append(dict(id=f'stream-random-{seed}',kind='pipeline',seed=seed,
                parameters=dict(base,DISPLAY=0,BUBBLES=1,STALLS=1),periods=periods,phases=phases))
    pipe('stream-small',dict(W=13,H=5,D0=4,D1=4,D2=8,DISPLAY=0,BUBBLES=1,STALLS=1))
    pipe('stream-ratios',dict(W=17,H=9,D0=4,D1=8,D2=16,DISPLAY=0,BUBBLES=1,STALLS=1),
         (19,11,27,13),(2.5,0,5,1))
    pipe('stream-reset',dict(W=17,H=9,D0=4,D1=8,D2=16,DISPLAY=0,BUBBLES=1,STALLS=1,RESET_TEST=1))
    pipe('display-normal',dict(DISPLAY=1))
    pipe('display-slow',dict(DISPLAY=1),(a.key_ns,a.pix_ns*1.1,a.blend_ns,a.pix_ns))
    pipe('display-clock-change',dict(DISPLAY=1,CHANGE_OK=1))
    pipe('display-starve',dict(DISPLAY=1,UNDERFLOW_KIND=1))
    pipe('display-clock-underflow',dict(DISPLAY=1,UNDERFLOW_KIND=2))
    pipe('display-reset',dict(DISPLAY=1,RESET_TEST=1))
    pipe('display-tiny',dict(W=2,H=2,D0=4,D1=4,D2=4,DISPLAY=1))
    return cases


def completion(log):
    markers=re.findall(r'^RESULT PASS checks=(\d+)$',log,re.M)
    pairs=re.findall(r'^COUNT ([a-z_]+)=(\d+)$',log,re.M)
    if len(markers)!=1 or int(markers[0])<=0 or 'CHECK_FAIL' in log or 'FATAL:' in log or 'WARNING:' in log or len(dict(pairs))!=len(pairs):
        raise ValueError('missing, duplicate, zero, or failed completion evidence')
    return int(markers[0]),{k:int(v) for k,v in pairs}


def context(case):
    return f"test={case['id']} seed={case['seed']} clocks={case.get('periods')} phases={case.get('phases')} parameters={case.get('parameters')}"


def simulate(a,case,directory):
    """Generate independent expectations, compile, execute and audit one complete case."""
    directory=directory.resolve();directory.mkdir(parents=True)
    kind=case['kind'];pars=case.get('parameters',{})
    top={'arithmetic':'arithmetic_tb','fifo':'fifo_tb','pipeline':'pipeline_tb'}[kind]
    sources={'arithmetic':ARITH_SOURCES,'fifo':FIFO_SOURCES,'pipeline':PIPELINE_SOURCES}[kind]
    plus=[]
    if kind=='arithmetic':
        rows=M.arithmetic_vectors(case['seed'])
        (directory/'vectors.txt').write_text(''.join(f'{op} {p:x} {v:x}\n' for op,p,v in rows))
        plus=['+VECTORS='+str(directory/'vectors.txt')]
    elif kind=='fifo':
        plus=[f'+{k}={v}' for k,v in zip(('WP','RP','WPHASE','RPHASE'),(*case['periods'],*case['phases']))]
    else:
        M.prepare(directory,pars['W'],pars['H'],pars['FRAMES'],case['seed'])
        plus=['+DIR='+str(directory),'+CASE='+case['id'],f"+SEED={case['seed']}"]
        plus += [f'+{k}={v}' for k,v in zip(('KEY_NS','CSC_NS','BLEND_NS','PIX_NS','KEY_PHASE','CSC_PHASE','BLEND_PHASE','PIX_PHASE'),(*case['periods'],*case['phases']))]
    if a.waves and kind!='arithmetic':plus.append('+WAVE='+str(directory/'trace.vcd'))
    inputs=sorted(directory.glob('*.hex'))+sorted(directory.glob('*.txt'))
    hashes={str(p):E.hashlib.sha256(p.read_bytes()).hexdigest() for p in [*sources,*inputs]}
    E.P.write_json(directory/'manifest.json',dict(case=case,source_sha256=hashes))
    binary=directory/'simulation.vvp'
    build=E.P.execute([a.iverilog,'-g2012','-s',top,'-o',str(binary),
        *[f'-P{top}.{k}={v}' for k,v in sorted(pars.items())],*map(str,sources)],directory/'build.log',a.timeout,directory)
    result=dict(case=case,build=build,success=False)
    if build['error'] or build['returncode']!=0:
        result['problem']='build failed';E.P.write_json(directory/'result.json',result);return result
    execution=E.P.execute([a.vvp,str(binary),*plus],directory/'simulation.log',a.timeout,directory)
    result['execution']=execution
    log=(directory/'simulation.log').read_text(errors='replace')
    try:
        checks,counts=completion(log);result.update(checks=checks,counts=counts)
        if execution['error'] or execution['returncode']!=0:raise ValueError('simulation execution failed')
        if kind=='arithmetic':
            if checks!=len(rows) or counts:raise ValueError('arithmetic count differs')
        elif kind=='fifo':
            expected={'writes','reads','full_waits','empty_waits','simultaneous','full_releases','empty_releases'}
            if set(counts)!=expected or counts['writes']!=512 or counts['reads']!=512 or checks!=512 or any(counts[n]==0 for n in ('full_waits','empty_waits','full_releases','empty_releases')):
                raise ValueError('FIFO transfer or boundary coverage differs')
            if case['id']=='fifo-same-edge' and counts['simultaneous']==0:raise ValueError('same-time read/write not observed')
        else:
            total=pars['W']*pars['H']*pars['FRAMES']
            epoch=int(bool(pars.get('RESET_TEST') or pars.get('UNDERFLOW_KIND')))
            if set(counts)!={'accepted_in','accepted_out','full_waits','max_level','reset_epochs','discarded'} or counts['accepted_in']!=total or counts['accepted_out']!=total or counts['reset_epochs']!=epoch:
                raise ValueError('pipeline completion counts differ')
            if epoch and (counts['discarded']==0 or 'RESET_DISCARD' not in log):raise ValueError('busy reset not observed')
            if pars.get('UNDERFLOW_KIND') and 'EXPECTED_ERROR display_underflow observed' not in log:raise ValueError('expected underflow not observed')
            if pars.get('CHANGE_OK') and 'CLOCK_CHANGE restored' not in log:raise ValueError('runtime clock change not completed')
            result['images']=C.compare(directory,pars['W'],pars['H'],pars['FRAMES'],case['seed'],epoch,context(case))
            E.P.write_json(directory/'image-summary.json',result['images'])
            if pars.get('UNDERFLOW_KIND') and result['images']['black_error_pixels']==0:raise ValueError('error black pixels missing')
        if a.waves and kind!='arithmetic' and '$enddefinitions' not in (directory/'trace.vcd').read_text():raise ValueError('waveform missing')
        changed=[p for p,h in hashes.items() if E.hashlib.sha256(Path(p).read_bytes()).hexdigest()!=h]
        if changed:raise ValueError('source/input changed during execution')
        result['success']=True
    except (ValueError,OSError,IndexError,KeyError) as exc:
        diagnostic=next((line for line in log.splitlines() if line.startswith('CHECK_FAIL ')),'')
        position=''
        if kind=='pipeline' and (match:=re.search(r'\bread=(\d+)',diagnostic)):
            index=int(match[1]);position=f"frame={index//(pars['W']*pars['H'])} x={index%pars['W']} y={(index//pars['W'])%pars['H']} "
        result['problem']=context(case)+' '+position+str(exc)+' '+diagnostic
        print('CASE_ERROR',result['problem'],flush=True)
    E.P.write_json(directory/'result.json',result)
    return result


def run(a):
    cases=plans(a)
    paths=[Path(__file__),HERE/'model.py',HERE/'compare.py',HERE/'requirements.json',*RTL,*sorted((HERE/'tb').glob('*.sv'))]
    e=E.Evidence('local-video-async',a,paths,dict(cases=cases),['toolchain',*[c['id'] for c in cases],'requirements','source-freshness'])
    probes={n:E.P.execute([getattr(a,n),'-V'],e.out/(n+'-version.log'),a.timeout,e.out) for n in ('iverilog','vvp')}
    E.P.write_json(e.out/'tools.json',probes)
    e.check('toolchain',all(not r['error'] and r['returncode']==0 for r in probes.values()),probes)
    results=[]
    for case in cases:
        result=simulate(a,case,e.out/case['id']);results.append(result);e.check(case['id'],result['success'],result)
    E.P.write_json(e.out/'executions.json',results)
    _,catalog_goals=E.C.catalog(HERE/'requirements.json')
    required=set().union(*(scenario_goals(c) for c in cases))
    hit=set().union(*(scenario_goals(r['case']) for r in results if r['success']))
    coverage=dict(scope='passed scenario evidence; not native covergroups, code coverage, or CDC signoff',
        required=sorted(required),hit=sorted(hit),missing=sorted(required-hit),not_selected=sorted(catalog_goals-required))
    E.P.write_json(e.out/'coverage.json',coverage)
    e.check('requirements',not (required-hit) and required<=catalog_goals and (bool(a.case) or required==catalog_goals),coverage)
    frozen=json.loads((e.out/'manifest.json').read_text())['source_sha256']
    changed=[p for p,h in frozen.items() if E.hashlib.sha256((ROOT/p).read_bytes()).hexdigest()!=h]
    e.check('source-freshness',not changed,changed)
    return e.finish()


def parser():
    p=E.parser(__doc__,'local-video-async')
    for name,default in (('width',64),('height',32),('frames',3),('depth0',16),('depth1',16),('depth2',128),('prefill',64),
                         ('h-fp',8),('h-sync',4),('h-bp',4),('v-fp',3),('v-sync',2),('v-bp',3)):
        p.add_argument('--'+name,type=int,default=default)
    for name,default in (('key-ns',10),('csc-ns',13),('blend-ns',17),('pix-ns',20),
                         ('key-phase',0),('csc-phase',1),('blend-phase',3),('pix-phase',7)):
        p.add_argument('--'+name,type=float,default=default)
    p.add_argument('--case',action='append',choices=CASE_NAMES)
    p.add_argument('--waves',action='store_true')
    return p


def main():
    p=parser();a=p.parse_args();E.validate(p,a)
    if not 0<=a.seed<=2**31-4:p.error('seed must fit three signed 32-bit seeds')
    if any(getattr(a,n)<1 for n in ('width','height','frames','prefill','h_fp','h_sync','h_bp','v_fp','v_sync','v_bp')) or a.width*a.height*a.frames>65536:
        p.error('positive dimensions/timings and at most 65536 pixels per generation required')
    if any(v<4 or v&(v-1) for v in (a.depth0,a.depth1,a.depth2)):p.error('FIFO depths must be powers of two, at least four')
    if any(not math.isfinite(getattr(a,n)) or getattr(a,n)<4 for n in ('key_ns','csc_ns','blend_ns','pix_ns')):
        p.error('clock periods must be finite and at least 4 ns')
    if any(not math.isfinite(getattr(a,n)) or getattr(a,n)<0 for n in ('key_phase','csc_phase','blend_phase','pix_phase')):
        p.error('phases must be finite and nonnegative')
    try:return run(a)
    except (OSError,ValueError,TypeError,KeyError) as exc:print('RUNNER_ERROR',exc,file=sys.stderr);return 1


if __name__=='__main__':sys.exit(main())

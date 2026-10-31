#!/usr/bin/env python3
"""Native RTL code coverage: measure gaps, add tests, merge and annotate."""
from collections import Counter
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import random
import re
import shutil
import sys
HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('code_evidence',HERE.parent/'local-exploration-common/evidence.py')
E=importlib.util.module_from_spec(spec);spec.loader.exec_module(E)
RTL=HERE/'rtl/command_unit.sv'
KINDS={'line','branch','expr','toggle','fsm_state','fsm_arc'}
CONFIGS={'width8':8,'width16':16}
FLAGS=['--coverage-line','--coverage-toggle','--coverage-expr','--coverage-fsm','--coverage-per-instance']

class Plan:
    # Transaction contract: modular sum or bitwise XOR; two execution edges then a held response.
    def __init__(self,width):self.mask=(1<<width)-1;self.rows=[];self.reset()
    def reset(self):self.stage='idle';self.answer=0;self.error=0;self.pending=None
    def cycle(self,rst=1,req=None,ready=1):
        can=int(rst and self.stage=='idle');valid=int(rst and self.stage=='response')
        command=(1,self.mask,0,0,1) if req is None else req
        self.rows.append([rst,int(req is not None),*command[:3],*command[3:],ready,can,valid,self.answer,self.error])
        if not rst:self.reset()
        elif self.stage=='idle' and req is not None:
            op,a,b,enable,authorized=req
            self.pending=(op,a,b);self.error=int(not (enable and authorized));self.stage='execute'
        elif self.stage=='execute':
            op,a,b=self.pending
            self.answer=0 if self.error else ((a^b) if op else (a+b)&self.mask)
            self.stage='response'
        elif self.stage=='response' and ready:self.stage='idle'
        return can
    def transfer(self,op,a,b,enable=1,authorized=1,hold=0):
        req=(op,a,b,enable,authorized)
        while not self.cycle(req=req):pass
        self.cycle(req=(1-op,b^self.mask,a^self.mask,0,0)) # busy inputs must not replace the captured command
        for _ in range(hold):self.cycle(ready=0)
        self.cycle();self.cycle()

def vectors(width,seed=17,iterations=0,supplement=False):
    p=Plan(width);p.cycle(rst=0);p.cycle()
    if not supplement:
        for a,b in ((1,2),(3,4),(0,0)):p.transfer(0,a,b)
    else:
        for op in (0,1):
            for a,b in ((p.mask,0),(0,p.mask),(p.mask,p.mask),(0,0),(p.mask,1)):
                p.transfer(op,a,b,hold=2)
        for enable,authorized in ((0,0),(0,1),(1,0)):
            p.transfer(1,p.mask,p.mask,enable,authorized,hold=2)
        # Cancel during each non-idle state; explicit reset activity remains in the measured interval.
        for enable in (0,1):
            p.cycle(req=(0,1,2,enable,1));p.cycle(rst=0);p.cycle()
        p.cycle(req=(0,1,2,1,1));p.cycle();p.cycle(rst=0);p.cycle()
        rng=random.Random(seed)
        for _ in range(iterations):p.transfer(rng.randrange(2),rng.randrange(p.mask+1),rng.randrange(p.mask+1),rng.randrange(2),rng.randrange(2),rng.randrange(4))
        p.transfer(0,0,0);p.cycle(rst=0);p.cycle()
    return p.rows

def point_id(meta):
    return json.dumps({k:v for k,v in meta.items() if k!='f'},sort_keys=True,separators=(',',':'))

def read_native(path):
    points={}
    for line in path.read_text().splitlines():
        if not line or line.startswith('#'):continue
        m=re.fullmatch(r"C '([^']*)' (\d+)",line)
        if not m:raise ValueError('CODE_FORMAT: malformed native counter')
        pairs=[field.split('\x02',1) for field in m[1].split('\x01') if field]
        if any(len(p)!=2 for p in pairs) or len(dict(pairs))!=len(pairs):raise ValueError('CODE_FORMAT: metadata')
        meta=dict(pairs)
        if Path(meta.get('f','')).resolve()!=RTL.resolve() or meta.get('t') not in KINDS:raise ValueError('CODE_IDENTITY: source/type')
        identity=point_id(meta)
        if identity in points:raise ValueError('CODE_INVENTORY: duplicate point')
        points[identity]=dict(metadata=meta,count=int(m[2]))
    if not points:raise ValueError('CODE_INVENTORY: no instrumentation')
    return points

def inventory_hash(points):return hashlib.sha256(('\n'.join(sorted(points))+'\n').encode()).hexdigest()

def validate_inventory(points,contract):
    if dict(Counter(p['metadata']['t'] for p in points.values()))!=contract['counts'] or inventory_hash(points)!=contract['inventory_sha256']:
        raise ValueError('CODE_INVENTORY: instrumentation differs from pinned plan')
    if set(contract['not_required'])-points.keys():raise ValueError('CODE_INVENTORY: exclusion missing')

def report(points,contract):
    validate_inventory(points,contract);result={}
    for kind in sorted(KINDS):
        items={k:p for k,p in points.items() if p['metadata']['t']==kind}
        required={k:p for k,p in items.items() if k not in contract['not_required']}
        missing=[k for k,p in required.items() if p['count']==0]
        result[kind]=dict(total=len(items),hit=sum(p['count']>0 for p in items.values()),required=len(required),required_hit=len(required)-len(missing),missing=missing,
          zero_points=[dict(id=k,metadata=p['metadata'],review=contract['not_required'].get(k,'required: add stimulus or investigate')) for k,p in items.items() if p['count']==0])
    return result

def require_covered(points,contract):
    r=report(points,contract)
    if any(not s['required'] or s['missing'] for s in r.values()):raise ValueError('CODE_UNCOVERED: required code points missing')
    return r

def merge_counts(inputs):
    if not inputs or not inputs[0]:raise ValueError('CODE_MERGE: empty inputs')
    if any(p.keys()!=inputs[0].keys() for p in inputs):raise ValueError('CODE_MERGE: incompatible inventories')
    return {k:sum(p[k]['count'] for p in inputs) for k in inputs[0]}

def check_simulation(ex,log,rows,wave,expect_data_error=False):
    if ex['error'] or re.findall(r'^COUNT steps=(\d+)$',log,re.M)!=[str(len(rows))]:raise ValueError('CODE_EXECUTION: incomplete process/count')
    if not wave.is_file() or '$enddefinitions' not in wave.read_text():raise ValueError('CODE_EXECUTION: waveform missing')
    if expect_data_error:
        if ex['returncode']!=1 or re.findall(r'^CHECK_FAIL (\S+)$',log,re.M)!=['CODE_DATA'] or not re.search(rf'^RESULT FAIL checks={len(rows)} failures=[1-9]\d*$',log,re.M):raise ValueError('CODE_EXECUTION: expected data mismatch not observed')
    elif ex['returncode']!=0 or re.findall(r'^RESULT PASS checks=(\d+)$',log,re.M)!=[str(len(rows))] or 'CHECK_FAIL' in log:raise ValueError('CODE_EXECUTION: functional comparison failed')

def resolve_tool(command):
    found=shutil.which(command);return str(Path(found).resolve()) if found else command

def check_sources(manifest):
    sources=json.loads(manifest.read_text())['source_sha256']
    if not sources:raise ValueError('CODE_IDENTITY: source manifest empty')
    for name,digest in sources.items():
        if hashlib.sha256((HERE.parents[1]/name).read_bytes()).hexdigest()!=digest:
            raise ValueError('CODE_IDENTITY: source changed during run: '+name)

def run(args):
    plan=json.loads((HERE/'coverage-plan.json').read_text())
    if hashlib.sha256(RTL.read_bytes()).hexdigest()!=plan['rtl_sha256']:raise ValueError('CODE_PLAN: RTL changed; review instrumentation and requirements')
    configs=CONFIGS if args.configuration=='all' else {args.configuration:CONFIGS[args.configuration]}
    seeds=list(range(args.seed,args.seed+(3 if args.profile=='nightly' else 1)))
    stages=['build','baseline','baseline-gap',*[f'supplement-seed{s}' for s in seeds],'merge','closure','annotate','build-mutant','coverage-with-wrong-data','build-uninstrumented','reject-uninstrumented']
    e=E.Evidence('local-code-coverage',args,[Path(__file__),HERE/'coverage-plan.json',HERE/'sim_main.cpp',RTL],dict(configurations=configs,seeds=seeds,coverage_plan=plan),[f'{cfg}-{stage}' for cfg in configs for stage in stages]+['source-identity'])
    E.P.write_json(e.out/'tools.json',{name:E.P.execute([tool,'--version'],e.out/(name+'-version.log'),args.timeout,e.out) for name,tool in [('verilator',args.verilator),('coverage',args.coverage_tool)]})
    executions=[]
    def build(cfg,width,mode):
        path=e.out/f'{cfg}-{mode}-build'
        cmd=[args.verilator,'--cc','--exe','--build','--trace','-j',str(args.jobs),'--top-module','command_unit','--Mdir',str(path),f'-GWIDTH={width}',f'-GMUTATION={int(mode=="mutant")}',*([] if mode=='uninstrumented' else FLAGS),str(RTL),str(HERE/'sim_main.cpp')]
        b=E.P.execute(cmd,e.out/f'{cfg}-{mode}-build.log',args.build_timeout,e.out);E.P.write_json(e.out/f'{cfg}-{mode}-build.json',b)
        ok=not b['error'] and b['returncode']==0;e.check(cfg+'-'+('build' if mode=='normal' else 'build-'+mode),ok,b);return path/'Vcommand_unit',ok
    def simulate(cfg,name,binary,built,rows,contract,mode='normal'):
        d=e.out/f'{cfg}-{name}';d.mkdir();v=d/'vectors.txt';wave=d/'wave.vcd'
        v.write_text(''.join(' '.join(format(n,'x') for n in row)+'\n' for row in rows))
        if built:ex=E.P.execute([str(binary),str(v),str(wave)],d/'simulation.log',args.timeout,d)
        else:ex=dict(error='build failed',returncode=None);(d/'simulation.log').write_text('build failed\n')
        ok=False;message='';points={};stats={}
        try:
            check_simulation(ex,(d/'simulation.log').read_text(errors='replace'),rows,wave,mode=='mutant')
            if mode=='uninstrumented':
                if (d/'coverage.dat').exists():raise ValueError('CODE_INVENTORY: unexpected DB in uninstrumented build')
                try:read_native(d/'coverage.dat')
                except FileNotFoundError:ok=True;message='instrumentation absence rejected after successful functional simulation'
            else:
                points=read_native(d/'coverage.dat');stats=report(points,contract)
                if mode=='mutant':require_covered(points,contract)
                ok=True
        except (OSError,ValueError,KeyError,TypeError) as exc:message=str(exc)
        record=dict(id=f'{cfg}-{name}',success=ok,credited=ok and mode=='normal',mode=mode,metrics=stats,message=message,**ex)
        E.P.write_json(d/'result.json',record);executions.append(record);e.check(cfg+'-'+name,ok,message)
        return d,points if record['credited'] else None
    for cfg,width in configs.items():
        contract=plan['configurations'][cfg];binary,built=build(cfg,width,'normal')
        baseline=vectors(width);d,base=simulate(cfg,'baseline',binary,built,baseline,contract)
        gap=base is not None and any(s['missing'] for s in report(base,contract).values());e.check(cfg+'-baseline-gap',gap,'baseline must leave required code points unhit')
        sources=[d];points=[base] if base else []
        for seed in seeds:
            rows=vectors(width,seed,100 if args.profile=='nightly' else 8,True)
            d,p=simulate(cfg,f'supplement-seed{seed}',binary,built,rows,contract);sources.append(d)
            if p:points.append(p)
        merged_path=e.out/f'{cfg}-merged.dat';merged={};merge_ok=False
        try:
            if len(points)!=1+len(seeds):raise ValueError('CODE_MERGE: only successful complete normal cases may merge')
            expected=merge_counts(points)
            m=E.P.execute([args.coverage_tool,'--write',str(merged_path),*[str(d/'coverage.dat') for d in sources]],e.out/f'{cfg}-merge.log',args.timeout,e.out)
            if m['error'] or m['returncode']!=0:raise ValueError('CODE_MERGE: tool failed')
            merged=read_native(merged_path);validate_inventory(merged,contract)
            if {k:p['count'] for k,p in merged.items()}!=expected:raise ValueError('CODE_MERGE: summed native counters differ')
            merge_ok=True
        except (OSError,ValueError,KeyError,TypeError) as exc:message=str(exc)
        e.check(cfg+'-merge',merge_ok,dict(inputs=[str(d) for d in sources]) if merge_ok else message)
        try:
            if not merge_ok:raise ValueError('CODE_MERGE: unavailable')
            stats=require_covered(merged,contract);e.check(cfg+'-closure',True,stats)
        except (ValueError,KeyError,TypeError) as exc:stats={};e.check(cfg+'-closure',False,str(exc))
        E.P.write_json(e.out/f'{cfg}-coverage.json',dict(metrics=stats,all_points=merged,not_required=contract['not_required']))
        a=E.P.execute([args.coverage_tool,'--annotate',str(e.out/f'{cfg}-annotated'),'--annotate-all','--annotate-points','--annotate-min','1',str(merged_path)],e.out/f'{cfg}-annotate.log',args.timeout,e.out) if merge_ok else dict(error='no merge',returncode=None)
        annotated=e.out/f'{cfg}-annotated'/RTL.name
        e.check(cfg+'-annotate',not a['error'] and a['returncode']==0 and annotated.is_file() and 'point: type=' in annotated.read_text(),a)
        mutant,ok=build(cfg,width,'mutant')
        simulate(cfg,'coverage-with-wrong-data',mutant,ok,baseline+vectors(width,supplement=True),contract,'mutant')
        off,ok=build(cfg,width,'uninstrumented')
        simulate(cfg,'reject-uninstrumented',off,ok,baseline,contract,'uninstrumented')
    try:check_sources(e.out/'manifest.json');e.check('source-identity',True,'source hashes unchanged')
    except (OSError,ValueError,KeyError,TypeError) as exc:e.check('source-identity',False,str(exc))
    E.P.write_json(e.out/'executions.json',executions);return e.finish()

def main():
    p=E.parser(__doc__,'local-code-coverage');p.add_argument('--configuration',choices=['all',*CONFIGS],default='all');p.add_argument('--verilator',default='verilator');p.add_argument('--coverage-tool',default='verilator_coverage');p.add_argument('--jobs',type=int,default=4);p.add_argument('--build-timeout',type=float,default=180)
    args=p.parse_args();E.validate(p,args)
    if args.jobs<1 or not math.isfinite(args.build_timeout) or args.build_timeout<=0:p.error('positive jobs/build timeout required')
    args.verilator=resolve_tool(args.verilator);args.coverage_tool=resolve_tool(args.coverage_tool)
    try:return run(args)
    except (OSError,ValueError,KeyError,TypeError) as exc:print('RUNNER_ERROR',exc,file=sys.stderr);return 1
if __name__=='__main__':sys.exit(main())

#!/usr/bin/env python3
"""Single-port, 1R1W, and true dual-port RAM with byte/word address bug detection."""
import importlib.util
import json
from pathlib import Path
import re
import sys

HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1]
spec=importlib.util.spec_from_file_location('ram_evidence',HERE.parent/'local-exploration-common/evidence.py')
E=importlib.util.module_from_spec(spec);spec.loader.exec_module(E)
M=E.load('ram_byte_oracle',HERE/'model.py')
RTL=sorted((HERE/'rtl').glob('*.sv'));SOURCES=[*RTL,HERE/'tb/ram_ports_tb.sv']
MODES=('read-first','write-first','no-change')
COMMON={'access/read','access/write','address/word','address/byte','address/misaligned','address/range',
        'bounds/first','bounds/last','data/partial','data/zero-mask','reset/retained','timing/idle-hold','timing/registered-response'}


def configurations(a):
    result={}
    def add(prefix,kind,mode,width,depth,base=None):
        result[f'{prefix}-w{width}-d{depth}']=dict(DATA_W=width,DEPTH=depth,KIND=kind,RDW_MODE=mode,BASE_ADDR=a.base if base is None else base)
    add('sp',0,0,a.width,a.depth)
    for kind,label in ((1,'1r1w'),(2,'tdp')):
        for mode in range(3):add(label+'-'+MODES[mode],kind,mode,a.width,a.depth)
    for kind,label in ((0,'sp'),(1,'1r1w'),(2,'tdp')):add('wide-'+label,kind,0 if kind==0 else 1,64,8)
    add('odd-tdp',2,1,32,13)
    add('offset-tdp',2,1,32,16,264)
    return result


def required_goals(pars):
    required=set(COMMON);kind=pars['KIND']
    if kind<2:required.add('port/rejected')
    if kind!=0:required.update(('concurrent/read-write','collision/read-write','rdw/'+MODES[pars['RDW_MODE']]))
    if kind==2:required.update(('concurrent/two-read','concurrent/two-write','collision/write-reject'))
    return required


def rows_for(pars,seed,count):
    return M.stimulus(pars['DATA_W'],pars['DEPTH'],pars['KIND'],pars['RDW_MODE'],pars['BASE_ADDR'],seed,count)


def counts_for(rows):
    counts=dict(rows=len(rows),reads=0,writes=0,errors=0,collisions=0,resets=0);old=0
    for row in rows:
        counts['resets']+=int(bool(old and not row[0]));old=row[0]
        if not row[0]:continue
        counts['collisions']+=row[17]
        for valid,write,error in ((row[1],row[2],row[15]),(row[7],row[8],row[16])):
            if valid:
                if error:counts['errors']+=1
                else:counts['writes' if write else 'reads']+=1
    return counts


def completion(log,expected):
    pairs=re.findall(r'^COUNT ([a-z_]+)=(\d+)$',log,re.M)
    if len(pairs)!=len(dict(pairs)) or {k:int(v) for k,v in pairs}!=expected:
        raise ValueError('completion counts differ')
    if 'WARNING:' in log:raise ValueError('unexpected simulation warning')


class Simulator:
    def __init__(self,a,out):self.args=a;self.out=out.resolve();self.builds={};self.records=[]

    def execute(self,name,pars,rows,seed,mutation=0,label=None):
        d=self.out/name;d.mkdir(parents=True)
        vectors=d/'vectors.txt';vectors.write_text(''.join(' '.join(f'{v:x}' for v in row)+'\n' for row in rows))
        counts=counts_for(rows);parameters=dict(pars,MUTATION=mutation)
        hashes={str(p):E.hashlib.sha256(p.read_bytes()).hexdigest() for p in [*SOURCES,vectors]}
        E.P.write_json(d/'manifest.json',dict(parameters=parameters,seed=seed,expected_failure=label,counts=counts,source_sha256=hashes))
        key='-'.join(f'{k}{v}' for k,v in sorted(parameters.items()))
        if key not in self.builds:
            binary=self.out/(key+'.vvp')
            build=E.P.execute([self.args.iverilog,'-g2012','-s','ram_ports_tb','-o',str(binary),
                *[f'-Pram_ports_tb.{k}={v}' for k,v in parameters.items()],*map(str,SOURCES)],self.out/(key+'-build.log'),self.args.timeout,self.out)
            self.builds[key]=(binary,build)
        binary,build=self.builds[key]
        if build['error'] or build['returncode']!=0:
            execution=dict(returncode=None,error='build failed');(d/'simulation.log').write_text('build failed\n')
        else:
            command=[self.args.vvp,str(binary),'+VECTORS='+str(vectors),f'+CHECKS={len(rows)}',f'+SEED={seed}','+CASE='+name]
            if self.args.waves:command.append('+WAVE='+str(d/'trace.vcd'))
            execution=E.P.execute(command,d/'simulation.log',self.args.timeout,d)
        log=(d/'simulation.log').read_text(errors='replace')
        status,message=E.P.classify(dict(checks=len(rows),expected_failure=label),execution,log)
        try:
            if status=='pass':completion(log,counts)
            if status in ('pass','detected') and self.args.waves and '$enddefinitions' not in (d/'trace.vcd').read_text():raise ValueError('waveform missing')
            if any(E.hashlib.sha256(Path(p).read_bytes()).hexdigest()!=h for p,h in hashes.items()):raise ValueError('source/input changed')
        except (ValueError,OSError) as exc:status,message='error',str(exc)
        result=dict(id=name,parameters=parameters,seed=seed,status=status,message=message,counts=counts,
            coverage=sorted(set(re.findall(r'^COVER (\S+)$',log,re.M))) if status=='pass' and mutation==0 else [],build=build,execution=execution)
        E.P.write_json(d/'result.json',result);self.records.append(result);return result


def run(a):
    configs=configurations(a);seeds=list(range(a.seed,a.seed+(3 if a.profile=='nightly' else 1)))
    variants=list(configs.items())
    standard_new=next((name,pars) for name,pars in variants if pars['KIND']==2 and pars['RDW_MODE']==1)
    wide_new=next((name,pars) for name,pars in variants if name.startswith('wide-tdp'))
    offset_new=next((name,pars) for name,pars in variants if name.startswith('offset-tdp'))
    mutations=[(i,wide_new if i==3 else offset_new if i==12 else standard_new,'RAM_STATUS' if i in (4,5,10) else 'RAM_DATA') for i in range(1,13)]
    ids=['toolchain',*[f'{name}/seed{seed}' for name in configs for seed in seeds],
         *[f'{name}/coverage' for name in configs],*[f'mutation-{i}' for i,_,_ in mutations],'source-freshness']
    e=E.Evidence('local-ram-ports',a,[Path(__file__),HERE/'model.py',HERE/'requirements.json',*SOURCES],dict(configurations=configs,seeds=seeds),ids)
    probes={n:E.P.execute([getattr(a,n),'-V'],e.out/(n+'-version.log'),a.timeout,e.out) for n in ('iverilog','vvp')}
    E.P.write_json(e.out/'tools.json',probes);e.check('toolchain',all(not r['error'] and r['returncode']==0 for r in probes.values()),probes)
    sim=Simulator(a,e.out);_,catalog=E.C.catalog(HERE/'requirements.json');coverage={}
    for name,pars in configs.items():
        for seed in seeds:
            rows=rows_for(pars,seed,384 if a.profile=='nightly' else 96)
            r=sim.execute(f'{name}/seed{seed}',pars,rows,seed);e.check(r['id'],r['status']=='pass',r)
        hits=set(g for r in sim.records if r['id'].startswith(name+'/') for g in r['coverage'])
        required=required_goals(pars);coverage[name]=dict(required=sorted(required),hit=sorted(hits),missing=sorted(required-hits))
        e.check(name+'/coverage',not (required-hits) and required<=catalog,coverage[name])
    for mutation,(_,pars),label in mutations:
        r=sim.execute(f'mutation-{mutation}',pars,rows_for(pars,a.seed,0),a.seed,mutation,label)
        e.check(r['id'],r['status']=='detected',r)
    E.P.write_json(e.out/'executions.json',sim.records);E.P.write_json(e.out/'coverage.json',coverage)
    frozen=json.loads((e.out/'manifest.json').read_text())['source_sha256']
    changed=[p for p,h in frozen.items() if E.hashlib.sha256((ROOT/p).read_bytes()).hexdigest()!=h]
    e.check('source-freshness',not changed,changed);return e.finish()


def main():
    p=E.parser(__doc__,'local-ram-ports')
    p.add_argument('--width',type=int,choices=(32,64),default=32);p.add_argument('--depth',type=int,default=16)
    p.add_argument('--base',type=lambda v:int(v,0),default=256);p.add_argument('--waves',action='store_true')
    a=p.parse_args();E.validate(p,a)
    if not 0<=a.seed<=2**31-4 or not 4<=a.depth<=256 or not 8<=a.base<=32768 or a.base%8:
        p.error('nonnegative 31-bit seed, depth 4..256, and eight-byte-aligned base 8..32768 required')
    try:return run(a)
    except (OSError,ValueError,TypeError,KeyError) as exc:print('RUNNER_ERROR',exc,file=sys.stderr);return 1


if __name__=='__main__':sys.exit(main())

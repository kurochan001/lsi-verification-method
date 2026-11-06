"""Bounded packet simulation, frozen generated inputs, and strict completion evidence."""
import importlib.util
import json
from pathlib import Path
import re
import sys

HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1]
def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(spec);sys.modules[name]=m;spec.loader.exec_module(m);return m
E=load('network_evidence',HERE.parent/'local-exploration-common/evidence.py')
MODEL=load('network_model',HERE/'model.py')


def validate_case(directory,expected,counts,soc=False,ram_frames=None):
    if expected!=counts:raise ValueError('completion counts differ: '+str(counts)+' expected '+str(expected))
    if soc:
        observed=[int(line,16) for line in (directory/'ram-readback.hex').read_text().splitlines()]
        if observed!=[v for frame in ram_frames for v in frame]:raise ValueError('CPU-produced RAM packet differs')
        if not (directory/'retirement.log').read_text().strip():raise ValueError('retirement trace missing')


class Simulator:
    def __init__(self,e,top,sources):self.e=e;self.top=top;self.sources=sources;self.builds={};self.records=[]
    def execute(self,name,parameters,frames,replies,rows,seed,counts,mutation=0,expected_failure=None,scenario=0,firmware=None,ram_frames=None,drops=None,admitted=(),plusargs=None):
        d=self.e.out/name;d.mkdir(parents=True)
        vectors=d/'vectors.txt';vectors.write_text(''.join(' '.join(f'{v:x}' for v in row)+'\n' for row in rows))
        drops=drops or dict(reasons=[],full=0,long=0)
        (d/'reasons.hex').write_text(''.join(f'{v:x}\n' for v in drops['reasons']))
        for prefix,packets in (('input',frames),('expected',replies),('admitted',admitted)):
            data=[bytes(f['data']) if isinstance(f,dict) else bytes(f) for f in packets]
            (d/(prefix+'.hex')).write_text(''.join(f'{v:02x}\n' for packet in data for v in packet))
            (d/(prefix+'-lengths.hex')).write_text(''.join(f'{len(packet):04x}\n' for packet in data))
        if firmware is not None:(d/'rom.hex').write_text(''.join(f'{v:08x}\n' for v in firmware))
        files=[vectors,*sorted(d.glob('*.hex'))]
        checks=1+sum(map(len,replies))
        E.P.write_json(d/'manifest.json',dict(parameters=parameters,seed=seed,scenario=scenario,mutation=mutation,checks=checks,
            expected_counts=counts,expected_failure=expected_failure,
            source_sha256={str(p):E.hashlib.sha256(p.read_bytes()).hexdigest() for p in files}))
        key='-'.join(f'{k}{v}' for k,v in sorted(dict(parameters,MUTATION=mutation).items()))
        if key not in self.builds:
            binary=self.e.out/(key+'.vvp')
            command=[self.e.args.iverilog,'-g2012','-s',self.top,'-o',str(binary),*[f'-P{self.top}.{k}={v}' for k,v in dict(parameters,MUTATION=mutation).items()],*map(str,self.sources)]
            self.builds[key]=binary,E.P.execute(command,self.e.out/(key+'-build.log'),self.e.args.timeout,self.e.out)
        binary,build=self.builds[key]
        command=[self.e.args.vvp,str(binary),'+VECTORS='+str(vectors),'+EXPECTED='+str(d/'expected.hex'),'+LENGTHS='+str(d/'expected-lengths.hex'),
                 '+ROM='+str(d/'rom.hex'),'+WAVE='+str(d/'trace.vcd'),'+TRACE='+str(d/'retirement.log'),'+RAMFILE='+str(d/'ram-readback.hex'),
                 f'+RX_FRAMES={counts["rx_frames"]}',f'+TX_FRAMES={counts["tx_frames"]}',f'+TX_BYTES={counts["tx_bytes"]}',f'+DROPS={counts["drops"]}',
                 f'+SCENARIO={scenario}',f'+SEED={seed}',f'+CHECKS={checks}',
                 '+REASONS='+str(d/'reasons.hex'),f'+REJECTED={len(drops["reasons"])}',f'+FULL_DROPS={drops["full"]}',f'+LONG_DROPS={drops["long"]}',
                 '+ADMITTED='+str(d/'admitted.hex'),'+ADMITTED_LENGTHS='+str(d/'admitted-lengths.hex'),f'+ADMITTED_FRAMES={len(admitted)}',*[f'+{k}={v}' for k,v in (plusargs or {}).items()]]
        if build['error'] or build['returncode']!=0:
            execution=dict(error='build failed: '+key+'-build.log',returncode=None,seconds=0);(d/'simulation.log').write_text(execution['error']+'\n')
        else:execution=E.P.execute(command,d/'simulation.log',self.e.args.timeout,d)
        log=(d/'simulation.log').read_text(errors='replace');status,message=E.P.classify(dict(checks=checks,expected_failure=expected_failure),execution,log)
        pairs=re.findall(r'^COUNT ([a-z_]+)=(\d+)$',log,re.M);observed={k:int(v) for k,v in pairs}
        if status=='pass':
            try:
                if len(pairs)!=len(observed):raise ValueError('duplicate counts')
                validate_case(d,counts,observed,firmware is not None,ram_frames)
            except (OSError,ValueError) as exc:status,message='error',str(exc)
        wave=d/'trace.vcd'
        if status in ('pass','detected') and (not wave.is_file() or '$enddefinitions' not in wave.read_text()):status,message='error','waveform missing'
        r=dict(id=name,parameters=parameters,seed=seed,scenario=scenario,mutation=mutation,status=status,message=message,checks=checks,
               expected_counts=counts,counts=observed,expected_failure=expected_failure,coverage=sorted(set(re.findall(r'^COVER (\S+)$',log,re.M))) if status=='pass' and mutation==0 else [],execution=execution)
        E.P.write_json(d/'result.json',r);self.records.append(r);self.e.check(name,status in ('pass','detected'),r);return r
    def save(self):
        E.P.write_json(self.e.out/'executions.json',self.records);E.P.write_json(self.e.out/'builds.json',{k:dict(binary=str(v[0]),execution=v[1]) for k,v in self.builds.items()})


def fresh(e):
    changed=[]
    for p in e.out.rglob('manifest.json'):
        for name,value in json.loads(p.read_text()).get('source_sha256',{}).items():
            if not (ROOT/name).is_file() or E.hashlib.sha256((ROOT/name).read_bytes()).hexdigest()!=value:changed.append(name)
    e.check('source-freshness',not changed,changed)

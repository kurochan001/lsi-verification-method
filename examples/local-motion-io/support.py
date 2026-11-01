"""Strict generated-vector evidence for motion I/O and closed-loop control examples."""
import importlib.util
import json
from pathlib import Path
import re
import sys
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1]
def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(spec);sys.modules[name]=m;spec.loader.exec_module(m);return m
E=load('motion_evidence',HERE.parent/'local-exploration-common/evidence.py')

def completion(log,expected):
    pairs=re.findall(r'^COUNT ([a-z_]+)=(\d+)$',log,re.M);actual={k:int(v) for k,v in pairs}
    if len(pairs)!=len(actual) or actual!=expected:raise ValueError('completion counts differ')
    return actual

class Simulator:
    def __init__(self,e,top,sources):self.e=e;self.top=top;self.sources=sources;self.builds={};self.records=[]
    def execute(self,name,pars,rows,expected,counts,seed,mutation=0,label=None):
        d=self.e.out/name;d.mkdir(parents=True)
        (d/'vectors.txt').write_text(''.join(' '.join(f'{v:x}' for v in row)+'\n' for row in rows))
        (d/'expected.hex').write_text(''.join(' '.join(f'{v:x}' for v in row)+'\n' for row in expected))
        files=[d/'vectors.txt',d/'expected.hex'];checks=len(rows)
        E.P.write_json(d/'manifest.json',dict(parameters=pars,seed=seed,mutation=mutation,checks=checks,expected_counts=counts,expected_failure=label,
            source_sha256={str(p):E.hashlib.sha256(p.read_bytes()).hexdigest() for p in files}))
        parameters=dict(pars,MUTATION=mutation);key='-'.join(f'{k}{v}' for k,v in sorted(parameters.items()))
        if key not in self.builds:
            binary=self.e.out/(key+'.vvp');command=[self.e.args.iverilog,'-g2012','-s',self.top,'-o',str(binary),*[f'-P{self.top}.{k}={v}' for k,v in parameters.items()],*map(str,self.sources)]
            self.builds[key]=binary,E.P.execute(command,self.e.out/(key+'-build.log'),self.e.args.timeout,self.e.out)
        binary,build=self.builds[key]
        command=[self.e.args.vvp,str(binary),'+VECTORS='+str(d/'vectors.txt'),'+EXPECTED='+str(d/'expected.hex'),'+WAVE='+str(d/'trace.vcd'),f'+CHECKS={checks}']
        if build['error'] or build['returncode']!=0:r=dict(error='build failed',returncode=None,seconds=0);(d/'simulation.log').write_text('build failed\n')
        else:r=E.P.execute(command,d/'simulation.log',self.e.args.timeout,d)
        log=(d/'simulation.log').read_text(errors='replace');status,message=E.P.classify(dict(checks=checks,expected_failure=label),r,log);actual={}
        if status=='pass':
            try:actual=completion(log,counts)
            except ValueError as exc:status,message='error',str(exc)
        wave=d/'trace.vcd'
        if status in ('pass','detected') and (not wave.is_file() or '$enddefinitions' not in wave.read_text()):status,message='error','waveform missing'
        result=dict(id=name,parameters=pars,seed=seed,mutation=mutation,status=status,message=message,checks=checks,expected_counts=counts,counts=actual,expected_failure=label,
            coverage=sorted(set(re.findall(r'^COVER (\S+)$',log,re.M))) if status=='pass' and mutation==0 else [],execution=r)
        E.P.write_json(d/'result.json',result);self.records.append(result);self.e.check(name,status in ('pass','detected'),result);return result
    def save(self):E.P.write_json(self.e.out/'executions.json',self.records);E.P.write_json(self.e.out/'builds.json',{k:dict(binary=str(v[0]),execution=v[1]) for k,v in self.builds.items()})

def fresh(e):
    changed=[]
    for p in e.out.rglob('manifest.json'):
        for name,sha in json.loads(p.read_text()).get('source_sha256',{}).items():
            f=ROOT/name
            if not f.is_file() or E.hashlib.sha256(f.read_bytes()).hexdigest()!=sha:changed.append(name)
    e.check('source-freshness',not changed,changed)

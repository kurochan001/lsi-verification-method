"""Verilator/C++ execution and strict, shared evidence for native model examples."""
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import re
import shlex
import shutil

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module
E=load('native_evidence',HERE.parent/'local-exploration-common/evidence.py')

def parser(description,name):
    p=E.parser(description,name)
    p.add_argument('--verilator',default='verilator')
    p.add_argument('--cxx',default='c++')
    p.add_argument('--build-timeout',type=float,default=600)
    return p

def validate(p,a):
    E.validate(p,a)
    if not math.isfinite(a.build_timeout) or a.build_timeout<=0 or a.seed>2**31-4:
        p.error('positive finite build timeout and seed 0..2^31-4 required')
    for name in ('verilator','cxx'):setattr(a,name,shutil.which(getattr(a,name)) or getattr(a,name))

def counts(log,expected):
    pairs=re.findall(r'^COUNT ([a-z_]+)=(\d+)$',log,re.M)
    if len(pairs)!=len(dict(pairs)) or {k:int(v) for k,v in pairs}!=expected:
        raise ValueError('missing, duplicate or incorrect completion counts')

class Native:
    def __init__(self,e,top,rtl,cpp):
        self.e=e;self.a=e.args;self.top=top;self.rtl=rtl;self.cpp=cpp
        self.builds={};self.records=[]

    def probes(self):
        results={n:E.P.execute(cmd,self.e.out/(n+'-version.log'),self.a.timeout,self.e.out)
                 for n,cmd in [('verilator',[self.a.verilator,'--version']),('cxx',[self.a.cxx,'--version'])]}
        good=all(not r['error'] and r['returncode']==0 for r in results.values())
        good=good and bool(re.fullmatch(r'Verilator 5\.052 [^\n]+\s*',(self.e.out/'verilator-version.log').read_text()))
        E.P.write_json(self.e.out/'tools.json',results)
        return good,results

    def build(self,cfg,parameters,mutation=0,flags=(),ldflags=()):
        key=(cfg,mutation)
        if key not in self.builds:
            d=self.e.out/'build'/f'{cfg}-m{mutation}';d.mkdir(parents=True)
            cppflags=['-std=c++17',*[f'-DCFG_{k}={v}' for k,v in parameters.items()],*flags]
            cmd=[self.a.verilator,'--cc','--exe','--build','-j','2','--trace','-Wno-fatal',
                 '--top-module',self.top,'--prefix','Vdut','--Mdir',str(d/'obj'),
                 '-MAKEFLAGS','CXX='+shlex.quote(self.a.cxx),'-CFLAGS',shlex.join(cppflags),
                 *([ '-LDFLAGS',shlex.join(ldflags)] if ldflags else []),
                 *[f'-G{k}={v}' for k,v in parameters.items()],f'-GMUTATION={mutation}',
                 *map(str,self.rtl),*map(str,self.cpp)]
            result=E.P.execute(cmd,d/'build.log',self.a.build_timeout,d)
            self.builds[key]=dict(binary=str(d/'obj/Vdut'),execution=result)
            E.P.write_json(d/'build.json',self.builds[key])
        return self.builds[key]

    def execute(self,identity,build,arguments,expected_counts,checks,label=None,credited=True,validator=None):
        d=self.e.out/identity;d.mkdir(parents=True)
        E.P.write_json(d/'manifest.json',dict(arguments=list(map(str,arguments)),expected_counts=expected_counts,checks=checks,expected_failure=label,source_sha256={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in arguments if isinstance(p,Path) and p.is_file()}))
        if build['execution']['error'] or build['execution']['returncode']!=0:
            execution=dict(command=[],returncode=None,error='build failed',seconds=0)
            (d/'simulation.log').write_text('build failed\n')
        else:
            execution=E.P.execute([build['binary'],*map(str,arguments),str(d/'trace.vcd'),str(d/'trace.csv')],d/'simulation.log',self.a.timeout,d)
        log=(d/'simulation.log').read_text(errors='replace')
        status,message=E.P.classify(dict(checks=checks,expected_failure=label),execution,log)
        if status=='pass':
            try:counts(log,expected_counts);message=f'{checks} completed checks'
            except ValueError as err:status,message='error',str(err)
        if status in ('pass','detected'):
            wave=d/'trace.vcd';csv=d/'trace.csv'
            if not wave.is_file() or '$enddefinitions' not in wave.read_text(errors='replace') or not csv.is_file() or len(csv.read_text().splitlines())<2:
                status,message='error','missing waveform or sampled trace'
        extra={}
        if status=='pass' and validator is not None:
            try:extra=validator(d)
            except (OSError,ValueError,KeyError,TypeError) as err:status,message='error',str(err)
        goals=sorted(set(re.findall(r'^COVER (\S+)$',log,re.M))) if status=='pass' and credited else []
        result=dict(id=identity,status=status,message=message,expected_failure=label,expected_counts=expected_counts,checks=checks,coverage=goals,execution=execution,build=build['execution'],metrics=extra)
        E.P.write_json(d/'result.json',result);self.records.append(result)
        self.e.check(identity,status in ('pass','detected'),result)
        return result

    def save(self):
        E.P.write_json(self.e.out/'executions.json',self.records)
        E.P.write_json(self.e.out/'builds.json',{str(k):v for k,v in self.builds.items()})

def fresh(e,extra=()):
    records={}
    for manifest in e.out.rglob('manifest.json'):
        records.update(json.loads(manifest.read_text()).get('source_sha256',{}))
    changed=[n for n,h in records.items() if not (ROOT/n).is_file() or hashlib.sha256((ROOT/n).read_bytes()).hexdigest()!=h]
    e.check('source-freshness',not changed and not extra,[*changed,*extra])

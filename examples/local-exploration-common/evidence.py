"""Fail-closed evidence for local search, reduction and native UVM examples."""
import argparse
from datetime import datetime,timezone
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import re
import sys
import xml.etree.ElementTree as ET
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1]
def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
C=load('exploration_common_runner',HERE.parent/'local-common/runner.py');P=C.PROCESS

def parser(description,name):
    p=argparse.ArgumentParser(description=description)
    p.add_argument('--profile',choices=('smoke','nightly'),default='smoke');p.add_argument('--seed',type=int,default=17)
    p.add_argument('--timeout',type=float,default=30);p.add_argument('--iverilog',default='iverilog');p.add_argument('--vvp',default='vvp')
    p.add_argument('--out',type=Path,default=Path('artifacts')/datetime.now(timezone.utc).strftime(name+'-%Y%m%dT%H%M%S%fZ'))
    return p

def validate(p,a):
    if a.seed<0 or not math.isfinite(a.timeout) or a.timeout<=0:p.error('nonnegative seed and finite positive timeout required')
    if a.out.exists():p.error('output exists; choose a new --out')

class Evidence:
    def __init__(self,name,args,inputs,plan,check_ids):
        self.expected=list(check_ids)
        if not self.expected or len(set(self.expected))!=len(self.expected):raise ValueError('empty/duplicate check plan')
        self.name=name;self.args=args;self.out=args.out.resolve();self.out.mkdir(parents=True,exist_ok=False);self.results=[]
        paths={Path(__file__),Path(C.__file__),C.PROCESS_PATH,*map(Path,inputs)}
        P.write_json(self.out/'manifest.json',dict(name=name,python=sys.version,profile=args.profile,seed=args.seed,plan=plan,
            check_ids=self.expected,options={k:str(v) if isinstance(v,Path) else v for k,v in vars(args).items()},
            source_sha256={str(p.relative_to(ROOT) if p.is_relative_to(ROOT) else p):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(paths)}))
    def check(self,name,ok,detail):
        if name not in self.expected:raise ValueError('unplanned check: '+name)
        if any(r['id']==name for r in self.results):raise ValueError('duplicate check: '+name)
        self.results.append(dict(id=name,status='pass' if ok else 'fail',detail=detail));print('PASS' if ok else 'FAIL',name,flush=True);return bool(ok)
    def finish(self):
        completed={r['id'] for r in self.results}
        complete=completed==set(self.expected)
        for name in self.expected:
            if name not in completed:self.results.append(dict(id=name,status='fail',detail='planned check did not complete'))
        success=complete and all(r['status']=='pass' for r in self.results)
        P.write_json(self.out/'summary.json',dict(success=success,planned=len(self.expected),results=self.results,complete=complete))
        suite=ET.Element('testsuite',name=self.name,tests=str(len(self.results)),failures=str(sum(r['status']=='fail' for r in self.results)),errors='0')
        for r in self.results:
            case=ET.SubElement(suite,'testcase',name=r['id'],classname=self.name)
            if r['status']!='pass':ET.SubElement(case,'failure',message=str(r['detail']))
        ET.indent(suite);ET.ElementTree(suite).write(self.out/'junit.xml',encoding='utf-8',xml_declaration=True)
        print('Artifacts:',self.out,'\nRegression:','PASS' if success else 'FAIL');return 0 if success else 1

class AxisSimulator:
    def __init__(self,evidence):
        self.e=evidence;self.args=evidence.args;self.plugin=load('exploration_axis',HERE.parent/'local-axis/run.py');self.builds={};self.runs=[]
        probes={}
        for name,command in (('iverilog',[self.args.iverilog,'-V']),('vvp',[self.args.vvp,'-V'])):
            probes[name]=P.execute(command,self.e.out/(name+'-version.log'),self.args.timeout,self.e.out)
        P.write_json(self.e.out/'tools.json',probes)
    def execute(self,name,rows,mutation=0,expected=None,allow_clean=False):
        if mutation not in self.builds:
            binary=self.e.out/f'axis-m{mutation}.vvp'
            command=[self.args.iverilog,'-g2012','-s','axis_tb','-Paxis_tb.DEPTH=2',f'-Paxis_tb.MUTATION={mutation}','-o',str(binary),*map(str,self.plugin.SOURCES)]
            self.builds[mutation]=(binary,P.execute(command,self.e.out/f'build-m{mutation}.log',self.args.timeout,self.e.out))
        d=self.e.out/name;d.mkdir();vectors=d/'vectors.txt';vectors.write_text(''.join(' '.join(format(v,'x') for v in row)+'\n' for row in rows))
        case=dict(checks=len(rows),counts=self.plugin.counts(rows),expected_failure=expected)
        binary,build=self.builds[mutation]
        if build['error'] or build['returncode']!=0:
            execution=dict(returncode=None,error='build failed',seconds=0);(d/'simulation.log').write_text('build failed\n')
        else:execution=P.execute([self.args.vvp,str(binary),'+VECTORS='+str(vectors),'+WAVE='+str(d/'wave.vcd')],d/'simulation.log',self.args.timeout,d)
        log=(d/'simulation.log').read_text(errors='replace');status,message=P.classify(dict(case,expected_failure=None),execution,log) if allow_clean else P.classify(case,execution,log)
        if allow_clean and status!='pass':status,message=P.classify(case,execution,log)
        if status=='pass':
            pairs=re.findall(r'^COUNT ([a-z_]+)=(\d+)$',log,re.M)
            if len(pairs)!=len(dict(pairs)) or {k:int(v) for k,v in pairs}!=case['counts']:status='error';message='count evidence differs'
        if status in ('pass','detected') and (not (d/'wave.vcd').is_file() or '$enddefinitions' not in (d/'wave.vcd').read_text()):status='error';message='waveform missing'
        record=dict(id=name,status=status,message=message,expected_failure=expected,allow_clean=allow_clean,mutation=mutation,checks=len(rows),counts=case['counts'],
            coverage=sorted(set(re.findall(r'^COVER (\S+)$',log,re.M))) if status=='pass' and mutation==0 else [],**execution)
        P.write_json(d/'result.json',record);self.runs.append(record);return record
    def save(self):
        P.write_json(self.e.out/'executions.json',self.runs);P.write_json(self.e.out/'builds.json',{str(k):dict(binary=str(v[0]),**v[1]) for k,v in self.builds.items()})

def axis_inputs():
    base=HERE.parent/'local-axis'
    return [base/'run.py',base/'requirements.json',base/'rtl/axis_packet_fifo.sv',base/'tb/axis_tb.sv']

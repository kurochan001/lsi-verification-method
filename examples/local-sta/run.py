#!/usr/bin/env python3
"""Run real OpenSTA and reject violations, missing constraints and disappearing paths."""
import argparse
from datetime import datetime,timezone
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import re
import shutil
import sys
import xml.etree.ElementTree as ET

HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1]
PROCESS=HERE.parent/'local-irq-cdc/run.py'
spec=importlib.util.spec_from_file_location('sta_process',PROCESS)
P=importlib.util.module_from_spec(spec);spec.loader.exec_module(P)
CONTRACT=HERE/'contract.json'
SOURCES=[Path(__file__),PROCESS,CONTRACT,HERE/'toolchain.json',HERE/'check.tcl',*sorted((HERE/'design').glob('*'))]
LABELS={1:'STA_SETUP',2:'STA_HOLD',3:'STA_CONSTRAINT',4:'STA_PATH'}


def load_contract(path=CONTRACT):
    data=json.loads(path.read_text())
    if data.get('schema_version')!=1 or type(data.get('revision')) is not int or data['revision']<1:
        raise ValueError('invalid timing contract version')
    if data.get('paths')!=['input','internal','output'] or set(data.get('corners',{}))!={'fast','slow'}:
        raise ValueError('timing contract must contain all three paths and both corners')
    for corner in data['corners'].values():
        for mode in ('setup','hold'):
            values=corner.get(mode)
            if not isinstance(values,list) or len(values)!=3 or any(type(v) not in (int,float) or not math.isfinite(v) or v<0 for v in values):
                raise ValueError('timing contract needs three finite nonnegative slacks per mode')
        for field in ('period','input_min'):
            value=corner.get(field)
            if type(value) not in (int,float) or not math.isfinite(value) or value<0 or (field=='period' and value==0):
                raise ValueError('invalid timing contract constraint')
    return data


def judge(case,execution,log,contract):
    if execution['error']:return 'error',execution['error'],{}
    if re.search(r'^(?:Error:|TOOL_ERROR)',log,re.M):return 'error','tool reported an error',{}
    outcomes=re.findall(r'^RESULT STA (\w+) checks=(\d+)$',log,re.M)
    audits=re.findall(r'^AUDIT constraints ([01])$',log,re.M)
    slots={};missing=set()
    try:
        for name,mode,value in re.findall(r'^MEASURE (\w+) (min|max) (\S+)$',log,re.M):
            key=f'{name}/{mode}';value=float(value)
            if key in slots or not math.isfinite(value):raise ValueError('duplicate/nonfinite measurement')
            slots[key]=value
        for name,mode in re.findall(r'^MISSING (\w+) (min|max)$',log,re.M):
            key=f'{name}/{mode}'
            if key in missing or key in slots:raise ValueError('duplicate path record')
            missing.add(key)
        expected={f'{name}/{mode}' for name in contract['paths'] for mode in ('min','max')}
        if set(slots)|missing!=expected or len(outcomes)!=1 or outcomes[0][1]!='6' or len(audits)!=1:
            raise ValueError('incomplete or unexpected timing evidence')
    except ValueError as exc:return 'error',str(exc),slots
    label=outcomes[0][0]
    if execution['returncode']!=(0 if label=='PASS' else 1):return 'error','status/exit mismatch',slots
    # Recompute the verdict from the measurements, independently of Tcl's label.
    derived='STA_CONSTRAINT' if audits[0]=='0' else 'STA_PATH' if missing else 'STA_SETUP' if any(v<0 for k,v in slots.items() if k.endswith('/max')) else 'STA_HOLD' if any(v<0 for k,v in slots.items() if k.endswith('/min')) else 'PASS'
    if label!=derived:return 'error','label differs from measured evidence',slots
    if label!=case['expect']:return 'fail',f"expected {case['expect']}, got {label}",slots
    if case['category']=='mutation':
        if case['mutation']==4 and missing!={'internal/min','internal/max'}:return 'error','different path disappeared',slots
        return 'detected',f'confirmed {label}',slots
    corner=contract['corners'][case['configuration']]
    for mode,values in [('max',corner['setup']),('min',corner['hold'])]:
        if any(abs(slots[f'{path}/{mode}']-value)>0.00005 for path,value in zip(contract['paths'],values)):
            return 'fail','slack differs from independently calculated contract',slots
    return 'pass','six constrained path slacks agree',slots


def run(args):
    out=args.out.resolve();out.mkdir(parents=True,exist_ok=False)
    contract=load_contract();configs=contract['corners'] if args.configuration=='all' else {args.configuration:contract['corners'][args.configuration]}
    cases=[]
    for config in configs:
        cases.append(dict(id=config+'-normal',configuration=config,category='normal',mutation=args.demo_bug,expect='PASS'))
        for m,label in LABELS.items():cases.append(dict(id=f'{config}-detect-mutation{m}',configuration=config,category='mutation',mutation=m,expect=label))
    binary=shutil.which(args.sta)
    if binary:binary=str(Path(binary).resolve())
    command=binary or args.sta
    tool=P.execute([command,'-version'],out/'version.log',args.timeout,out)
    hashes={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in SOURCES}
    P.write_json(out/'manifest.json',dict(schema_version=1,created_at=datetime.now(timezone.utc).isoformat(),cases=cases,
        source_sha256=hashes,
        tool=dict(path=binary,sha256=hashlib.sha256(Path(binary).read_bytes()).hexdigest() if binary else None,version=(out/'version.log').read_text(),execution=tool)))
    results=[]
    for case in cases:
        directory=out/case['id'];directory.mkdir();config=case['configuration'];corner=configs[config];m=case['mutation']
        shutil.copy2(HERE/'design'/f'{config}.lib',directory/'cells.lib');shutil.copy2(HERE/'check.tcl',directory/'check.tcl')
        shutil.copy2(HERE/'design/constraints.tcl',directory/'constraints.tcl')
        netlist=(HERE/'design/pipeline.v').read_text()
        if m==2:netlist=netlist.replace('.D(b1)','.D(q0)')
        (directory/'pipeline.v').write_text(netlist)
        period=(0.3 if config=='fast' else 0.8) if m==1 else corner['period']
        (directory/'run.tcl').write_text(f"set period {period}\nset input_min {corner['input_min']}\nset mutation {m}\nsource check.tcl\n")
        execution=P.execute([command,'-no_init','-exit','run.tcl'],directory/'console.log',args.timeout,directory)
        status,message,slacks=judge(case,execution,(directory/'console.log').read_text(),contract)
        result=dict(**case,status=status,message=message,slacks=slacks,execution=execution)
        P.write_json(directory/'result.json',result);results.append(result);print(status.upper(),case['id'],message,flush=True)
    evidence_ok=not tool['error'] and tool['returncode']==0 and bool((out/'version.log').read_text().strip()) and all(
        hashlib.sha256((ROOT/name).read_bytes()).hexdigest()==digest for name,digest in hashes.items())
    success=evidence_ok and len(results)==len(cases) and all(r['status'] in ('pass','detected') for r in results)
    P.write_json(out/'summary.json',dict(success=success,evidence_ok=evidence_ok,planned=len(cases),results=results))
    suite=ET.Element('testsuite',name='opensta',tests=str(len(results)+1),failures=str(sum(r['status']=='fail' for r in results)),errors=str(sum(r['status']=='error' for r in results)+(not evidence_ok)))
    for r in results:
        node=ET.SubElement(suite,'testcase',name=r['id'],classname='opensta.'+r['configuration'])
        if r['status'] in ('fail','error'):ET.SubElement(node,'failure' if r['status']=='fail' else 'error',message=r['message'])
    gate=ET.SubElement(suite,'testcase',name='evidence',classname='opensta')
    if not evidence_ok:ET.SubElement(gate,'error',message='version acquisition or source hashes changed')
    ET.indent(suite);ET.ElementTree(suite).write(out/'junit.xml',encoding='utf-8',xml_declaration=True)
    print('Artifacts:',out,'\nSTA:', 'PASS' if success else 'FAIL');return 0 if success else 1


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    default=ROOT/'artifacts/toolchains/opensta-build/sta'
    parser.add_argument('--sta',default=str(default) if default.exists() else 'sta')
    parser.add_argument('--configuration',choices=('all','fast','slow'),default='all')
    parser.add_argument('--demo-bug',type=int,choices=range(5),default=0)
    parser.add_argument('--timeout',type=float,default=30)
    parser.add_argument('--out',type=Path,default=ROOT/'artifacts'/datetime.now(timezone.utc).strftime('sta-%Y%m%dT%H%M%S%fZ'))
    args=parser.parse_args()
    P.resolve_tools(args)
    if args.out.exists() or not math.isfinite(args.timeout) or args.timeout<=0:parser.error('requires a new output directory and finite positive timeout')
    try:return run(args)
    except (OSError,ValueError,KeyError) as exc:print('RUNNER_ERROR',exc,file=sys.stderr);return 1


if __name__=='__main__':sys.exit(main())

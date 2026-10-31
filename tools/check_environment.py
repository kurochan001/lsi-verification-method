#!/usr/bin/env python3
"""Diagnose the prepared docs, smoke or full open-source verification environment."""
import argparse
from datetime import datetime,timezone
import json
import math
import os
from pathlib import Path
import re
import shutil
import sys
import quality_common as Q
HERE=Path(__file__).resolve().parent
DOC_TOOLS={'git':['--version'],'node':['--version'],'npm':['--version']}
SIM_TOOLS={'iverilog':['-V'],'vvp':['-V'],'verilator':['--version'],'verilator_coverage':['--version'],'c++':['--version'],'cc':['--version'],'make':['--version']}
FORMAL_TOOLS={'yowasp-yosys':['--version'],'yowasp-sby':['--version'],'yowasp-yosys-smtbmc':['--help'],'yowasp-yosys-witness':['--help'],'z3':['--version'],'sta':['-version'],'llvm-mc':['--version'],'llvm-objcopy':['--version']}
def tool_plan(profile):return {**(DOC_TOOLS if profile in ('docs','full') else {}),**(SIM_TOOLS if profile in ('smoke','full') else {}),**(FORMAL_TOOLS if profile=='full' else {})}
def version_ok(name,output):
    if name=='node':return bool((m:=re.fullmatch(r'v(\d+)\.\d+\.\d+\s*',output)) and int(m[1])>=22)
    if name in ('iverilog','vvp'):return bool(re.search(r'Icarus Verilog(?: runtime)? version 14\.',output))
    if name in ('verilator','verilator_coverage'):return bool(re.fullmatch(r'Verilator 5\.052 [^\n]+\s*',output))
    if name=='sta':return bool(re.match(r'3\.1\.0\b',output.strip()))
    if name=='yowasp-yosys':return bool(re.search(r'Yosys 0\.70\b',output))
    if name=='z3':return bool(re.search(r'Z3 version 4\.15\.3\b',output))
    return bool(output.strip())
def package_command(python,requirements):
    code='import importlib,importlib.metadata,json,sys; names=json.loads(sys.argv[1]); [importlib.import_module(v["import"]) for v in names.values()]; print(json.dumps({"python":list(sys.version_info[:3]),"executable":sys.executable,"packages":{n:importlib.metadata.version(n) for n in names}}))'
    return [python,'-c',code,json.dumps(requirements)]
def guidance(name):
    if name in DOC_TOOLS:return 'Node.js 22以上・npm・Gitを準備し、npm ci --prefix tools/docs --ignore-scriptsを実行。'
    if name in SIM_TOOLS:return 'tools/ENVIRONMENT.mdのOS別ネイティブ依存と固定版Icarus/Verilatorを準備。'
    return '固定版のformal環境とOpenSTAを準備し、--formal-pythonと--tool-binの指定を確認。'
def uvm_snapshot(home,expected):
    paths=sorted(p for p in (home/'src').rglob('*') if p.is_file())
    observed={str(p.relative_to(home)):Q.digest(p) for p in paths}
    good=set(observed)=={n for n in expected if n.startswith('src/')} and all((home/n).is_file() and Q.digest(home/n)==h for n,h in expected.items())
    return good,observed
def run(a):
    config=json.loads((HERE/'environment.json').read_text());tools=tool_plan(a.profile)
    roles={'docs':(a.python,config['packages']['docs'])} if a.profile in ('docs','full') else {}
    if a.profile=='full':
        roles.update(simulation=(a.python,{'z3-solver':config['packages']['simulation']['z3-solver']}),rdl=(a.rdl_python,{'systemrdl-compiler':config['packages']['simulation']['systemrdl-compiler']}),cocotb=(a.cocotb_python,{'cocotb':config['packages']['simulation']['cocotb']}),formal=(a.formal_python,config['packages']['formal']))
    ids=['python',*['tool/'+n for n in tools],*['packages/'+r for r in roles]]
    if a.profile in ('docs','full'):ids+=['docs-runtime']
    if a.profile in ('smoke','full'):ids+=['cxx20','c11']
    if a.profile=='full':ids+=['uvm']
    ids+=['source-freshness']
    report=Q.Report('environment',a.out,[Path(__file__),HERE/'environment.json',HERE/'uvm-source-sha256.json',HERE/'docs/package.json',HERE/'docs/package-lock.json',HERE/'docs/check_mermaid.mjs',HERE/'docs-requirements.txt',HERE/'simulation-requirements.txt',Q.ROOT/'examples/local-fifo-formal/tools-requirements.txt'],ids,dict(profile=a.profile,python=a.python,formal_python=a.formal_python,tool_bin=[str(p) for p in a.tool_bin]))
    env_path=os.pathsep.join([*[str(p.absolute()) for p in a.tool_bin],str(Path(a.formal_python).absolute().parent),os.environ.get('PATH','')]);os.environ['PATH']=env_path
    r=Q.P.execute([a.python,'-c','import json,sys;print(json.dumps(list(sys.version_info[:3])))'],report.out/'python.log',a.timeout,report.out)
    try:py=json.loads((report.out/'python.log').read_text());ok=not r['error'] and r['returncode']==0 and isinstance(py,list) and tuple(py)>=tuple(config['python_minimum'][a.profile])
    except (ValueError,TypeError):py=None;ok=False
    report.check('python',ok,dict(execution=r,version=py,required=config['python_minimum'][a.profile]));observed={}
    for name,flags in tools.items():
        command=shutil.which(name) or name;r=Q.P.execute([command,*flags],report.out/(name.replace('+','p')+'.log'),a.timeout,report.out)
        output=(report.out/(name.replace('+','p')+'.log')).read_text(errors='replace')
        good=not r['error'] and r['returncode']==0 and version_ok(name,output)
        observed[name]=dict(execution=r,output=output,guidance=guidance(name));report.check('tool/'+name,good,observed[name])
    for role,(python,requirements) in roles.items():
        r=Q.P.execute(package_command(python,requirements),report.out/(role+'-packages.log'),a.timeout,report.out);data={}
        try:
            data=json.loads((report.out/(role+'-packages.log')).read_text());good=not r['error'] and r['returncode']==0 and data['packages']=={n:v['version'] for n,v in requirements.items()} and tuple(data['python'])>=tuple(config['python_minimum'][a.profile])
        except (ValueError,KeyError,TypeError):good=False
        report.check('packages/'+role,good,dict(execution=r,observed=data,expected=requirements,guidance='tools/setup_environment.pyで専用venvを準備し、各--*-pythonを指定。'))
    if a.profile in ('docs','full'):
        Q.write(report.out/'probe.json',[dict(id='probe',source='flowchart LR\n A-->B')])
        r=Q.P.execute([shutil.which('node') or 'node',str(HERE/'docs/check_mermaid.mjs'),str(report.out/'probe.json'),str(report.out/'probe-result.json')],report.out/'docs-runtime.log',a.timeout,report.out)
        try:good=not r['error'] and r['returncode']==0 and json.loads((report.out/'probe-result.json').read_text())==dict(success=True,results=[dict(id='probe',success=True)])
        except (OSError,ValueError):good=False
        report.check('docs-runtime',good,dict(execution=r,guidance='npm ci --prefix tools/docs --ignore-scripts'))
    if a.profile in ('smoke','full'):
        for label,compiler,extension,standard,source in [('cxx20','c++','cpp','c++20','#include <coroutine>\nstatic_assert(__cplusplus>=202002L);\nint main(){return 0;}\n'),('c11','cc','c','c11','_Static_assert(sizeof(int)>=4,"int width");\nint main(void){return 0;}\n')]:
            path=report.out/('probe.'+extension);path.write_text(source)
            r=Q.P.execute([shutil.which(compiler) or compiler,'-std='+standard,'-fsyntax-only',str(path)],report.out/(label+'.log'),a.timeout,report.out)
            report.check(label,not r['error'] and r['returncode']==0,r)
    if a.profile=='full':
        home=a.uvm_home.absolute();expected=json.loads((HERE/'uvm-source-sha256.json').read_text())['sha256']
        good,observed_uvm=uvm_snapshot(home,expected)
        report.check('uvm',good,dict(root=str(home),files=len(observed_uvm),guidance='examples/local-uvm/setup_uvm.pyで固定SHA-256の公式アーカイブを準備。'))
        Q.write(report.out/'uvm-source.json',dict(root=str(home),source_sha256=observed_uvm))
    Q.write(report.out/'tools.json',observed);changed=report.fresh();report.check('source-freshness',not changed,changed);return report.finish()
def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--profile',choices=('docs','smoke','full'),default='full');p.add_argument('--python',default=sys.executable);p.add_argument('--formal-python');p.add_argument('--rdl-python');p.add_argument('--cocotb-python');p.add_argument('--uvm-home',type=Path,default=Q.ROOT/'artifacts/toolchains/quality/uvm/1800.2-2020.3.2');p.add_argument('--tool-bin',type=Path,action='append',default=[]);p.add_argument('--timeout',type=float,default=60);p.add_argument('--out',type=Path,default=Q.ROOT/'artifacts'/datetime.now(timezone.utc).strftime('environment-%Y%m%dT%H%M%S%fZ'))
    a=p.parse_args()
    if not math.isfinite(a.timeout) or a.timeout<=0 or a.out.exists():p.error('positive finite timeout and fresh --out required')
    a.python=Q.executable(a.python)
    for name in ('formal_python','rdl_python','cocotb_python'):
        value=getattr(a,name) or a.python;setattr(a,name,Q.executable(value))
    try:return run(a)
    except (OSError,ValueError,KeyError,TypeError) as exc:print('ENVIRONMENT_ERROR',exc,file=sys.stderr);return 1
if __name__=='__main__':sys.exit(main())

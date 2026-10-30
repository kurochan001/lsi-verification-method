#!/usr/bin/env python3
"""Local-only AHB-Lite/AXI4-Lite safety, bounded data, reachability and sensitivity checks."""
import argparse
from collections import Counter
from datetime import datetime,timezone
import hashlib
import importlib.metadata
import importlib.util
import json
import math
import os
from pathlib import Path
import re
import shutil
import signal
import sys
import xml.etree.ElementTree as ET

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
SUPPORT_PATH=HERE.parent/'local-irq-cdc/run.py'
spec=importlib.util.spec_from_file_location('formal_process_support',SUPPORT_PATH)
SUPPORT=importlib.util.module_from_spec(spec);spec.loader.exec_module(SUPPORT)
CONFIGS={**{f'ahb-wait{n}':dict(bus='ahb',parameter='WAIT_CYCLES',value=n,rtl='ahb_regs.sv') for n in (0,1,3)},
         **{f'axi-delay{n}':dict(bus='axi',parameter='RESP_DELAY',value=n,rtl='axi_lite_regs.sv') for n in (0,2)}}
PROPERTIES={
 'ahb':dict(control={'ap_response','ap_reset','ap_error_pair'},data={'ap_data'},
            assumptions={'as_initial_reset','as_hold_address','as_hold_data'},
            covers={'cp_write','cp_read','cp_pipeline','cp_error_first','cp_error','cp_subword','cp_reset_pending','cp_recovery'},
            failures={1:'ap_data',2:'ap_data',3:'ap_response',4:'ap_data'}),
 'axi':dict(control={'ap_reset','ap_b_hold','ap_r_hold','ap_ready','ap_valid','ap_causality',
                     'ai_read_exclusive','ai_read_bounds','ai_write_bounds','ai_write_state','ai_reference_bounds'},data={'ap_payload'},
            assumptions={'as_initial_reset','as_aw_hold','as_w_hold','as_ar_hold'},
            covers={'cp_aw_first','cp_w_first','cp_together','cp_b_stall','cp_r_stall','cp_strobe_zero',
                    'cp_read_write','cp_error','cp_reset_partial','cp_reset_response','cp_recovery','cp_snapshot'},
            failures={1:'ap_payload',2:'ap_payload',3:'ap_valid',4:'ap_payload'})}
PACKAGES=('yowasp-yosys','yowasp-runtime','wasmtime','platformdirs','click','z3-solver')


def plan(demo_bug,bound):
    cases=[dict(id='safety-proof',mode='prove',data=0,mutation=demo_bug,lock=0,expect='PASS',depth=12,category='normal'),
           dict(id='data-bmc',mode='bmc',data=1,mutation=demo_bug,lock=0,expect='PASS',depth=bound,category='normal'),
           dict(id='scenario-cover',mode='cover',data=1,mutation=0,lock=0,expect='PASS',depth=bound,category='normal')]
    cases += [dict(id=f'detect-mutation{m}',mode='bmc',data=1,mutation=m,lock=0,expect='FAIL',depth=bound,category='mutation') for m in range(1,5)]
    cases += [dict(id='overconstrained-proof',mode='prove',data=0,mutation=0,lock=1,expect='PASS',depth=12,category='diagnostic'),
              dict(id='detect-overconstraint',mode='cover',data=0,mutation=0,lock=1,expect='FAIL',depth=bound,category='diagnostic')]
    return cases


def inspect_model(path,config,case):
    compiled=json.loads(path.read_text());bus=config['bus']
    modules=compiled['modules'];top=modules[bus+'_formal']
    expected_parameters={config['parameter']:config['value'],'MUTATION':case['mutation'],
                         'CHECK_DATA':case['data'],'LOCK_RESET':case['lock']}
    if any(int(top['parameter_default_values'][key],2)!=value for key,value in expected_parameters.items()):
        raise ValueError('compiled parameters differ from the selected task')
    properties={f:Counter() for f in ('assert','assume','cover')}
    for module in modules.values():
        for name,cell in module.get('cells',{}).items():
            if cell['type']=='$check':
                flavor=cell['parameters']['FLAVOR']
                if flavor in properties:
                    label=name.rsplit('.',1)[-1]
                    properties[flavor][label]+=1
    catalog=PROPERTIES[bus]
    expected=dict(assertions=catalog['control'] | (catalog['data'] if case['data'] else set()),
                  assumptions=catalog['assumptions'] | ({'as_lock_reset'} if case['lock'] else set()))
    if (properties['assert']!=Counter(expected['assertions']) or properties['assume']!=Counter(expected['assumptions']) or
            properties['cover']!=Counter(catalog['covers'])):
        raise ValueError('compiled assertion/assumption/cover inventory differs from the fixed plan')
    return {key:sorted(value) for key,value in properties.items()}


def observations(bus,log):
    def names(pattern):
        return {name.rsplit('.',1)[-1] for name in re.findall(pattern,log)}
    scope=bus+r'_formal(?:[.\w]*): ([\w.]+)'
    reached=names(r'Reached cover statement in step \d+ at '+scope)
    unreached=names(r'Unreached cover statement at '+scope)
    failed=names(r'Assert failed in '+scope)
    return reached,unreached,failed


def judge(bus,case,execution,status,log,traces):
    if execution['error']:return 'error',execution['error']
    if status not in ('PASS','FAIL'):return 'error','formal task incomplete or invalid: '+status
    if execution['returncode']!=(0 if status=='PASS' else 2):return 'error','status and SBY exit code disagree'
    if status!=case['expect']:return 'fail',f"expected {case['expect']}, got {status}"
    reached,unreached,failed=observations(bus,log)
    catalog=PROPERTIES[bus]
    if status=='PASS':
        if failed:return 'error','PASS contains a failed assertion'
        if case['mode']=='prove' and 'successful proof by k-induction' not in log:return 'error','missing completed induction proof'
        if case['mode']=='bmc' and 'Status: passed' not in log:return 'error','missing completed bounded check'
        if case['mode']=='cover' and (reached!=catalog['covers'] or unreached or not traces):return 'error','cover goals or witness traces missing'
        return 'pass',('permanent-reset diagnostic only' if case['lock'] else
                        'selected safety properties proven' if case['mode']=='prove' else
                        f"no counterexample within depth {case['depth']}" if case['mode']=='bmc' else 'all formal cover goals reached')
    if case['category']=='mutation':
        label=catalog['failures'][case['mutation']]
        if label in failed and failed<=catalog['control']|catalog['data'] and traces:return 'detected','counterexample confirms '+label
        return 'error','FAIL lacks the intended assertion and counterexample trace'
    if case['lock'] and case['mode']=='cover' and unreached==catalog['covers'] and not reached and not failed and not traces:
        return 'detected','all normal cover goals blocked by permanent reset'
    return 'error','unexplained formal FAIL'


def make_config(config,case,timeout):
    bus=config['bus'];rtl=config['rtl']
    return (f"[options]\nmode {case['mode']}\ndepth {case['depth']}\ntimeout {max(1,int(timeout)-5)}\n"+
            ('cover_assert on\n' if case['mode']=='cover' else '')+
            f"\n[engines]\nsmtbmc z3\n\n[script]\nread -formal -sv {rtl} {bus}_formal.sv\n"+
            f"chparam -set {config['parameter']} {config['value']} -set MUTATION {case['mutation']} -set CHECK_DATA {case['data']} -set LOCK_RESET {case['lock']} {bus}_formal\n"+
            f"prep -top {bus}_formal\nopt_clean\nopt_expr\nwrite_json ../model/inventory.json\nasync2sync\n\n[files]\n{rtl}\n{bus}_formal.sv\n")


def run(args):
    configurations={n:c for n,c in CONFIGS.items() if (args.bus=='both' or c['bus']==args.bus) and
                    (args.configuration=='all' or n==args.configuration)}
    if not configurations:raise ValueError('configuration does not match selected bus')
    out=args.out.resolve();out.mkdir(parents=True,exist_ok=False)
    cases=plan(args.demo_bug,args.bound)
    inputs={Path(__file__),SUPPORT_PATH,HERE/'tools-requirements.txt',HERE.parent/'local-fifo-formal/tools-requirements.txt'}
    for c in configurations.values():inputs.update((HERE/f"{c['bus']}_formal.sv",HERE.parent/f"local-{c['bus']}/rtl"/c['rtl']))
    versions={}
    for package in PACKAGES:
        try:versions[package]=importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:versions[package]='not installed in runner Python environment'
    SUPPORT.write_json(out/'manifest.json',dict(schema_version=1,created_at=datetime.now(timezone.utc).isoformat(),
        python=sys.version,configurations=configurations,cases=cases,bound=args.bound,timeout_seconds=args.timeout,
        tools=dict(sby=args.sby,yosys=args.yosys,smtbmc=args.smtbmc,witness=args.witness),packages=versions,
        proof_scope='AHB: response timing/error/reset; AXI: request/response timing, holding, causality, reset and inductive invariants. Data values are bounded.',
        reset_model='one clock; two-state; async2sync; reset changes observed at sampling edges',
        symbolic_data='arbitrary constant watched word index 0..3; other words are not assumed equal',
        property_plan={bus:{key:sorted(value) for key,value in p.items() if isinstance(value,set)} for bus,p in PROPERTIES.items()},
        source_sha256={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(inputs)}))
    probes={}
    for name,command in [('yosys',[args.yosys,'-V']),('sby',[args.sby,'--version']),('z3',['z3','--version'])]:
        probes[name]=SUPPORT.execute(command,out/f'{name}-version.log',args.timeout,out)
    SUPPORT.write_json(out/'tools.json',dict(packages=versions,probes=probes))
    results=[];coverage={}
    for name,config in configurations.items():
        bus=config['bus']
        for case in cases:
            directory=out/(name+'-'+case['id']);directory.mkdir()
            shutil.copy2(HERE/f'{bus}_formal.sv',directory/f'{bus}_formal.sv')
            shutil.copy2(HERE.parent/f'local-{bus}/rtl'/config['rtl'],directory/config['rtl'])
            (directory/'task.sby').write_text(make_config(config,case,args.timeout))
            command=[args.sby,'--yosys',args.yosys,'--smtbmc',args.smtbmc,'--witness',args.witness,'task.sby']
            execution=SUPPORT.execute(command,directory/'console.log',args.timeout,directory)
            work=directory/'task';status_file=work/'status';log_file=work/'logfile.txt'
            status=status_file.read_text().split()[0] if status_file.is_file() and status_file.read_text().strip() else 'MISSING'
            log=log_file.read_text(errors='replace') if log_file.exists() else ''
            inventory=None;traces=[]
            try:
                for trace in sorted((work/'engine_0').glob('*.vcd')):
                    if '$enddefinitions' not in trace.read_text(errors='replace') or not trace.with_suffix('.yw').is_file() or trace.with_suffix('.yw').stat().st_size==0:
                        raise ValueError('incomplete VCD/witness evidence')
                    traces.append(str(trace.relative_to(out)))
                if not execution['error'] and status in ('PASS','FAIL'):inventory=inspect_model(work/'model/inventory.json',config,case)
                outcome,message=judge(bus,case,execution,status,log,traces)
            except (OSError,ValueError,KeyError,TypeError) as exc:outcome,message='error','invalid formal evidence: '+str(exc)
            result=dict(id=directory.name,configuration=name,category=case['category'],mode=case['mode'],
                        outcome=outcome,message=message,formal_status=status,inventory=inventory,traces=traces,**execution)
            results.append(result);SUPPORT.write_json(directory/'result.json',result)
            if case['id']=='scenario-cover':
                reached,_,_=observations(bus,log)
                credited=reached if outcome=='pass' else set()
                coverage[name]=dict(success=credited==PROPERTIES[bus]['covers'],required=len(PROPERTIES[bus]['covers']),
                                    hit=len(credited),missing=sorted(PROPERTIES[bus]['covers']-credited))
            print(f"{outcome.upper():8} {result['id']}: {message}",flush=True)
    success=len(results)==len(configurations)*len(cases) and all(r['outcome'] in ('pass','detected') for r in results) and all(c['success'] for c in coverage.values())
    SUPPORT.write_json(out/'coverage.json',coverage)
    SUPPORT.write_json(out/'summary.json',dict(success=success,planned=len(configurations)*len(cases),results=results,
        explanation='Safety proof, bounded data, cover and diagnostics have separate scopes; formal goals do not fill simulation coverage.'))
    suite=ET.Element('testsuite',name='local.bus-formal',tests=str(len(results)),
        failures=str(sum(r['outcome']=='fail' for r in results)),errors=str(sum(r['outcome']=='error' for r in results)))
    for result in results:
        node=ET.SubElement(suite,'testcase',name=result['id'],classname='local.formal.'+result['configuration'],time=f"{result['seconds']:.6f}")
        if result['outcome'] in ('fail','error'):ET.SubElement(node,'failure' if result['outcome']=='fail' else 'error',message=result['message'])
        ET.SubElement(node,'system-out').text=f"SBY={result['formal_status']}; {result['message']}"
    ET.indent(suite);ET.ElementTree(suite).write(out/'junit.xml',encoding='utf-8',xml_declaration=True)
    print(f"Artifacts: {out}\nFormal regression: {'PASS' if success else 'FAIL'}")
    return 0 if success else 1


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bus',choices=('both','ahb','axi'),default='both')
    parser.add_argument('--configuration',choices=('all',*CONFIGS),default='all')
    parser.add_argument('--bound',type=int,default=12)
    parser.add_argument('--demo-bug',type=int,choices=(0,1,2,3,4),default=0)
    parser.add_argument('--sby',default='yowasp-sby');parser.add_argument('--yosys',default='yowasp-yosys')
    parser.add_argument('--smtbmc',default='yowasp-yosys-smtbmc');parser.add_argument('--witness',default='yowasp-yosys-witness')
    parser.add_argument('--timeout',type=float,default=120.0)
    parser.add_argument('--out',type=Path,default=Path('artifacts')/datetime.now(timezone.utc).strftime('local-bus-formal-%Y%m%dT%H%M%S%fZ'))
    args=parser.parse_args()
    if os.name!='posix' or not 12<=args.bound<=100 or not math.isfinite(args.timeout) or args.timeout<=0:parser.error('requires POSIX, bound 12..100, finite positive timeout')
    if args.out.exists():parser.error('output directory already exists; choose a new --out')
    if args.configuration!='all' and args.bus!='both' and CONFIGS[args.configuration]['bus']!=args.bus:parser.error('configuration does not match selected bus')
    previous=signal.signal(signal.SIGTERM,SUPPORT.interrupted)
    try:return run(args)
    except SUPPORT.RunInterrupted as exc:return 128+exc.signum
    except KeyboardInterrupt:return 130
    except (OSError,ValueError,KeyError,TypeError) as exc:print('RUNNER_ERROR '+str(exc),file=sys.stderr);return 1
    finally:signal.signal(signal.SIGTERM,previous)


if __name__=='__main__':sys.exit(main())

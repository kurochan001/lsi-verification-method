#!/usr/bin/env python3
"""Conservative Git-change selection with a reviewed dependency inventory and evidence."""
import argparse
from datetime import datetime,timezone
import json
import math
from pathlib import Path
import re
import subprocess
import sys
from types import SimpleNamespace
import quality_common as Q
import run_regression as R
HERE=Path(__file__).resolve().parent
DEPENDENCIES=HERE/'regression_dependencies.json'
IMAGES={'.svg','.png','.jpg','.jpeg','.gif','.pdf'}

def tracked(root):
    data=subprocess.check_output(['git','-C',str(root),'ls-files','-z','--cached','--others','--exclude-standard'])
    return sorted(set(n.decode() for n in data.split(b'\0') if n))

def documentation(name):
    p=Path(name)
    if p.suffix.lower() in IMAGES:return name.startswith('docs/') or '/docs/' in name
    if p.suffix.lower()!='.md':return False
    if name.startswith('docs/templates/'):return False
    return not name.startswith('examples/') or p.name.lower()=='readme.md' or '/upstream/docs/' in name

def runtime_files(root):
    return [n for n in tracked(root) if n.startswith('examples/') and not documentation(n) and (root/n).is_file()]

def dependency_inventory(root,entries):
    files=runtime_files(root);nodes={Path(n).parts[1] for n in files}|{owner(e) for e in entries.values()};edges={n:set() for n in nodes}
    for name in files:
        if '/tests/' in name:continue
        folder=Path(name).parts[1]
        for other in re.findall(r'(?<![a-z0-9-])local-[a-z0-9-]+',(root/name).read_text(errors='replace')):
            if other in nodes and other!=folder:edges[folder].add(other)
    for name,entry in entries.items():
        folder=owner(entry)
        edges[folder].update(owner(entries[c]) for c in entry.get('children',{}) if owner(entries[c])!=folder)
    # Shared DUT ownership is explicit even when the source path is assembled in Python.
    catalog=json.loads((root/'tools/lint_targets.json').read_text());targets={t['id']:t for t in catalog['targets']}
    for name,binding in catalog['examples'].items():
        if name not in nodes:continue
        for target in binding['targets']:
            edges[name].update(Path(n).parts[1] for n in targets[target]['sources'] if n.startswith('examples/') and Path(n).parts[1]!=name)
    if 'local-lint-targets' in entries:edges[owner(entries['local-lint-targets'])].update(Path(n).parts[1] for n in catalog['rtl_files'])
    return dict(schema_version=1,files=files,dependencies={n:sorted(edges[n]) for n in sorted(nodes)},policy='reviewed folder ownership, literal cross-example references, registry children and shared DUT catalogue; unknown changes run all')

def owner(entry):
    parts=Path(entry['script']).parts
    return parts[1] if parts[0]=='examples' else '@'+entry['id']

def diff_records(raw):
    parts=raw.decode().split('\0');parts=[p for p in parts if p];result=[];i=0
    while i<len(parts):
        status=parts[i];i+=1;count=2 if status.startswith(('R','C')) else 1
        if not re.fullmatch(r'[ACDMRTUXB]\d*',status) or i+count>len(parts):raise ValueError('unsupported Git diff record')
        result.append(dict(status=status,paths=parts[i:i+count]));i+=count
    return result

def changes(root,base,head,worktree):
    resolved={};reason=None;records=[]
    for label,ref in [('base',base),('head',head)]:
        r=subprocess.run(['git','-C',str(root),'rev-parse','--verify',ref+'^{commit}'],capture_output=True,text=True)
        if r.returncode:
            if label=='head':raise ValueError('head commit unavailable')
            reason='Git reference unavailable: '+label
        else:resolved[label]=r.stdout.strip()
    if resolved['head']!=subprocess.check_output(['git','-C',str(root),'rev-parse','HEAD'],text=True).strip():raise ValueError('head must be the checked-out HEAD')
    pending=diff_records(subprocess.check_output(['git','-C',str(root),'diff','--name-status','-z','--find-renames','HEAD']))
    untracked=[dict(status='A',paths=[p.decode()]) for p in subprocess.check_output(['git','-C',str(root),'ls-files','--others','--exclude-standard','-z']).split(b'\0') if p]
    if not worktree and (pending or untracked):raise ValueError('dirty worktree: use --include-worktree to bind current inputs')
    if reason:return [],resolved,reason
    records=diff_records(subprocess.check_output(['git','-C',str(root),'diff','--name-status','-z','--find-renames',resolved['base'],resolved['head']]))
    if worktree:
        records+=pending+untracked
    return records,resolved,None

def select(root,entries,records,catalog,uncertain=None):
    full=[];reasons={};changed=sorted({p for r in records for p in r['paths']});current=dependency_inventory(root,entries)
    if uncertain:full.append(uncertain)
    if catalog!=current:full.append('dependency inventory changed; review and regenerate it')
    known=set(catalog.get('files',[]));edges=catalog.get('dependencies',{});affected=set()
    for record in records:
        for name in record['paths']:
            if documentation(name):continue
            if record['status'][0] not in ('M','A'):full.append('runtime deletion/rename/type change: '+name);continue
            if name not in known:full.append('shared or unclassified runtime input: '+name);continue
            folder=Path(name).parts[1];affected.add(folder);reasons.setdefault(folder,[]).append('changed input: '+name)
    # A path reference change invalidates the reviewed dependency inventory above.
    # Unknown/global inputs (tools, workflows, templates, requirements) are all-run.
    todo=list(affected)
    while todo:
        dependency=todo.pop()
        for consumer,requires in edges.items():
            if dependency in requires and consumer not in affected:
                affected.add(consumer);todo.append(consumer);reasons.setdefault(consumer,[]).append('depends on '+dependency)
    selected=sorted(entries if full else [name for name,e in entries.items() if owner(e) in affected])
    if changed and not selected and any(not documentation(n) for n in changed):full.append('runtime changes without an execution owner');selected=sorted(entries)
    status='full' if full else 'affected' if selected else 'docs-only' if changed else 'no-change'
    return dict(status=status,changed=changed,records=records,examples=selected,full_reasons=sorted(set(full)),reasons=reasons)

def plan_args(a,out,examples):
    return SimpleNamespace(example=examples,suite='all',profile=a.profile,seed=a.seed,out=out,python=sys.executable,formal_python=sys.executable,rdl_python=sys.executable,cocotb_python=sys.executable,uvm_home=None,oss_home=None,formal_timeout=None,child_timeout=None,build_timeout=None,command_timeout=None,tool_bin=[])

def run(a):
    root=Q.ROOT;entries=R.load_registry(root/'tools/regressions.json',root);catalog=json.loads(DEPENDENCIES.read_text())
    inventory=dependency_inventory(root,entries);tracked_inventory=tracked(root)
    records,resolved,uncertain=changes(root,a.base,a.head,a.include_worktree);selection=select(root,entries,records,catalog,uncertain)
    selected=selection['examples'];jobs=R.make_plan(entries,plan_args(a,a.out/'campaign',selected),root) if selected else []
    selection.update(refs=resolved,profile=a.profile,seed=a.seed,selected_jobs=[j['id'] for j in jobs],executed_jobs=0,hardware_verified=False)
    inputs=[Path(__file__),DEPENDENCIES,root/'tools/run_regression.py',root/'tools/regression_report.py',root/'tools/regressions.json',root/'tools/lint_targets.json',*[root/n for n in tracked_inventory if (root/n).is_file() and not documentation(n)]]
    report=Q.Report('affected-regression',a.out,inputs,['selection','execution','audit','source-freshness'],dict(base=a.base,head=a.head,include_worktree=a.include_worktree,run=a.run,refs=resolved))
    Q.write(report.out/'selection.json',selection);report.check('selection',True,dict(status=selection['status'],jobs=len(jobs),full_reasons=selection['full_reasons']))
    if a.run and jobs:
        command=[sys.executable,str(root/'tools/run_regression.py'),'--profile',a.profile,'--seed',str(a.seed)]
        for name in selected:command+=['--example',name]
        command+=a.runner_args+['--out',str(report.out/'campaign')];Q.write(report.out/'command.json',command)
        r=Q.P.execute(command,report.out/'campaign.log',a.execution_timeout,root);good=False
        try:
            data=json.loads((report.out/'campaign/summary.json').read_text());manifest=json.loads((report.out/'campaign/manifest.json').read_text())
            selection['executed_jobs']=len(data['results'])
            good=not r['error'] and r['returncode']==0 and data['success'] is True and data['complete'] is True and [j['id'] for j in manifest['jobs']]==selection['selected_jobs'] and data['planned']==len(jobs)
        except (OSError,ValueError,KeyError,TypeError):pass
        report.check('execution',good,r)
        r=Q.P.execute([sys.executable,str(root/'tools/regression_report.py'),'--plan',str(report.out/'campaign/manifest.json'),'--campaign',str(report.out/'campaign'),'--out',str(report.out/'audit')],report.out/'audit.log',a.execution_timeout,root)
        try:audited=not r['error'] and r['returncode']==0 and json.loads((report.out/'audit/summary.json').read_text())['success'] is True
        except (OSError,ValueError,KeyError,TypeError):audited=False
        report.check('audit',audited,r);selection['hardware_verified']=good and audited
    else:
        detail=dict(executed=False,reason='plan only' if not a.run else 'no affected hardware jobs; documentation gates remain separate')
        report.check('execution',True,detail);report.check('audit',True,detail)
    changed=report.fresh()
    if tracked(root)!=tracked_inventory:changed.append('repository input inventory changed')
    try:
        if changes(root,a.base,a.head,a.include_worktree)!=(records,resolved,uncertain):changed.append('Git changes or references changed')
    except (ValueError,subprocess.SubprocessError) as exc:changed.append(str(exc))
    if dependency_inventory(root,entries)!=inventory:changed.append('runtime/dependency inventory changed during selection or execution')
    report.check('source-freshness',not changed,changed);Q.write(report.out/'selection.json',selection)
    print('Selection:',selection['status'],'planned',len(jobs),'executed',selection['executed_jobs'],'hardware_verified',selection['hardware_verified'])
    return report.finish()

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--base',required=True);p.add_argument('--head',default='HEAD');p.add_argument('--include-worktree',action='store_true');p.add_argument('--profile',choices=('smoke','nightly'),default='smoke');p.add_argument('--seed',type=int,default=17);p.add_argument('--run',action='store_true');p.add_argument('--execution-timeout',type=float,default=14400);p.add_argument('--out',type=Path,default=Q.ROOT/'artifacts'/datetime.now(timezone.utc).strftime('affected-%Y%m%dT%H%M%S%fZ'));p.add_argument('runner_args',nargs=argparse.REMAINDER)
    a=p.parse_args();a.runner_args=a.runner_args[1:] if a.runner_args[:1]==['--'] else a.runner_args
    allowed={'--jobs','--job-timeout','--command-timeout','--formal-timeout','--child-timeout','--build-timeout','--python','--formal-python','--rdl-python','--cocotb-python','--tool-bin','--uvm-home','--oss-home'}
    if len(a.runner_args)%2 or any(k not in allowed for k in a.runner_args[::2]):p.error('only tool bindings and limits may follow --')
    if not math.isfinite(a.execution_timeout) or a.execution_timeout<=0 or not 0<=a.seed<=2**31-4 or a.out.exists():p.error('valid seed, finite timeout and fresh output required')
    try:return run(a)
    except (OSError,ValueError,KeyError,TypeError,subprocess.SubprocessError) as exc:print('SELECTION_ERROR',exc,file=sys.stderr);return 1
if __name__=='__main__':sys.exit(main())

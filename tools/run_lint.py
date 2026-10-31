#!/usr/bin/env python3
"""Lint the explicit DUT/configuration inventory and gate warning changes."""
from collections import Counter
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import sys
HERE=Path(__file__).resolve().parent;ROOT=HERE.parent
s=importlib.util.spec_from_file_location('lint_evidence',ROOT/'examples/local-exploration-common/evidence.py');E=importlib.util.module_from_spec(s);s.loader.exec_module(E)
def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def rtl_files(root=ROOT):return sorted(str(p.relative_to(root)) for p in (root/'examples').rglob('*') if p.suffix in ('.sv','.v') and 'rtl' in p.relative_to(root/'examples').parts[:-1])
def validate_catalog(catalog,root=ROOT):
    if catalog.get('schema_version')!=1 or catalog.get('rtl_files')!=rtl_files(root):raise ValueError('DUT source inventory differs; update lint_targets.json')
    targets=catalog['targets'];ids=[t['id'] for t in targets]
    if not targets or len(ids)!=len(set(ids)):raise ValueError('empty/duplicate targets')
    stubs=catalog.get('blackbox_sources',{})
    if any(not reason or not (root/f).is_file() or not (root/f).resolve().is_relative_to(root.resolve()) for f,reason in stubs.items()):raise ValueError('invalid black-box scope')
    declared={(f,m) for f in catalog['rtl_files'] for m in re.findall(r'^\s*module\s+(?:automatic\s+)?(\w+)',(root/f).read_text(),re.M)}
    covered=set();used=set()
    for t in targets:
        if not re.fullmatch(r'[\w./=-]+',t['id']) or not t['sources'] or len(t['sources'])!=len(set(t['sources'])) or set(t['sources'])-(set(catalog['rtl_files'])|set(stubs)):raise ValueError('invalid target/source')
        if (t['file'],t['top']) not in declared or t['file'] not in t['sources']:raise ValueError('unknown top module')
        if not isinstance(t['parameters'],dict) or any(not re.fullmatch(r'[A-Z][A-Z0-9_]*',k) or type(v)!=int for k,v in t['parameters'].items()) or t['parameters'].get('MUTATION',0)!=0:raise ValueError('invalid/nonfunctional target parameters')
        covered.add((t['file'],t['top']));used.update(t['sources'])
    if covered!=declared or used!=(set(catalog['rtl_files'])|set(stubs)):raise ValueError('module/package inventory incomplete')
    examples={p.parent.name for p in (root/'examples').glob('*/run.py')};bindings=catalog['examples']
    if set(bindings)!=examples:raise ValueError('example inventory differs')
    for name,b in bindings.items():
        if set(b['targets'])-set(ids) or not b['reason'] or b['scope'] not in ('dut','shared-dut','workflow'):raise ValueError('invalid example scope: '+name)
        if b['scope']=='workflow' and b['targets'] or b['scope']!='workflow' and not b['targets']:raise ValueError('scope/targets differ: '+name)
    return targets
def diagnostics(log,root=ROOT):
    result=[]
    for line in log.splitlines():
        if not line.startswith('%'):continue
        m=re.fullmatch(r'%(Warning|Error)(?:-([A-Z0-9_]+))?:\s+(?:(.*?):(\d+):(?:(\d+):)?\s+)?(.*)',line)
        if not m:raise ValueError('unrecognized diagnostic: '+line)
        severity,rule,path,row,col,message=m.groups()
        if severity=='Warning' and (not rule or not path):raise ValueError('warning lacks rule/location')
        if path:
            p=Path(path);p=p if p.is_absolute() else root/p
            if not p.resolve().is_relative_to(root.resolve()):raise ValueError('diagnostic outside repository')
            path=str(p.resolve().relative_to(root.resolve()))
        result.append(dict(severity=severity,rule=rule or 'ERROR',file=path,line=int(row) if row else None,column=int(col) if col else None,message=message.replace(str(root)+'/','')))
    return result
def key(d):return json.dumps(d,sort_keys=True,separators=(',',':'))
def release_version(output):
    """Gate the release; preserve packaging-specific build identity in tools.json."""
    m=re.fullmatch(r'Verilator (\d+\.\d+) [^\n]+',output.strip())
    return m[1] if m else None
def changes(current,baseline,source_sha256):
    old=Counter()
    for item in baseline.get('diagnostics',[]):
        if type(item.get('count'))!=int or item['count']<=0 or item.get('disposition') not in ('known-debt','waived') or any(not isinstance(item.get(k),str) or not item[k].strip() or 'REVIEW REQUIRED' in item[k] for k in ('reason','impact','reviewer','method','expires')):raise ValueError('invalid warning disposition')
        k=key(item['diagnostic'])
        if k in old:raise ValueError('duplicate warning baseline')
        old[k]=item['count']
    now=Counter(key(d) for d in current if d['severity']=='Warning')
    return dict(new=[dict(diagnostic=json.loads(k),count=v) for k,v in sorted((now-old).items())],resolved=[dict(diagnostic=json.loads(k),count=v) for k,v in sorted((old-now).items())],source_changed=baseline.get('source_sha256')!=source_sha256,errors=[d for d in current if d['severity']=='Error'])
def run(a):
    catalog=json.loads(a.catalog.read_text());baseline=json.loads(a.baseline.read_text()) if a.baseline.is_file() else dict(schema_version=1,tool_version=None,targets={})
    targets=validate_catalog(catalog);ids=['inventory','tool-version',*[t['id'] for t in targets],'source-freshness']
    paths=[Path(__file__),a.catalog,ROOT/'tools/regressions.json',*[ROOT/f for f in catalog['rtl_files']],*[ROOT/f for f in catalog.get('blackbox_sources',{})]]
    if a.baseline.is_file():paths.append(a.baseline)
    e=E.Evidence('local-lint-targets',a,paths,dict(scope='checked-in DUT RTL; each declared module and explicit configuration',targets=targets),ids)
    version=E.P.execute([a.verilator,'--version'],e.out/'verilator-version.log',a.timeout,e.out);version_text=(e.out/'verilator-version.log').read_text().strip()
    release=release_version(version_text)
    version_ok=not version['error'] and version['returncode']==0 and release is not None and release==baseline.get('tool_version')
    E.P.write_json(e.out/'tools.json',dict(verilator=version,version=version_text,release=release));e.check('tool-version',version_ok,dict(current=version_text,release=release,baseline=baseline.get('tool_version')))
    inv_ok=baseline.get('schema_version')==1 and set(baseline.get('targets',{}))=={t['id'] for t in targets}
    e.check('inventory',inv_ok,dict(targets=len(targets),rtl_files=len(catalog['rtl_files']),baseline_targets=len(baseline.get('targets',{}))))
    candidate=dict(schema_version=1,tool_version=release,policy='Known warning debt is retained explicitly; success means unchanged diagnostics, not warning-free RTL or human approval.',targets={});results=[]
    for t in targets:
        d=e.out/'targets'/t['id'];d.mkdir(parents=True)
        sha={f:digest(ROOT/f) for f in t['sources']}
        command=[a.verilator,'--lint-only','--Wall','-Wno-fatal','--top-module',t['top'],*[f'-G{k}={v}' for k,v in sorted(t['parameters'].items())],*[str(ROOT/f) for f in t['sources']]]
        execution=E.P.execute(command,d/'lint.log',a.timeout,d);log=(d/'lint.log').read_text(errors='replace');ds=[];problem=None
        try:
            ds=diagnostics(log)
            if any(x['file'] and x['file'] not in t['sources'] for x in ds):raise ValueError('diagnostic source outside target')
            previous=baseline.get('targets',{}).get(t['id'],{});delta=changes(ds,previous,sha)
            delta['configuration_changed']=previous.get('target_sha256')!=hashlib.sha256(key(t).encode()).hexdigest()
        except (ValueError,KeyError,TypeError) as exc:problem=str(exc);delta=dict(new=[],resolved=[],source_changed=True,errors=[])
        ok=version_ok and inv_ok and not execution['error'] and execution['returncode']==0 and problem is None and not any(delta.values())
        result=dict(id=t['id'],success=ok,clean=not ds and not problem and not execution['error'] and execution['returncode']==0,diagnostics=ds,changes=delta,problem=problem,source_sha256=sha,execution=execution)
        results.append(result);E.P.write_json(d/'result.json',result);e.check(t['id'],ok,result)
        candidate['targets'][t['id']]=dict(target_sha256=hashlib.sha256(key(t).encode()).hexdigest(),source_sha256=sha,diagnostics=[dict(diagnostic=json.loads(k),count=v,disposition='known-debt',reason='REVIEW REQUIRED',impact='REVIEW REQUIRED',reviewer='REVIEW REQUIRED',method='REVIEW REQUIRED',expires='source/tool/configuration change') for k,v in sorted(Counter(key(x) for x in ds if x['severity']=='Warning').items())])
    E.P.write_json(e.out/'baseline-candidate.json',candidate);E.P.write_json(e.out/'diagnostics.json',dict(clean=all(r['clean'] for r in results),warnings=sum(d['severity']=='Warning' for r in results for d in r['diagnostics']),results=results))
    frozen=json.loads((e.out/'manifest.json').read_text())['source_sha256'];changed=[p for p,h in frozen.items() if not (ROOT/p).is_file() or digest(ROOT/p)!=h]
    e.check('source-freshness',not changed,changed);return e.finish()
def main():
    p=E.parser(__doc__,'local-lint-targets');p.add_argument('--verilator',default='verilator');p.add_argument('--catalog',type=Path,default=HERE/'lint_targets.json');p.add_argument('--baseline',type=Path,default=HERE/'lint_baseline.json')
    a=p.parse_args();E.validate(p,a);a.catalog=a.catalog.resolve();a.baseline=a.baseline.resolve()
    try:return run(a)
    except (OSError,ValueError,KeyError,TypeError,RuntimeError) as exc:print('RUNNER_ERROR',exc,file=sys.stderr);return 1
if __name__=='__main__':sys.exit(main())

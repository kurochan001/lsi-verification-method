#!/usr/bin/env python3
"""Unbounded fair liveness by finite-state liveness-to-safety and ABC PDR."""
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
from types import SimpleNamespace
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1]
sys.path.insert(0,str(HERE));sys.path.insert(0,str(ROOT/'tools'))
import oss_cad as O
from reference import graph_result
from witness import read_vcd,replay
def load(name,path):
    s=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
E=load('liveness_evidence',HERE.parent/'local-exploration-common/evidence.py')
F=load('liveness_formal_common',HERE.parent/'local-formal-common/runner.py')
CASES=[('fair-proof',0,1,'prove','PASS'),('no-fairness',0,0,'prove','FAIL'),('starvation',1,1,'prove','FAIL'),('lost-request',2,1,'prove','FAIL'),('reachable-long-wait',0,1,'cover','PASS')]
COVERS=['cp_request','cp_completion','cp_long_wait']

def run(a):
    O.prepare_environment()
    inputs=[Path(__file__),HERE/'reference.py',HERE/'witness.py',HERE/'rtl/fair_arbiter.sv',HERE/'liveness_formal.sv',Path(F.__file__),Path(O.__file__),O.CONFIG]
    e=E.Evidence('local-liveness',a,inputs,dict(configuration={'requesters':2,'state_bits':4},method='finite-state liveness-to-safety; no response deadline',cases=CASES),[c[0] for c in CASES])
    ready=True
    try:snapshot=O.verify(a.oss_home)
    except (OSError,ValueError,RuntimeError) as exc:ready=False;snapshot=dict(error=str(exc))
    E.P.write_json(e.out/'oss-source.json',snapshot)
    if ready:
        version=E.P.execute([O.bin_path(a.oss_home,'yosys'),'-V'],e.out/'yosys-version.log',a.timeout,e.out)
        E.P.write_json(e.out/'tools.json',dict(yosys=version,toolchain=snapshot));ready=not version['error'] and version['returncode']==0
    records=[]
    for name,mutation,fair,mode,expected in CASES:
        d=e.out/name;d.mkdir();work=d/'task';params=dict(MUTATION=mutation,FAIR=fair,COVER_MODE=int(mode=='cover'))
        for file in inputs[3:5]:(d/file.name).write_bytes(file.read_bytes())
        script='[options]\nmode '+mode+'\n'+('depth 32\n' if mode=='cover' else '')+'[engines]\n'+('smtbmc z3' if mode=='cover' else 'abc pdr')+'\n[script]\nread -formal -sv fair_arbiter.sv liveness_formal.sv\n'
        script+='chparam '+ ' '.join('-set '+k+' '+str(v) for k,v in params.items())+' liveness_formal\nprep -top liveness_formal\nwrite_json properties.json\n[files]\nfair_arbiter.sv\nliveness_formal.sv\n'
        path=d/'task.sby';path.write_text(script)
        r=E.P.execute([str(a.oss_home/'bin/sby'),'-f','-d',str(work),str(path)],d/'formal.log',a.timeout,d) if ready else dict(returncode=None,error='toolchain not verified')
        status=(work/'status').read_text().split()[0] if (work/'status').is_file() else None
        log=(work/'logfile.txt').read_text() if (work/'logfile.txt').is_file() else '';ok=False;reason='task incomplete';details={}
        try:
            if r['error'] or status!=expected or r['returncode']!=(0 if status=='PASS' else 2):raise ValueError('status/exit/expected outcome differs')
            expected_properties={'assert':[] if mode=='cover' else ['ap_no_fair_lasso'],'assume':['as_initial_reset','as_request_contract'],'cover':COVERS if mode=='cover' else []}
            plugin=SimpleNamespace(TOP='liveness_formal',properties=lambda p,c:expected_properties)
            props=F.inventory(work/'src/properties.json',plugin,{},dict(parameters=params))
            reached,unreached,failed=F.observed(log);traces=F.witnessed_traces(work/'engine_0',e.out)
            if mode=='cover':
                if reached!=set(COVERS) or unreached or failed or len(traces)!=len(COVERS):raise ValueError('cover inventory or witnesses incomplete')
                details=dict(properties=props,traces=traces)
            else:
                graph=graph_result(mutation,bool(fair));E.P.write_json(d/'state-graph.json',graph)
                if graph['success']!=(expected=='PASS'):raise ValueError('independent state graph disagrees')
                if status=='PASS':
                    if failed or 'Property proved.' not in log:raise ValueError('PDR proof not completed')
                    details=dict(properties=props,graph=graph)
                else:
                    if failed!={'ap_no_fair_lasso'} or len(traces)!=1:raise ValueError('wrong assertion or missing counterexample')
                    witness=replay(read_vcd((e.out/traces[0]).read_text()),mutation,bool(fair));E.P.write_json(d/'lasso.json',witness)
                    details=dict(properties=props,graph=graph,lasso=witness,traces=traces)
            ok=True;reason='all covers witnessed' if mode=='cover' else 'unbounded PDR proof and state graph agree' if expected=='PASS' else 'reachable fair lasso replayed' if fair else 'non-fair infinite wait replayed'
        except (OSError,ValueError,KeyError,TypeError,IndexError) as exc:reason=str(exc)
        records.append(dict(id=name,mode=mode,expected=expected,formal_status=status,success=ok,outcome=('pass' if expected=='PASS' else 'detected') if ok else 'error',message=reason,details=details,execution=r,sby_sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
    changed=[p for p,h in json.loads((e.out/'manifest.json').read_text())['source_sha256'].items() if not (ROOT/p).is_file() or hashlib.sha256((ROOT/p).read_bytes()).hexdigest()!=h]
    try:
        if O.verify(a.oss_home)!=snapshot:changed.append('toolchain changed')
    except (OSError,ValueError,RuntimeError):changed.append('toolchain changed')
    for record in records:
        if changed:record.update(success=False,outcome='error',message=record['message']+'; source/toolchain drift: '+str(changed))
        e.check(record['id'],record['success'],record)
    E.P.write_json(e.out/'executions.json',records);return e.finish()

def main():
    p=E.parser(__doc__,'local-liveness');p.add_argument('--oss-home',type=Path,required=True);a=p.parse_args();E.validate(p,a);a.oss_home=a.oss_home.absolute()
    try:return run(a)
    except (OSError,ValueError,KeyError,TypeError,RuntimeError) as exc:print('LIVENESS_ERROR',exc,file=sys.stderr);return 1
if __name__=='__main__':sys.exit(main())

#!/usr/bin/env python3
"""Run the actual SoCLib CABA VciRam with independent packet-level expected data."""
import importlib.util,json,sys,shutil
from pathlib import Path
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1]
def load(name,p):
 s=importlib.util.spec_from_file_location(name,p);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
E=load('vci_evidence',HERE.parent/'local-exploration-common/evidence.py');M=load('vci_model',HERE/'model.py');SC=load('vci_systemc',ROOT/'tools/systemc.py')
NAMES=('basic','packets','errors','reset')
def sources():
 manifest=json.loads((HERE/'upstream.json').read_text());files=manifest['files'];actual={str(p.relative_to(HERE/'upstream')) for p in (HERE/'upstream').rglob('*') if p.is_file()}
 if actual!=set(files):raise ValueError('SoCLib inventory differs')
 for name,record in files.items():
  p=HERE/'upstream'/name;data=p.read_bytes()
  if E.hashlib.sha256(data).hexdigest()!=record['sha256']:raise ValueError('SoCLib content changed '+name)
  original=data.replace(b'// Local change 2026-11-02: preserve all lanes during a 64-bit partial write.\n    ',b'').replace(b'ram_t cur = tab[index];',b'unsigned int cur = tab[index];') if 'modification' in record else data
  if E.hashlib.sha256(original).hexdigest()!=record['original_sha256']:raise ValueError('SoCLib original reconstruction differs '+name)
 return [HERE/'upstream'/name for name in sorted(files)]
def completion(log,expected):
 import re
 pairs=re.findall(r'^COUNT ([a-z_]+)=(\d+)$',log,re.M)
 if len(pairs)!=len(dict(pairs)) or {k:int(v) for k,v in pairs}!=expected:raise ValueError('completion counts differ')
def run(a):
 inputs=sources();seeds=list(range(a.seed,a.seed+(3 if a.profile=='nightly' else 1)));_,goals=E.C.catalog(HERE/'requirements.json')
 names=[*NAMES,*[f'random-{s}' for s in seeds],'detect-byte-enable','detect-id'];plan=['toolchain',*[f'b{b}/{n}' for b in (4,8) for n in [*names,*(['upstream-original'] if b==8 else []),'coverage']],'source-freshness']
 e=E.Evidence('local-vci-soclib',a,[Path(__file__),HERE/'model.py',HERE/'tb/vci_tb.cpp',HERE/'requirements.json',HERE/'upstream.json',Path(SC.__file__),ROOT/'tools/environment.json',*inputs],dict(cell_bytes=[4,8],seeds=seeds),plan)
 prefix_probe=E.P.execute([a.systemc_config,'--prefix'],e.out/'systemc-prefix.log',a.timeout,e.out)
 if prefix_probe['error'] or prefix_probe['returncode']!=0:raise ValueError('SystemC prefix unavailable')
 home=Path((e.out/'systemc-prefix.log').read_text().strip());record=SC.snapshot(home);E.P.write_json(e.out/'systemc-source.json',record)
 versions={n:E.P.execute(cmd,e.out/(n+'.log'),a.timeout,e.out) for n,cmd in [('cxx',[a.cxx,'--version']),('systemc',[a.systemc_config,'--version'])]}
 good=all(not v['error'] and v['returncode']==0 for v in versions.values()) and (e.out/'systemc.log').read_text().strip()=='SystemC 2.3.4';e.check('toolchain',good,versions)
 includes=set()
 for p in inputs:
  if p.suffix not in ('.h','.cpp'):continue
  q=p.parent
  while q!=HERE/'upstream':includes.add(q);q=q.parent
 records=[];builds={}
 import re
 for b in (4,8):
  hits=set()
  for name in [*names,*(['upstream-original'] if b==8 else [])]:
   mutation={'upstream-original':1,'detect-byte-enable':2,'detect-id':3}.get(name,0);scenario='basic' if mutation else 'random' if name.startswith('random-') else name
   seed=int(name.removeprefix('random-')) if name.startswith('random-') else a.seed;rows,counts=M.make(scenario,b,seed,128 if a.profile=='nightly' else 32)
   d=e.out/f'b{b}'/name;d.mkdir(parents=True);vectors=d/'vectors.txt';vectors.write_text(''.join(' '.join(f'{x:x}' for x in row)+'\n' for row in rows))
   E.P.write_json(d/'manifest.json',dict(source_sha256={str(vectors):E.hashlib.sha256(vectors.read_bytes()).hexdigest()},expected_counts=counts,cell_bytes=b,seed=seed,scenario=scenario,mutation=mutation))
   key=(b,mutation)
   if key not in builds:
    out=e.out/f'build-b{b}-m{mutation}';out.mkdir();files=[]
    for p in inputs:
     if p.name not in ('vci_ram.cpp','vci_target_fsm.cpp'):continue
     data=p.read_text()
     if mutation==1 and p.name=='vci_ram.cpp':data=data.replace('ram_t cur = tab[index];','unsigned int cur = tab[index];')
     if mutation==2 and p.name=='vci_ram.cpp':data=data.replace('vci_param::be2mask(be)','vci_param::be2mask((1 << vci_param::B)-1)')
     if mutation==3 and p.name=='vci_target_fsm.cpp':data=data.replace('m_current_cmd.srcid = p_vci.srcid.read();','m_current_cmd.srcid = p_vci.srcid.read() ^ 1;')
     target=out/p.name;target.write_text(data);files.append(target)
    E.P.write_json(out/'manifest.json',dict(source_sha256={str(p):E.hashlib.sha256(p.read_bytes()).hexdigest() for p in files}))
    binary=out/'simulation';cmd=[a.cxx,'-std=gnu++17',f'-DCELL_BYTES={b}','-I'+str(out),'-I'+str(home/'include'),*['-I'+str(p) for p in sorted(includes)],str(HERE/'tb/vci_tb.cpp'),str(home/'lib/libsystemc.a'),'-pthread','-o',str(binary)]
    build=E.P.execute(cmd,out/'build.log',a.build_timeout,out);builds[key]=(binary,build)
   binary,build=builds[key]
   if build['error'] or build['returncode']!=0:ex=dict(error='build failed',returncode=None);(d/'simulation.log').write_text('build failed\n')
   else:ex=E.P.execute([str(binary),str(vectors),str(d/'trace')],d/'simulation.log',a.timeout,d)
   log=(d/'simulation.log').read_text(errors='replace');label='VCI_ID' if mutation==3 else 'VCI_DATA' if mutation else None
   status,message=E.P.classify(dict(checks=len(rows),expected_failure=label),ex,log)
   if status=='pass':
    try:completion(log,counts)
    except ValueError as err:status,message='error',str(err)
   wave=d/'trace.vcd'
   if status in ('pass','detected') and (not wave.is_file() or '$enddefinitions' not in wave.read_text()):status,message='error','waveform missing'
   observed=set(re.findall(r'^COVER (\S+)$',log,re.M)) if status=='pass' and not mutation else set();hits|=observed
   r=dict(id=f'b{b}/{name}',status=status,message=message,cell_bytes=b,seed=seed,scenario=scenario,mutation=mutation,checks=len(rows),expected_counts=counts,expected_failure=label,coverage=sorted(observed),execution=ex);E.P.write_json(d/'result.json',r);records.append(r);e.check(r['id'],status in ('pass','detected'),r)
  e.check(f'b{b}/coverage',not goals-hits,dict(required=sorted(goals),hit=sorted(hits),missing=sorted(goals-hits)))
 E.P.write_json(e.out/'executions.json',records);E.P.write_json(e.out/'builds.json',{str(k):dict(binary=str(v[0]),execution=v[1]) for k,v in builds.items()})
 changed=[]
 for p in e.out.rglob('manifest.json'):
  for name,h in json.loads(p.read_text()).get('source_sha256',{}).items():
   f=ROOT/name
   if not f.is_file() or E.hashlib.sha256(f.read_bytes()).hexdigest()!=h:changed.append(name)
 try:SC.verify(record)
 except (OSError,ValueError) as err:changed.append(str(err))
 e.check('source-freshness',not changed,changed);return e.finish()
def main():
 p=E.parser(__doc__,'local-vci-soclib');p.add_argument('--systemc-config',default='lsi-systemc-config');p.add_argument('--cxx',default='c++');p.add_argument('--build-timeout',type=float,default=600);a=p.parse_args();E.validate(p,a)
 import math
 if not math.isfinite(a.build_timeout) or a.build_timeout<=0 or a.seed>2**31-4:p.error('valid timeout and seed required')
 a.cxx=shutil.which(a.cxx) or a.cxx;a.systemc_config=shutil.which(a.systemc_config) or a.systemc_config
 try:return run(a)
 except (OSError,ValueError,KeyError,TypeError) as err:print('RUNNER_ERROR',err,file=sys.stderr);return 1
if __name__=='__main__':sys.exit(main())

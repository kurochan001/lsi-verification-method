"""Shared reproducible evidence for diagnosis and saved AI proposal exercises."""
from collections import Counter
import importlib.util
from pathlib import Path
import random
import re
HERE=Path(__file__).resolve().parent
def load(name,path):
    s=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
E=load('triage_evidence',HERE.parent/'local-exploration-common/evidence.py')
HARNESS=HERE.parent/'local-uvm-random/sim_main.cpp'
SOURCES=[HERE.parent/'local-irq-cdc/rtl/irq_pending.sv',HERE/'tb/top.sv']
COVERS={'cp_event','cp_collision','cp_masked','cp_reset_pending','cp_obligation'}
def inputs():return [Path(__file__),HARNESS,*SOURCES]
def vectors(seed,n):
    # Reset pending, masked storage, and event/clear collision are mandatory.
    rows=[[0,0,0,0],[1,1,0,0],[1,0,0,1],[1,1,1,1],[1,0,1,1],
          [1,1,0,1],[0,0,0,0],[1,0,0,1]]
    rng=random.Random(seed)
    return rows+[[1,rng.randrange(2),rng.randrange(2),rng.randrange(2)] for _ in range(n)]+[[1,0,0,1]]
def oracle(log,rows,complete=False):
    matches=re.findall(r'^TRACE cycle=(\d+) rst=([01]) event=([01]) clear=([01]) enable=([01]) pend=([01]) irq=([01]) expected=([01])$',log,re.M)
    lines=[l for l in log.splitlines() if l.startswith('TRACE')]
    if len(matches)!=len(lines) or not matches:raise ValueError('missing/malformed trace')
    if complete and len(matches)!=len(rows):raise ValueError('incomplete trace')
    expected=0;rtl=[];model=[]
    for i,m in enumerate(matches):
        cycle,r,e,c,en,p,irq,ref=map(int,m)
        if cycle!=i or i>=len(rows) or [r,e,c,en]!=rows[i]:raise ValueError('trace input/order differs')
        # Independent specification form: set union retained state, then reset.
        expected=int(bool(r) and (bool(e) or (bool(expected) and not bool(c))))
        if p!=expected or irq!=(expected & en):rtl.append(i)
        if ref!=expected:model.append(i)
    return dict(cycles=len(matches),rtl_mismatches=rtl,model_mismatches=model)
def native(path,log):
    counts={}
    for line in path.read_text().splitlines():
        if not line or line.startswith('#'):continue
        m=re.fullmatch(r"C '([^']*)' (\d+)",line)
        if not m:raise ValueError('malformed native cover record')
        meta=dict(p.split('\x02',1) for p in m[1].split('\x01') if p)
        if meta.get('t')!='user':continue
        label=meta.get('o')
        if label not in COVERS or label in counts or meta.get('h')!='TOP.top.'+label or Path(meta.get('f','')).resolve()!=(HERE/'tb/top.sv').resolve():raise ValueError('cover source/inventory differs')
        counts[label]=int(m[2])
    logged=Counter(re.findall(r'^REVIEW_COVER (\w+)$',log,re.M))
    if counts.keys()!=COVERS or set(logged)-COVERS or any(logged[k]!=v for k,v in counts.items()):raise ValueError('cover instrumentation/actions differ')
    return counts
class Simulator:
    def __init__(self,e):
        self.e=e;self.args=e.args;self.records=[]
        E.P.write_json(e.out/'tools.json',dict(verilator=E.P.execute([self.args.verilator,'--version'],e.out/'verilator-version.log',self.args.timeout,e.out)))
        self.build=E.P.execute([self.args.verilator,'--cc','--exe','--build','--timing','--trace','--coverage-user','--assert','-Wno-fatal','-j','2','--top-module','top','--Mdir',str(e.out/'build'),*map(str,SOURCES),str(HARNESS)],e.out/'build.log',self.args.build_timeout,e.out)
        E.P.write_json(e.out/'build.json',self.build);self.built=not self.build['error'] and self.build['returncode']==0;e.check('build',self.built,self.build)
    def execute(self,identity,rows,mutation=0,model=0,sva_off=0,sva_mode=0,hang=0,missing=False):
        d=self.e.out/identity;d.mkdir(parents=True);vectors_path=d/'vectors.txt';vectors_path.write_text(''.join(' '.join(map(str,row))+'\n' for row in rows))
        command=[str(self.e.out/('missing-simulator' if missing else 'build/Vtop')),f'+VECTORS={vectors_path}',f'+WAVE={d/"wave.vcd"}',f'+CHECKS={len(rows)}',f'+MUTATION={mutation}',f'+MODEL={model}',f'+SVA_OFF={sva_off}',f'+SVA_MODE={sva_mode}',f'+HANG={hang}']
        if self.built:r=E.P.execute(command,d/'simulation.log',min(self.args.timeout,0.2) if hang else self.args.timeout,d)
        else:r=dict(error='build failed',returncode=None,command=command);(d/'simulation.log').write_text('build failed\n')
        log=(d/'simulation.log').read_text(errors='replace');status,message=E.P.classify(dict(checks=len(rows),expected_failure=None),r,log)
        analysis=None;counts=None;problems=[]
        try:
            if not r['error']:analysis=oracle(log,rows,complete=status=='pass')
        except ValueError as exc:problems.append(str(exc))
        try:
            if status=='pass':counts=native(d/'coverage.dat',log)
            if not r['error'] and (not (d/'wave.vcd').is_file() or '$enddefinitions' not in (d/'wave.vcd').read_text()):raise ValueError('waveform missing')
        except (OSError,ValueError) as exc:problems.append(str(exc))
        compared=re.findall(r'^TRIAGE_COMPARED compared=(\d+)$',log,re.M)
        record=dict(id=identity,status=status,message=message,execution=r,oracle=analysis,native=counts,compared=int(compared[0]) if len(compared)==1 else None,problems=problems,rows=len(rows),mutation=mutation,model=model,sva_off=sva_off,sva_mode=sva_mode)
        E.P.write_json(d/'execution.json',record);self.records.append(record)
        return record,log
    def save(self):E.P.write_json(self.e.out/'executions.json',self.records)
def detected(record,log,label):
    r=record['execution'];return not r['error'] and r['returncode']!=0 and re.findall(r'^CHECK_FAIL (\w+)$',log,re.M)==[label] and not re.search(r'^RESULT PASS',log,re.M) and not record['problems']
def good(record):
    return record['status']=='pass' and not record['problems'] and record['oracle'] is not None and not record['oracle']['rtl_mismatches'] and not record['oracle']['model_mismatches'] and record['native'] is not None and all(n>0 for n in record['native'].values()) and record['compared']==record['rows']
def diagnose(record,log):
    # These are evidence-backed classifications for this bounded exercise.
    error=record['execution']['error']
    if error=='command timeout':return 'timeout'
    if error and 'No such file or directory' in error:return 'missing-tool'
    if error or record['problems']:return 'unclassified'
    # Judge from what ran: required covers and executed comparisons, not from the requested settings.
    if record['status']=='pass' and (not record['native'] or not all(record['native'].values()) or record['compared']!=record['rows']):return 'verification-configuration'
    o=record['oracle']
    if o and o['rtl_mismatches']:return 'rtl-mismatch' if not o['model_mismatches'] else 'rtl-and-model-mismatch'
    if o and o['model_mismatches']:return 'expected-value-mismatch'
    return 'pass' if good(record) else 'unclassified'

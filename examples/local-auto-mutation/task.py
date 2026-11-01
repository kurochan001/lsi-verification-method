#!/usr/bin/env python3
"""Bounded MCY adapter: execution failures never count as detected mutations."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import sys
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1]
sys.path.insert(0,str(ROOT/'tools'));sys.path.insert(0,str(HERE))
import quality_common as Q
from vectors import vectors
spec=importlib.util.spec_from_file_location('mcy_formal_evidence',ROOT/'examples/local-formal-common/runner.py');F=importlib.util.module_from_spec(spec);spec.loader.exec_module(F)

def sim_status(execution,log,count):
    if execution['error']:return 'TIMEOUT' if execution['error']=='command timeout' else 'ERROR'
    if execution['returncode']==0 and log.count(f'MCY_COMPARE PASS checks={count}\n')==1 and 'CHECK_FAIL' not in log:return 'PASS'
    failures=re.findall(r'^CHECK_FAIL IRQ_VALUE row=(\d+)$',log,re.M)
    if execution['returncode']==1 and len(failures)==1 and int(failures[0])<count and 'MCY_COMPARE PASS' not in log:return 'FAIL'
    return 'ERROR'

def compare(kind,source,directory,project,compiler=None):
    directory.mkdir(parents=True,exist_ok=False);records={};status='ERROR'
    if kind in ('weak','strong'):
        rows=vectors(kind);path=directory/'vectors.txt';path.write_text(''.join(' '.join(format(x,'x') for x in row)+'\n' for row in rows))
        binary=directory/'sim.vvp';wave=directory/'trace_sim.vcd'
        build=Q.P.execute([compiler or os.environ.get('MCY_IVERILOG','iverilog'),'-g2012','-s','tb','-o',str(binary),str(source),str(HERE/'tb.sv')],directory/'build.log',60,directory)
        records['build']=build
        if not build['error'] and build['returncode']==0:
            execution=Q.P.execute([os.environ.get('MCY_VVP','vvp'),'-N',str(binary),'+VECTORS='+str(path),'+WAVE='+str(wave)],directory/'simulation.log',30,directory)
            log=(directory/'simulation.log').read_text(errors='replace');status=sim_status(execution,log,len(rows));records.update(execution=execution,planned_checks=len(rows),checks=len(rows) if status=='PASS' else int(re.search(r'^CHECK_FAIL IRQ_VALUE row=(\d+)$',log,re.M)[1])+1 if status=='FAIL' else 0)
            if status in ('PASS','FAIL') and (not wave.is_file() or '$enddefinitions' not in wave.read_text()):status='ERROR'
    else:
        shutil.copyfile(source,directory/'mutated.v')
        original=(HERE/'rtl/irq_regs.sv').read_text();reference,n=re.subn(r'\bmodule irq_regs\b','module reference_irq',original,count=1)
        if n!=1:raise ValueError('reference module identity differs')
        (directory/'reference.sv').write_text(reference);shutil.copyfile(HERE/'miter.sv',directory/'miter.sv')
        (directory/'task.sby').write_text('[options]\nmode prove\ntimeout 60\n[engines]\nabc pdr\n[script]\nread -formal -sv reference.sv mutated.v miter.sv\nprep -top miter\nwrite_json properties.json\n[files]\nreference.sv\nmutated.v\nmiter.sv\n')
        execution=Q.P.execute([os.environ['MCY_SBY'],'-f','-d',str(directory/'formal'),str(directory/'task.sby')],directory/'formal.log',90,directory);records['execution']=execution
        work=directory/'formal';observed=(work/'status').read_text().split()[0] if (work/'status').is_file() else None
        try:
            if execution['error']:status='TIMEOUT' if execution['error']=='command timeout' else 'ERROR'
            elif observed in ('PASS','FAIL') and execution['returncode']==(0 if observed=='PASS' else 2):
                model=json.loads((work/'src/properties.json').read_text());cells=[(n,c) for m in model['modules'].values() for n,c in m['cells'].items() if c['type']=='$check']
                if sorted((c['parameters']['FLAVOR'],n.rsplit('.',1)[-1]) for n,c in cells)!=[('assert','ap_functional_equivalence'),('assume','as_initial_reset')]:raise ValueError('equivalence property inventory differs')
                log=(work/'logfile.txt').read_text();reached,unreached,failed=F.observed(log)
                if observed=='PASS' and not failed and 'Property proved.' in log:status='PASS'
                elif observed=='FAIL' and failed=={'ap_functional_equivalence'}:
                    traces=F.witnessed_traces(work/'engine_0',directory)
                    if len(traces)==1:status='FAIL';records['traces']=traces
        except (OSError,ValueError,KeyError,TypeError) as exc:status='ERROR';records['error']=str(exc)
    records.update(status=status,kind=kind,mutated_sha256=Q.digest(source));Q.write(directory/'result.json',records);return status

def main():
    kind=sys.argv[1];project=Path(os.environ['PRJDIR']);lines=Path('input.txt').read_text().splitlines()
    if len(lines)!=1:raise ValueError('one mutation per task required')
    fields=lines[0].split(maxsplit=1);identities=os.environ.get('MUTATIONS','').split()
    if len(fields)!=2 or fields[0]!='1' or not fields[1].startswith('mutate ') or len(identities)!=1 or not identities[0].isdigit():raise ValueError('invalid MCY mutation input')
    identity=int(identities[0]);output=project/'evidence'/str(identity)/kind
    generated=Q.P.execute(['bash',str(Path(os.environ['SCRIPTS'])/'create_mutated.sh')],Path.cwd()/'export.log',60,Path.cwd())
    if generated['error'] or generated['returncode']!=0:status='ERROR'
    else:
        # Copy all generated inputs before MCY removes its temporary task directory.
        output.parent.mkdir(parents=True,exist_ok=True)
        source=output.parent/'mutated.v'
        data=Path('mutated.v').read_bytes()
        if source.exists() and source.read_bytes()!=data:raise ValueError('mutation differs between tests')
        source.write_bytes(data);status=compare(kind,source,output,project)
        shutil.copyfile('input.txt',output/'input.txt');shutil.copyfile('export.log',output/'export.log')
    Path('output.txt').write_text('1 '+status+'\n')
if __name__=='__main__':main()

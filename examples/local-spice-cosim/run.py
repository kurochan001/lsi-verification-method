#!/usr/bin/env python3
"""Close an RTL hysteresis-control loop through the actual ngspice RC solver."""
import importlib.util
import json
import math
from pathlib import Path
import random
import shutil
import sys
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1]
def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module
S=load('spice_native',HERE.parent/'local-native-common/runner.py');E=S.E
N=load('spice_installation',ROOT/'tools/ngspice.py')
CONFIGS={'adc8-rc100us':dict(bits=8,resistance=1000,capacitance=1e-7),'adc10-rc200us':dict(bits=10,resistance=2000,capacitance=1e-7)}
FIXED=('control','reset-enable','supply-step','setpoint-step')
RTL=[HERE/'rtl/rc_hysteresis.sv'];CPP=[HERE/'harness.cpp']

def program(name,bits,seed,random_count):
    if bits not in (8,10) or not 1<=random_count<=2000:raise ValueError('unsupported ADC width or program length')
    rng=random.Random(seed);full=(1<<bits)-1;rows=[]
    count=random_count if name=='random' else 280 if name=='reset-enable' else 300 if name in ('supply-step','setpoint-step') else 240
    low=int(full*0.30);high=int(full*0.50);supply=3300
    for k in range(1,count+1):
        resetn=int(k!=1 and not (name=='reset-enable' and k in (80,81)))
        enable=int(not (name=='reset-enable' and (120<=k<140 or 240<=k<250)))
        if name=='supply-step':supply=2700 if 100<=k<200 else 3300
        if name=='setpoint-step':
            low=int(full*(0.30 if k<100 else 0.18 if k<200 else 0.40))
            high=int(full*(0.50 if k<100 else 0.32 if k<200 else 0.65))
        if name=='random':
            if k%32==1:
                low=rng.randrange(full//10,full*4//10);high=rng.randrange(full//2,full*7//10);supply=rng.choice((2700,3000,3300))
            enable=int(rng.randrange(8)!=0)
            if k==count//2:resetn=0
        rows.append([resetn,enable,low,high,supply])
    return rows

def metrics(directory,expected):
    record=json.loads((directory/'metrics.json').read_text())
    if record['samples']!=expected or record['analog_points']<2*expected or record['source_queries']<record['analog_points']:
        raise ValueError('ngspice work/clock count evidence differs')
    if not math.isfinite(record['max_error']) or record['max_error']>2e-4 or abs(record['last_time']-expected*1e-5)>1e-12:
        raise ValueError('ngspice numerical/time evidence differs')
    return record

def run(a):
    seeds=list(range(a.seed,a.seed+(3 if a.profile=='nightly' else 1)))
    names=[*FIXED,*[f'random-{s}' for s in seeds],'detect-rtl-1','detect-rtl-2','detect-plant','detect-adc','detect-dac']
    ids=['toolchain','ngspice-installation',*[f'{cfg}/{name}' for cfg in CONFIGS for name in [*names,'coverage']],'source-freshness']
    inputs=[Path(__file__),Path(S.__file__),Path(N.__file__),N.CONFIG,ROOT/N.spec()['patch']['file'],*RTL,*CPP,HERE/'model.hpp',HERE/'plant.cir.in',HERE/'requirements.json']
    e=E.Evidence('local-spice-cosim',a,inputs,dict(configurations=CONFIGS,seeds=seeds,clock_seconds=1e-5,voltage_tolerance=2e-4),ids)
    sim=S.Native(e,'rc_hysteresis',RTL,CPP);good,probes=sim.probes();e.check('toolchain',good,probes)
    probe=E.P.execute([a.ngspice_config,'--prefix'],e.out/'ngspice-prefix.log',a.timeout,e.out)
    if probe['error'] or probe['returncode']!=0:raise ValueError('ngspice configuration unavailable; run tools/setup_ngspice.py')
    prefix=Path((e.out/'ngspice-prefix.log').read_text().strip());snapshot=N.snapshot(prefix)
    E.P.write_json(e.out/'ngspice-source.json',snapshot)
    diagnosis=N.probe(prefix);E.P.write_json(e.out/'ngspice-probe.json',diagnosis);e.check('ngspice-installation',diagnosis['success'],diagnosis)
    _,goals=E.C.catalog(HERE/'requirements.json');coverage={}
    for cfg,config in CONFIGS.items():
        hits=set()
        for name in names:
            mutation=int(name[-1]) if name.startswith('detect-rtl-') else 0
            scenario='reset-enable' if mutation==2 else 'control' if name.startswith('detect-') else 'random' if name.startswith('random-') else name
            seed=int(name[7:]) if name.startswith('random-') else a.seed
            rows=program(scenario,config['bits'],seed,640 if a.profile=='nightly' else 192)
            vectors=e.out/'vectors'/cfg/name/'vectors.txt';vectors.parent.mkdir(parents=True);vectors.write_text(''.join(' '.join(map(str,row))+'\n' for row in rows))
            fault={'detect-plant':1,'detect-adc':2,'detect-dac':3}.get(name,0)
            template=(HERE/'plant.cir.in').read_text()
            if template.count('@R@')!=1 or template.count('@C@')!=1:raise ValueError('RC template placeholders differ')
            deck=vectors.parent/'plant.cir';deck.write_text(template.replace('@R@',str(config['resistance']*(2 if fault==1 else 1))).replace('@C@',format(config['capacitance'],'.17g')))
            label='SPICE_CONTROL' if mutation else {'detect-plant':'SPICE_ANALOG','detect-adc':'SPICE_ADC','detect-dac':'SPICE_DAC'}.get(name)
            build=sim.build(cfg,dict(ADC_BITS=config['bits']),mutation,flags=['-I'+str(prefix/'include')],ldflags=['-ldl'])
            expected=dict(samples=len(rows),resets=sum(not r[0] for r in rows),disabled=sum(not r[1] for r in rows),updates=len(rows))
            result=sim.execute(cfg+'/'+name,build,[scenario,vectors,Path(snapshot['library']),config['resistance'],config['capacitance'],fault,deck],expected,len(rows),label,credited=label is None,validator=lambda d,n=len(rows):metrics(d,n))
            hits.update(result['coverage'])
        coverage[cfg]=dict(required=sorted(goals),hit=sorted(hits),missing=sorted(goals-hits));e.check(cfg+'/coverage',not goals-hits,coverage[cfg])
    sim.save();E.P.write_json(e.out/'coverage.json',coverage)
    changed=[]
    try:N.verify(snapshot)
    except (OSError,ValueError,KeyError,TypeError) as err:changed.append(str(err))
    S.fresh(e,changed);return e.finish()

def main():
    p=S.parser(__doc__,'local-spice-cosim');p.add_argument('--ngspice-config',default='lsi-ngspice-config');a=p.parse_args();S.validate(p,a)
    a.ngspice_config=shutil.which(a.ngspice_config) or a.ngspice_config
    try:return run(a)
    except (OSError,ValueError,KeyError,TypeError,AttributeError) as err:print('RUNNER_ERROR',err,file=sys.stderr);return 1
if __name__=='__main__':sys.exit(main())

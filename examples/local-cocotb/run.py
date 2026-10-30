#!/usr/bin/env python3
"""Real cocotb APB driver, monitor, independent register oracle and checker sensitivity."""
import importlib.util
from pathlib import Path
import random
import sys
HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('host_runner',HERE.parent/'local-host-common/runner.py');H=importlib.util.module_from_spec(spec);spec.loader.exec_module(H)
NAME='local-cocotb';CONFIGS={'wait0':0,'wait2':2};ITERATIONS={'smoke':32,'nightly':300}
INPUTS=[HERE/'test_apb.py',HERE/'worker.py',HERE/'tools-requirements.txt',HERE.parent/'local-apb/rtl/apb_regs.sv']
def operations(seed,iterations,boundary=False):
    # Each transaction has setup/access events. New events win over W1C on completion.
    fixed=[[0,1,0x12345678,0,0],[0,0,0,0,0],[4,0,0,0,0],[8,1,15,3,3],[8,0,0,0,0],
           [4,1,0xffffffff,0,0],[12,1,1,0,0],[3,0,0,0,0],[0,1,0,0,0],[0,0,0,0,0]]
    if boundary:return fixed
    rng=random.Random(seed)
    return fixed+[[rng.choice((0,4,8,12,3)),rng.randrange(2),rng.getrandbits(32),rng.randrange(16),rng.randrange(16)] for _ in range(iterations)]
def totals(ops):return dict(transactions=len(ops),reads=sum(not r[1] for r in ops),writes=sum(r[1] for r in ops),errors=sum(r[0] not in (0,4,8) or (r[1] and r[0]==4) for r in ops))
def cases(args):
    result=[]
    for config,wait in CONFIGS.items():
        def case(name,ops,mutation=0,checker=0,category='functional',label=None,seed=None):
            return dict(id=config+'-'+name,configuration=config,wait=wait,operations=ops,mutation=mutation,checker=checker,category=category,expected_failure=label,checks=len(ops),counts=totals(ops),seed=args.seed if seed is None else seed)
        baseline=operations(17,0,True);result.append(case('boundaries',baseline))
        for seed in range(args.seed,args.seed+(3 if args.profile=='nightly' else 1)):result.append(case(f'random-seed{seed}',operations(seed,args.iterations),seed=seed))
        for m,label in ((1,'COCOTB_SETUP'),(2,'COCOTB_PENDING'),(3,'COCOTB_CONFIG')):result.append(case(f'detect-mutation{m}',baseline,m,category='mutation',label=label))
        # Deliberately corrupt the independent expected ID, with the original RTL.
        result.append(case('detect-bad-expectation',baseline,checker=1,category='diagnostic',label='COCOTB_READ'))
    return result
def probes(args):return {'iverilog':[args.iverilog,'-V'],'cocotb':[sys.executable,'-c','import cocotb,sys;print(cocotb.__version__);print(sys.version)'],'packages':[sys.executable,'-m','pip','freeze']}
def prepare(args,out):return None
def execute(args,out,d,case,context):
    execution=H.P.execute([sys.executable,str(HERE/'worker.py'),str(d/'case.json'),args.iverilog,args.vvp],d/'simulation.log',args.timeout,d)
    try:
        import xml.etree.ElementTree as ET
        nodes=list(ET.parse(d/'cocotb-junit.xml').getroot().iter('testcase'))
        failures=sum(bool(list(n.iter('failure')) or list(n.iter('error'))) for n in nodes)
        if len(nodes)!=1 or failures!=int(case['expected_failure'] is not None):raise ValueError('native cocotb JUnit differs from plan')
        wave=d/'build/apb_regs.fst'
        if not wave.is_file() or not wave.stat().st_size:raise ValueError('native waveform missing')
    except (OSError,ValueError,ET.ParseError) as exc:execution=dict(execution,error='invalid cocotb evidence: '+str(exc))
    return execution
if __name__=='__main__':sys.exit(H.main(sys.modules[__name__]))

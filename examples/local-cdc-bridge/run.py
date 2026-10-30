#!/usr/bin/env python3
"""Wide asynchronous request/response FIFOs connected to an APB target."""
import importlib.util
from pathlib import Path
import random
import sys
HERE=Path(__file__).resolve().parent
NAME='local-cdc-bridge';TOP='cdc_bridge_tb'
CONFIGS={'source-fast':dict(SRC_HALF=3,DST_HALF=7,SYNC_STAGES=2,WAIT_CYCLES=2),
         'target-fast':dict(SRC_HALF=7,DST_HALF=3,SYNC_STAGES=3,WAIT_CYCLES=0)}
ITERATIONS={'smoke':12,'nightly':100}
SOURCES=[HERE/'rtl/packet_fifo.sv',HERE/'rtl/cdc_apb_bridge.sv',HERE.parent/'local-apb/rtl/apb_regs.sv',HERE/'tb/cdc_bridge_tb.sv']
def expected(n,seed):
    value=checksum=errors=0
    for index in range(n):
        op=index%5;data=(seed+index*0x01030507)&0xffffffff
        if op==0:value=data
        result=value if op==1 else 0x41504233 if op==2 else 0
        error=int(op>=3);errors+=error
        checksum=((checksum*33)^result^error^(index+1))&0xffffffff
    return checksum,errors
def vector(n,seed,reset=0,stall=0):
    checksum,errors=expected(n,seed);return [n,seed,reset,stall,checksum,errors]
def counts(rows):
    return dict(requests=sum(r[0]+bool(r[2]) for r in rows),responses=sum(r[0] for r in rows),
                apb=sum(r[0]+bool(r[2]) for r in rows),errors=sum(r[5] for r in rows),flushes=sum(bool(r[2]) for r in rows))
def make_cases(args,parameters):
    baseline=[vector(10,0x12345678),vector(12,0x87654321,1,5),vector(11,0xa5a55a5a,2,7),vector(9,0,3,3)]
    cases=[dict(id='boundaries',vectors=baseline,mutation=args.demo_bug,category='functional',expected_failure=None)]
    for seed in range(args.seed,args.seed+(3 if args.profile=='nightly' else 1)):
        rng=random.Random(seed);rows=[vector(rng.randint(5,16),rng.getrandbits(32),rng.randrange(4),rng.randrange(9)) for _ in range(args.iterations)]
        cases.append(dict(id=f'random-seed{seed}',vectors=rows,mutation=args.demo_bug,category='functional',expected_failure=None))
    for m,label in ((1,'CDC_TAG'),(2,'CDC_APB'),(3,'CDC_RESET'),(4,'CDC_DATA')):
        cases.append(dict(id=f'detect-mutation{m}',vectors=baseline,mutation=m,category='mutation',expected_failure=label))
    for c in cases:c['counts']=counts(c['vectors'])
    return cases
if __name__=='__main__':
    spec=importlib.util.spec_from_file_location('local_runner',HERE.parent/'local-common/runner.py')
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);sys.exit(m.main(sys.modules[__name__]))

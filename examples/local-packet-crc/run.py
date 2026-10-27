#!/usr/bin/env python3
import importlib.util
from pathlib import Path
import random
import sys
HERE=Path(__file__).resolve().parent
NAME='local-packet-crc';TOP='crc_tb';CONFIGS={'init0': {'INIT': 0}, 'initff': {'INIT': 255}}
ITERATIONS={'smoke': 30, 'nightly': 200};SOURCES=[HERE/'rtl/crc.sv',HERE/'tb/crc_tb.sv']
def reference(data,initial):
    # Polynomial division of the complete message, not the RTL byte/bit recurrence.
    value=(initial << (8*len(data))) ^ (int.from_bytes(bytes(data),'big')<<8)
    while value.bit_length()>8:value^=0x107 << (value.bit_length()-9)
    return value
class Plan:
    def __init__(self,initial):self.initial=initial;self.rows=[];self.data=[];self.output=None
    def cycle(self,rst=1,valid=0,data=0,keep=0,last=0,check=0,expected=0,ready=1):
        if not rst:self.data=[];self.output=None
        available=int(bool(rst and self.output is None));out=self.output or (0,0)
        self.rows.append([rst,valid,data,keep,last,check,expected,ready,available,int(self.output is not None),*out])
        if rst:
            if self.output is not None and ready:self.output=None
            if valid and available:
                self.data += [(data>>(8*i))&255 for i in range(4) if keep&(1<<i)]
                if last:
                    crc=reference(self.data,self.initial);self.output=(crc,int(bool(check and crc!=expected)));self.data=[]
    def packet(self,beats,check=0,bad=0,stall=0):
        payload=[(d>>(8*i))&255 for d,k in beats for i in range(4) if k&(1<<i)]
        wanted=reference(payload,self.initial)^bad
        for i,(d,k) in enumerate(beats):self.cycle(valid=1,data=d,keep=k,last=int(i==len(beats)-1),check=check,expected=wanted)
        for _ in range(stall):self.cycle(ready=0)
        self.cycle();self.cycle()
def vectors(seed,iterations,parameters,boundary=False):
    p=Plan(parameters['INIT']);p.cycle(rst=0)
    p.packet([(0x34333231,15),(0x38373635,15),(0xeeeeee39,1)],1,stall=3)
    p.packet([(0xa5a5a5a5,0)],1);p.packet([(0x12345678,5),(0x1234abcd,10)],1,1)
    p.cycle(valid=1,data=0xabcdef,keep=7);p.cycle(rst=0);p.packet([(0x99887766,15)],1)
    if not boundary:
        rng=random.Random(seed)
        for _ in range(iterations):p.packet([(rng.getrandbits(32),rng.randrange(16)) for _ in range(rng.randint(1,6))],rng.randrange(2),rng.randrange(2),rng.randrange(4))
    return p.rows

def make_cases(args,parameters):
    base=vectors(args.seed,0,parameters,True)
    cs=[dict(id='boundaries',vectors=base,mutation=args.demo_bug,category='functional',expected_failure=None)]
    for seed in range(args.seed,args.seed+(3 if args.profile=='nightly' else 1)):
        cs.append(dict(id=f'random-seed{seed}',vectors=vectors(seed,args.iterations,parameters),mutation=args.demo_bug,category='functional',expected_failure=None))
    for mutation,label in [(1, 'CRC_DATA'), (2, 'CRC_DATA'), (3, 'CRC_DATA'), (4, 'CRC_ERROR')]:
        cs.append(dict(id=f'detect-mutation{mutation}',vectors=base,mutation=mutation,category='mutation',expected_failure=label))
    for c in cs:c['counts']={'steps':len(c['vectors'])}
    return cs
if __name__=='__main__':
    spec=importlib.util.spec_from_file_location('local_runner',HERE.parent/'local-common/runner.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);sys.exit(m.main(sys.modules[__name__]))

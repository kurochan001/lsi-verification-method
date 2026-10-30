#!/usr/bin/env python3
"""Local AXI4 subset: INCR bursts, IDs, two outstanding and response backpressure."""
import importlib.util
from pathlib import Path
import random
import sys
HERE=Path(__file__).resolve().parent
NAME='local-axi4';TOP='axi4_tb';CONFIGS={'two-outstanding':{}}
ITERATIONS={'smoke':48,'nightly':500}
SOURCES=[HERE/'rtl/axi4_ram.sv',HERE/'tb/axi4_tb.sv']


def pattern(seed,beat):
    return (seed+0x01030507*beat)&0xffffffff


def mask(mode,beat):
    return (15,5,0,(1,2,4,8)[beat%4])[mode]


def invalid(address,beats,size,burst):
    return bool(address%4 or size!=2 or burst!=1 or beats>4 or address+4*beats>8192 or address//4096!=(address+4*beats-1)//4096)


class Plan:
    def __init__(self):self.memory=bytearray(8192);self.rows=[]
    def batch(self,a=0,b=64,n=4,m=4,i=1,j=2,seed=0x12345678,mode=0,stall=3,gap=0,size=2,burst=1):
        if not (0<=a<8192 and 0<=b<8192 and 1<=n<=4 and 1<=m<=4 and 0<=i<4 and 0<=j<4):
            raise ValueError('batch exceeds address/length/ID vector fields')
        descriptors=[(a,n,i),(b,m,j)];expected=[];errors=[]
        for index,(address,beats,ident) in enumerate(descriptors):
            error=invalid(address,beats,size,burst);errors.append(int(error))
            for beat in range(beats):
                data=pattern(seed ^ (0x5a5a5a5a if index else 0),beat)
                if not error:
                    for lane in range(4):
                        if mask(mode,beat)&(1<<lane):self.memory[address+beat*4+lane]=(data>>(lane*8))&255
        for address,beats,ident in descriptors:
            expected += [int.from_bytes(self.memory[address+4*beat:address+4*beat+4],'little') if not invalid(address,beats,size,burst) else 0 for beat in range(beats)]
        expected += [0]*(8-len(expected))
        self.rows.append([a,b,n,m,i,j,seed,mode,stall,gap,size,burst,*errors,*expected])


def boundary_vectors():
    p=Plan()
    for n in range(1,5):p.batch(n=n,m=5-n,i=n-1,j=n%4,stall=n,gap=4-n)
    p.batch(i=3,j=3,mode=1,seed=0xa5c36987);p.batch(mode=2,stall=0,seed=0xffffffff);p.batch(mode=3,seed=0x76543210)
    p.batch(a=0xff0,b=0x1000,n=4,m=4) # Last legal beat before, and first after, the 4KB boundary.
    p.batch(a=0xffc,b=0x1ffc,n=2,m=2) # Defensive response to illegal boundary/range requests.
    p.batch(a=3,size=2);p.batch(size=1);p.batch(burst=0)
    p.batch(stall=64,gap=5,mode=2);p.batch(a=0xff0,b=0x1000,mode=2,stall=0) # Read back rejected-write targets.
    return p.rows


def random_vectors(seed,iterations):
    rng=random.Random(seed);p=Plan()
    for _ in range(iterations):
        region=rng.choice((0,4096));a=region+4*rng.randrange(0,16);b=region+128+4*rng.randrange(0,16)
        p.batch(a=a,b=b,n=rng.randint(1,4),m=rng.randint(1,4),i=rng.randrange(4),j=rng.randrange(4),
                seed=rng.getrandbits(32),mode=rng.randrange(4),stall=rng.randrange(7),gap=rng.randrange(5))
    return p.rows


def counts(rows):
    return dict(writes=2*len(rows),reads=2*len(rows),write_beats=sum(r[2]+r[3] for r in rows),
                read_beats=sum(r[2]+r[3] for r in rows),errors=2*sum(r[12]+r[13] for r in rows))


def make_cases(args,parameters):
    baseline=boundary_vectors()
    result=[dict(id='boundaries',vectors=baseline,mutation=args.demo_bug,category='functional',expected_failure=None)]
    for seed in range(args.seed,args.seed+(3 if args.profile=='nightly' else 1)):
        result.append(dict(id=f'random-seed{seed}',vectors=random_vectors(seed,args.iterations),mutation=args.demo_bug,
                           category='functional',expected_failure=None))
    for mutation,label in ((1,'AXI4_DATA'),(2,'AXI4_ID'),(3,'AXI4_LAST'),(4,'AXI4_DATA')):
        result.append(dict(id=f'detect-mutation{mutation}',vectors=baseline,mutation=mutation,category='mutation',expected_failure=label))
    for case in result:case['counts']=counts(case['vectors'])
    return result

if __name__=='__main__':
    spec=importlib.util.spec_from_file_location('local_runner',HERE.parent/'local-common/runner.py')
    support=importlib.util.module_from_spec(spec);spec.loader.exec_module(support)
    sys.exit(support.main(sys.modules[__name__]))

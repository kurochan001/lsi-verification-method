#!/usr/bin/env python3
"""AHB-Lite pipeline regression using a byte store and absolute completion times."""
import importlib.util
from pathlib import Path
import random
import sys
HERE=Path(__file__).resolve().parent
NAME='local-ahb';TOP='ahb_tb'
CONFIGS={f'wait{n}':dict(WAIT_CYCLES=n) for n in (0,1,3)}
ITERATIONS={'smoke':64,'nightly':500}
SOURCES=[HERE/'rtl/ahb_regs.sv',HERE/'tb/ahb_tb.sv']


def request(address,write=False,data=0,size=2,trans=2,burst=0,sel=1):
    return dict(address=address,write=int(write),data=data,size=size,trans=trans,burst=burst,sel=sel)


def invalid(address,write,size):
    return size>2 or address%(1<<size)!=0 or address>=20 or (write and address>=16)


class Oracle:
    def __init__(self,wait):self.wait=wait;self.time=0;self.pending=None;self.memory=bytearray(16)
    def step(self,inputs):
        rst,sel,trans,address,write,size,burst,data=inputs
        work=self.pending
        ready=1 if not rst or work is None else int(self.time>=work['finish'])
        response=int(bool(rst and work and work['bad'] and self.time>=work['finish']-1))
        read=0
        if rst and work and not work['write'] and not work['bad']:
            base=work['address']//4*4
            read=0x4148424c if base==16 else int.from_bytes(self.memory[base:base+4],'little')
        active=int(bool(rst and work));dw=work['write'] if active else 0
        da=work['address'] if active else 0;ds=work['size'] if active else 0
        if not rst:self.memory=bytearray(16);self.pending=None
        else:
            if work and ready:
                if not response and work['write']:
                    base=work['address'];offset=base%4
                    self.memory[base:base+(1<<work['size'])]=data.to_bytes(4,'little')[offset:offset+(1<<work['size'])]
                self.pending=None
            if ready and sel and trans>=2:
                bad=invalid(address,write,size)
                self.pending=dict(address=address,write=write,size=size,bad=bad,
                                  finish=self.time+1+self.wait+int(bad))
        registers=[int.from_bytes(self.memory[i:i+4],'little') for i in range(0,16,4)]
        self.time+=1
        return [*inputs,ready,response,read,active,dw,da,ds,*registers]


class Plan:
    def __init__(self,wait):self.model=Oracle(wait);self.rows=[]
    def cycle(self,rst=1,sel=0,trans=0,address=0,write=0,size=2,burst=0,data=0):
        row=self.model.step([rst,sel,trans,address,write,size,burst,data]);self.rows.append(row);return row
    def pipeline(self,requests):
        index=0;payload=0;cancel=False
        while index<len(requests) or self.model.pending is not None:
            req=requests[index] if index<len(requests) else request(0,trans=0,sel=0)
            row=self.cycle(sel=req['sel'],trans=0 if cancel else req['trans'],address=req['address'],
                           write=req['write'],size=req['size'],burst=req['burst'],data=payload)
            if row[8]:
                if not cancel and index<len(requests):
                    if req['sel'] and req['trans']>=2:payload=req['data']
                    else:payload=0
                    index+=1
                cancel=False
            elif row[9]:cancel=True  # Cancel the visible next address on first ERROR cycle.


def boundary_vectors(wait):
    p=Plan(wait);p.cycle(rst=0)
    for _ in range(wait+3):p.cycle(sel=1,write=1,address=0,data=0xdeadbeef)
    p.pipeline([request(0,True,0),request(4,True,0xffffffff),request(8,True,0x55555555),
                request(0),request(4),request(8),request(16)])
    p.pipeline([request(1,True,0x12ef34ab,size=0),request(2,True,0x9876abcd,size=1),
                request(0),request(1,size=0),request(2,size=1)])
    for write in (True,False):
        burst=[request(i*4,write,0x10203040+i,trans=2 if i==0 else 3,burst=3) for i in range(4)]
        burst.insert(2,request(8,write,trans=1,burst=3))
        p.pipeline(burst)
    p.pipeline([request(0,True,0xdeadbeef,sel=0),request(0)])
    p.pipeline([request(32),request(4),request(1,size=1),request(4),
                request(0,size=3),request(8),request(16,True,0x1234),request(16)])
    # Reset cancels the data phase before its completion, even in the zero-wait build.
    p.cycle(sel=1,trans=2,address=12,write=1);p.cycle(rst=0,data=0xfeedface)
    p.pipeline([request(12),request(12,True,0xa5a55a5a),request(12)])
    p.cycle(rst=0);p.cycle()
    return p.rows


def random_vectors(seed,iterations,wait):
    rng=random.Random(seed);p=Plan(wait);p.cycle(rst=0)
    requests=[]
    for _ in range(iterations):
        if rng.randrange(12)==0:
            p.pipeline(requests);requests=[]
            p.cycle(sel=1,trans=2,address=rng.randrange(4)*4,write=rng.randrange(2))
            p.cycle(rst=0,data=rng.getrandbits(32));p.cycle()
            continue
        if rng.randrange(4)==0:
            write=rng.randrange(2)
            for beat in range(4):
                if beat and rng.randrange(3)==0:
                    requests.append(request(beat*4,write,trans=1,burst=3))
                requests.append(request(beat*4,write,rng.getrandbits(32),trans=2 if beat==0 else 3,burst=3))
        else:
            size=rng.choice((0,1,2,2,2,3));address=rng.randrange(16)
            if size<=2:address=address//(1<<size)*(1<<size)
            if rng.randrange(8)==0:address=rng.choice((1,17,32,1020))
            requests.append(request(address,bool(rng.randrange(2)),rng.getrandbits(32),size=size))
        if rng.randrange(10)==0:requests.append(request(0,trans=0))
    p.pipeline(requests)
    p.pipeline([request(i*4) for i in range(4)])
    p.cycle(rst=0);p.cycle()
    return p.rows


def totals(rows):
    return dict(accepted=sum(bool(r[0] and r[1] and r[2]>=2 and r[8]) for r in rows),
                reads=sum(bool(r[11] and r[8] and not r[9] and not r[12]) for r in rows),
                writes=sum(bool(r[11] and r[8] and not r[9] and r[12]) for r in rows),
                errors=sum(bool(r[11] and r[8] and r[9]) for r in rows),
                waits=sum(bool(r[11] and not r[8]) for r in rows))


def make_cases(args,parameters):
    wait=parameters['WAIT_CYCLES'];baseline=boundary_vectors(wait)
    result=[dict(id='boundaries',vectors=baseline,mutation=args.demo_bug,expected_failure=None,category='functional')]
    for seed in range(args.seed,args.seed+(3 if args.profile=='nightly' else 1)):
        result.append(dict(id=f'random-seed{seed}',seed=seed,vectors=random_vectors(seed,args.iterations,wait),
                           mutation=args.demo_bug,expected_failure=None,category='functional'))
    for m,label in ((1,'AHB_STATE'),(2,'AHB_STATE'),(3,'AHB_RESPONSE'),(4,'AHB_DATA')):
        result.append(dict(id=f'detect-mutation{m}',vectors=baseline,mutation=m,expected_failure=label,category='mutation'))
    for case in result:case['counts']=totals(case['vectors'])
    return result


if __name__=='__main__':
    spec=importlib.util.spec_from_file_location('local_runner',HERE.parent/'local-common/runner.py')
    support=importlib.util.module_from_spec(spec);spec.loader.exec_module(support)
    sys.exit(support.main(sys.modules[__name__]))

#!/usr/bin/env python3
"""AXI4-Lite regression: independent request queues, byte store and response deadlines."""
from collections import deque
import importlib.util
from pathlib import Path
import random
import sys
HERE=Path(__file__).resolve().parent
NAME='local-axi';TOP='axi_tb'
CONFIGS={f'delay{n}':dict(RESP_DELAY=n) for n in (0,2)}
ITERATIONS={'smoke':40,'nightly':300}
SOURCES=[HERE/'rtl/axi_lite_regs.sv',HERE/'tb/axi_tb.sv']


def valid_address(address):return address%4==0 and address<=16


class Oracle:
    def __init__(self,delay):self.delay=delay;self.time=0;self.reset()
    def reset(self):
        self.memory=bytearray(16);self.aw=deque();self.w=deque()
        self.write_due=None;self.read_due=None;self.b=None;self.r=None
    def read_word(self,address):
        if not valid_address(address):return 0,2
        return (0x4158494c if address==16 else int.from_bytes(self.memory[address:address+4],'little')),0
    def outputs(self,rst=1):
        if not rst:return [0]*8
        return [int(not self.aw and self.write_due is None and self.b is None),
                int(not self.w and self.write_due is None and self.b is None),
                int(self.read_due is None and self.r is None),int(self.b is not None),
                0 if self.b is None else self.b,int(self.r is not None),
                0 if self.r is None else self.r[0],0 if self.r is None else self.r[1]]
    def step(self,inputs):
        rst,awv,awa,awp,wv,wd,ws,arv,ara,arp,br,rr=inputs
        outputs=self.outputs(rst)
        awready,wready,arready,bvalid,bresp,rvalid,rdata,rresp=outputs
        # Snapshot at AR acceptance, before a same-edge write commits.
        snapshot=self.read_word(ara) if arv and arready else None
        if not rst:self.reset()
        else:
            if bvalid and br:self.b=None
            if rvalid and rr:self.r=None
            if awv and awready:self.aw.append(awa)
            if wv and wready:self.w.append((wd,ws))
            if snapshot is not None:self.read_due=(self.time+1+self.delay,snapshot)
            if self.write_due==self.time:
                address=self.aw.popleft();value,strobe=self.w.popleft()
                self.b=0 if valid_address(address) and address<16 else 2
                if self.b==0:
                    for lane,byte in enumerate(value.to_bytes(4,'little')):
                        if strobe & (1<<lane):self.memory[address+lane]=byte
                self.write_due=None
            if self.read_due is not None and self.read_due[0]==self.time:
                self.r=self.read_due[1];self.read_due=None
            if self.aw and self.w and self.write_due is None and self.b is None:
                self.write_due=self.time+1+self.delay
        registers=[int.from_bytes(self.memory[i:i+4],'little') for i in range(0,16,4)]
        self.time+=1
        return [*inputs,*outputs,*registers]


class Plan:
    def __init__(self,delay):self.model=Oracle(delay);self.rows=[];self.delay=delay
    def cycle(self,rst=1,awv=0,awa=0,awp=0,wv=0,wd=0xdeadbeef,ws=0,arv=0,ara=0,arp=0,br=0,rr=0):
        row=self.model.step([rst,awv,awa,awp,wv,wd,ws,arv,ara,arp,br,rr]);self.rows.append(row);return row
    def idle(self,n=1,**kwargs):
        for _ in range(n):self.cycle(**kwargs)
    def write(self,address,data,strobe=15,aw_delay=0,w_delay=0,b_stall=0,read_address=None,r_stall=0,hold_r=False,protection=0):
        aw_done=w_done=b_done=ar_done=r_done=False
        bwait=rwait=0
        for tick in range(100):
            signals=self.model.outputs()
            br=int(b_stall==0 or (signals[3] and bwait>=b_stall))
            rr=0 if hold_r else int(r_stall==0 or (signals[5] and rwait>=r_stall))
            row=self.cycle(awv=int(tick>=aw_delay and not aw_done),awa=address if not aw_done else 0xfc,awp=protection,
                wv=int(tick>=w_delay and not w_done),wd=data if not w_done else data^0xffffffff,ws=strobe,
                arv=int(read_address is not None and not ar_done),ara=read_address or 0,arp=protection,br=br,rr=rr)
            aw_done|=bool(row[1] and row[12]);w_done|=bool(row[4] and row[13])
            ar_done|=bool(row[7] and row[14]);b_done|=bool(row[15] and br);r_done|=bool(row[17] and rr)
            if row[15] and not br:bwait+=1
            if row[17] and not rr:rwait+=1
            if b_done and (read_address is None or r_done):return
        raise ValueError('write plan did not complete')
    def read(self,address,stall=0,protection=0):
        ar_done=False;wait=0
        for _ in range(100):
            outputs=self.model.outputs();rr=int(stall==0 or (outputs[5] and wait>=stall))
            row=self.cycle(arv=int(not ar_done),ara=address,arp=protection,rr=rr)
            ar_done|=bool(row[7] and row[14])
            if row[17] and not rr:wait+=1
            if row[17] and rr:return
        raise ValueError('read plan did not complete')


def boundary_vectors(delay):
    p=Plan(delay);p.cycle(rst=0);p.idle()
    p.write(0,0,aw_delay=0,w_delay=3,b_stall=2)
    p.write(4,0xffffffff,aw_delay=3,w_delay=0)
    p.write(8,0x55555555,read_address=4,r_stall=2)
    # Present the next requests while the old B/R response blocks their READY.
    p.cycle(awv=1,awa=0,wv=1,wd=0x01020304,ws=15);p.idle(delay+2)
    p.cycle(awv=1,awa=4,wv=1,wd=0x05060708,ws=15)
    p.cycle(awv=1,awa=4,wv=1,wd=0x05060708,ws=15,br=1)
    p.cycle(awv=1,awa=4,wv=1,wd=0x05060708,ws=15,br=1);p.idle(delay+2,br=1)
    p.cycle(arv=1,ara=0);p.idle(delay+2)
    p.cycle(arv=1,ara=4);p.cycle(arv=1,ara=4,rr=1)
    p.cycle(arv=1,ara=4,rr=1);p.idle(delay+2,rr=1)
    for strobe in range(16):
        p.write(12,0x87654321 ^ (strobe*0x01010101),strobe=strobe,aw_delay=strobe%3,w_delay=(strobe+1)%3)
        p.read(12,stall=strobe%2)
    for address in (0,4,8,16):p.read(address)
    p.write(16,0xdeadbeef);p.write(3,0xdeadbeef);p.write(32,0xdeadbeef)
    p.read(3,stall=2);p.read(32)
    # AR acceptance on the exact write-commit edge observes the old value.
    p.cycle(awv=1,awa=0,wv=1,wd=0x11223344,ws=15);p.idle(delay)
    p.cycle(arv=1,ara=0);p.idle(delay+1);p.cycle(br=1,rr=1)
    # An old read response remains stable while a later write changes the same register.
    p.cycle(arv=1,ara=0);p.idle(delay+1);p.cycle(rr=0)
    p.write(0,0xa5a55a5a,b_stall=2,hold_r=True);p.cycle(rr=1);p.read(0)
    # Reset with only AW, only W, B pending, and R pending.
    p.cycle(awv=1,awa=4);p.cycle(rst=0);p.idle(2)
    p.cycle(wv=1,wd=0xffffffff,ws=15);p.cycle(rst=0);p.idle(2)
    p.cycle(awv=1,awa=4,wv=1,wd=0xffffffff,ws=15);p.idle(delay+2);p.cycle(rst=0);p.idle(2)
    p.cycle(arv=1,ara=0);p.idle(delay+2);p.cycle(rst=0);p.idle(2)
    p.write(0,0x12345678);p.read(0,stall=1)
    p.cycle(rst=0);p.idle(2)
    return p.rows


def random_vectors(seed,iterations,delay):
    rng=random.Random(seed);p=Plan(delay);p.cycle(rst=0)
    for _ in range(iterations):
        address=rng.choice((0,4,8,12,16,3,32))
        if rng.randrange(12)==0:
            mode=rng.randrange(4)
            if mode==0:p.cycle(awv=1,awa=address)
            elif mode==1:p.cycle(wv=1,wd=rng.getrandbits(32),ws=rng.randrange(16))
            elif mode==2:
                p.cycle(awv=1,awa=address,wv=1,wd=rng.getrandbits(32),ws=rng.randrange(16));p.idle(delay+2)
            else:p.cycle(arv=1,ara=address);p.idle(delay+2)
            p.idle(rng.randrange(5));p.cycle(rst=0);p.idle()
        elif rng.randrange(2):
            p.write(address,rng.getrandbits(32),rng.randrange(16),rng.randrange(9),rng.randrange(9),rng.randrange(13),
                    rng.choice((0,4,8,12)) if rng.randrange(3)==0 else None,rng.randrange(13),protection=rng.randrange(8))
        else:p.read(address,rng.randrange(13),rng.randrange(8))
    for address in (0,4,8,12):p.read(address)
    p.cycle(rst=0);p.idle(2)
    return p.rows


def totals(rows):
    return dict(aw=sum(bool(r[1] and r[12]) for r in rows),w=sum(bool(r[4] and r[13]) for r in rows),
        ar=sum(bool(r[7] and r[14]) for r in rows),b=sum(bool(r[15] and r[10]) for r in rows),
        r=sum(bool(r[17] and r[11]) for r in rows),write_errors=sum(bool(r[15] and r[10] and r[16]) for r in rows),
        read_errors=sum(bool(r[17] and r[11] and r[19]) for r in rows),
        b_stalls=sum(bool(r[15] and not r[10]) for r in rows),r_stalls=sum(bool(r[17] and not r[11]) for r in rows))


def make_cases(args,parameters):
    delay=parameters['RESP_DELAY'];baseline=boundary_vectors(delay)
    result=[dict(id='boundaries',vectors=baseline,mutation=args.demo_bug,expected_failure=None,category='functional')]
    for seed in range(args.seed,args.seed+(3 if args.profile=='nightly' else 1)):
        result.append(dict(id=f'random-seed{seed}',seed=seed,vectors=random_vectors(seed,args.iterations,delay),
                           mutation=args.demo_bug,expected_failure=None,category='functional'))
    for m,label in ((1,'AXI_STATE'),(2,'AXI_STATE'),(3,'AXI_STABILITY'),(4,'AXI_STABILITY')):
        result.append(dict(id=f'detect-mutation{m}',vectors=baseline,mutation=m,expected_failure=label,category='mutation'))
    for case in result:case['counts']=totals(case['vectors'])
    return result


if __name__=='__main__':
    spec=importlib.util.spec_from_file_location('local_runner',HERE.parent/'local-common/runner.py')
    support=importlib.util.module_from_spec(spec);spec.loader.exec_module(support)
    sys.exit(support.main(sys.modules[__name__]))

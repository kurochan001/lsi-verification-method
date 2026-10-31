#!/usr/bin/env python3
"""Stop-and-wait link: independent polynomial division and delivery ledger."""
import importlib.util
from pathlib import Path
import random
import sys
HERE=Path(__file__).resolve().parent
NAME='local-retry-link';TOP='retry_tb'
CONFIGS={'timeout3':{'TIMEOUT':3,'RETRIES':2},'timeout5':{'TIMEOUT':5,'RETRIES':3}}
ITERATIONS={'smoke':60,'nightly':500}
SOURCES=[HERE/'rtl/crc9.sv',HERE/'rtl/retry_sender.sv',HERE/'rtl/retry_receiver.sv',HERE/'tb/retry_tb.sv']


def crc(message):
    polynomial=message<<8
    for bit in range(16,7,-1):
        if polynomial&(1<<bit):polynomial^=0x107<<(bit-8)
    return polynomial


class Plan:
    def __init__(self,timeout,retries):
        self.timeout=timeout;self.retries=retries;self.rows=[];self.counts=dict(steps=0,inputs=0,outputs=0,successes=0,failures=0,retries=0)
        self.reset()

    def reset(self):
        self.phase=0;self.seq=0;self.payload=0;self.age=0;self.retried=0;self.done=0;self.error=0;self.failed=0
        self.rxseq=0;self.rxvalid=0;self.rxdata=0;self.ackvalid=0;self.ack=0;self.sent=False

    def cycle(self,rst=1,valid=0,data=0,line_ready=1,drop=0,corrupt=0,drop_ack=0,corrupt_ack=0,old_ack=0,ready=1,done_ready=1):
        if not rst:self.reset()
        sready=int(bool(rst and self.phase==0 and not self.done and not self.failed));txvalid=int(bool(rst and self.phase==1))
        message=(self.seq<<8)|self.payload;word=(message<<8)|crc(message)
        ack_valid=bool(self.ackvalid and not drop_ack);ack=self.ack^(1 if corrupt_ack else 0)
        injected_ack=(3 if self.seq else 12) if old_ack else 0
        if injected_ack:ack_valid=True;ack=injected_ack
        self.rows.append([rst,valid,data,line_ready,drop,corrupt,drop_ack,corrupt_ack,injected_ack,ready,done_ready,
                          sready,txvalid,word,self.rxvalid,self.rxdata,self.done,self.error,self.failed])
        self.counts['steps']+=1
        if not rst:return sready
        if self.rxvalid and ready:self.counts['outputs']+=1
        if self.done and done_ready:self.counts['failures' if self.error else 'successes']+=1
        if txvalid and line_ready:
            if self.sent:self.counts['retries']+=1
            self.sent=True
        if self.done and done_ready:self.done=0
        if self.phase==2:
            if ack_valid and ack in (3,12) and (ack>>3)==self.seq:self.phase=0;self.done=1;self.error=0;self.seq^=1
            elif self.age==self.timeout-1:
                self.age=0
                if self.retried<self.retries:self.retried+=1;self.phase=1
                else:self.phase=0;self.done=1;self.error=1;self.failed=1
            else:self.age+=1
        elif self.phase==1 and line_ready:self.phase=2;self.age=0
        if valid and sready:self.phase=1;self.payload=data;self.retried=0;self.age=0;self.error=0;self.sent=False;self.counts['inputs']+=1
        # Receiver acts on the frame and state that were visible before the edge.
        can_buffer=not self.rxvalid or ready
        if self.rxvalid and ready:self.rxvalid=0
        self.ackvalid=0
        if txvalid and line_ready and not drop:
            delivered=word^(0x100 if corrupt else 0);message=delivered>>8;seq=message>>8
            if delivered&255==crc(message):
                duplicate=seq!=self.rxseq
                if duplicate or can_buffer:
                    self.ackvalid=1;self.ack=12 if seq else 3
                    if not duplicate:self.rxvalid=1;self.rxdata=message&255;self.rxseq^=1
        return sready

    def transfer(self,data,mode='good',hold=0):
        if not self.cycle(valid=1,data=data):raise ValueError('sender not ready')
        attempt=0;steps=0
        while not self.done:
            sending=self.phase==1
            drop=int(mode in ('drop','lose-all') and (attempt==0 or mode=='lose-all'))
            corrupt=int(mode=='crc' and attempt==0)
            ackdrop=int(mode in ('ack-loss','ack-all') and (attempt==1 or mode=='ack-all'))
            ackbad=int(mode=='ack-crc' and attempt==1)
            old=int(mode=='old-ack' and attempt==1 and self.phase==2 and self.age==0)
            # For old ACK test, discard the real first frame, then retry normally.
            if mode=='old-ack' and attempt==0:drop=1
            self.cycle(drop=drop,corrupt=corrupt,drop_ack=ackdrop,corrupt_ack=ackbad,old_ack=old)
            if sending:attempt+=1
            steps+=1
            if steps>100:raise ValueError('link did not terminate')
        for _ in range(hold):self.cycle(done_ready=0)
        self.cycle();self.cycle()


def vectors(seed,iterations,timeout,retries,boundary=False):
    p=Plan(timeout,retries);p.cycle(rst=0)
    for i,mode in enumerate(('good','drop','crc','ack-loss','ack-crc','old-ack','good','good')):p.transfer(0x21+i,mode,2 if i==0 else 0)
    p.cycle(valid=1,data=0xa5)
    for _ in range(timeout+2):p.cycle(line_ready=0)
    while not p.done:p.cycle()
    p.cycle();p.cycle()
    # Hold receiver data over several retries; the duplicate still gets ACKed.
    p.cycle(valid=1,data=0x81)
    while not p.done:p.cycle(ready=0,drop_ack=int(p.retried==0))
    for _ in range(3):p.cycle(ready=0)
    p.cycle();p.cycle()
    p.cycle(valid=1,data=0x82)
    while not p.done:p.cycle(ready=0)
    p.cycle(ready=0);p.cycle(valid=1,data=0x83,ready=0);p.cycle(ready=0);p.cycle(ready=0)
    while not p.done:p.cycle()
    p.cycle();p.cycle()
    p.transfer(0x91,'lose-all');p.cycle(valid=1,data=0x92);p.cycle(rst=0)
    p.transfer(0x93,'ack-all');p.cycle(valid=1,data=0x94);p.cycle(rst=0)
    p.cycle(valid=1,data=0xb1);p.cycle(rst=0);p.transfer(0xb2)
    if not boundary:
        rng=random.Random(seed)
        for _ in range(iterations):p.transfer(rng.randrange(256),rng.choice(('good','drop','crc','ack-loss','ack-crc')),rng.randrange(3))
    p.cycle();return p.rows,p.counts


def make_cases(args,parameters):
    timeout,retries=parameters['TIMEOUT'],parameters['RETRIES'];base,counts=vectors(args.seed,0,timeout,retries,True)
    cases=[dict(id='boundaries',vectors=base,counts=counts,mutation=args.demo_bug,expected_failure=None,category='functional')]
    for seed in range(args.seed,args.seed+(3 if args.profile=='nightly' else 1)):
        rows,stats=vectors(seed,args.iterations,timeout,retries)
        cases.append(dict(id=f'random-seed{seed}',vectors=rows,counts=stats,mutation=args.demo_bug,expected_failure=None,category='functional'))
    for m,label in ((1,'LINK_TX'),(2,'LINK_RX'),(3,'LINK_RX'),(4,'LINK_TX')):
        cases.append(dict(id=f'detect-mutation{m}',vectors=base,counts=counts,mutation=m,expected_failure=label,category='mutation'))
    return cases


if __name__=='__main__':
    spec=importlib.util.spec_from_file_location('runner',HERE.parent/'local-common/runner.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);sys.exit(module.main(sys.modules[__name__]))

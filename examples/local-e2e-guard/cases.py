"""Directed protocol boundaries plus a driver that holds stalled requests."""
import importlib.util
from pathlib import Path
import random
spec=importlib.util.spec_from_file_location('e2e_reference',Path(__file__).with_name('model.py'));M=importlib.util.module_from_spec(spec);spec.loader.exec_module(M)
NAMES=('normal-wrap','corruption-identity','sequence','backpressure-reset')
class Campaign:
    def __init__(self,p):self.p=p;self.m=M.Guard(p['DATA_ID']);self.rows=[];self.expected=[];self.last_rst=0;self.counts=dict(rows=0,inputs=0,validated=0,rejected=0,retired=0,cancelled=0,resets=0)
    def tick(self,rst=1,flush=0,valid=0,packet=0,ready=1):
        old=self.m.pending;row=[rst,flush,valid,packet,ready];e=self.m.step(*row)
        n=self.counts;n['rows']+=1;n['inputs']+=valid*e[0];n['validated']+=e[3];n['rejected']+=e[4]
        n['resets']+=int(self.last_rst and not rst);self.last_rst=rst
        n['cancelled']+=int(old is not None and (not rst or flush));n['retired']+=int(old is not None and rst and not flush and ready)
        self.rows.append(row);self.expected.append(e);return e
    def send(self,counter=None,payload=123,data_id=None,damage=0):
        packet=M.frame(self.p['DATA_ID'] if data_id is None else data_id,self.m.expected if counter is None else counter,payload)^damage
        return self.tick(valid=1,packet=packet)
    def finish(self):
        self.tick();self.tick()
        assert self.m.pending is None and self.counts['inputs']==self.counts['validated']+self.counts['rejected']
        assert self.counts['validated']==self.counts['retired']+self.counts['cancelled']
        return self.rows,self.expected,self.counts
def make(name,p,seed=17,iterations=200):
    c=Campaign(p);c.tick(rst=0)
    if name=='normal-wrap':
        for i in range(260):c.send(payload=0 if i==0 else 0xffff if i==1 else i)
    elif name=='corruption-identity':
        c.send(counter=0)
        for bit in range(48):c.send(damage=1<<bit)
        c.send(data_id=p['DATA_ID']^0x8001)
        c.send(data_id=p['DATA_ID']^1,damage=1)
        c.send(counter=(c.m.expected+7)%256,data_id=p['DATA_ID']^0x8001)
        c.send()
    elif name=='sequence':
        c.send(counter=1);c.send(counter=0);c.send(counter=0);c.send(counter=2);c.send(counter=1);c.send(counter=3);c.send(counter=2)
    elif name=='backpressure-reset':
        c.send(payload=0x1234);held=M.frame(p['DATA_ID'],1,0xabcd)
        for _ in range(5):c.tick(valid=1,packet=held,ready=0)
        c.tick(valid=1,packet=held);c.tick(rst=0);c.send(counter=0)
        c.tick(flush=1,valid=1,packet=held);c.send(counter=0);c.tick(flush=1,ready=0);c.send(counter=0)
    elif name=='random':
        rng=random.Random(seed);held=None
        for _ in range(iterations):
            rst=int(rng.randrange(100)!=0);flush=int(rng.randrange(80)==0);ready=int(rng.randrange(4)!=0)
            if held is None and rng.randrange(3):
                counter=c.m.expected;data_id=p['DATA_ID'];damage=0;kind=rng.randrange(8)
                if kind==0:damage=1<<rng.randrange(48)
                elif kind==1:data_id^=1
                elif kind==2:counter=(counter+rng.choice([-1,2,128]))%256
                held=M.frame(data_id,counter,rng.randrange(65536))^damage
            e=c.tick(rst,flush,int(held is not None),held or 0,ready)
            if not rst or flush or e[0]:held=None
        if held is not None:
            while not c.tick(valid=1,packet=held)[0]:pass
    else:raise ValueError('unknown E2E case')
    return c.finish()

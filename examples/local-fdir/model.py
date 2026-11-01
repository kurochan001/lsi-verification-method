"""Behavioural FDIR oracle and minimum-distance SECDED decoder.

The decoder searches the codebook; it does not duplicate RTL syndrome correction.
Events are evaluated from pre-edge state; injected bits flip the functional next state.
"""
from functools import lru_cache
import importlib.util
from pathlib import Path
spec=importlib.util.spec_from_file_location('fdir_tmr_model',Path(__file__).resolve().parent.parent/'local-tmr/model.py');T=importlib.util.module_from_spec(spec);spec.loader.exec_module(T)
DATA_BITS=(2,4,5,6,8,9,10,11);PARITY_BITS=(0,1,3,7,12)

def valid(code):return code.bit_count()%2==0 and all(sum((code>>(i-1))&1 for i in range(1,13) if i&(1<<p))%2==0 for p in range(4))

def encode(data):
    if type(data) is not int or not 0<=data<=255:raise ValueError('8-bit data required')
    base=sum(((data>>i)&1)<<b for i,b in enumerate(DATA_BITS))
    return next(code for p in range(32) if valid(code:=base|sum(((p>>i)&1)<<b for i,b in enumerate(PARITY_BITS))))
CODES=tuple(encode(v) for v in range(256))
@lru_cache(maxsize=8192)
def decode(code):
    if type(code) is not int or not 0<=code<8192:raise ValueError('13-bit code required')
    for data,word in enumerate(CODES):
        distance=(code^word).bit_count()
        if distance<=1:return data,int(distance==1),0,word
    # Data on an uncorrectable read is explicitly unusable; expose raw payload for exact RTL observation.
    return sum(((code>>b)&1)<<i for i,b in enumerate(DATA_BITS)),0,1,code

FIELDS='rst start kick ack recover scrub cfg_write cfg_data f0 f1 f2 inject inject_addr inject_mask maint maint_addr maint_data valid op addr data seq'.split()

class Node:
    def __init__(self,depth=4,wd_limit=5,trip=3):
        self.depth=depth;self.limit=wd_limit;self.trip=trip;self.reset()
    def reset(self):
        self.state=0;self.cause=0;self.irq=0;self.seq=0;self.pending=None;self.act=0;self.result=0;self.streak=0;self.scan=0
        self.cfg=T.Register(8);self.mem=[0]*self.depth;self.scrub_at=0;self.scrub_c=0;self.scrub_u=0;self.wd=0
        self.commit=self.cancel=self.recovered=self.failed=0
    def before(self,row):
        if len(row)!=len(FIELDS) or any(type(v) is not int or v<0 for v in row):raise ValueError('complete unsigned input row required')
        a=dict(zip(FIELDS,row))
        for field in FIELDS:
            bound=self.depth if field in ('addr','inject_addr','maint_addr') else 8192 if field=='inject_mask' else 4 if field=='op' else 256 if field in ('cfg_data','f0','f1','f2','maint_data','data','seq') else 2
            if a[field]>=bound:raise ValueError('input exceeds port width: '+field)
        p=self.pending;value,c,u,fixed=decode(self.mem[self.scan if self.state==3 else a['maint_addr'] if self.state==2 else p[1] if p else 0])
        pre=(int(self.cfg.mismatch() and self.streak>=self.trip-1)|2*int(self.scrub_u or (p is not None and p[0]==1 and u))|4*int(self.wd==1 and not a['kick']))
        ready=int(bool(a['rst'] and self.state==1 and p is None and pre==0));accepted=bool(a['valid'] and ready)
        event=(pre|8*int(accepted and (a['op']>1 or a['seq']!=self.seq))) if self.state==1 else 0
        return a,value,c,u,fixed,ready,accepted,event
    def step(self,row):
        a,value,c,u,fixed,ready,accepted,event=self.before(row)
        if not a['rst']:self.reset();return self.observe()
        old_state=self.state;p=self.pending;cfg_vote=self.cfg.vote();cfg_bad=self.cfg.mismatch()
        finishing=old_state==3 and not cfg_bad and not u and self.scan==self.depth-1
        load=bool(old_state==0 and a['start']) or finishing
        if load:self.wd=self.limit
        elif old_state==1:self.wd=self.limit if a['kick'] else max(0,self.wd-1)
        self.commit=self.cancel=self.recovered=self.failed=0
        if a['ack']:self.irq=0
        self.streak=min(self.trip,self.streak+1) if cfg_bad and old_state==1 else 0
        # Apply independent read/scrub/write arbitration to a next-state memory image.
        updated=list(self.mem);sv,sc,su,sfixed=decode(self.mem[self.scrub_at])
        bg=bool(a['scrub'] and old_state!=3);reading=old_state==3 or (old_state==1 and p is not None and p[0]==1)
        address=self.scan if old_state==3 else a['maint_addr'] if old_state==2 else p[1] if p else 0
        if bg and sc:updated[self.scrub_at]=sfixed
        if reading and c:updated[address]=fixed
        if old_state==2 and a['maint']:updated[address]=encode(a['maint_data'])
        elif old_state==1 and p is not None and p[0]==0 and not event:updated[address]=encode(p[2])
        if a['inject']:updated[a['inject_addr']]^=a['inject_mask']
        self.mem=updated;self.scrub_c=int(bg and sc);self.scrub_u=int(bg and su)
        if bg:self.scrub_at=(self.scrub_at+1)%self.depth
        if old_state==0 and a['start']:self.state=1
        elif old_state==1:
            if event:self.state=2;self.cause|=event;self.irq=1;self.act=0;self.cancel=int(p is not None);self.pending=None
            elif p is not None:
                self.commit=1;self.result=p[2] if p[0]==0 else min(value,cfg_vote)
                if p[0]==1:self.act=self.result
                self.seq=(self.seq+1)&255;self.pending=None
            elif accepted:self.pending=(a['op'],a['addr'],a['data'])
        elif old_state==2 and a['recover'] and not cfg_bad:self.state=3;self.scan=0
        elif old_state==3:
            if cfg_bad or u:self.state=2;self.cause|=int(cfg_bad)|2*u;self.irq=1;self.failed=1
            elif self.scan==self.depth-1:self.state=1;self.cause=0;self.irq=0;self.recovered=1;self.act=0
            else:self.scan+=1
        self.cfg.step([1,int(a['cfg_write'] and old_state in (0,2)),a['cfg_data'],a['scrub'],a['f0'],a['f1'],a['f2']])
        return self.observe()
    def observe(self):
        return [self.state,self.cause,self.irq,self.seq,self.commit,self.cancel,self.recovered,self.failed,self.result,self.act if self.state==1 else 0,
            self.wd,self.cfg.vote(),self.cfg.mismatch(),self.scrub_at,self.scrub_c,self.scrub_u,int(self.pending is not None),self.streak,*self.cfg.q,*self.mem]

"""Deterministic fault campaigns; command sources advance independently of DUT outputs."""
import random
from pathlib import Path
import importlib.util
spec=importlib.util.spec_from_file_location('fdir_cases_model',Path(__file__).with_name('model.py'));M=importlib.util.module_from_spec(spec);spec.loader.exec_module(M)

class Campaign:
    def __init__(self,depth,wd_limit,trip):
        self.m=M.Node(depth,wd_limit,trip);self.rows=[];self.expected=[];self.old_rst=0
        self.counts=dict(rows=0,injections=0,resets=0,accepted=0,commits=0,cancels=0,recoveries=0,failures=0,rejected=0,reset_cancels=0)
        self.boot()
    def tick(self,**kw):
        a=dict.fromkeys(M.FIELDS,0);a.update(rst=1,kick=1,scrub=1);a.update(kw);row=[a[k] for k in M.FIELDS]
        pre=self.m.before(row);self.counts['accepted']+=int(bool(a['rst'] and pre[6]))
        self.counts['rejected']+=int(bool(a['rst'] and pre[6] and (a['op']>1 or a['seq']!=self.m.seq)))
        self.counts['reset_cancels']+=int(bool(self.old_rst and not a['rst'] and self.m.pending is not None))
        self.counts['injections']+=int(bool(a['rst'] and (a['inject'] or a['f0'] or a['f1'] or a['f2'])))
        self.counts['resets']+=int(bool(self.old_rst and not a['rst']));self.old_rst=a['rst']
        result=self.m.step(row)
        for key,index in (('commits',4),('cancels',5),('recoveries',6),('failures',7)):self.counts[key]+=int(bool(a['rst'] and result[index]))
        self.rows.append(row);self.expected.append(result);self.counts['rows']+=1
    def boot(self):
        self.tick(rst=0,kick=0);self.tick(rst=0,kick=0);self.tick(cfg_write=1,cfg_data=180);self.tick(start=1)
    def command(self,op,addr=0,data=0,seq=None,**kw):
        self.tick(valid=1,op=op,addr=addr,data=data,seq=self.m.seq if seq is None else seq,**kw);self.tick(**kw)
    def recovery(self):
        self.tick(ack=1);self.tick(recover=1)
        self.tick(cfg_write=1,cfg_data=0)  # CHECK must ignore configuration writes.
        for _ in range(self.m.depth):self.tick()
    def finish(self):
        self.tick();self.tick()
        if self.m.pending is not None or self.m.state==3:raise ValueError('campaign did not drain')
        return self.rows,self.expected,self.counts

NAMES=('normal','single-bit','scrub','tmr-persistent','watchdog','kick-boundary','bad-command','recovery-ecc','recovery-cfg','reset-pending','reset-check','write-upset','scrub-write-collision','simultaneous','sequence-wrap')
def make(name,pars,seed=17,random_count=16):
    c=Campaign(pars['DEPTH'],pars['WD_LIMIT'],pars['TRIP']);d=c.m.depth
    if name=='normal':
        c.tick(cfg_write=1,cfg_data=17)  # RUN must also ignore configuration writes.
        for a in range(d):c.command(0,a,50+a*30);c.command(1,a)
    elif name=='single-bit':
        c.command(0,0,201)
        for bit in range(13):c.tick(inject=1,inject_mask=1<<bit,scrub=0);c.command(1,scrub=0)
        for lane in range(3):c.tick(**{'f'+str(lane):0x40});c.command(1)
    elif name=='scrub':
        c.command(0,d-1,75);c.tick(inject=1,inject_addr=d-1,inject_mask=1)
        for _ in range(d+2):c.tick()
        c.command(1,d-1)
    elif name in ('tmr-persistent','recovery-cfg'):
        c.command(0,0,80);c.command(1)
        if name=='recovery-cfg':
            c.tick(f1=1,scrub=0)
            for _ in range(c.m.trip+1):c.tick(scrub=0)
        else:
            for _ in range(c.m.trip+2):c.tick(f1=1)
        c.tick(ack=1,scrub=int(name!='recovery-cfg'))
        if name=='recovery-cfg':c.tick(recover=1,scrub=0);c.tick(cfg_write=1,cfg_data=60,scrub=0)
        c.recovery();c.command(1)
    elif name in ('watchdog','kick-boundary'):
        c.command(0,0,90);c.command(1)
        for _ in range(c.m.limit-2):c.tick(kick=0)
        c.tick(valid=1,op=1,seq=c.m.seq,kick=0)
        c.tick(kick=int(name=='kick-boundary'),ack=1)
        if name=='watchdog':c.tick(ack=1);c.recovery();c.command(1)
    elif name=='bad-command':
        c.command(0,0,99);c.command(1,seq=(c.m.seq-1)&255);c.recovery();c.command(0,0,81);c.command(3);c.recovery();c.command(1)
    elif name in ('recovery-ecc','reset-check'):
        c.command(0,d-1,95);c.tick(inject=1,inject_addr=d-1,inject_mask=3,scrub=0);c.command(1,d-1,scrub=0)
        c.tick(ack=1,scrub=0);c.tick(recover=1,scrub=0)
        if name=='reset-check':c.boot();c.command(0,0,33);c.command(1)
        else:
            for _ in range(d+1):c.tick(scrub=0)
            c.tick(maint=1,maint_addr=d-1,maint_data=95);c.recovery();c.command(1,d-1)
    elif name=='reset-pending':
        c.tick(valid=1,op=0,data=55,seq=c.m.seq);c.boot();c.command(1)
    elif name=='write-upset':
        c.tick(valid=1,op=0,data=123,seq=c.m.seq,scrub=0);c.tick(inject=1,inject_mask=1,scrub=0);c.command(1,scrub=0)
    elif name=='scrub-write-collision':
        c.command(0,0,44);c.tick(inject=1,inject_mask=1,scrub=0)
        while c.m.scrub_at!=0:c.tick()
        c.tick(valid=1,op=0,data=99,seq=c.m.seq,scrub=0);c.tick();c.command(1)
    elif name=='simultaneous':
        for _ in range(c.m.limit-c.m.trip-1):c.tick(kick=0,scrub=0)
        c.tick(f0=1,kick=0,scrub=0)
        for i in range(c.m.trip-1):c.tick(kick=0,scrub=0,valid=int(i==c.m.trip-2),op=1,seq=c.m.seq)
        c.tick(kick=0,scrub=0,ack=1);c.tick();c.recovery();c.command(1)
    elif name=='sequence-wrap':
        for i in range(260):c.command(0,i%d,i&255)
        c.command(1)
    elif name=='random':
        rng=random.Random(seed)
        for _ in range(random_count):
            a=rng.randrange(d);c.command(0,a,rng.randrange(256))
            if rng.randrange(2):c.tick(inject=1,inject_addr=a,inject_mask=1<<rng.randrange(13),scrub=0)
            if rng.randrange(2):c.tick(**{'f'+str(rng.randrange(3)):1<<rng.randrange(8)})
            c.command(1,a)
    else:raise ValueError('unknown campaign')
    return c.finish()

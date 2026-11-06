"""Complete ECU episodes, with independent deadlines and explicit fault collisions."""
import importlib.util
from pathlib import Path
import random
spec=importlib.util.spec_from_file_location('ecu_reference',Path(__file__).with_name('model.py'));M=importlib.util.module_from_spec(spec);spec.loader.exec_module(M)
NAMES=('window-boundaries','early-late','freshness-errors','shutdown-pending','recovery-reset','range-priority','off-external')
class Campaign:
    def __init__(self,p):
        self.p=p;self.m=M.ECU(p);self.rows=[];self.expected=[];self.last_rst=0
        self.counts=dict(rows=0,inputs=0,validated=0,rejected=0,applied=0,cancelled=0,reset_cancels=0,resets=0,faults=0,recoveries=0,starts=0,disarms=0)
    def tick(self,**kw):
        a=dict.fromkeys(M.FIELDS,0);a['rst']=1;a.update(kw)
        if set(a)!=set(M.FIELDS):raise ValueError('unknown input')
        row=[a[k] for k in M.FIELDS];old=self.m.state;pending=self.m.guard.pending;e=self.m.step(row);n=self.counts
        n['rows']+=1;n['inputs']+=a['valid']*e[0];n['validated']+=e[8];n['rejected']+=e[9];n['applied']+=e[6];n['cancelled']+=e[7]
        n['reset_cancels']+=int(not a['rst'] and pending is not None);n['resets']+=int(self.last_rst and not a['rst']);self.last_rst=a['rst']
        n['faults']+=int(a['rst'] and old!=2 and self.m.state==2);n['recoveries']+=int(a['rst'] and old==2 and self.m.state==0)
        n['starts']+=int(a['rst'] and old==0 and self.m.state==1);n['disarms']+=int(a['rst'] and old==1 and self.m.state==0)
        self.rows.append(row);self.expected.append(e);return e
    def start(self):self.tick(rst=0);self.tick(arm=1)
    def send(self,payload=200,damage=0,**kw):
        packet=M.G.frame(self.p['DATA_ID'],self.m.guard.expected,payload)^damage
        return self.tick(valid=1,frame=packet,**kw)
    def advance(self,n,refresh=True,service_at=None,bad=False):
        at=self.p['WINDOW_MIN'] if service_at is None else service_at
        for index in range(n):
            m=self.m;delta=m.time+1-m.last_service
            kw=dict(service=int(m.state==1 and delta==at))
            if m.state==1 and (bad or (refresh and m.guard.pending is None and m.time+1-m.last_apply>=self.p['FRESH_MAX']-3)):
                if bad:
                    mode=index%3;counter=(m.guard.expected+(2 if mode==2 else 0))%256
                    packet=M.G.frame(self.p['DATA_ID']^(1 if mode==1 else 0),counter,200)^(1 if mode==0 else 0)
                    self.tick(valid=1,frame=packet,**kw)
                else:self.send(**kw)
            else:self.tick(**kw)
    def finish(self):
        self.tick(rst=0);self.tick();self.tick()
        n=self.counts;assert n['inputs']==n['validated']+n['rejected']
        assert n['validated']==n['applied']+n['cancelled']+n['reset_cancels'] and self.m.guard.pending is None
        return self.rows,self.expected,n
def make(name,p,seed=17,iterations=12):
    c=Campaign(p);lo=p['WINDOW_MIN'];hi=p['WINDOW_MAX'];fresh=p['FRESH_MAX']
    if name=='window-boundaries':
        for interval in (lo,hi):c.start();c.advance(3*fresh,service_at=interval);c.tick(disarm=1)
        # Place a decoded command exactly on the freshness deadline.
        c.start();c.advance(fresh-2,refresh=False);c.send(payload=1000,service=int(c.m.time+1-c.m.last_service==lo));c.tick(service=int(c.m.time+1-c.m.last_service==lo));c.send(payload=0,service=int(c.m.time+1-c.m.last_service==lo));c.tick(service=int(c.m.time+1-c.m.last_service==lo));c.tick(disarm=1)
    elif name=='early-late':
        c.start();c.tick(service=1);c.tick(ack=1);c.tick(external=1);c.tick(ack=1)
        c.start();c.advance(hi,refresh=True,service_at=hi+1)
        c.start();c.advance(lo-1);c.tick(service=1);c.tick(service=1)
    elif name=='freshness-errors':
        c.start();c.send(payload=350);c.tick();c.advance(2*fresh,refresh=False,bad=True)
        c.tick(ack=1);c.tick(recover=1,permit=0);c.tick(recover=1,permit=1,arm=1);c.tick(arm=1);c.send(payload=0);c.tick()
    elif name=='shutdown-pending':
        c.start();c.send(payload=700);c.tick(external=1,ack=1);c.tick(ack=1)
        c.tick(recover=1,permit=1,arm=1);c.tick(arm=1);c.send(payload=800);c.tick(disarm=1)
    elif name=='recovery-reset':
        c.start();c.send(payload=600);c.tick(rst=0);c.tick(arm=1);c.send(payload=10);c.tick();c.tick(external=1)
        c.tick(recover=1,permit=1,external=1);c.tick(ack=1);c.tick(arm=1,recover=1,permit=0);c.tick(arm=1,recover=1,permit=1);c.tick(arm=1);c.send(payload=0);c.tick()
    elif name=='range-priority':
        c.start();c.send(payload=1001);c.tick()
        c.start();c.advance(hi-2,service_at=hi+1);c.send(payload=1001);c.tick(disarm=1,ack=1)
    elif name=='off-external':
        # OFF also latches the external input, and the fault beats a simultaneous ARM.
        c.tick(rst=0);c.tick(external=1);c.tick();c.tick(recover=1,permit=1)
        c.tick(arm=1,external=1);c.tick(recover=1,permit=1);c.tick(arm=1);c.send(payload=5);c.tick()
    elif name=='random':
        rng=random.Random(seed)
        for _ in range(iterations):
            c.start();c.advance(rng.randrange(fresh,3*fresh),service_at=rng.choice([lo,hi]))
            variant=rng.randrange(5)
            if variant==0:c.tick(service=1);c.tick(service=1)
            elif variant==1:c.advance(2*fresh,refresh=False,bad=True)
            elif variant==2:c.send(payload=rng.randrange(1,1001));c.tick(external=1)
            elif variant==3:c.send(payload=65535);c.tick(service=int(c.m.time+1-c.m.last_service==lo))
            else:c.tick(disarm=1)
            if c.m.state==2:
                c.tick(ack=1);c.tick(recover=1,permit=0);c.tick(recover=1,permit=1,arm=1)
            c.tick(rst=0)
    else:raise ValueError('unknown ECU case')
    return c.finish()

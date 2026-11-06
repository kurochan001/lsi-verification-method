import importlib.util
from pathlib import Path
import random
spec=importlib.util.spec_from_file_location('motion_axis_cases_model',Path(__file__).with_name('model.py'));M=importlib.util.module_from_spec(spec);spec.loader.exec_module(M)
NAMES=('tracking','reversal','load-step','saturation','estop-rearm','encoder-invalid','encoder-stuck','mechanical-stall','deadline','deadline-boundary','overspeed','position-wrap','reset-pending','origin-arm','overspeed-reverse','arm-on-notice','saturation-boundary')
class Campaign:
    def __init__(self,p):
        self.p=p;self.m=M.Axis(p['PERIOD'],p['DEAD'],p['FILTER'],p['SAMPLE'],p['LATENCY'],p['SPEED_LIMIT']);self.rows=[];self.expected=[];self.old_rst=0
        self.counts=dict(rows=0,resets=0,samples=0,updates=0,cancels=0,reset_cancels=0)
        self.tick(rst=0);self.tick(rst=0)
    def tick(self,**kw):
        a=dict.fromkeys(M.FIELDS,0);a.update(rst=1);a.update(kw)
        if any(type(v) is not int or not -2**31<=v<2**31 for v in a.values()):raise ValueError('host stimulus exceeds signed 32-bit range')
        row=[M.U(a[k]) for k in M.FIELDS];self.m.inputs(row)
        if self.old_rst and not a['rst']:
            self.counts['resets']+=1;self.counts['reset_cancels']+=int(bool(self.m.pi.busy or self.m.pi.done))
        self.old_rst=a['rst'];expected=self.m.step(row);self.rows.append(row);self.expected.append(expected);self.counts['rows']+=1
        if a['settled'] and (not self.m.armed or self.m.cause or abs(self.m.encoder.position-a['target'])>2 or abs(self.m.plant_pos//4096-a['target'])>3):raise ValueError('reference loop did not settle')
        if a['rst']:
            self.counts['samples']+=self.m.sampled;self.counts['updates']+=self.m.updated;self.counts['cancels']+=self.m.cancel
    def hold(self,n,**kw):
        for _ in range(n):self.tick(**kw)
    def track(self,n,**kw):
        for i in range(n):self.tick(settled=int(i>=n-4*self.p['SAMPLE']),**kw)
    def arm(self,**kw):self.tick(arm=1,**kw)
    def finish(self):
        self.tick(disarm=1);self.hold(3)
        if self.counts['samples']!=self.counts['updates']+self.counts['cancels']+self.counts['reset_cancels']:raise ValueError('control jobs did not drain')
        return self.rows,self.expected,self.counts

def make(name,p,seed=17,random_count=4):
    c=Campaign(p);s=p['SAMPLE'];target=12
    if name=='origin-arm':
        c.tick(origin_en=1,origin=1000,arm=1,target=1000);c.tick(origin_en=1,origin=-1000,target=1000);c.hold(5*s,target=1000);return c.finish()
    if name=='position-wrap':
        c.tick(origin_en=1,origin=32767);c.arm(target=32767,load=-768);c.hold(3*s,target=32767,load=-768);return c.finish()
    if name=='arm-on-notice':
        # ARM is refused on the cycle an encoder notice is visible and accepted on a later edge.
        c.hold(p['FILTER']+6,mode=2,override=3)
        while not c.m.encoder.invalid:c.tick(mode=2,override=0)
        c.tick(arm=1,mode=2,override=0);c.tick(mode=2,override=0);c.tick(origin_en=1,origin=32767,mode=2,override=0)
        while not c.m.encoder.wrapped:c.tick(mode=2,override=1)
        c.tick(arm=1,mode=2,override=1);c.tick(mode=2,override=1);c.tick(arm=1,mode=2,override=1);c.hold(3,mode=2,override=1)
        return c.finish()
    if name=='saturation-boundary':
        # With no integral yet, an error of 2U+1 rounds to exactly U+1 once the update is frozen.
        for sign in (1,-1):
            c.tick(rst=0);c.tick();c.arm();c.hold(s-1)
            c.tick(target=c.m.encoder.position+sign*(p['PERIOD']+1));c.hold(p['LATENCY']+2)
        return c.finish()
    c.arm(target=target)
    if name=='tracking':c.track(40*s,target=target)
    elif name=='reversal':c.track(32*s,target=target);c.track(40*s,target=-target)
    elif name=='load-step':c.track(32*s,target=target);c.track(40*s,target=target,load=16)
    elif name=='saturation':c.hold(12*s,target=100);c.track(40*s,target=target)
    elif name=='estop-rearm':
        c.hold(5*s,target=target);c.tick(arm=1,estop=1,ack=1,target=-target);c.hold(2*s,target=-target);c.tick(ack=1);c.hold(s,target=-target)
        c.arm(target=-target);c.track(40*s,target=-target)
    elif name=='encoder-invalid':
        c.hold(p['FILTER']+6,mode=2,override=3,target=target);c.hold(s,target=target);c.tick(ack=1)
    elif name=='encoder-stuck':c.hold(8*s,target=100,mode=1)
    elif name=='mechanical-stall':c.hold(8*s,target=100,freeze=1)
    elif name=='deadline':c.hold(3*s,target=target,hold=1)
    elif name=='deadline-boundary':
        c.hold(s,target=target)
        c.hold(s-p['LATENCY']-1,target=target,hold=1);c.hold(p['LATENCY']+3,target=target);c.hold(2*s,target=target)
    elif name=='overspeed':c.hold(4*s,target=target,load=-768)
    elif name=='overspeed-reverse':c.hold(4*s,target=-target,load=768)
    elif name=='reset-pending':
        c.hold(s+1,target=target,hold=1);c.tick(rst=0,arm=1,target=target);c.tick();c.arm(target=-target);c.track(40*s,target=-target)
    elif name=='random':
        rng=random.Random(seed)
        for _ in range(random_count):c.track(40*s,target=rng.randrange(-16,17),load=rng.choice((-16,0,16)))
    else:raise ValueError('unknown scenario')
    return c.finish()

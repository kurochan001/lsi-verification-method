import importlib.util
from pathlib import Path
import random
spec=importlib.util.spec_from_file_location('motion_io_cases_model',Path(__file__).with_name('model.py'));M=importlib.util.module_from_spec(spec);spec.loader.exec_module(M)
FIELDS='rst enable stop load duty raw origin_en origin'.split()
NAMES=('pwm-boundaries','encoder','noise-invalid','wrap','reset-active','origin-collision')
class Campaign:
    def __init__(self,p):
        self.p=p;self.pwm=M.PWM(p['PERIOD'],p['DEAD']);self.q=M.Encoder(p['FILTER']);self.rows=[];self.expected=[];self.old_rst=0
        self.counts=dict(rows=0,resets=0,steps=0,invalid=0,wraps=0,rejected=0,boundaries=0)
        self.tick(rst=0);self.tick(rst=0)
    def tick(self,**kw):
        a=dict.fromkeys(FIELDS,0);a.update(rst=1);a.update(kw)
        if any(type(v) is not int for v in a.values()) or any(a[k] not in (0,1) for k in ('rst','enable','stop','load','origin_en')) or not 0<=a['duty']<2**32 or not 0<=a['raw']<4 or not -32768<=a['origin']<=32767:raise ValueError('I/O stimulus outside port widths')
        self.counts['resets']+=int(bool(self.old_rst and not a['rst']));self.old_rst=a['rst']
        self.pwm.step(a['rst'],a['enable'],a['stop'],a['load'],a['duty']);self.q.step(a['rst'],a['raw'],a['origin_en'],a['origin'])
        self.rows.append([M.u32(a[k]) for k in FIELDS]);self.expected.append(self.pwm.observe(a['rst'],a['enable'],a['stop'])+self.q.observe());self.counts['rows']+=1
        if a['rst']:
            for key,value in (('steps',self.q.step_flag),('invalid',self.q.invalid),('wraps',self.q.wrapped),('rejected',self.pwm.error),('boundaries',self.pwm.boundary)):self.counts[key]+=value
    def hold(self,n,**kw):
        for _ in range(n):self.tick(**kw)
    def finish(self,raw=0):
        self.hold(self.p['FILTER']+4,raw=raw);return self.rows,self.expected,self.counts

def make(name,p,seed=17,random_count=32):
    c=Campaign(p);period=p['PERIOD'];wait=p['FILTER']+3
    if name=='pwm-boundaries':
        for duty in (0,period,period//2,1,period-1):
            c.tick(load=1,duty=duty);c.hold(3*period+3,enable=1);c.tick(enable=1,load=1,duty=period//3);c.hold(2*period,enable=1)
            c.tick(enable=1,stop=1);c.hold(2,enable=1,stop=1)
        c.tick(enable=1,load=1,duty=period+1);c.tick(enable=1,load=1,duty=0xffffffff);c.hold(2*period,enable=1)
        while c.pwm.phase!=period-1:c.tick(enable=1)
        c.tick(enable=1,load=1,duty=period//2);c.hold(2*period,enable=1)
    elif name=='encoder':
        for raw in (*M.GRAY[1:],0,*reversed(M.GRAY[1:]),0):c.hold(wait,raw=raw,enable=1)
    elif name=='noise-invalid':
        c.hold(5);c.hold(p['FILTER']-1,raw=1);c.hold(wait);c.hold(wait,raw=3);c.hold(wait,raw=2);c.hold(wait,raw=0)
    elif name=='wrap':
        c.tick(origin_en=1,origin=32767);c.hold(wait,raw=1);c.tick(origin_en=1,origin=-32768,raw=1);c.hold(wait,raw=0)
    elif name=='reset-active':
        c.hold(2*period,enable=1,raw=1);c.tick(rst=0,enable=1,load=1,duty=period,raw=3,origin_en=1,origin=123);c.hold(2*period,enable=1)
    elif name=='origin-collision':
        # Sweep the origin write across the edge where the filter adopts the next Gray state.
        c.hold(wait)
        for delay in range(wait):
            raw=M.GRAY[(M.GRAY.index(c.q.filtered)+1)%4]
            c.hold(delay,raw=raw);c.tick(raw=raw,origin_en=1,origin=1000+delay);c.hold(wait,raw=raw)
    elif name=='random':
        rng=random.Random(seed);raw=0
        for _ in range(random_count):
            raw=M.GRAY[(M.GRAY.index(raw)+rng.choice((-1,1,2)))%4]
            c.hold(wait+2,raw=raw,enable=int(rng.randrange(5)!=0),load=1,duty=rng.randrange(period+2),stop=int(rng.randrange(8)==0))
        return c.finish(raw)
    else:raise ValueError('unknown scenario')
    return c.finish()

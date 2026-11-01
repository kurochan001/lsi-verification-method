"""Reference control arithmetic uses exact rationals; plant reacts to actual PWM in the RTL TB.

Plant velocity/position are normalized Q12 encoder units, not a characterized motor.
"""
from fractions import Fraction
import importlib.util
from pathlib import Path
spec=importlib.util.spec_from_file_location('motion_io_reference',Path(__file__).resolve().parent.parent/'local-motion-io/model.py');IO=importlib.util.module_from_spec(spec);spec.loader.exec_module(IO)
U=IO.u32;S=IO.signed
FIELDS='rst arm disarm ack estop target origin_en origin hold load freeze mode override settled'.split()

class PI:
    def __init__(self,limit,latency):self.limit=limit;self.latency=latency;self.reset()
    def reset(self):self.busy=self.done=self.clip=self.anti=0;self.effort=self.integral=self.error=self.remaining=0
    def step(self,rst,clear,start,hold,error):
        if not rst or clear:self.reset();return
        self.done=0
        if start and not self.busy:self.busy=1;self.error=error;self.remaining=self.latency
        elif self.busy and not hold:
            self.remaining-=1
            if self.remaining==0:
                candidate=max(-self.limit*16,min(self.limit*16,self.integral+self.error))
                raw=Fraction(8*self.error+candidate,16)
                self.anti=int((raw>self.limit and self.error>0) or (raw< -self.limit and self.error<0))
                if self.anti:candidate=self.integral
                raw=Fraction(8*self.error+candidate,16);rounded=int(abs(raw)+Fraction(1,2))*(1 if raw>=0 else -1)
                self.integral=candidate;self.clip=int(abs(rounded)>self.limit);self.effort=max(-self.limit,min(self.limit,rounded));self.busy=0;self.done=1
    def observe(self):return [U(self.effort),U(self.integral),self.busy,self.done,self.clip,self.anti,max(0,self.remaining-1),U(self.error)]

class Axis:
    def __init__(self,period=16,dead=2,filter=2,sample=64,latency=3,speed_limit=6):
        self.period=period;self.dead=dead;self.filter=filter;self.sample=sample;self.latency=latency;self.speed_limit=speed_limit;self.reset()
    def reset(self):
        self.pwm=IO.PWM(self.period,self.dead);self.encoder=IO.Encoder(self.filter);self.pi=PI(self.period//2,self.latency)
        self.armed=self.irq=self.cause=self.updated=self.cancel=self.sampled=self.phase=self.stalled=self.last_position=0
        self.plant_pos=self.plant_velocity=self.frozen_phase=self.old_mode=self.raw=0
    def inputs(self,row):
        if len(row)!=len(FIELDS) or any(type(v) is not int or not 0<=v<=0xffffffff for v in row):raise ValueError('unsigned 32-bit row required')
        a=dict(zip(FIELDS,row))
        for f in ('rst','arm','disarm','ack','estop','origin_en','hold','freeze','settled'):
            if a[f]>1:raise ValueError('logic input exceeds one bit')
        for f in ('target','origin'):
            a[f]=S(a[f])
            if not -32768<=a[f]<=32767:raise ValueError('signed 16-bit input required')
        a['load']=S(a['load'])
        if abs(a['load'])>1024 or a['mode']>2 or a['override']>3:raise ValueError('plant/sensor input exceeds model bounds')
        return a
    def events(self,a):
        tick=self.armed and self.phase==self.sample-1;velocity=S(self.encoder.position-self.last_position,16)
        moving=abs(self.pi.effort)>=3
        event=int(bool(a['estop']))
        if self.armed:
            event|=2*self.encoder.invalid|4*int(tick and self.pi.busy)|8*int(moving and not self.encoder.step_flag and self.stalled>=3*self.sample-1)
            event|=16*int(tick and abs(velocity)>self.speed_limit)|32*self.encoder.wrapped
        return event,int(bool(tick))
    def pins(self,a):
        event,_=self.events(a);return self.pwm.pins(a['rst'],self.armed and not event and not a['disarm'],a['estop'])
    def step(self,row):
        a=self.inputs(row)
        if not a['rst']:self.reset();return self.observe(a)
        event,tick=self.events(a);old_armed=self.armed;busy,done=self.pi.busy,self.pi.done;pos=self.encoder.position;effort=self.pi.effort
        enabled=bool(old_armed and not event and not a['disarm']);hi,lo=self.pins(a)
        physical=IO.GRAY[(self.plant_pos//4096)%4]
        if a['mode']==1:
            if self.old_mode!=1:self.frozen_phase=physical
            raw=self.frozen_phase
        elif a['mode']==2:raw=a['override']
        else:raw=physical
        self.raw=raw;self.old_mode=a['mode']
        if a['freeze']:self.plant_velocity=0
        else:
            self.plant_velocity=int(Fraction(15*self.plant_velocity+256*(hi-lo)-a['load'],16));self.plant_pos+=self.plant_velocity
        if not (-2**31<=self.plant_pos<2**31 and -2**31<=self.plant_velocity<2**31):raise ValueError('plant state exceeds signed 32-bit range')
        self.updated=self.cancel=self.sampled=0
        if a['ack']:self.irq=0
        if old_armed:
            self.phase=0 if tick else self.phase+1
            self.stalled=0 if abs(effort)<3 or self.encoder.step_flag else min(3*self.sample,self.stalled+1)
        else:self.phase=self.stalled=0
        if event:self.armed=0;self.cause|=event;self.irq=1;self.cancel=int(bool(busy or done));self.phase=self.stalled=0
        elif a['disarm']:self.armed=0;self.cancel=int(bool(busy or done));self.phase=self.stalled=0
        elif a['arm'] and not old_armed and not self.encoder.invalid and not self.encoder.wrapped:
            self.armed=1;self.cause=0;self.irq=0;self.phase=self.stalled=0;self.last_position=a['origin'] if a['origin_en'] else pos
        elif old_armed:
            if tick:self.last_position=pos;self.sampled=int(not busy)
            if done:self.updated=1
        self.pwm.step(a['rst'],enabled,a['estop'],int(bool(done and enabled) or not enabled),self.period//2+effort if enabled else self.period//2)
        self.pi.step(a['rst'],not enabled,int(bool(tick and not event and not a['disarm'])),a['hold'],a['target']-pos)
        self.encoder.step(a['rst'],raw,int(bool(a['origin_en'] and not old_armed)),a['origin'])
        return self.observe(a)
    def observe(self,a):
        event,_=self.events(a);en=self.armed and not event and not a['disarm']
        return [self.armed,self.cause,self.irq,self.updated,self.cancel,self.sampled,U(self.encoder.position),*self.pi.observe(),self.phase,self.stalled,U(self.last_position),
            *self.pwm.observe(a['rst'],en,a['estop']),self.encoder.step_flag,self.encoder.invalid,self.encoder.wrapped,self.encoder.errors,
            self.encoder.s1,self.encoder.s2,self.encoder.candidate,self.encoder.filtered,self.encoder.previous,self.encoder.stable,
            U(self.plant_pos),U(self.plant_velocity),self.raw,self.frozen_phase,self.old_mode,event]

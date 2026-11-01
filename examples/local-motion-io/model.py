"""Cycle reference: timestamp-based PWM blanking and Gray-ring encoder decoding."""
def u32(v):return v&0xffffffff
def signed(v,bits=32):return (v&((1<<bits)-1))-(1<<bits) if v&(1<<(bits-1)) else v&((1<<bits)-1)
GRAY=(0,1,3,2)

class PWM:
    def __init__(self,period=16,dead=2):self.period=period;self.dead=dead;self.reset()
    def reset(self):
        self.phase=self.period-1;self.active=self.shadow=self.period//2;self.running=0;self.drive=0;self.target=0;self.boundary=self.error=0;self.time=0;self.allowed=self.dead
    def pins(self,rst,en,stop):return [int(bool(rst and en and not stop and self.drive==1)),int(bool(rst and en and not stop and self.drive==2))]
    def step(self,rst,en,stop,load,duty):
        if not rst:self.reset();return
        self.time+=1;self.boundary=0;self.error=int(bool(load and duty>self.period))
        if load and duty<=self.period:self.shadow=duty
        if not en or stop:self.running=0;self.drive=0;self.phase=self.period-1;self.allowed=self.time+self.dead;return
        first=not self.running;self.phase=0 if first or self.phase==self.period-1 else self.phase+1
        if self.phase==0:self.active=self.shadow;self.boundary=1
        want=int(self.phase<self.active)
        if first or want!=self.target:self.drive=0;self.target=want;self.allowed=self.time+self.dead
        elif self.time>=self.allowed:self.drive=1 if want else 2
        else:self.drive=0
        self.running=1
    def gap(self):return max(0,self.allowed-self.time-1)
    def observe(self,rst,en,stop):return [*self.pins(rst,en,stop),self.boundary,self.error,self.phase,self.active,self.shadow,self.drive,self.gap(),self.target,self.running]

class Encoder:
    def __init__(self,filter=2):self.filter=filter;self.reset()
    def reset(self):
        self.s1=self.s2=self.candidate=self.filtered=self.previous=0;self.stable=0;self.position=0;self.step_flag=self.invalid=self.wrapped=self.errors=0
    def step(self,rst,raw,origin_en=0,origin=0):
        if not rst:self.reset();return
        filt=self.filtered
        if (self.candidate==self.s2 and self.stable>=self.filter-1) or (self.candidate!=self.s2 and self.filter==1):filt=self.s2
        old_candidate=self.candidate
        self.candidate=self.s2;self.stable=min(self.filter,self.stable+1) if old_candidate==self.s2 else 1
        self.s2,self.s1=self.s1,raw;self.step_flag=self.invalid=self.wrapped=0
        if origin_en:self.position=origin
        elif self.previous!=filt:
            jump=(GRAY.index(filt)-GRAY.index(self.previous))%4
            if jump==2:self.invalid=1;self.errors+=1
            else:
                value=self.position+(1 if jump==1 else -1);self.step_flag=1;self.wrapped=int(not -32768<=value<=32767);self.position=signed(value,16)
        self.filtered=self.previous=filt
    def observe(self):return [u32(self.position),self.step_flag,self.invalid,self.wrapped,self.errors,self.s1,self.s2,self.candidate,self.filtered,self.previous,self.stable]

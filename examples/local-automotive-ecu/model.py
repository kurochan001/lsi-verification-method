"""Absolute service/command deadlines, and transaction-level frame protection."""
import importlib.util
from pathlib import Path
spec=importlib.util.spec_from_file_location('automotive_guard_model',Path(__file__).resolve().parent.parent/'local-e2e-guard/model.py')
G=importlib.util.module_from_spec(spec);spec.loader.exec_module(G)
FIELDS='rst arm disarm ack recover permit external service valid frame'.split()

class ECU:
    def __init__(self,pars):
        self.p=pars;self.time=0;self.guard=G.Guard(pars['DATA_ID'])
        if not 1<=pars['WINDOW_MIN']<pars['WINDOW_MAX']<pars['FRESH_MAX']:raise ValueError('ordered timing bounds required')
        self.reset()
    def reset(self):
        self.state=0;self.command=self.cause=self.irq=0;self.last_service=self.last_apply=self.time;self.guard.reset()
    def events(self,a):
        event=a['external']
        if self.state==1:
            delta=self.time-self.last_service
            event|=2*int(bool(a['service'] and delta<self.p['WINDOW_MIN']))
            event|=4*int(bool(not a['service'] and delta>=self.p['WINDOW_MAX']))
            event|=8*int(self.guard.pending is None and self.time-self.last_apply>=self.p['FRESH_MAX'])
            event|=16*int(self.guard.pending is not None and self.guard.pending>1000)
        return event
    def step(self,row):
        if len(row)!=len(FIELDS) or any(type(v)is not int or v<0 for v in row):raise ValueError('ECU row')
        a=dict(zip(FIELDS,row))
        if any(a[n]>1 for n in FIELDS[:-1]) or a['frame']>=2**48:raise ValueError('ECU input range')
        self.time+=1;old_pending=self.guard.pending;event=self.events(a)
        consume=int(self.state==1 and not a['disarm'] and not event)
        flush=int(self.state!=1 or a['disarm'] or bool(event))
        ready=self.guard.ready(a['rst'],flush,consume)&consume
        g=self.guard.step(a['rst'],flush,a['valid']&consume,a['frame'],consume)
        applied=cancelled=0
        if not a['rst']:self.reset()
        else:
            if a['ack']:self.irq=0
            if event:
                self.state=2;self.cause|=event;self.irq=1;self.command=0;cancelled=int(old_pending is not None)
            elif self.state==2:
                if a['recover'] and a['permit']:self.state=0;self.cause=self.irq=0
            elif a['disarm'] and self.state==1:self.state=0;self.command=0;cancelled=int(old_pending is not None)
            elif self.state==0:
                if a['arm']:self.state=1;self.command=0;self.last_service=self.last_apply=self.time
            else:
                if a['service']:self.last_service=self.time
                if old_pending is not None:self.command=old_pending;applied=1;self.last_apply=self.time
        return [ready,int(bool(a['rst'] and self.state==1)),int(self.state==2),self.command,self.cause,self.irq,applied,cancelled,g[3],g[4],g[5],int(self.guard.pending is not None)]

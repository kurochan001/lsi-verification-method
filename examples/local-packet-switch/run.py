#!/usr/bin/env python3
"""Packet-level arbitration, routing and output reservation in a 2x2 switch."""
import importlib.util
from pathlib import Path
import random
import sys
HERE=Path(__file__).resolve().parent
NAME='local-packet-switch'
TOP='packet_switch_tb'
CONFIGS={'width8':{'WIDTH':8},'width16':{'WIDTH':16}}
ITERATIONS={'smoke':40,'nightly':300}
SOURCES=[HERE/'rtl/packet_switch.sv',HERE/'tb/packet_switch_tb.sv']
class Plan:
    def __init__(self,width):self.width=width;self.rows=[];self.reset()
    def reset(self):self.reserved=[None,None];self.prefer=[0,0];self.routes=[None,None]
    def cycle(self,beats=(None,None),ready=3,rst=1):
        dest=[None if b is None else (b[0] if self.routes[s] is None else self.routes[s]) for s,b in enumerate(beats)]
        sr=mv=ml=md=0;chosen=[None,None]
        if rst:
            for o in range(2):
                candidates=[s for s in range(2) if dest[s]==o]
                s=self.reserved[o]
                if s is None and candidates:s=self.prefer[o] if self.prefer[o] in candidates else candidates[0]
                chosen[o]=s
                if s is not None and beats[s] is not None and dest[s]==o:
                    mv|=1<<o;ml|=beats[s][1]<<o;md|=beats[s][2]<<(o*self.width)
                    if ready>>o&1:sr|=1<<s
        sv=sum((b is not None)<<s for s,b in enumerate(beats));sl=sum((0 if b is None else b[1])<<s for s,b in enumerate(beats))
        sd=sum((0 if b is None else b[0])<<s for s,b in enumerate(beats));data=sum((0 if b is None else b[2])<<(s*self.width) for s,b in enumerate(beats))
        self.rows.append([rst,sv,sl,sd,data,ready,sr,mv,ml,md])
        if not rst:self.reset();return sr
        for o,s in enumerate(chosen):
            if mv>>o&1:
                self.reserved[o]=s
                if ready>>o&1 and ml>>o&1:self.reserved[o]=None;self.prefer[o]=1-s
        for s,b in enumerate(beats):
            if sr>>s&1:self.routes[s]=None if b[1] else dest[s]
        return sr
    def streams(self,streams,readies=(),gaps=False):
        queues=[list(s) for s in streams];t=0;offered=[None,None]
        while any(queues) or any(b is not None for b in offered):
            for s in range(2):
                if offered[s] is None and queues[s] and (not gaps or t%4!=s):offered[s]=queues[s].pop(0)
            sr=self.cycle(offered,readies[t] if t<len(readies) else 3)
            for s in range(2):
                if sr>>s&1:offered[s]=None
            t+=1
            if t>100000:raise ValueError('switch failed to drain')
        self.cycle()

def packet(dest,data):return [(dest if i==0 else 1-dest,int(i==len(data)-1),x) for i,x in enumerate(data)]
def vectors(seed,iterations,width):
    p=Plan(width);p.cycle(rst=0)
    p.streams([packet(0,[11,12,13]),packet(1,[21,22])]) # simultaneous outputs
    p.streams([packet(0,[31,32,33])+packet(0,[34]),packet(0,[41,42])+packet(0,[43])],gaps=True)
    # Contender arrives while a header is held: output 0 has preference 1 here, but must retain input 0.
    p.cycle([packet(0,[51,52])[0],None],ready=0)
    p.streams([packet(0,[51,52]),packet(0,[61,62])],[0,0,3,0,3,0,3],gaps=False)
    # Leave an owned output empty between body flits.
    p.cycle([(1,0,71),None]);p.cycle([None,(1,1,81)]);p.cycle([None,(1,1,81)])
    p.streams([[(0,1,72)],[(1,1,81)]],[0,0,3])
    p.cycle([(0,0,91),None]);p.cycle(rst=0);p.streams([packet(1,[92]),packet(0,[93])])
    rng=random.Random(seed)
    for _ in range(iterations):
        streams=[packet(rng.randrange(2),[rng.randrange(1<<width) for _ in range(rng.randrange(1,7))]) for _ in range(2)]
        p.streams(streams,[rng.randrange(4) for _ in range(10)],gaps=True)
    p.cycle();return p.rows

def make_cases(args,parameters):
    width=parameters['WIDTH'];base=vectors(args.seed,0,width)
    def case(name,rows,m,expected=None,category='functional'):
        return dict(id=name,vectors=rows,counts={'steps':len(rows)},mutation=m,expected_failure=expected,category=category)
    cases=[case('boundaries',base,args.demo_bug)]
    for seed in range(args.seed,args.seed+(3 if args.profile=='nightly' else 1)):
        cases.append(case(f'random-seed{seed}',vectors(seed,args.iterations,width),args.demo_bug))
    cases += [case(f'detect-mutation{m}',base,m,'PACKET_DATA' if m==4 else 'PACKET_FLOW','mutation') for m in range(1,5)]
    return cases
if __name__=='__main__':
    spec=importlib.util.spec_from_file_location('runner',HERE.parent/'local-common/runner.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);sys.exit(module.main(sys.modules[__name__]))

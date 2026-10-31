#!/usr/bin/env python3
"""Exhaustive ATPG for 64 assignments and 14 named single stuck-at faults."""
import json

FAULTS=tuple((site,value) for site in range(7) for value in range(2))


def functional(q,x):
    """Independent, collapsed next-state expressions for fault-free operation."""
    a,b,c,d=((q>>i)&1 for i in range(4));u,v=x&1,x>>1
    low=(a*u)^(b|v)
    return low | ((low|(c*(1-d)))<<1) | ((a^c^v)<<2) | ((b*u)<<3)


def faulty(q,x,fault=None):
    """Named logic sites correspond to explicit fault-injection hooks in RTL."""
    def node(site,value):return fault[1] if fault and fault[0]==site else value
    bits=[(q>>i)&1 for i in range(4)];a,b=x&1,x>>1
    n0=node(0,bits[0]&a);n1=node(1,bits[1]|b)
    n2=node(2,n0^n1);n3=node(3,bits[2]&(1-bits[3]))
    n4=node(4,n2|n3);n5=node(5,0);n6=node(6,bits[0]^bits[2]^b)
    return n2|(n4<<1)|(n6<<2)|((n5|(bits[1]&a))<<3)


def report():
    patterns=[(q,x) for q in range(16) for x in range(4)]
    detects={p:{f for f in FAULTS if faulty(*p,f)!=functional(*p)} for p in patterns}
    detectable=set().union(*detects.values());remaining=set(detectable);selected=[]
    while remaining:
        best=max(patterns,key=lambda p:len(detects[p]&remaining))
        selected.append(best);remaining-=detects[best]
    return {'assignments':64,'faults':14,'detectable':len(detectable),
            'redundant':[list(f) for f in FAULTS if f not in detectable],
            'patterns':[list(p) for p in selected]}


if __name__=='__main__':print(json.dumps(report(),indent=2))

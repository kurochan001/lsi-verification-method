#!/usr/bin/env python3
"""Explore every reachable abstract state of the bounded store-buffer litmus."""
from collections import deque
import json


def explore(fenced=False):
    programs=[[(1,0,1),(0,1,0)],[(1,1,1),(0,0,0)]]
    if fenced:
        for program in programs:program.insert(1,(2,0,0))
    # pc0,pc1; each core's pending store; visible x/y; load results.
    initial=(0,0,None,None,0,0,-1,-1)
    queue=deque([(initial,[])]);seen={initial};witnesses={}
    while queue:
        state,path=queue.popleft();pc=list(state[:2]);pending=list(state[2:4]);memory=list(state[4:6]);results=list(state[6:8])
        if all(pc[c]==len(programs[c]) for c in (0,1)) and pending==[None,None]:
            witnesses[tuple(results)]=path;continue
        for c in (0,1):
            next_states=[]
            if pc[c]<len(programs[c]):
                op,address,value=programs[c][pc[c]]
                if (op==1 and pending[c] is None) or op==0 or (op==2 and pending[c] is None):
                    p=pc.copy();s=pending.copy();r=results.copy();p[c]+=1
                    if op==1:s[c]=(address,value)
                    if op==0:r[c]=s[c][1] if s[c] and s[c][0]==address else memory[address]
                    next_states.append(((*p,*s,*memory,*r),('issue',c,op,address,value)))
            if pending[c] is not None:
                s=pending.copy();m=memory.copy();address,value=s[c];s[c]=None;m[address]=value
                next_states.append(((*pc,*s,*m,*results),('drain',c)))
            for successor,event in next_states:
                if successor not in seen:seen.add(successor);queue.append((successor,path+[event]))
    return {'states':len(seen),'witnesses':witnesses}


if __name__=='__main__':
    for fenced in (False,True):
        result=explore(fenced)
        print(json.dumps(dict(fenced=fenced,states=result['states'],outcomes=[list(x) for x in sorted(result['witnesses'])])))

"""Enumerate the finite request/arbiter graph and find fair bad SCCs."""
from collections import deque
from itertools import product

def successors(state,mutation):
    turn,p0,p1,owed=state
    for r0,r1,enable in product((0,1),repeat=3):
        chosen=0 if mutation==1 else turn
        g0=enable and p0 and (not p1 or not chosen)
        g1=enable and p1 and (not p0 or chosen)
        if r0 and p0 and not g0 or r1 and p1 and not g1:continue
        n0=int(bool((p0 and not g0) or r0));n1=int(bool((p1 and not g1) or r1))
        if mutation==2 and not enable:n1=0
        nt=int(bool(g0)) if g0 or g1 else turn
        no=1 if r1 else 0 if g1 else owed
        yield (nt,n0,n1,no),dict(request=[r0,r1],enable=enable,grant=[int(g0),int(g1)])

def graph_result(mutation=0,fair=True):
    start=(0,0,0,0);graph={};queue=deque([start])
    while queue:
        state=queue.popleft()
        if state in graph:continue
        graph[state]=list(successors(state,mutation));queue.extend(t for t,_ in graph[state] if t not in graph)
    bad={s:[(t,e) for t,e in edges if s[3] and t[3] and not e['grant'][1]] for s,edges in graph.items()}
    # Reachability within the bad subgraph suffices for the tiny graph. An edge
    # lies on a bad cycle iff its destination can reach its source again.
    cycles=[]
    for source,edges in bad.items():
        for target,event in edges:
            if fair and not event['enable']:continue
            seen=set();todo=[target]
            while todo:
                at=todo.pop()
                if at in seen:continue
                seen.add(at);todo.extend(t for t,_ in bad[at] if t not in seen)
            if source in seen:cycles.append(dict(source=list(source),target=list(target),event=event))
    return dict(success=not cycles,states=len(graph),edges=sum(map(len,graph.values())),fair=fair,mutation=mutation,bad_cycle_edges=cycles)

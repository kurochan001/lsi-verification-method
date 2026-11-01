"""Replay a concrete lasso using only observed inputs and an independent transition graph."""
import re
from reference import successors

FIELDS={'rst_n':1,'request':2,'enable':1,'choose':1,'state':4,'pending':2,'turn':1,'owed':1,'grant':2,'ready':2,'active':1,'snapshot':4,'fair_seen':1}

def read_vcd(text):
    scope=[];signals={};step=None;body=False;values={};changed=set();rows=[]
    def finish(final=False):
        if step in changed:
            if final and not set(signals).intersection(changed) and values[step]==len(rows):return
            if not set(signals)<=changed:raise ValueError('incomplete VCD state')
            row={name:values[code] for code,(name,_) in signals.items()};row['step']=values[step];rows.append(row)
    for line in text.splitlines():
        parts=line.split()
        if not parts:continue
        if not body:
            if parts[0]=='$scope':scope.append(parts[2])
            elif parts[0]=='$upscope':scope.pop()
            elif parts[0]=='$var':
                if parts[4]=='smt_step':step=parts[3]
                elif scope==['liveness_formal'] and parts[4] in FIELDS:
                    name=parts[4]
                    if int(parts[2])!=FIELDS[name] or any(v[0]==name for v in signals.values()):raise ValueError('VCD signal identity differs')
                    signals[parts[3]]=(name,int(parts[2]))
            elif parts[0]=='$enddefinitions':body=True
            continue
        if line.startswith('#'):
            finish();changed=set()
        elif re.fullmatch(r'b[01]+ \S+',line):
            raw,code=line.split();values[code]=int(raw[1:],2);changed.add(code)
        elif line.startswith('b') and line.split()[-1] in signals:raise ValueError('unknown VCD value')
    finish(final=True)
    if not body or step is None or {v[0] for v in signals.values()}!=FIELDS.keys() or len(rows)<3:raise ValueError('VCD interface incomplete')
    if [r['step'] for r in rows]!=list(range(len(rows))):raise ValueError('VCD step inventory differs')
    return rows

def replay(rows,mutation,fair):
    if rows[0]['rst_n']!=0:raise ValueError('trace does not start with reset')
    state=(0,0,0,0);active=seen=snapshot=0;capture=None;failure=None;failure_capture=None
    for index,row in enumerate(rows[1:],1):
        turn,p0,p1,owed=state;bits=(turn<<3)|(p1<<2)|(p0<<1)|owed
        if row['rst_n']!=1 or row['state']!=bits or row['pending']!=(p0|(p1<<1)) or row['turn']!=turn or row['owed']!=owed:raise ValueError('DUT/ledger state differs from input replay')
        if (row['active'],row['snapshot'],row['fair_seen'])!=(active,snapshot,seen):raise ValueError('lasso monitor state differs')
        event=dict(request=[row['request']&1,(row['request']>>1)&1],enable=row['enable'])
        options=[(t,e) for t,e in successors(state,mutation) if e['request']==event['request'] and e['enable']==event['enable']]
        if len(options)!=1:raise ValueError('request violates environment contract')
        target,edge=options[0];g0,g1=edge['grant']
        if row['grant']!=(g0|(g1<<1)) or row['ready']!=((int(not p0 or g0))|(int(not p1 or g1)<<1)):raise ValueError('observed handshake differs')
        if g1 or not owed:active=seen=0;capture=None
        elif not active:
            if row['choose']:active=1;snapshot=bits;seen=row['enable'];capture=index
        else:
            if bits==snapshot and (not fair or seen) and failure is None:failure=index;failure_capture=capture
            seen|=row['enable']
        state=target
    if failure is None or not 0<=len(rows)-1-failure<=1 or failure_capture is None or failure<=failure_capture:raise ValueError('no final reachable bad closed walk')
    cycle=rows[failure_capture:failure]
    if any(r['grant']&2 or not r['owed'] for r in cycle) or fair and not any(r['enable'] for r in cycle):raise ValueError('loop is not a fair non-completing request')
    return dict(prefix_steps=failure_capture,loop_steps=failure-failure_capture,assert_sample_delay=len(rows)-1-failure,fair_opportunities=sum(r['enable'] for r in cycle),inputs=[{k:r[k] for k in ('rst_n','request','enable','choose')} for r in rows])

"""Check reviewed proof dependencies; this is bookkeeping, not a theorem prover."""
import hashlib
from pathlib import Path

def audit(plan,records,source_sha256,root,bindings):
    errors=[];order=[]
    try:
        if type(plan.get('schema_version')) is not int or plan['schema_version']!=1:raise ValueError('schema')
        rows=plan['nodes']
        if not isinstance(rows,list) or not rows or any(not isinstance(r,dict) for r in rows):raise ValueError('nodes')
        nodes={r['id']:r for r in rows}
        if len(nodes)!=len(rows) or nodes.keys()!=bindings.keys() or any(r.get('task')!=bindings[n] for n,r in nodes.items()):raise ValueError('proof inventory')
        for r in rows:
            req=r.get('requires')
            if not isinstance(req,list) or any(not isinstance(n,str) or n not in nodes for n in req) or len(req)!=len(set(req)):raise ValueError('dependency inventory')
        def visit(n,trail):
            if n in trail:raise ValueError('cyclic dependency')
            if n in order:return
            for dep in nodes[n]['requires']:visit(dep,trail|{n})
            order.append(n)
        visit(plan['target'],set())
        if set(order)!=nodes.keys():raise ValueError('orphan proof')
        if not isinstance(source_sha256,dict) or not source_sha256:raise ValueError('source inventory')
        for name,digest in source_sha256.items():
            path=Path(root)/name
            if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest()!=digest:raise ValueError('stale source: '+name)
        if not isinstance(records,list) or len(records)!=len(nodes) or len({r['id'] for r in records})!=len(records):raise ValueError('missing/duplicate proof')
        by_id={r['id']:r for r in records}
        if by_id.keys()!={'chain-'+t for t in bindings.values()}:raise ValueError('proof result inventory')
        for n in order:
            r=by_id['chain-'+bindings[n]]
            if r.get('configuration')!='chain' or r.get('category')!='normal' or r.get('mode')!='prove' or r.get('outcome')!='pass' or r.get('formal_status')!='PASS' or not r.get('inventory',{}).get('assert'):raise ValueError('unproven dependency: '+n)
    except (ValueError,KeyError,TypeError,OSError,AttributeError) as exc:errors.append(str(exc))
    return dict(success=not errors,errors=errors,order=order,target=plan.get('target') if isinstance(plan,dict) else None)

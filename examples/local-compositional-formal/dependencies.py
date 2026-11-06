"""Check reviewed proof dependencies and assumption discharge; this is bookkeeping, not a theorem prover."""
import hashlib
from pathlib import Path

def compiled_properties(model):
    """Map each compiled property to its flavor and the source statement it came from."""
    table={}
    for module in model['modules'].values():
        for name,cell in module.get('cells',{}).items():
            if cell['type']=='$check':
                label=name.rsplit('.',1)[-1]
                if label in table:raise ValueError('duplicate compiled property: '+label)
                table[label]=[cell['parameters']['FLAVOR'],cell['attributes'].get('src')]
    return table

def audit(plan,records,source_sha256,root,bindings,cases,properties,required_sources):
    errors=[];order=[]
    try:
        if type(plan.get('schema_version')) is not int or plan['schema_version']!=2:raise ValueError('schema')
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
        # A cross-check stands alone: its result is compared with the composition, never derived from it.
        cross=plan.get('cross_checks')
        if not isinstance(cross,list) or len(cross)!=len(set(cross)) or any(n not in nodes for n in cross):raise ValueError('cross-check inventory')
        for n in cross:
            if n in order or nodes[n]['requires']:raise ValueError('cross-check is not independent: '+n)
            order.append(n)
        if set(order)!=nodes.keys():raise ValueError('orphan proof')
        if not isinstance(source_sha256,dict) or not source_sha256 or set(required_sources)-source_sha256.keys():raise ValueError('source inventory')
        for name,digest in source_sha256.items():
            path=Path(root)/name
            if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest()!=digest:raise ValueError('stale source: '+name)
        if not isinstance(records,list) or len(records)!=len(nodes) or len({r['id'] for r in records})!=len(records):raise ValueError('missing/duplicate proof')
        by_id={r['id']:r for r in records}
        if by_id.keys()!={'chain-'+t for t in bindings.values()}:raise ValueError('proof result inventory')
        compiled={};expected={}
        for n in order:
            r=by_id['chain-'+bindings[n]]
            if r.get('configuration')!='chain' or r.get('category')!='normal' or r.get('mode')!='prove' or r.get('outcome')!='pass' or r.get('formal_status')!='PASS':raise ValueError('unproven dependency: '+n)
            case=cases[bindings[n]];p=case['parameters'];expected[n]={k:sorted(v) for k,v in properties({},case).items()}
            compiled[n]=r.get('compiled',{}).get('properties',{})
            flavors={k:sorted(name for name,(flavor,_) in compiled[n].items() if flavor==k) for k in expected[n]}
            if r.get('inventory')!=expected[n] or flavors!=expected[n]:raise ValueError('property inventory differs: '+n)
            if r['compiled'].get('parameters')!=p or p['MUTATION']!=0 or p['LOCK_RESET']!=0 or p['ASSUME_HOLD']!=1:raise ValueError('proof configuration differs: '+n)
        contracts=plan.get('contracts');environment=plan.get('environment_assumptions')
        if not isinstance(contracts,list) or not isinstance(environment,list):raise ValueError('contract inventory')
        discharged=set();edges=set()
        for c in contracts:
            name,user,owner=c['assumption'],c['assumed_by'],c['guaranteed_by']
            if user not in nodes or owner not in nodes or name in environment:raise ValueError('contract inventory')
            assumption=compiled[user].get(name);guarantee=compiled[owner].get(name)
            if assumption is None or guarantee is None or assumption[0]!='assume' or guarantee[0]!='assert':raise ValueError('contract roles differ: '+name)
            if not assumption[1] or assumption[1]!=guarantee[1]:raise ValueError('assumption and guarantee are not one statement: '+name)
            discharged.add((user,name));edges.add((user,owner))
        for n in order:
            for name in expected[n]['assume']:
                if name not in environment and (n,name) not in discharged:raise ValueError('undischarged assumption: '+n+'/'+name)
        if {(n,dep) for n in nodes for dep in nodes[n]['requires']}!=edges:raise ValueError('dependency without a contract')
    except (ValueError,KeyError,TypeError,OSError,AttributeError) as exc:errors.append(str(exc))
    return dict(success=not errors,errors=errors,order=order,target=plan.get('target') if isinstance(plan,dict) else None)

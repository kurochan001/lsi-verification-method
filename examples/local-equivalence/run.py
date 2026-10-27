#!/usr/bin/env python3
"""Cycle equivalence of a shift FIFO and a circular FIFO, proved with an SBY miter."""
import importlib.util
from pathlib import Path
import sys
HERE=Path(__file__).resolve().parent
TOP='equivalence_formal';CONFIGS={f'depth{d}':dict(DEPTH=d,WIDTH=4) for d in (2,4)};BOUND=12
SOURCES=[HERE/'rtl/fifo_pair.sv',HERE/'equivalence_formal.sv']
SCOPE='Unbounded cycle equivalence after initial synchronous reset; 4-bit data, depths 2/4; empty payload ignored. SBY miter, not an EQY invocation.'
COVERS={'cp_full','cp_drain','cp_simultaneous','cp_reset_pending','cp_recovery'}
def properties(parameters,case):
    return {'assert':{'ap_control','ap_data'}|({'ai_count','ai_pointer','ai_mapping'} if case['parameters']['AUXILIARY'] else set()),
            'assume':{'as_initial_reset'}|({'as_lock_reset'} if case['parameters']['LOCK_RESET'] else set()),'cover':COVERS}
def plan(bound,demo_bug):
    def case(name,mode,expect='PASS',mutation=0,aux=1,lock=0,category='normal',failure=None):
        return dict(id=name,mode=mode,expect=expect,depth=bound,category=category,failure=failure,
                    parameters=dict(MUTATION=mutation,AUXILIARY=aux,LOCK_RESET=lock))
    return [case('equivalence-proof','prove',mutation=demo_bug),case('scenario-cover','cover')]+[
        case(f'detect-mutation{m}','bmc','FAIL',m,0,category='mutation',failure='ap_control' if m in (1,3) else 'ap_data') for m in range(1,5)]+[
        case('overconstrained-proof','prove',lock=1,category='diagnostic'),case('detect-overconstraint','cover','FAIL',lock=1,category='diagnostic')]
if __name__=='__main__':
    spec=importlib.util.spec_from_file_location('formal_runner',HERE.parent/'local-formal-common/runner.py')
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);sys.exit(m.main(sys.modules[__name__]))

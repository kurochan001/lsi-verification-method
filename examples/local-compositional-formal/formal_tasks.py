#!/usr/bin/env python3
"""Prove source, sink, connection contract and the small composed implementation."""
import importlib.util
from pathlib import Path
import sys
HERE=Path(__file__).resolve().parent
TOP='contract_formal';CONFIGS={'chain':{}};BOUND=8;TIMEOUT=120
SOURCES=[HERE/'rtl/blocks.sv',HERE/'contract_formal.sv']
SCOPE='Single-clock two-state source/sink contracts; four induction proofs, reachability and explicit counterexamples. Physical timing and arbitrary IP composition are outside the model.'
PROOFS={'producer':'producer-guarantee','consumer':'consumer-guarantee','connection':'connection-contract','integration':'integration-result'}
def properties(parameters,case):
    p=case['parameters'];role=p['ROLE'];a={'ap_reset'}|({'ap_hold'} if role==0 else {'ap_contract'} if role==2 else {'ap_done','ap_result'})
    assumptions={'as_initial_reset'}|({'as_upstream_hold'} if role==1 and p['ASSUME_HOLD'] else set())|({'as_lock_reset'} if p['LOCK_RESET'] else set())
    return {'assert':a,'assume':assumptions,'cover':{'cp_activity','cp_stall'}}
def plan(bound,demo_bug):
    def c(name,role,mode='prove',expect='PASS',mutation=0,category='normal',failure=None,hold=1,lock=0):
        return dict(id=name,mode=mode,expect=expect,depth=bound,category=category,failure=failure,parameters=dict(ROLE=role,MUTATION=mutation,ASSUME_HOLD=hold,LOCK_RESET=lock))
    return [c('producer-guarantee',0,mutation=demo_bug),c('consumer-guarantee',1,mutation=demo_bug),
            c('connection-contract',2,mutation=demo_bug),c('integration-result',3,mutation=demo_bug),c('scenario-cover',3,'cover'),
            c('detect-source',0,'bmc','FAIL',1,'mutation','ap_hold'),c('detect-sink',1,'bmc','FAIL',2,'mutation','ap_result'),
            c('detect-wiring',2,'bmc','FAIL',3,'mutation','ap_contract'),
            c('missing-assumption',1,'bmc','FAIL',0,'counterexample','ap_result',hold=0),
            c('overconstrained-proof',1,lock=1,category='diagnostic'),c('detect-overconstraint',1,'cover','FAIL',category='diagnostic',lock=1)]
if __name__=='__main__':
    s=importlib.util.spec_from_file_location('contract_tasks_runner',HERE.parent/'local-formal-common/runner.py');m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
    sys.exit(m.main(sys.modules[__name__]))

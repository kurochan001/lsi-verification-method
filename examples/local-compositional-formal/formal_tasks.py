#!/usr/bin/env python3
"""Prove source, wiring and sink contracts, plus an independent direct proof of the composed implementation."""
import importlib.util
from pathlib import Path
import sys
HERE=Path(__file__).resolve().parent
TOP='contract_formal';CONFIGS={'chain':{}};BOUND=8;TIMEOUT=120
SOURCES=[HERE/'rtl/blocks.sv',HERE/'contract_formal.sv']
SCOPE='Single-clock two-state source/wiring/sink contracts; four induction proofs, reachability under the same assumptions and explicit counterexamples. Physical timing and arbitrary IP composition are outside the model.'
PROOFS={'producer':'producer-guarantee','consumer':'consumer-guarantee','connection':'connection-contract','integration':'integration-result'}
def properties(parameters,case):
    p=case['parameters'];role=p['ROLE'];hold=p['ASSUME_HOLD']
    a={0:{'ap_reset','ag_source_hold'},1:{'ap_reset','ap_done','ap_result'},2:{'ag_sink_hold'},3:{'ap_reset','ap_done','ap_result'}}[role]
    assumptions={'as_initial_reset'}|({'ag_sink_hold'} if role==1 and hold else {'ag_source_hold'} if role==2 and hold else set())|({'as_lock_reset'} if p['LOCK_RESET'] else set())
    return {'assert':a,'assume':assumptions,'cover':{'cp_activity','cp_stall','cp_hold','cp_nonzero'}}
def prepare(parameters,case):
    p=case['parameters'];script='read -formal -sv blocks.sv contract_formal.sv\n'+''.join(f'chparam -set {k} {v} {TOP}\n' for k,v in p.items())
    # The connection relies on the producer's statement and discharges the consumer's: same cells, flipped roles.
    if p['ROLE']==2:script+=f'hierarchy -top {TOP}\nproc\nchformal -assert2assume c:*ag_source_hold\nchformal -assume2assert c:*ag_sink_hold\n'
    return script
def plan(bound,demo_bug):
    def c(name,role,mode='prove',expect='PASS',mutation=0,category='normal',failure=None,hold=1,lock=0):
        return dict(id=name,mode=mode,expect=expect,depth=bound,category=category,failure=failure,parameters=dict(ROLE=role,MUTATION=mutation,ASSUME_HOLD=hold,LOCK_RESET=lock))
    return [c('producer-guarantee',0,mutation=demo_bug),c('consumer-guarantee',1,mutation=demo_bug),
            c('connection-contract',2,mutation=demo_bug),c('integration-result',3,mutation=demo_bug),
            c('cover-producer',0,'cover'),c('cover-consumer',1,'cover'),c('cover-connection',2,'cover'),c('scenario-cover',3,'cover'),
            c('detect-source',0,'bmc','FAIL',1,'mutation','ag_source_hold'),c('detect-source-valid',0,'bmc','FAIL',4,'mutation','ag_source_hold'),
            c('detect-sink',1,'bmc','FAIL',2,'mutation','ap_result'),
            c('detect-wiring',2,'bmc','FAIL',3,'mutation','ag_sink_hold'),c('detect-wiring-valid',2,'bmc','FAIL',5,'mutation','ag_sink_hold'),
            c('detect-integration',3,'bmc','FAIL',1,'mutation','ap_result'),
            c('missing-assumption',1,'bmc','FAIL',0,'counterexample','ap_result',hold=0),
            c('connection-missing-assumption',2,'bmc','FAIL',0,'counterexample','ag_sink_hold',hold=0),
            c('overconstrained-proof',1,lock=1,category='diagnostic'),c('detect-overconstraint',1,'cover','FAIL',category='diagnostic',lock=1)]
if __name__=='__main__':
    s=importlib.util.spec_from_file_location('contract_tasks_runner',HERE.parent/'local-formal-common/runner.py');m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
    sys.exit(m.main(sys.modules[__name__]))

#!/usr/bin/env python3
"""Bounded acceptance/completion under explicit receiver fairness, with an unfair counterexample."""
import importlib.util
from pathlib import Path
import sys
HERE=Path(__file__).resolve().parent
TOP='progress_formal';CONFIGS={'service1-gap2':dict(SERVICE=1,READY_GAP=2),'service2-gap3':dict(SERVICE=2,READY_GAP=3)};BOUND=24
SOURCES=[HERE/'rtl/bounded_server.sv',HERE/'progress_formal.sv']
SCOPE='Unbounded safety and finite response bounds under a bounded-ready assumption. No general unbounded-LTL liveness claim. Unfair receiver counterexample is expected.'
COVERS={'cp_contention','cp_stall','cp_done0','cp_done1','cp_wait','cp_reset_pending','cp_recovery'}
def properties(parameters,case):
    p=case['parameters']
    return {'assert':{'ap_owner','ap_exclusive','ap_hold'}|({'ap_completion','ap_accept'} if p['CHECK_DEADLINES'] else set())|
             ({'ai_ledger','ai_owner','ai_counter','ai_state','ai_nonnegative'} if p['AUXILIARY'] else set())|({'ai_timing','ai_fair_counter'} if p['AUXILIARY'] and p['FAIR'] else set()),
            'assume':{'as_initial_reset','as_hold0','as_hold1'}|({'as_receiver_fair'} if p['FAIR'] else set())|({'as_no_receiver'} if p['FORCE_STALL'] else set()),'cover':COVERS}
def plan(bound,demo_bug):
    def case(name,mode='prove',expect='PASS',mutation=0,fair=1,force=0,deadlines=1,aux=1,category='normal',failure=None):
        return dict(id=name,mode=mode,expect=expect,depth=bound,category=category,failure=failure,parameters=dict(MUTATION=mutation,FAIR=fair,FORCE_STALL=force,CHECK_DEADLINES=deadlines,AUXILIARY=aux))
    return [case('deadline-proof',mutation=demo_bug),case('scenario-cover','cover')]+[
      case(f'detect-mutation{m}','bmc','FAIL',m,aux=0,category='mutation',failure={1:'ap_accept',2:'ap_hold',3:'ap_completion',4:'ap_owner'}[m]) for m in range(1,5)]+[
      case('unfair-safety-proof',fair=0,deadlines=0,category='diagnostic'),
      case('detect-missing-fairness','bmc','FAIL',fair=0,force=1,aux=0,category='counterexample',failure='ap_completion')]
if __name__=='__main__':
    spec=importlib.util.spec_from_file_location('formal_runner',HERE.parent/'local-formal-common/runner.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);sys.exit(m.main(sys.modules[__name__]))

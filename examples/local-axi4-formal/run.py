#!/usr/bin/env python3
"""AXI4 small-memory safety proof, bounded IDs/LAST/data and reachability."""
import importlib.util
from pathlib import Path
import sys
HERE=Path(__file__).resolve().parent
TOP='axi4_formal';CONFIGS={f'bytes{n}':dict(MEM_BYTES=n) for n in (16,32)};BOUND=12;TIMEOUT=300
SOURCES=[HERE.parent/'local-axi4/rtl/axi4_ram.sv',HERE/'axi4_formal.sv']
SCOPE='One clock, 2-state, sampled reset via async2sync; legal aligned INCR 1/2 beats, 16/32-byte memories, two credits. Holding/accounting proof permits two outstanding per direction; IDs/LAST/watched-byte BMC serializes memory transactions; covers permit concurrency.'
CONTROL={'ap_reset','ap_b_hold','ap_r_hold'}
AUX={'ai_fifo_bounds','ai_write_accounting','ai_write_pointers','ai_read_pointers','ai_write_head','ai_read_pending','ai_credit_match','ap_credit_bounds'}
DATA={'ap_ids','ap_last','ap_data','ap_response'}
ASSUMPTIONS={'as_initial_reset','as_aw_hold','as_w_hold','as_ar_hold'}
COVERS={'cp_two_write','cp_two_read','cp_w_first','cp_b_stall','cp_r_stall','cp_burst','cp_zero_strobe','cp_reset_pending','cp_recovery'}
def properties(parameters,case):
    p=case['parameters'];return {'assert':CONTROL|(AUX if p['AUXILIARY'] else set())|(DATA if p['CHECK_DATA'] else set()),
        'assume':ASSUMPTIONS|({'as_serial_channels','as_serial_aw','as_serial_ar'} if p['SERIAL_DATA'] else set())|({'as_aw_legal','as_ar_legal','as_wlast'} if p['CHECK_DATA'] else set())|({'as_lock_reset'} if p['LOCK_RESET'] else set()),'cover':COVERS}
def plan(bound,demo_bug):
    def case(name,mode,expect='PASS',mutation=0,data=0,aux=1,lock=0,category='normal',failure=None):
        return dict(id=name,mode=mode,expect=expect,depth=8 if mode=='prove' else bound,category=category,failure=failure,
                    parameters=dict(MUTATION=mutation,CHECK_DATA=data,AUXILIARY=aux,LOCK_RESET=lock,SERIAL_DATA=int(data and mode=='bmc')))
    return [case('safety-proof','prove',mutation=demo_bug),case('data-bmc','bmc',mutation=demo_bug,data=1),case('scenario-cover','cover',data=1)]+[
        case(f'detect-mutation{m}','bmc','FAIL',m,1,0,category='mutation',failure={1:'ap_data',2:'ap_ids',3:'ap_last',4:'ap_data'}[m]) for m in range(1,5)]+[
        case('overconstrained-proof','prove',lock=1,category='diagnostic'),case('detect-overconstraint','cover','FAIL',lock=1,category='diagnostic')]
if __name__=='__main__':
    spec=importlib.util.spec_from_file_location('formal_runner',HERE.parent/'local-formal-common/runner.py')
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);sys.exit(m.main(sys.modules[__name__]))

#!/usr/bin/env python3
"""Prove constant public timing by self-composition, with explicit result declassification."""
import importlib.util
from pathlib import Path
import sys
HERE=Path(__file__).resolve().parent
TOP='compare_formal';CONFIGS={'bytes2':{'BYTES':2},'bytes4':{'BYTES':4}}
BOUND=12;PROOF_DEPTH=8
SOURCES=[HERE/'rtl/constant_time_compare.sv',HERE/'compare_formal.sv']
SCOPE=('Unbounded self-composition proof for 2/4-byte comparisons: identical public inputs and arbitrary '
       'independent changing secrets produce identical ready/busy/result-valid and public status. '
       'Only the comparison result at result-valid is declassified. Each accepted operation completes '
       'after BYTES cycles with the equality of the captured operands, unless reset; held results stay stable. '
       'This is a digital cycle/public-port property, not physical power/EM or cache side-channel security.')
ASSERTS={'ap_timing','ap_public','ap_result','ap_hold','ai_model_bounds'}
COVERS={'cp_match','cp_mismatch','cp_different_secrets','cp_first_byte','cp_last_byte','cp_backpressure','cp_reset_busy'}


def properties(parameters,case):return {'assert':ASSERTS,'assume':{'as_initial_reset'},'cover':COVERS}


def plan(bound,demo_bug):
    def case(name,mode='prove',expect='PASS',mutation=0,category='normal',failure=None):
        return dict(id=name,mode=mode,expect=expect,depth=PROOF_DEPTH if mode=='prove' else bound,
                    category=category,failure=failure,parameters={'MUTATION':mutation})
    return [case('constant-time-proof',mutation=demo_bug),case('scenario-cover','cover')]+[
        case(f'detect-mutation{m}','bmc','FAIL',m,'mutation',label)
        for m,label in ((1,'ap_timing'),(2,'ap_public'),(3,'ap_result'),(4,'ap_result'))]


if __name__=='__main__':
    spec=importlib.util.spec_from_file_location('formal_runner',HERE.parent/'local-formal-common/runner.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);sys.exit(module.main(sys.modules[__name__]))

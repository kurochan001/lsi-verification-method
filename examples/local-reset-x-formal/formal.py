#!/usr/bin/env python3
"""Known values after reset, proved from arbitrary first register values: two copies must agree, and one copy must match a model."""
import importlib.util
from pathlib import Path
import sys
HERE = Path(__file__).resolve().parent
TOP = 'reset_x_formal'
CONFIGS = {'stages3': dict(WIDTH=8, STAGES=3), 'stages2': dict(WIDTH=4, STAGES=2)}
BOUND = 12
PROOF_DEPTH = 5
TIMEOUT = 300
SOURCES = [HERE / 'rtl/reset_x_unit.sv', HERE / 'reset_x_formal.sv']
SCOPE = ('Unbounded proof by k-induction, with no assumption about the first state and no assumed reset: '
         'after any clock edge with rst high, the control outputs and the registers that hold control state '
         'are the same in two copies that started from independent arbitrary register values, the valid bit '
         'of stage j is the same after j more edges, and data is the same wherever it is valid. '
         'A second proof compares one copy with reset values, the time of ready and a model with defined '
         'first values. One clock, synchronous reset, two-valued. Data values are not compared with a model.')
KNOWN = {'ap_known_ready', 'ap_known_stream', 'ap_known_odd', 'ap_known_count', 'ap_known_err',
         'ap_known_step', 'ap_known_stages', 'ai_known_init', 'ai_known_data'}
VALUE = {'ap_reset_values', 'ap_ready_time', 'ap_valid_model', 'ap_count_model', 'ap_err_model',
         'ai_step_model', 'ai_init_model', 'ai_stage_model'}
COVERS = {'cp_unknown_data', 'cp_first_output', 'cp_refused', 'cp_step2', 'cp_reset_in_flight'}
# The check that every counterexample of the mutant violates at the first failing step.
KNOWN_FAILURES = {1: 'ap_known_count', 2: 'ap_known_odd', 3: 'ap_known_stream', 4: 'ap_known_err', 5: 'ap_known_step'}
VALUE_FAILURES = {3: 'ap_ready_time', 6: 'ap_reset_values'}
# Mutants 4 and 5 pass the simulation that starts from X (see run.py); here they are counterexamples.


def properties(parameters, case):
    return {'assert': VALUE if case['parameters']['VALUES'] else KNOWN, 'assume': set(), 'cover': COVERS}


def plan(bound, demo_bug):
    def case(name, mode, values, expect='PASS', mutation=0, category='normal', failure=None):
        return dict(id=name, mode=mode, expect=expect, depth=PROOF_DEPTH if mode == 'prove' else bound,
                    category=category, failure=failure, parameters=dict(MUTATION=mutation, VALUES=values))
    cases = [case('known-proof', 'prove', 0, mutation=demo_bug), case('value-proof', 'prove', 1),
             case('scenario-cover', 'cover', 0)]
    cases += [case(f'known-detect-mutation{m}', 'bmc', 0, 'FAIL', m, 'mutation', KNOWN_FAILURES[m])
              for m in sorted(KNOWN_FAILURES)]
    cases += [case(f'value-detect-mutation{m}', 'bmc', 1, 'FAIL', m, 'mutation', VALUE_FAILURES[m])
              for m in sorted(VALUE_FAILURES)]
    # Two copies with the same wrong reset value agree: the comparison alone does not see mutant 6.
    cases.append(case('known-misses-mutation6', 'bmc', 0, 'PASS', 6, 'diagnostic'))
    return cases


if __name__ == '__main__':
    spec = importlib.util.spec_from_file_location('formal_runner', HERE.parent / 'local-formal-common/runner.py')
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    sys.exit(m.main(sys.modules[__name__]))

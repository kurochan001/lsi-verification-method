#!/usr/bin/env python3
"""RV32I decoder proved against the riscv-opcodes table for all 2^32 instruction words, with four mutants."""
import importlib.util
from pathlib import Path
import sys
HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('decoder_generate', HERE / 'generate.py')
G = importlib.util.module_from_spec(spec)
spec.loader.exec_module(G)
TOP = 'decoder_formal'
CONFIGS = {'rv32i': {}}
BOUND = 8
PROOF_DEPTH = 1  # the decoder has no state, so one step already covers every word
SOURCES = [G.SPEC, HERE / 'rtl/rv32i_decoder.sv', HERE / 'decoder_formal.sv', *G.UPSTREAM,
           HERE / 'upstream/LICENSE', HERE / 'generate.py']
SCOPE = ('Proof, for all 2^32 instruction words, that the decoder accepts exactly the RV32I '
         'encodings of the riscv-opcodes table and gives each the table\'s instruction, '
         'immediate and register use. Reserved encodings are treated as illegal.')
ASSERTS = {'ap_unique', 'ap_legal', 'ap_op', 'ap_imm', 'ap_regs'}
COVERS = {'cp_compressed', 'cp_fence_reserved_fields', 'cp_shift_rv64', 'cp_mul', 'cp_csr', 'cp_branch_far'}
FAILURES = {1: 'ap_legal', 2: 'ap_legal', 3: 'ap_legal', 4: 'ap_imm'}


def properties(parameters, case):
    return {'assert': ASSERTS, 'assume': set(), 'cover': COVERS}


def prepare(parameters, case):
    """Read only the Verilog sources; the table files are kept for hashing and reference."""
    settings = ''.join(f'chparam -set {k} {v} {TOP}\n' for k, v in {**parameters, **case['parameters']}.items())
    return 'read -formal -sv spec_decode.sv rv32i_decoder.sv decoder_formal.sv\n' + settings


def plan(bound, demo_bug):
    def case(name, mode='prove', expect='PASS', mutation=0, category='normal', failure=None):
        return dict(id=name, mode=mode, expect=expect, depth=PROOF_DEPTH if mode == 'prove' else bound,
                    category=category, failure=failure, parameters=dict(MUTATION=mutation))
    return [case('decoder-proof', mutation=demo_bug), case('scenario-cover', 'cover')] + [
        case(f'detect-mutation{m}', 'bmc', 'FAIL', m, 'mutation', FAILURES[m]) for m in range(1, 5)]


if __name__ == '__main__':
    if not G.SPEC.exists() or G.SPEC.read_text() != G.render():  # never prove a stale specification
        print('RUNNER_ERROR spec_decode.sv does not match the table; run generate.py', file=sys.stderr)
        sys.exit(1)
    spec = importlib.util.spec_from_file_location('formal_runner', HERE.parent / 'local-formal-common/runner.py')
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    sys.exit(m.main(sys.modules[__name__]))

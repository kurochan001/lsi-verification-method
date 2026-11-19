#!/usr/bin/env python3
"""Check SECDED RAM byte writes, serialized RMW, scrub priority and reset abort."""
import importlib.util
from pathlib import Path
import sys
HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('memory_sim', HERE.parent/'local-memory-common/sim.py')
S=importlib.util.module_from_spec(spec);spec.loader.exec_module(S)
M=S.load('ecc_rmw_model',HERE/'model.py')
NAME='local-ecc-rmw'; TOP='ecc_rmw_tb'; LABEL='ECC_RMW'
SOURCES=[HERE/'rtl/ecc_rmw_ram.sv',HERE/'tb/ecc_rmw_tb.sv'];INPUTS=[HERE/'model.py']
GOALS={'access/read','access/partial','access/zero-mask','fault/corrected','fault/uncorrectable','scrub/completed','race/foreground','race/queued-write','reset/abort','response/stall'}


def cases(a):
    result=[]
    for width in (32,64):
        config=f'width{width}'
        for seed in range(a.seed,a.seed+(3 if a.profile=='nightly' else 1)):
            rows=M.stimulus(width,8,seed,128 if a.profile=='nightly' else 32)
            result.append(dict(id=f'{config}/seed{seed}',configuration=config,seed=seed,
                parameters=dict(DATA_W=width,DEPTH=8),checks=len(rows),
                text=''.join(' '.join(f'{v:x}' for v in row)+'\n' for row in rows)))
    for mutation in range(1,5):
        rows=M.stimulus(32,8,a.seed,0)
        result.append(dict(id=f'mutation-{mutation}',configuration='width32',seed=a.seed,
            parameters=dict(DATA_W=32,DEPTH=8),checks=len(rows),mutation=mutation,expected_failure=LABEL,
            text=''.join(' '.join(f'{v:x}' for v in row)+'\n' for row in rows)))
    return result


if __name__=='__main__':sys.exit(S.main(sys.modules[__name__]))

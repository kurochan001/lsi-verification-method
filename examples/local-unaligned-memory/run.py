#!/usr/bin/env python3
"""Split byte-addressed accesses, endian mapping, retained memory and partial errors."""
import importlib.util
from pathlib import Path
import sys
HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('memory_sim',HERE.parent/'local-memory-common/sim.py')
S=importlib.util.module_from_spec(spec);spec.loader.exec_module(S)
M=S.load('unaligned_model',HERE/'model.py')
NAME='local-unaligned-memory';TOP='unaligned_memory_tb';LABEL='UNALIGNED_MEMORY'
SOURCES=[HERE/'rtl/byte_word_ram.sv',HERE/'rtl/unaligned_memory.sv',HERE/'tb/unaligned_memory_tb.sv'];INPUTS=[HERE/'model.py']
GOALS={'access/read','access/write','split/cross-word','bounds/rejected','error/partial','reset/partial','response/stall','endian/mapped'}


def cases(a):
    result=[]
    for width in (32,64):
        for endian in (0,1):
            config=f'w{width}-'+('big' if endian else 'little')
            for seed in range(a.seed,a.seed+(3 if a.profile=='nightly' else 1)):
                rows=M.stimulus(width,16,bool(endian),seed,96 if a.profile=='nightly' else 24)
                result.append(dict(id=f'{config}/seed{seed}',configuration=config,seed=seed,
                    parameters=dict(DATA_W=width,DEPTH=16,BIG_ENDIAN=endian),checks=len(rows),
                    text=''.join(' '.join(f'{v:x}' for v in row)+'\n' for row in rows)))
    for mutation in range(1,5):
        rows=M.stimulus(32,16,True,a.seed,0)
        result.append(dict(id=f'mutation-{mutation}',configuration='w32-big',seed=a.seed,
            parameters=dict(DATA_W=32,DEPTH=16,BIG_ENDIAN=1),checks=len(rows),mutation=mutation,expected_failure=LABEL,
            text=''.join(' '.join(f'{v:x}' for v in row)+'\n' for row in rows)))
    return result


if __name__=='__main__':sys.exit(S.main(sys.modules[__name__]))

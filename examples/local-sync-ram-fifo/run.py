#!/usr/bin/env python3
"""Exercise a Gray-pointer FIFO with synchronous RAM and reserved prefetch slots."""
import importlib.util
from pathlib import Path
import sys
HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('memory_sim',HERE.parent/'local-memory-common/sim.py')
S=importlib.util.module_from_spec(spec);spec.loader.exec_module(S)
NAME='local-sync-ram-fifo';TOP='sync_ram_fifo_tb';LABEL='SYNC_RAM_FIFO'
SOURCES=[*sorted((HERE/'rtl').glob('*.sv')),HERE/'tb/sync_ram_fifo_tb.sv'];INPUTS=[]
GOALS={'fifo/full','fifo/empty','flow/stall','flow/resume','pointer/wrap','reset/pending','reset/new-generation','ram/prefetch'}
CONFIGS={
    'fast-write-lat1':dict(DEPTH=4,READ_LATENCY=1,WR_PERIOD=10,RD_PERIOD=17,RD_PHASE=3),
    'fast-read-lat2':dict(DEPTH=8,READ_LATENCY=2,WR_PERIOD=19,RD_PERIOD=10,RD_PHASE=2),
    'coincident-lat1':dict(DEPTH=4,READ_LATENCY=1,WR_PERIOD=12,RD_PERIOD=12,RD_PHASE=0),
    'phase-lat2':dict(DEPTH=8,READ_LATENCY=2,WR_PERIOD=12,RD_PERIOD=12,RD_PHASE=3),
    'byte-lat2':dict(WIDTH=8,DEPTH=4,READ_LATENCY=2,WR_PERIOD=13,RD_PERIOD=17,RD_PHASE=1),
    'bit-lat1':dict(WIDTH=1,DEPTH=4,READ_LATENCY=1,WR_PERIOD=17,RD_PERIOD=13,RD_PHASE=2)}


def cases(a):
    result=[]
    for config,parameters in CONFIGS.items():
        for seed in range(a.seed,a.seed+(3 if a.profile=='nightly' else 1)):
            count=512 if a.profile=='nightly' else 128
            result.append(dict(id=f'{config}/seed{seed}',configuration=config,seed=seed,
                parameters=parameters,checks=count))
    for mutation in range(1,5):
        result.append(dict(id=f'mutation-{mutation}',configuration='fast-write-lat1',seed=a.seed,
            parameters=CONFIGS['fast-write-lat1'],checks=128,mutation=mutation,expected_failure=LABEL))
    return result


if __name__=='__main__':sys.exit(S.main(sys.modules[__name__]))

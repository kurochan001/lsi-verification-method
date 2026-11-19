#!/usr/bin/env python3
"""Check two-clock frame ownership, frame-boundary swaps, repetition and reset."""
import importlib.util
from pathlib import Path
import sys
HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('memory_sim',HERE.parent/'local-memory-common/sim.py')
S=importlib.util.module_from_spec(spec);spec.loader.exec_module(S)
M=S.load('double_buffer_model',HERE/'model.py')
NAME='local-video-double-buffer';TOP='video_double_buffer_tb';LABEL='VIDEO_DOUBLE_BUFFER'
SOURCES=[HERE.parent/'local-sync-ram-fifo/rtl/memory_reset_sync.sv',HERE/'rtl/video_double_buffer.sv',HERE/'tb/video_double_buffer_tb.sv']
INPUTS=[HERE/'model.py']
GOALS={'input/backpressure','frame/published','frame/boundary-swap','frame/repeated','reset/pending','reset/new-generation'}
CONFIGS={'fast-writer':dict(WIDTH=8,HEIGHT=4,WR_PERIOD=7,PIX_PERIOD=20,PIX_PHASE=3),
    'slow-writer':dict(WIDTH=7,HEIGHT=3,WR_PERIOD=29,PIX_PERIOD=17,PIX_PHASE=2),
    'one-pixel':dict(WIDTH=1,HEIGHT=1,WR_PERIOD=11,PIX_PERIOD=19,PIX_PHASE=1)}


def cases(a):
    result=[]
    for config,params in CONFIGS.items():
        for seed in range(a.seed,a.seed+(3 if a.profile=='nightly' else 1)):
            rows=M.vectors(params['WIDTH'],params['HEIGHT'],seed)
            result.append(dict(id=f'{config}/seed{seed}',configuration=config,seed=seed,parameters=params,
                checks=(params['WIDTH']+4)*(params['HEIGHT']+3)*20,
                text=''.join(' '.join(f'{v:x}' for v in row)+'\n' for row in rows)))
    for mutation in range(1,5):
        params=CONFIGS['fast-writer'];rows=M.vectors(params['WIDTH'],params['HEIGHT'],a.seed)
        result.append(dict(id=f'mutation-{mutation}',configuration='fast-writer',seed=a.seed,parameters=params,
            checks=(params['WIDTH']+4)*(params['HEIGHT']+3)*20,mutation=mutation,expected_failure=LABEL,
            text=''.join(' '.join(f'{v:x}' for v in row)+'\n' for row in rows)))
    return result


def postcheck(case,directory):return M.compare(case,directory)


if __name__=='__main__':sys.exit(S.main(sys.modules[__name__]))

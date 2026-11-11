#!/usr/bin/env python3
"""ROM-booted RV32I + AHB-Lite/APB/AXI4 + shared RAM + two-line Sobel accelerator."""
import importlib.util
from pathlib import Path
import sys

HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('soc_image_support',HERE.parent/'local-image-sobel/support.py');S=importlib.util.module_from_spec(spec);spec.loader.exec_module(S)
E=S.E
FW=S.load('image_rom_firmware',HERE/'firmware.py')
CONFIGS={'w5h5-wait0':dict(W=5,H=5,WAIT_CYCLES=0),'w7h5-wait2':dict(W=7,H=5,WAIT_CYCLES=2)}
SOURCES=[HERE.parent/'local-riscv-decoder/rtl/rv32i_decoder.sv',HERE.parent/'local-riscv-iss/rtl/rv32i_core.sv',
         HERE.parent/'local-conv-window/rtl/conv_window.sv',HERE.parent/'local-image-sobel/rtl/sobel_stream.sv',
         *sorted((HERE/'rtl').glob('*.sv')),HERE/'tb/image_soc_tb.sv']
SCENARIOS={'irq-during-read':9,'read-error':1,'write-error':2,'invalid-config':3,'bus-errors':4,'reset-read':5,'reset-write':6,'relocated-up':7,'relocated-down':8}
SINGLE={'read-error-mid':1,'read-error-last':1,'write-error-mid':2,'write-error-last':2}


def run(a):
    seeds=list(range(a.seed,a.seed+(3 if a.profile=='nightly' else 1)))
    names=['boot',*[f'random-{s}' for s in seeds],*SCENARIOS,*SINGLE,*[f'mutation-{i}' for i in range(1,6)]]
    ids=['toolchain',*[f'{cfg}/{n}' for cfg in CONFIGS for n in [*names,'coverage']],'source-freshness']
    inputs=[Path(__file__),HERE/'firmware.py',HERE/'requirements.json',Path(S.__file__),S.HERE/'model.py',
            HERE.parent/'local-riscv-iss/iss.py',*SOURCES]
    e=E.Evidence('local-image-soc',a,inputs,dict(configurations=CONFIGS,seeds=seeds,scenarios=SCENARIOS),ids)
    sim=S.Simulator(e,'image_soc_tb',SOURCES)
    probes={name:E.P.execute([getattr(a,name),'-V'],e.out/(name+'-version.log'),a.timeout,e.out) for name in ('iverilog','vvp')}
    E.P.write_json(e.out/'tools.json',probes);e.check('toolchain',all(not r['error'] and r['returncode']==0 for r in probes.values()),probes)
    _,goals=E.C.catalog(HERE/'requirements.json');coverage={}
    def execute(name,parameters,frames,seed,mutation=0,label=None,scenario=0,fault=-1):
        w,h=parameters['W'],parameters['H'];expected=[S.MODEL.sobel(frame,w,h) for frame in frames];source,destination=FW.buffers(scenario,w*h)
        plusargs=dict(FAULT=fault,SRC_BASE=source,DST_BASE=destination,APB_ERRORS=FW.REJECTED_APB if scenario==4 else 0,AHB_ERRORS=FW.REJECTED_APB+FW.REJECTED_AHB if scenario==4 else 0)
        return sim.execute(name,parameters,frames,seed,mutation=mutation,expected=label,scenario=scenario,firmware=FW.program(frames,expected,scenario,(w,h)),plusargs=plusargs)
    for cfg,parameters in CONFIGS.items():
        w,h=parameters['W'],parameters['H'];frames=S.MODEL.directed(w,h)[:2]
        execute(cfg+'/boot',parameters,frames,a.seed)
        for seed in seeds:execute(cfg+f'/random-{seed}',parameters,S.MODEL.random_frames(w,h,seed,2),seed)
        for name,scenario in SCENARIOS.items():execute(cfg+'/'+name,parameters,frames[:1],a.seed,scenario=scenario)
        # One bad response only: a beat or burst in the middle, or the last one of the frame.
        faults={'read-error-mid':w*h//2,'read-error-last':w*h-1,'write-error-mid':0,'write-error-last':(w*h-1)//4}
        for name,scenario in SINGLE.items():execute(cfg+'/'+name,parameters,frames[:1],a.seed,scenario=scenario,fault=faults[name])
        for mutation,label in ((1,'SOC_AHB'),(2,'SOC_APB'),(3,'SOC_PIXEL'),(4,'SOC_COMPLETION')):
            execute(cfg+f'/mutation-{mutation}',parameters,frames[:1],a.seed,mutation=mutation,label=label)
        execute(cfg+'/mutation-5',parameters,frames,a.seed,mutation=5,label='SOC_CPU_HOLD',scenario=9)
        hit=set(g for r in sim.records if r['id'].startswith(cfg+'/') for g in r['coverage'])
        coverage[cfg]=dict(required=sorted(goals),hit=sorted(hit),missing=sorted(goals-hit));e.check(cfg+'/coverage',not goals-hit,coverage[cfg])
    sim.save();E.P.write_json(e.out/'coverage.json',coverage);S.fresh(e);return e.finish()


def main():
    p=E.parser(__doc__,'local-image-soc');a=p.parse_args();E.validate(p,a)
    if a.seed>2**31-4:p.error('seed must fit the three-seed signed 32-bit simulation range')
    try:return run(a)
    except (OSError,ValueError,KeyError,TypeError) as exc:print('RUNNER_ERROR',exc,file=sys.stderr);return 1
if __name__=='__main__':sys.exit(main())

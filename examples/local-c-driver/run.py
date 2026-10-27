#!/usr/bin/env python3
"""Compile a C11 DMA driver and run it against the real APB DMA RTL via MMIO callbacks."""
import importlib.util
from pathlib import Path
import random
import sys
HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('host_runner',HERE.parent/'local-host-common/runner.py');H=importlib.util.module_from_spec(spec);spec.loader.exec_module(H)
NAME='local-c-driver';CONFIGS={'host-c':{}};ITERATIONS={'smoke':24,'nightly':200}
INPUTS=[HERE/'c/dma_driver.c',HERE/'c/dma_driver.h',HERE/'harness.cpp',HERE.parent/'local-dma/rtl/apb_dma.sv']
def operations(seed,iterations,boundary=False):
    fixed=[[0,0,256,8,17,3],[0,4092,512,6,91,2],[0,0,4092,6,55,0],[0,0,256,0,1,0],
           [1,3,256,8,17,0],[2,0,256,8,19,3],[3,0,256,8,37,0],[4,64,512,7,128,2]]
    if boundary:return fixed
    rng=random.Random(seed)
    return fixed+[[0,rng.choice((0,64,4092)),rng.choice((512,1024,6144)),rng.randint(1,24),rng.randrange(256),rng.randrange(5)] for _ in range(iterations)]
def totals(ops):return dict(starts=len(ops)+sum(r[0]==3 for r in ops),copies=sum(r[0] in (0,3,4) for r in ops),errors=sum(r[0] in (1,2) for r in ops),timeouts=sum(r[0]==3 for r in ops))
def cases(args):
    baseline=operations(17,0,True)
    def case(name,ops,fault=0,label=None):return dict(id='host-c-'+name,configuration='host-c',operations=ops,fault=fault,expected_failure=label,category='mutation' if fault else 'functional',checks=len(ops),counts=totals(ops))
    result=[case('boundaries',baseline)]
    result += [case(f'random-seed{s}',operations(s,args.iterations)) for s in range(args.seed,args.seed+(3 if args.profile=='nightly' else 1))]
    result += [case(f'detect-driver-fault{m}',baseline,m,label) for m,label in ((1,'DRIVER_CONFIG'),(2,'DRIVER_COMPLETION'),(3,'DRIVER_IRQ'),(4,'DRIVER_STATUS'))]
    return result
def probes(args):return {'cc':[args.cc,'--version'],'verilator':[args.verilator,'--version']}
def prepare(args,out):
    build=out/'build';build.mkdir()
    cc=H.P.execute([args.cc,'-std=c11','-Wall','-Wextra','-Werror','-I'+str(HERE/'c'),'-c',str(HERE/'c/dma_driver.c'),'-o',str(build/'driver.o')],build/'c-build.log',args.build_timeout,build)
    H.P.write_json(build/'c-build.json',cc)
    if cc['error'] or cc['returncode']!=0:return cc,None
    cmd=[args.verilator,'--cc','--exe','--build','-j','2','--trace','-Wno-fatal','--prefix','Vdma_model','--top-module','apb_dma','--Mdir',str(build/'obj'),'-CFLAGS','-I'+str(HERE/'c'),'-LDFLAGS',str(build/'driver.o'),str(INPUTS[-1]),str(HERE/'harness.cpp')]
    e=H.P.execute(cmd,build/'verilator-build.log',args.build_timeout,build);H.P.write_json(build/'build.json',e);return e,[str(build/'obj/Vdma_model')]
def execute(args,out,d,case,context):
    build,binary=context
    if build['error'] or build['returncode']!=0:(d/'simulation.log').write_text('build failed\n');return dict(error='build failed',returncode=None,seconds=0,command=[])
    path=d/'vectors.txt';path.write_text(''.join(' '.join(format(v,'x') for v in row)+'\n' for row in case['operations']))
    e=H.P.execute([*binary,str(path),str(d/'wave.vcd'),str(case['fault'])],d/'simulation.log',args.timeout,d)
    wave=d/'wave.vcd'
    if not wave.is_file() or '$enddefinitions' not in wave.read_text(errors='replace'):e=dict(e,error='VCD evidence missing')
    return e
if __name__=='__main__':sys.exit(H.main(sys.modules[__name__]))

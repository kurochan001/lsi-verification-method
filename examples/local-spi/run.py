#!/usr/bin/env python3
"""Local four-mode SPI regression with independent serial timing and data checks."""
import importlib.util
from pathlib import Path
import random
import sys

HERE=Path(__file__).resolve().parent
NAME='local-spi'
TOP='spi_tb'
CONFIGS={f'mode{mode}-div{half}':dict(CPOL=mode//2,CPHA=mode%2,HALF_DIV=half)
         for mode in range(4) for half in (2,4)}
ITERATIONS={'smoke':32,'nightly':256}
SOURCES=[HERE/'rtl/spi_master.sv',HERE/'tb/spi_tb.sv']


def boundary_vectors():
    patterns=[0,255,85,1,128]
    return ([[0,value,patterns[(i+1)%5],i%2,i%3] for i,value in enumerate(patterns)]+
            [[0,0x96,0x69,1,0],[1,0x55,0xaa,0,0],[0,0x3c,0xc3,0,1]])


def random_vectors(seed,iterations):
    rng=random.Random(seed)
    return ([[int(rng.randrange(10)==0),rng.randrange(256),rng.randrange(256),rng.randrange(2),rng.randrange(4)]
             for _ in range(iterations)]+[[0,0x96,0x69,0,0]])


def make_cases(args,parameters):
    baseline=boundary_vectors()
    result=[dict(id='boundaries',vectors=baseline,mutation=args.demo_bug,expected_failure=None,category='functional')]
    for seed in range(args.seed,args.seed+(3 if args.profile=='nightly' else 1)):
        result.append(dict(id=f'random-seed{seed}',seed=seed,vectors=random_vectors(seed,args.iterations),
                           mutation=args.demo_bug,expected_failure=None,category='functional'))
    for mutation,label in ((1,'SPI_MOSI'),(2,'SPI_RX'),(3,'SPI_CS'),(4,'SPI_CLOCK')):
        result.append(dict(id=f'detect-mutation{mutation}',vectors=baseline,mutation=mutation,
                           expected_failure=label,category='mutation'))
    for case in result:
        case['counts']=dict(transfers=sum(r[0]==0 for r in case['vectors']),aborts=sum(r[0]==1 for r in case['vectors']))
    return result


if __name__=='__main__':
    spec=importlib.util.spec_from_file_location('local_runner',HERE.parent/'local-common/runner.py')
    support=importlib.util.module_from_spec(spec);spec.loader.exec_module(support)
    sys.exit(support.main(sys.modules[__name__]))

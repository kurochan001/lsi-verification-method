#!/usr/bin/env python3
"""I2C target randomized bus transactions including repeated START and stretching."""
import importlib.util
from pathlib import Path
import random
import sys
HERE=Path(__file__).resolve().parent
NAME='local-i2c';TOP='i2c_tb'
CONFIGS={f'half{h}':dict(HALF_DIV=h) for h in (8,12)}
ITERATIONS={'smoke':32,'nightly':256}
SOURCES=[HERE/'rtl/i2c_target.sv',HERE/'tb/i2c_tb.sv']
ADDRESS=0x42


def boundary_commands():
    return ([[1,ADDRESS,v,20*(i%2)] for i,v in enumerate((0,255,85,1,128))]+
            [[0,ADDRESS,0x96,0],[2,ADDRESS,0,28],[3,0x43,0,20],[4,ADDRESS,0x57,20],
             [5,ADDRESS,0xaa,20],[1,ADDRESS,0x3c,28]])


def random_commands(seed,iterations):
    rng=random.Random(seed)
    commands=[]
    for _ in range(iterations):
        mode=rng.choice((0,1,1,2,3,4,5))
        commands.append([mode,rng.choice((0x21,0x43,0x55)) if mode==3 else ADDRESS,
                         rng.randrange(256),rng.choice((0,20,28))])
    return commands+[[1,ADDRESS,0x96,20]]


def reference(commands):
    value=0;rows=[]
    counts=dict(writes=0,reads=0,target_nacks=0,resets=0,stretches=0)
    for mode,address,data,stretch in commands:
        before=value
        if mode in (0,1):value=data;counts['writes']+=1
        if mode in (1,2):counts['reads']+=1
        if mode in (3,4):counts['target_nacks']+=1
        if mode==5:value=0;counts['resets']+=1
        if stretch:counts['stretches']+={0:2,1:3,2:1,3:0,4:1,5:1}[mode]
        rows.append([mode,address,data,stretch,before,value])
    return rows,counts


def make_cases(args,parameters):
    vectors,counts=reference(boundary_commands())
    result=[dict(id='boundaries',vectors=vectors,counts=counts,mutation=args.demo_bug,
                 expected_failure=None,category='functional')]
    for seed in range(args.seed,args.seed+(3 if args.profile=='nightly' else 1)):
        rows,totals=reference(random_commands(seed,args.iterations))
        result.append(dict(id=f'random-seed{seed}',seed=seed,vectors=rows,counts=totals,
                           mutation=args.demo_bug,expected_failure=None,category='functional'))
    for m,label in ((1,'I2C_DATA'),(2,'I2C_STRETCH'),(3,'I2C_ACK'),(4,'I2C_ACK')):
        result.append(dict(id=f'detect-mutation{m}',vectors=vectors,counts=counts,mutation=m,
                           expected_failure=label,category='mutation'))
    return result


if __name__=='__main__':
    spec=importlib.util.spec_from_file_location('local_runner',HERE.parent/'local-common/runner.py')
    support=importlib.util.module_from_spec(spec);spec.loader.exec_module(support)
    sys.exit(support.main(sys.modules[__name__]))

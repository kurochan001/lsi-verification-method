#!/usr/bin/env python3
"""Local SECDED regression: exhaustive 0/1/2-bit errors and explicit limits."""
from collections import Counter
from functools import reduce, lru_cache
import importlib.util
from itertools import combinations
from operator import xor
from pathlib import Path
import random
import sys

HERE=Path(__file__).resolve().parent
NAME='local-ecc'
TOP='ecc_tb'
CONFIGS={'hamming13-8': {}}
ITERATIONS={'smoke':64,'nightly':1000}
SOURCES=[HERE/'rtl/secded.sv',HERE/'tb/ecc_tb.sv']
DATA_POSITIONS=(3,5,6,7,9,10,11,12)


def payload(word):
    return sum(((word>>(pos-1))&1)<<i for i,pos in enumerate(DATA_POSITIONS))


# Enumerate valid words from parity-check constraints, independently of RTL encoding.
CODEBOOK={payload(word):word for word in range(1<<13)
          if word.bit_count()%2==0 and
          reduce(xor,(pos for pos in range(1,13) if word & (1<<(pos-1))),0)==0}
assert len(CODEBOOK)==256


@lru_cache(maxsize=8192)
def decode(word):
    distance=min((word ^ candidate).bit_count() for candidate in CODEBOOK.values())
    if distance==0:
        return word,payload(word),0,0
    if distance==1:
        fixed=next(candidate for candidate in CODEBOOK.values() if (word ^ candidate).bit_count()==1)
        return fixed,payload(fixed),1,0
    return word,payload(word),0,1


def row(value,mask):
    encoded=CODEBOOK[value]
    received=encoded ^ mask
    return [value,received,encoded,*decode(received)]


def exhaustive_vectors():
    masks=[0]+[1<<b for b in range(13)]+[(1<<a)|(1<<b) for a,b in combinations(range(13),2)]
    return [row(value,mask) for value in range(256) for mask in masks]


def random_vectors(seed,iterations):
    rng=random.Random(seed)
    return [row(rng.randrange(256),sum(1<<b for b in rng.sample(range(13),rng.randrange(3))))
            for _ in range(iterations)]


def counts(rows):
    weights=Counter((r[1]^r[2]).bit_count() for r in rows)
    return dict(zip(('clean','single','double','triple','four'),(weights[i] for i in range(5))))


def make_cases(args,parameters):
    baseline=exhaustive_vectors()
    result=[dict(id='exhaustive',vectors=baseline,mutation=args.demo_bug,expected_failure=None,category='functional')]
    for seed in range(args.seed,args.seed+(3 if args.profile=='nightly' else 1)):
        result.append(dict(id=f'random-seed{seed}',seed=seed,vectors=random_vectors(seed,args.iterations),
                           mutation=args.demo_bug,expected_failure=None,category='functional'))
    for label,mask in (('triple-limit',7),('four-limit',CODEBOOK[1])):
        result.append(dict(id=label,vectors=[row(0,mask)],mutation=0,expected_failure=None,category='diagnostic'))
    for mutation,label in ((1,'ECC_CORRECTION'),(2,'ECC_FLAGS'),(3,'ECC_ENCODE'),(4,'ECC_FLAGS')):
        result.append(dict(id=f'detect-mutation{mutation}',vectors=baseline,mutation=mutation,
                           expected_failure=label,category='mutation'))
    for case in result:case['counts']=counts(case['vectors'])
    return result


if __name__=='__main__':
    spec=importlib.util.spec_from_file_location('local_runner',HERE.parent/'local-common/runner.py')
    support=importlib.util.module_from_spec(spec);spec.loader.exec_module(support)
    sys.exit(support.main(sys.modules[__name__]))

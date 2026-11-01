"""Specification-derived exhaustive transitions and a deliberately weak idle test."""
from itertools import product
def step(old,reset,event,clear,mask):
    bits=[False,False]
    if reset:
        for bit in range(2):bits[bit]=bool(event & (1<<bit)) or bool(old & (1<<bit)) and not bool(clear & (1<<bit))
    pending=sum(int(value)<<bit for bit,value in enumerate(bits))
    irq=int(any(value and mask & (1<<bit) for bit,value in enumerate(bits)))
    return pending,irq
def vectors(kind):
    if kind=='weak':return [[0,0,0,0,0,0]]+[[1,0,0,mask,0,0] for mask in range(4)]*8
    rows=[]
    for old,reset,event,clear,mask in product(range(4),range(2),range(4),range(4),range(4)):
        rows.extend([[0,0,0,0,0,0],[1,old,0,0,old,0],[reset,event,clear,mask,*step(old,reset,event,clear,mask)]])
    return rows

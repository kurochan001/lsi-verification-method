"""Byte-addressed operations; no RTL word splitting or address truncation is reused."""
import random


class Plan:
    def __init__(self,width=32,depth=16,big=False,seed=17):
        self.width,self.depth,self.big,self.seed=width,depth,big,seed
        self.word=width//8;self.memory=[None]*(self.word*depth);self.rows=[]

    def step(self,op,address=0,size=0,value=0,fault=0):
        data=error=transfers=0
        if op:
            legal=1<=size<=self.word and 0<=address and address+size<=len(self.memory)
            error=int(not legal)
            if legal:
                crosses=address//self.word != (address+size-1)//self.word
                transfers=1+int(crosses and not fault and op!=3)
                done=size if not (crosses and (fault or op==3)) else self.word-address%self.word
                error=int(bool(crosses and fault))
                if op in (1,3):
                    payload=list(value.to_bytes(size,'big' if self.big else 'little'))
                    self.memory[address:address+done]=payload[:done]
                elif not error:
                    assert None not in self.memory[address:address+size]
                    data=int.from_bytes(self.memory[address:address+size],'big' if self.big else 'little')
        self.rows.append([op,address,size,value,fault,data,error,transfers,self.seed])

    def read_all(self):
        for address in range(0,len(self.memory),self.word):self.step(2,address,self.word)


def stimulus(width=32,depth=16,big=False,seed=17,iterations=32):
    p=Plan(width,depth,big,seed);p.step(0)
    for address in range(0,len(p.memory),p.word):
        p.step(1,address,p.word,int.from_bytes(bytes((address+i)*13%256 for i in range(p.word)),'little'))
    for offset in range(p.word):
        for size in range(1,p.word+1):
            value=int.from_bytes(bytes((0x31+i*17)%256 for i in range(size)),'little')
            p.step(1,p.word+offset,size,value);p.step(2,p.word+offset,size);p.read_all()
    for op in (1,2):
        for address,size in ((0,0),(0,p.word+1),(len(p.memory)-1,2),(65535,p.word)):
            p.step(op,address,size,0x55);p.read_all()
    for op in (1,2):
        p.step(op,2*p.word-1,p.word,0x123456,1);p.read_all()
    p.step(3,2*p.word-1,p.word,0x654321);p.read_all()
    p.step(0);p.read_all()
    rng=random.Random(seed)
    for _ in range(iterations):
        size=rng.randint(1,p.word);address=rng.randrange(len(p.memory)-size+1)
        p.step(1,address,size,rng.getrandbits(size*8));p.step(2,address,size);p.read_all()
    return p.rows

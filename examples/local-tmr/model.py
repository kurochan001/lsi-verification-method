"""Bit-counting voter and next-state contract, independent of RTL Boolean expressions."""
class Register:
    def __init__(self,width=8):self.width=width;self.q=[0,0,0];self.attempt=0
    def vote(self):return sum((sum((q>>b)&1 for q in self.q)>=2)<<b for b in range(self.width))
    def mismatch(self):return int(len(set(self.q))!=1)
    def step(self,row):
        rst,write,data,repair,*faults=row
        if not rst:self.q=[0,0,0];self.attempt=0
        else:
            self.attempt=int(bool(repair and self.mismatch() and not write))
            if write:self.q=[data]*3
            elif self.attempt:self.q=[self.vote()]*3
            self.q=[(q^f)&((1<<self.width)-1) for q,f in zip(self.q,faults)]
        return [self.vote(),self.mismatch(),self.attempt,*self.q]

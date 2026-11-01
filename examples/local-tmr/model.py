"""Bit-counting voter and next-state contract, independent of RTL Boolean expressions."""
class Register:
    def __init__(self,width=8):self.width=width;self.q=[0,0,0];self.attempt=0
    def vote(self):return sum((sum((q>>b)&1 for q in self.q)>=2)<<b for b in range(self.width))
    def mismatch(self):return int(len(set(self.q))!=1)
    def step(self,row):
        if len(row)!=7 or any(type(v) is not int or v<0 for v in row) or any(row[i]>1 for i in (0,1,3)) or any(row[i]>=(1<<self.width) for i in (2,4,5,6)):raise ValueError('input exceeds TMR port width')
        rst,write,data,repair,*faults=row
        if not rst:self.q=[0,0,0];self.attempt=0
        else:
            self.attempt=int(bool(repair and self.mismatch() and not write))
            if write:self.q=[data]*3
            elif self.attempt:self.q=[self.vote()]*3
            self.q=[(q^f)&((1<<self.width)-1) for q,f in zip(self.q,faults)]
        return [self.vote(),self.mismatch(),self.attempt,*self.q]

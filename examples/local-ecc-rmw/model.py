"""Fault-free byte storage and independently tracked physical fault locations."""
import random


class Plan:
    def __init__(self, width, depth, seed):
        self.width, self.depth, self.seed = width, depth, seed
        self.size = width//8
        self.code_width = width + (7 if width == 64 else 6) + 1
        self.bytes = [None]*(depth*self.size)
        self.faults = [0]*depth
        self.rows = []

    def step(self, op, address=0, data=0, mask=0, fault=0):
        value=ce=ue=error=0
        if op in (1, 2, 6, 7):
            full=(1<<self.size)-1
            if op in (1, 6, 7) and mask in (0, full):
                if mask == full:
                    self.bytes[address*self.size:(address+1)*self.size]=list(data.to_bytes(self.size, 'little'))
                    self.faults[address]=0
            else:
                assert None not in self.bytes[address*self.size:(address+1)*self.size]
                count=self.faults[address].bit_count()
                assert count <= 2, 'test exceeds the SECDED fault contract'
                ce,ue=int(count==1),int(count==2)
                error=ue
                if not ue:
                    self.faults[address]=0
                    if op in (1, 6, 7):
                        payload=data.to_bytes(self.size, 'little')
                        for b in range(self.size):
                            if mask>>b&1:self.bytes[address*self.size+b]=payload[b]
                    else:value=int.from_bytes(self.bytes[address*self.size:(address+1)*self.size], 'little')
            if op==7 and not ue:self.bytes[address*self.size+1]=0xbb
        elif op==3:
            self.faults[address]^=fault
        elif op==4:
            self.faults=[f if f.bit_count()==2 else 0 for f in self.faults]
        # Reset aborts controller work, retaining the actual memory contents.
        self.rows.append([op,address,data,mask,fault,value,ce,ue,error,self.seed])

    def read_all(self):
        for address in range(self.depth):self.step(2,address)


def stimulus(width=32, depth=8, seed=17, iterations=32):
    p=Plan(width,depth,seed);p.step(0);full=(1<<p.size)-1
    for address in range(depth):p.step(1,address,((address+1)*0x123456789abcdef)&((1<<width)-1),full)
    for lane in range(p.size):
        p.step(1,1,0xa5<<(lane*8),1<<lane);p.step(2,1)
    p.step(1,1,(1<<width)-1,0);p.step(2,1)
    for bit in range(p.code_width):
        p.step(3,1,fault=1<<bit)
        p.step(1,1,bit*0x143,1<<(bit%p.size));p.step(2,1);p.step(2,1)
    for pair in (3, (1<<(p.code_width-1))|4):
        p.step(3,2,fault=pair);p.step(1,2,0x55,1);p.step(2,2)
        p.step(4);p.step(2,2);p.step(1,2,0x10203040,full);p.step(2,2)
    p.step(3,3,fault=8);p.step(4);p.step(2,3)
    p.step(3,1,fault=16);p.step(6,1,0xdeadbeef,5);p.step(2,1)
    p.step(7,1,0xaa,1);p.step(2,1)
    # Abort a pending RMW before its commit and check retention.
    p.step(5,1,0x1234,1);p.step(2,1)
    rng=random.Random(seed)
    for _ in range(iterations):
        address=rng.randrange(depth);mask=rng.randrange(1<<p.size)
        p.step(3,address,fault=1<<rng.randrange(p.code_width))
        p.step(6 if rng.randrange(2) else 1,address,rng.getrandbits(width),mask)
        p.step(2,address);p.step(2,address)
    p.read_all();p.step(0);p.read_all()
    return p.rows

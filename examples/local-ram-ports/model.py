"""Byte-array oracle: byte positions, not RTL bit slices or word-address shifts."""
import random

IDLE=(0,0,0,0,0,0)


class Memory:
    def __init__(self,width=32,depth=16,kind=2,mode=0,base=256):
        if width not in (8,16,32,64) or depth<2 or kind not in (0,1,2) or mode not in (0,1,2) or base<0 or base%(width//8):
            raise ValueError('invalid RAM configuration')
        self.width=width;self.depth=depth;self.kind=kind;self.mode=mode;self.base=base
        self.lanes=width//8;self.bytes=[None]*(depth*self.lanes);self.q=[0,0]

    def decode(self,transaction,port):
        valid,write,word,address,data,mask=transaction
        if valid not in (0,1) or write not in (0,1) or word not in (0,1) or address<0 or not 0<=data<1<<self.width or not 0<=mask<1<<self.lanes:
            raise ValueError('invalid request fields')
        capable=port==0 and (self.kind!=1 or write) or port==1 and (self.kind==2 or self.kind==1 and not write)
        position=address*self.lanes if word else address-self.base
        ok=capable and position>=0 and position+self.lanes<=len(self.bytes) and position%self.lanes==0
        return position,bool(valid and ok),bool(valid and not ok)

    def read(self,position,source=None):
        values=(source if source is not None else self.bytes)[position:position+self.lanes]
        if len(values)!=self.lanes or any(v is None for v in values):raise ValueError('comparison attempted before byte initialization')
        return int.from_bytes(bytes(values),'little')

    def store(self,source,position,data,mask):
        encoded=data.to_bytes(self.lanes,'little')
        for lane,value in enumerate(encoded):
            if mask&(1<<lane):source[position+lane]=value

    def step(self,rst=1,a=IDLE,b=IDLE):
        if rst not in (0,1):raise ValueError('reset must be binary')
        requests=(a,b);decoded=[self.decode(t,p) for p,t in enumerate(requests)]
        if not rst:
            self.q=[0,0]
            return [0,*a,*b,0,0,0,0,0,0,0,*self.q]
        positions=[d[0] for d in decoded];good=[d[1] for d in decoded];errors=[d[2] for d in decoded]
        writes=[good[p] and bool(t[1]) for p,t in enumerate(requests)]
        effective=[writes[p] and bool(t[5]) for p,t in enumerate(requests)]
        conflict=effective[0] and effective[1] and positions[0]==positions[1]
        read_collisions=[good[p] and not requests[p][1] and effective[1-p] and positions[p]==positions[1-p] for p in (0,1)]
        old=self.bytes[:]
        for p,t in enumerate(requests):
            if good[p] and not t[1]:
                if read_collisions[p] and self.mode==2:continue
                source=old[:]
                if read_collisions[p] and self.mode==1:
                    other=requests[1-p];self.store(source,positions[p],other[4],other[5])
                self.q[p]=self.read(positions[p],source)
        if not conflict:
            for p,t in enumerate(requests):
                if writes[p]:self.store(self.bytes,positions[p],t[4],t[5])
        errors=[int(e or conflict) for e in errors]
        return [1,*a,*b,a[0],b[0],*errors,int(conflict),*map(int,read_collisions),*self.q]


class Plan:
    def __init__(self,width=32,depth=16,kind=2,mode=0,base=256):
        self.memory=Memory(width,depth,kind,mode,base);self.rows=[];self.phase=0
        self.width=width;self.depth=depth;self.kind=kind;self.mode=mode;self.base=base
        self.lanes=width//8;self.full=(1<<self.lanes)-1;self.maximum=(1<<width)-1

    def step(self,a=IDLE,b=IDLE,rst=1):
        self.rows.append([*self.memory.step(rst,a,b),self.phase])

    def request(self,index,write=False,native=False,data=0,mask=None):
        return (1,int(write),int(native),index if native else self.base+index*self.lanes,data,self.full if mask is None else mask)

    def access(self,port,index,write=False,native=False,data=0,mask=None):
        t=self.request(index,write,native,data,mask);self.step(a=t) if port==0 else self.step(b=t)

    def write(self,index,data,mask=None,native=False,port=0):self.access(port,index,True,native,data,mask)

    def read(self,index,native=False,port=None):self.access((0 if self.kind==0 else 1) if port is None else port,index,False,native)

    def pattern(self,index,salt=0):
        return int.from_bytes(bytes((index*37+lane*53+salt*17+11)%256 for lane in range(self.lanes)),'little')

    def initialize(self,native=True):
        for index in range(self.depth):self.write(index,self.pattern(index),native=native)


def directed(p):
    p.step(rst=0);p.initialize();p.phase=1
    for index in range(p.depth):p.read(index)
    for index in reversed(range(p.depth)):p.read(index,native=True)
    for index in sorted({0,1,p.depth//2,p.depth-1}):
        p.write(index,p.pattern(index,3),native=True);p.read(index)
        p.write(index,p.pattern(index,7));p.read(index,native=True)
        if p.kind==2:
            p.write(index,p.pattern(index,11),native=False,port=1);p.read(index,native=True,port=0)
        p.step()
    p.phase=2;index=p.depth//2
    p.write(index,p.pattern(index,19))
    for lane in range(p.lanes):
        p.write(index,p.pattern(lane,29),mask=1<<lane)
        p.read(index,native=True);p.read((index+1)%p.depth,native=True)
    p.write(index,p.maximum,mask=0);p.read(index)
    for value in (0,p.maximum,p.pattern(index,0),sum(1<<b for b in range(0,p.width,2))):
        p.write(index,value);p.read(index,native=True)
    p.phase=3
    for bit in range((p.depth-1).bit_length()):
        index=1<<bit
        if index<p.depth:
            p.write(0,p.pattern(bit,41),native=True);p.write(index,p.pattern(bit,53),native=True)
            p.read(0);p.read(index)
    # Invalid writes are followed by a native sweep, not only an error-bit check.
    invalid=[(0,p.base+offset) for offset in range(1,p.lanes)]
    invalid += [(0,p.base-1),(0,p.base-p.lanes),(0,p.base+p.depth*p.lanes),
                (0,p.base+(1<<(p.depth-1).bit_length())*p.lanes),
                (1,p.depth),(1,1<<(p.depth-1).bit_length()),(1,0xfff)]
    for word,address in invalid:
        t=(1,1,word,address,p.maximum,p.full);p.step(a=t)
        p.step(a=(1,0,word,address,0,0)) if p.kind!=1 else p.step(b=(1,0,word,address,0,0))
        for index in range(p.depth):p.read(index,native=True)
    if p.kind==0:
        p.step(b=p.request(0,True,True,p.maximum));p.step(b=p.request(0,False,True));p.read(0)
    elif p.kind==1:
        p.step(a=p.request(0,False,True),b=p.request(0,True,True,p.maximum));p.read(0)
    p.phase=4
    if p.kind!=0:
        p.step(a=p.request(1,True,False,p.pattern(1,61)),b=p.request(2,False,True));p.read(1)
        for mask in (p.full,1,0):
            p.read(2)
            p.step(a=p.request(1,True,False,p.pattern(mask,67),mask),b=p.request(1,False,True))
            p.read(1,native=True)
        if p.kind==2:
            p.step(a=p.request(0),b=p.request(p.depth-1,native=True))
            p.step(a=p.request(1),b=p.request(1,native=True))
            p.step(a=p.request(0,True,True,p.pattern(0,71)),b=p.request(1,True,False,p.pattern(1,73)))
            p.read(0);p.read(1)
            for ma,mb in ((p.full,p.full),(1,2),(0,p.full),(0,0)):
                p.step(a=p.request(1,True,False,p.pattern(1,79),ma),b=p.request(1,True,True,p.pattern(1,83),mb))
                p.read(1,native=True)
            p.read(2,port=0)
            p.step(a=p.request(1,native=True),b=p.request(1,True,False,p.pattern(1,89),1))
            p.read(1,port=0)
    p.phase=5
    p.step(a=p.request(0,True,True,p.maximum),b=p.request(1,True,True,p.maximum),rst=0)
    for index in range(p.depth):p.read(index,native=True)
    p.step()


def stimulus(width,depth,kind,mode,base,seed,count=96):
    p=Plan(width,depth,kind,mode,base);directed(p);p.phase=6;rng=random.Random(seed)
    for _ in range(count):
        requests=[]
        for port in (0,1):
            if rng.randrange(5)==0:requests.append(IDLE);continue
            native=bool(rng.randrange(2));index=rng.randrange(depth)
            t=list(p.request(index, bool(rng.randrange(2)),native,rng.getrandbits(width),rng.randrange(1<<p.lanes)))
            if rng.randrange(9)==0:t[3]=depth+rng.randrange(8) if native else base+depth*p.lanes
            requests.append(tuple(t))
        if kind==2 and rng.randrange(6)==0:
            requests=[p.request(1,True,False,rng.getrandbits(width)),p.request(1,True,True,rng.getrandbits(width))]
        p.step(*requests)
    p.phase=7
    for index in range(depth):p.read(index,native=True);p.read(index)
    p.step()
    return p.rows

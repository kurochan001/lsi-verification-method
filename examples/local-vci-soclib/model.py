"""Independent byte-addressed RAM oracle and deterministic VCI transaction programs."""
import random
# cmd, address, cells, BE, SRCID, TRDID, PKTID, inter-flit gap, response wait, abort,
# four write words, four expected read words, expected error.
FIELDS=19
SEGMENTS=(0x1000,0x2000)
def mapped(address,b):return any(base<=address and address+b<=base+256 for base in SEGMENTS)
def oracle(ops,b):
    if b not in (4,8):raise ValueError('cell bytes must be 4 or 8')
    memory={};rows=[];counts=dict(rows=0,packets=0,commands=0,responses=0,completed=0,cancelled=0,resets=0,errors=0)
    for op in ops:
        cmd,addr,n,be,src,trd,pkt,gap,wait,abort,*data=op
        if len(op)!=14 or cmd not in (0,1,2) or not 0<=addr<2**32 or addr%b or n not in ((0,) if cmd==0 else (1,2,4)) or not 0<=be<2**b or cmd and not be or not 0<=src<16 or not 0<=trd<8 or not 0<=pkt<4 or not 0<=gap<=4 or not 0<=wait<=5 or abort not in (0,1,2) or any(type(v) is not int or not 0<=v<2**(8*b) for v in data):raise ValueError('invalid operation')
        if (n>1 or cmd==1) and be!=2**b-1:raise ValueError('burst and aligned read require full BE')
        if not cmd and any(op):raise ValueError('reset row must be zero')
        if abort==1 and not (cmd==2 and n>1) or abort==2 and cmd!=1:raise ValueError('abort point requires write packet or read response')
        expected=[0]*4;error=0
        if not cmd:memory.clear();counts['resets']+=1
        else:
            counts['packets']+=1;counts['commands']+=1 if cmd==1 or abort==1 else n
            if abort:memory.clear();counts['resets']+=1;counts['cancelled']+=1
            else:
                for i in range(n):
                    a=addr+i*b
                    if not mapped(a,b):error=1;continue
                    if cmd==2:
                        for lane in range(b):
                            if be>>lane&1:memory[a+lane]=(data[i]>>(8*lane))&255
                    else:expected[i]=sum(memory.get(a+lane,0)<<(8*lane) for lane in range(b))
                if error and n!=1:raise ValueError('error exercise is single-cell only')
                counts['completed']+=1;counts['responses']+=n if cmd==1 else 1;counts['errors']+=error
        rows.append([*op,*expected,error]);counts['rows']+=1
    return rows,counts

def make(name,b,seed=17,random_count=32):
    rng=random.Random(seed);ops=[];full=2**b-1;word=2**(8*b)-1
    def op(cmd,addr=0x1000,n=1,be=None,data=None,gap=0,wait=0,abort=0):
        values=list(data or [rng.getrandbits(8*b) for _ in range(n)])+[0]*4
        ops.append([cmd,addr,n,full if be is None else be,rng.randrange(16),rng.randrange(8),rng.randrange(4),gap,wait,abort,*values[:4]])
    def reset():ops.append([0]*14)
    reset()
    if name=='basic':
        op(2,data=[word]);op(2,be=1,data=[0x42]);op(1,wait=4)
        for base in SEGMENTS:
            for lane in range(b):op(2,base,be=1<<lane,data=[(lane+1)<<(8*lane)]);op(1,base,wait=2)
            op(2,base+256-b,data=[word^0x1234]);op(1,base+256-b)
    elif name=='packets':
        for n in (2,4):
            for base in SEGMENTS:op(2,base,n=n,gap=3);op(1,base,n=n,wait=5);op(1,base,n=1,wait=2)
    elif name=='errors':
        op(2,data=[word]);op(2,0x3000);op(1,0x3000,wait=3);op(1);op(1,0x2000)
    elif name=='reset':
        op(2,n=4);op(2,0x2000,n=4,gap=2,abort=1);op(1,n=4);op(2,data=[word]);op(1,abort=2,wait=3);op(1,n=4);op(2,0x2000);op(1,0x2000,wait=2)
    elif name=='random':
        for _ in range(random_count):
            n=rng.choice((1,2,4));a=rng.choice(SEGMENTS)+rng.randrange(256//b-n+1)*b
            cmd=rng.choice((1,2))
            op(cmd,a,n=n,be=rng.randrange(1,full+1) if cmd==2 and n==1 else full,gap=rng.randrange(5),wait=rng.randrange(6))
    else:raise ValueError('unknown scenario')
    reset();return oracle(ops,b)

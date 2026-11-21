#!/usr/bin/env python3
"""AXI4 beyond the local-axi4 subset: FIXED/WRAP, narrow and unaligned transfers, exclusive access, 256 beats."""
import importlib.util
from pathlib import Path
import random
import sys
HERE=Path(__file__).resolve().parent
NAME='local-axi4-full';TOP='axi4_full_tb';CONFIGS={'full':{}};MUTANTS=7
ITERATIONS={'smoke':60,'nightly':400}
SOURCES=[HERE/'rtl/axi4_full_ram.sv',HERE/'tb/axi4_full_tb.sv']
MEMORY=8192;PAGE=4096
FIXED,INCR,WRAP=0,1,2
OKAY,EXOKAY,SLVERR=0,1,2
IDLE,WRITE,WBEAT,READ,RBEAT,RESET=range(6)
CHAIN,W_FIRST=1,2
LABELS={1:'AXF_DATA',2:'AXF_DATA',3:'AXF_LANE',4:'AXF_EXCL',5:'AXF_LAST',6:'AXF_RESP',7:'AXF_DATA'}
# Scenario goals a row can claim. The testbench prints the name only after the row's checks passed.
TAGS=['handshake/idle-ready','wrap/start-mid','wrap/start-top','wrap/narrow','fixed/last-beat-wins','fixed/read-repeats',
      'strobe/partial','strobe/zero','strobe/outside-lanes','boundary/4k-exact','boundary/4k-cross-rejected',
      'boundary/4k-cross-by-one-byte','boundary/unaligned-last-bytes','boundary/memory-end','error/reserved-burst',
      'error/size','error/wrap-length','error/wrap-unaligned','error/fixed-length','error/wlast-early','error/wlast-missing',
      'error/no-write','excl/success','excl/second-write-fails','excl/fail-other-write','excl/adjacent-write-keeps',
      'excl/one-byte-overlap','excl/fail-mismatch','excl/other-id-attempt-keeps','excl/race-loser','excl/malformed-read',
      'excl/multi-beat','excl/reset-clears','excl/normal-read-keeps','excl/error-read','reset/vectors']


def code(tag):
    return 0 if tag is None else TAGS.index(tag)+1


def beat_bytes(addr,beats,size,burst):
    """For every beat, the ascending byte addresses it carries: from the beat address to the end of its container."""
    width=1<<size;result=[]
    for k in range(beats):
        if burst==FIXED:start=addr
        elif burst==INCR:start=addr if k==0 else (addr//width+k)*width
        else:
            total=width*beats;base=addr//total*total;start=base+(addr-base+k*width)%total
        result.append(list(range(start,(start//width+1)*width)))
    return result


def problem(addr,beats,size,burst):
    """Why the target answers SLVERR, or None for a request it carries out."""
    if size>2:return 'size'
    if burst==3:return 'burst'
    width=1<<size
    if burst==WRAP and beats not in (2,4,8,16):return 'wrap-length'
    if burst==WRAP and addr%width:return 'wrap-unaligned'
    if burst==FIXED and beats>16:return 'fixed-length'
    touched=[b for beat in beat_bytes(addr,beats,size,burst) for b in beat]
    if burst==INCR and min(touched)//PAGE!=max(touched)//PAGE:return '4k'
    return None


def exclusive_shape(addr,beats,size):
    total=beats<<size
    return beats<=16 and total&(total-1)==0 and addr%total==0


def words(seed,count):
    return [(seed+0x01030507*k)&0xffffffff for k in range(count)]


class Plan:
    """Byte memory and reservations applied in row order; it does not copy the RTL's address stepping."""
    def __init__(self):
        self.memory=bytearray(MEMORY);self.reserved={};self.rows=[]

    def _check(self,addr,beats,size,burst,ident,lock):
        if not (0<=addr<MEMORY and 1<=beats<=256 and 0<=size<=7 and 0<=burst<=3 and 0<=ident<=3 and lock in (0,1)):
            raise ValueError('request exceeds the vector fields')

    def write(self,addr,data,size=2,burst=INCR,ident=0,lock=0,strobes=None,lasts=None,gap=0,stall=0,flags=0,tag=None):
        beats=len(data);self._check(addr,beats,size,burst,ident,lock)
        reason=problem(addr,beats,size,burst)
        shape=[[]]*beats if reason else beat_bytes(addr,beats,size,burst)
        if strobes is None:strobes=[15 if reason else sum(1<<(b%4) for b in lanes) for lanes in shape]
        if lasts is None:lasts=[int(k==beats-1) for k in range(beats)]
        if len(strobes)!=beats or len(lasts)!=beats:raise ValueError('one strobe and one last flag per beat')
        key=(addr,beats,size,burst);perform=False;response=OKAY
        if reason:response=SLVERR
        elif lock:
            perform=self.reserved.get(ident)==key
            if perform:response=EXOKAY
        else:perform=True
        if lock:self.reserved.pop(ident,None)
        if perform:
            for lanes,value,strobe in zip(shape,data,strobes):
                for b in lanes:
                    if strobe>>(b%4)&1:self.memory[b]=(value>>(8*(b%4)))&255
            touched={b for lanes in shape for b in lanes}
            for other in [i for i,k in self.reserved.items() if touched & {b for lanes in beat_bytes(*k) for b in lanes}]:
                del self.reserved[other]
        if not reason and lasts!=[int(k==beats-1) for k in range(beats)]:response=SLVERR
        self.rows.append([WRITE,addr,beats,size,burst,ident,lock,response,gap,stall,flags,code(tag)])
        self.rows += [[WBEAT,value&0xffffffff,strobe,last,0,0,0,0,0,0,0,0] for value,strobe,last in zip(data,strobes,lasts)]
        return response

    def read(self,addr,beats,size=2,burst=INCR,ident=0,lock=0,stall=0,flags=0,tag=None):
        self._check(addr,beats,size,burst,ident,lock)
        reason=problem(addr,beats,size,burst);response=OKAY
        if reason:response=SLVERR
        elif lock and exclusive_shape(addr,beats,size):response=EXOKAY
        if lock:
            if response==EXOKAY:self.reserved[ident]=(addr,beats,size,burst)
            else:self.reserved.pop(ident,None)
        shape=[[]]*beats if reason else beat_bytes(addr,beats,size,burst)
        self.rows.append([READ,addr,beats,size,burst,ident,lock,response,stall,0,flags,code(tag)])
        for k,lanes in enumerate(shape):
            self.rows.append([RBEAT,sum(self.memory[b]<<(8*(b%4)) for b in lanes),sum(1<<(b%4) for b in lanes),
                              int(k==beats-1),0,0,0,0,0,0,0,0])
        return response

    def idle(self,cycles=1,tag=None):
        self.rows.append([IDLE,cycles,0,0,0,0,0,0,0,0,0,code(tag)])

    def reset(self,tag=None):
        self.memory=bytearray(MEMORY);self.reserved={}
        self.rows.append([RESET,0,0,0,0,0,0,0,0,0,0,code(tag)])

    def finish(self):
        heads=[r for r in self.rows if r[0] not in (WBEAT,RBEAT)]
        for row,following in zip(heads,heads[1:]+[[IDLE]+[0]*11]):
            if row[0] in (WRITE,READ) and row[10]&CHAIN and following[0]!=row[0]:
                raise ValueError('a chained request needs a following request of the same kind')
            if row[0]==WRITE and row[10]&CHAIN and following[10]&W_FIRST:
                raise ValueError('a request whose address is sent early cannot also send its data first')
        return self.rows


def boundary_vectors():
    p=Plan();p.idle(3,'handshake/idle-ready')
    # Plain word bursts first, so that a later mismatch points at the feature under test.
    p.write(0x100,words(0x11213141,4),ident=1);p.read(0x100,4,ident=1);p.write(0x120,words(0x51617181,1));p.read(0x120,1)
    # WRAP: write from the middle and from the top slot, then read the whole container with INCR, and the reverse.
    base=0x140
    for index,beats in enumerate((2,4,8,16)):
        total=4*beats
        p.write(base,words(0xa0a1a2a3+index,beats));p.write(base+total,words(0xeeeeeeee,1))
        p.write(base+4*(beats//2),words(0x21222324+0x10101010*index,beats),burst=WRAP,ident=index,tag='wrap/start-mid')
        p.read(base,beats+1,ident=index)
        p.write(base+total-4,words(0x61626364+index,beats),burst=WRAP,tag='wrap/start-top');p.read(base,beats+1)
        p.write(base,words(0xc1c2c3c4+index,beats))
        p.read(base+4*(beats//2),beats,burst=WRAP,stall=index%2);p.read(base+total-4,beats,burst=WRAP)
        base+=total+4
    p.write(0x240,words(0x31323334,3));p.write(0x242,[0x0000a1b2,0xc3d40000,0x0000e5f6,0x07180000],size=1,burst=WRAP,tag='wrap/narrow')
    p.read(0x240,3);p.read(0x246,4,size=1,burst=WRAP)
    p.write(0x24c,words(0x81828384,2));p.write(0x24e,[0xa1a1a1a1,0xb2b2b2b2,0xc3c3c3c3,0xd4d4d4d4],size=0,burst=WRAP,tag='wrap/narrow')
    p.read(0x24c,2);p.read(0x24f,4,size=0,burst=WRAP)
    # FIXED: every beat goes to the same container; the neighbours must keep their values.
    p.write(0x260,words(0x41424344,3));p.write(0x264,words(0x71727374,4),burst=FIXED,tag='fixed/last-beat-wins');p.read(0x260,3)
    p.read(0x264,3,burst=FIXED,tag='fixed/read-repeats');p.write(0x269,[0x55667788,0x99aabbcc],size=1,burst=FIXED);p.read(0x260,3)
    p.read(0x269,2,size=1,burst=FIXED);p.write(0x260,words(0x13579bdf,16),burst=FIXED);p.read(0x260,16,burst=FIXED)
    # Narrow and unaligned transfers. The surrounding bytes are nonzero, so a wrong lane shows.
    p.write(0x300,[0x11223344,0x55667788,0x99aabbcc,0xddeeff12,0x21436587]);p.write(0x301,words(0xa5b6c7d8,6),size=0)
    p.read(0x300,5);p.write(0x309,[0x0000fe00,0xdcba0000,0x00009876],size=1);p.read(0x300,5)
    p.write(0x30d,[0xf1e2d3c4,0x0b1a2938]);p.read(0x300,5)
    p.read(0x301,2);p.read(0x302,5,size=0);p.read(0x305,3,size=1);p.read(0x303,3,size=2,stall=1);p.read(0x30b,1,size=0)
    # Strobes: partial, none, and strobes outside the lanes of a narrow beat (this target ignores those).
    p.write(0x320,words(0x01020304,2));p.write(0x320,[0xa1a2a3a4,0xb1b2b3b4],strobes=[0b0101,0b1000],tag='strobe/partial')
    p.write(0x320,[0xffffffff,0xffffffff],strobes=[0,0],tag='strobe/zero');p.read(0x320,2)
    p.write(0x321,[0xc1c2c3c4,0xd1d2d3d4],size=0,strobes=[15,15],tag='strobe/outside-lanes');p.read(0x320,2)
    p.write(0x326,[0xe1e2e3e4],size=1,strobes=[15]);p.read(0x320,2)
    # The longest burst: 256 beats, as words and as bytes, ending exactly on the 4KiB boundary once.
    p.write(0x400,words(0x10203040,256),ident=2);p.read(0x400,256,ident=2);p.write(0x800,words(0x0000005a,256),size=0,gap=0)
    p.read(0x800,256,size=0);p.read(0x800,64);p.write(0xc00,words(0x90a0b0c0,256),tag='boundary/4k-exact');p.read(0xc00,256)
    # 4KiB boundary: the last legal burst, one beat too far, and one byte too far.
    p.write(0xff0,words(0x3c3c3c3c,4),tag='boundary/4k-exact');p.write(0x1000,words(0x4d4d4d4d,2))
    p.write(0xff4,words(0xdeadbeef,4),tag='boundary/4k-cross-rejected');p.read(0xff4,4,tag='boundary/4k-cross-rejected')
    p.read(0xff0,4);p.read(0x1000,2,tag='error/no-write')
    p.write(0xfff,[0x12000000,0x00000034],size=0,tag='boundary/4k-cross-by-one-byte');p.read(0xfff,2,size=0)
    p.write(0xffd,[0x9a8b7c00],tag='boundary/unaligned-last-bytes');p.read(0xffc,1);p.read(0xffe,1,size=1)
    p.write(0x1ff0,words(0x6e6e6e6e,4),tag='boundary/memory-end');p.read(0x1ff0,4);p.write(0x1ff4,words(0xbadbad00,4));p.read(0x1ff0,4)
    # Each rule on its own: the request breaks only that rule, and the memory keeps its value.
    p.write(0x500,words(0x7a7b7c7d,8))
    p.write(0x500,words(0xdead0001,2),burst=3,tag='error/reserved-burst');p.read(0x500,2,burst=3,tag='error/reserved-burst')
    p.write(0x500,words(0xdead0002,2),size=3,tag='error/size');p.read(0x500,2,size=3,tag='error/size')
    p.write(0x500,words(0xdead0003,3),burst=WRAP,tag='error/wrap-length');p.read(0x500,3,burst=WRAP,tag='error/wrap-length')
    p.write(0x502,words(0xdead0004,4),burst=WRAP,tag='error/wrap-unaligned');p.read(0x502,4,burst=WRAP,tag='error/wrap-unaligned')
    p.write(0x500,words(0xdead0005,17),burst=FIXED,tag='error/fixed-length');p.read(0x500,17,burst=FIXED,tag='error/fixed-length')
    p.read(0x500,8,tag='error/no-write')
    p.write(0x520,words(0x0e0e0e01,3),lasts=[0,1,0],tag='error/wlast-early');p.write(0x530,words(0x0e0e0e02,3),lasts=[0,0,0],tag='error/wlast-missing')
    p.read(0x520,3);p.read(0x530,3)
    # Exclusive access. IDs stand for masters; a reservation is per ID.
    p.write(0x600,words(0x00c0ffee,4))
    p.read(0x600,1,ident=1,lock=1);p.write(0x600,[0xe0000001],ident=1,lock=1,tag='excl/success');p.read(0x600,1)
    p.write(0x600,[0xe0000002],ident=1,lock=1,tag='excl/second-write-fails');p.read(0x600,1)
    # A failed attempt uses the reservation up as well: the correct write that follows it fails.
    p.read(0x600,1,ident=1,lock=1);p.write(0x604,[0xe0000012],ident=1,lock=1);p.write(0x600,[0xe0000013],ident=1,lock=1,tag='excl/second-write-fails')
    p.read(0x600,2)
    p.read(0x600,1,ident=1,lock=1);p.write(0x600,[0x0badf00d],ident=2);p.write(0x600,[0xe0000003],ident=1,lock=1,tag='excl/fail-other-write')
    p.read(0x600,1)
    p.read(0x604,1,ident=1,lock=1);p.write(0x600,[0xaaaa0001],ident=2);p.write(0x608,[0xaaaa0002],ident=2)
    p.write(0x603,[0x77000000],size=0,ident=3);p.write(0x608,[0x00000066],size=0,ident=3)
    p.write(0x600,words(0xf1f2f3f4,4),burst=FIXED,ident=2);p.write(0x60c,words(0xa1b1c1d1,2),burst=WRAP,ident=2);p.write(0x601,[0x5a5b5c00],ident=3)
    p.write(0x604,[0xe0000004],ident=1,lock=1,tag='excl/adjacent-write-keeps');p.read(0x600,3)
    p.read(0x604,1,ident=1,lock=1);p.write(0x607,[0x99000000],size=0,ident=2)
    p.write(0x604,[0xe0000005],ident=1,lock=1,tag='excl/one-byte-overlap');p.read(0x604,1)
    p.read(0x604,1,ident=1,lock=1);p.write(0x604,[0x00000011],size=0,ident=2)
    p.write(0x604,[0xe0000015],ident=1,lock=1,tag='excl/one-byte-overlap');p.read(0x604,1)
    p.read(0x604,1,size=0,ident=1,lock=1);p.write(0x605,[0x31323300],ident=2)
    p.write(0x604,[0x000000e5],size=0,ident=1,lock=1,tag='excl/adjacent-write-keeps');p.read(0x604,1)
    # The exclusive write must repeat the read exactly: one field different at a time.
    p.read(0x604,1,ident=1,lock=1);p.write(0x604,[0x0000e006,0xe0060000],size=1,ident=1,lock=1,tag='excl/fail-mismatch');p.read(0x604,1)
    p.read(0x604,1,ident=1,lock=1);p.write(0x608,[0xe0000016],ident=1,lock=1,tag='excl/fail-mismatch')
    p.read(0x604,2,size=1,ident=1,lock=1);p.write(0x604,[0x000000e7,0x0000e700],size=0,ident=1,lock=1,tag='excl/fail-mismatch')
    p.read(0x604,2,size=1,ident=1,lock=1);p.write(0x604,[0x0000e8e8],size=1,ident=1,lock=1,tag='excl/fail-mismatch')
    p.read(0x604,2,size=1,ident=1,lock=1);p.write(0x604,[0x0000e9e9,0xe9e90000],size=1,burst=WRAP,ident=1,lock=1,tag='excl/fail-mismatch')
    p.read(0x604,2);p.read(0x680,32,size=0,ident=1,lock=1,tag='excl/malformed-read');p.write(0x680,words(0xe00000a0,32),size=0,ident=1,lock=1);p.read(0x680,8)
    p.read(0x604,1,ident=1,lock=1);p.write(0x604,[0xe0000007],ident=3,lock=1,tag='excl/other-id-attempt-keeps')
    p.write(0x604,[0xe0000008],ident=1,lock=1,tag='excl/other-id-attempt-keeps');p.read(0x604,1)
    p.read(0x604,1,ident=1,lock=1);p.read(0x604,1,ident=2,lock=1);p.write(0x604,[0xe0000009],ident=2,lock=1,tag='excl/success')
    p.write(0x604,[0xe000000a],ident=1,lock=1,tag='excl/race-loser');p.read(0x604,1)
    p.read(0x600,3,ident=1,lock=1,tag='excl/malformed-read');p.write(0x600,words(0xe00000b0,3),ident=1,lock=1)
    p.read(0x604,2,ident=1,lock=1,tag='excl/malformed-read');p.write(0x604,words(0xe00000c0,2),ident=1,lock=1);p.read(0x600,3)
    p.read(0x640,4,ident=3,lock=1,stall=1,tag='excl/multi-beat');p.write(0x640,words(0xe00000d0,4),ident=3,lock=1,tag='excl/multi-beat')
    p.read(0x640,4);p.read(0x648,2,size=1,burst=WRAP,ident=0,lock=1);p.write(0x648,[0x0000e0e1,0xe0e20000],size=1,burst=WRAP,ident=0,lock=1,tag='excl/success')
    p.read(0x648,1)
    p.read(0x604,1,ident=1,lock=1);p.read(0x604,1,ident=1);p.read(0x600,4,ident=2);p.write(0x604,[0xe00000f0],ident=1,lock=1,tag='excl/normal-read-keeps')
    p.read(0x604,2,burst=3,ident=1,lock=1,tag='excl/error-read');p.write(0x604,[0xe00000f1],ident=1,lock=1);p.read(0x604,1)
    # Requests held while the target is busy, data before address, and stalled responses.
    p.write(0x700,words(0x0a0b0c0d,3),flags=CHAIN,gap=1,stall=2);p.write(0x70c,words(0x1a1b1c1d,1),flags=CHAIN)
    p.write(0x710,words(0x2a2b2c2d,4),burst=WRAP,stall=1);p.write(0x720,words(0x3a3b3c3d,2),flags=W_FIRST,gap=2)
    p.read(0x700,4,flags=CHAIN,stall=2);p.read(0x710,1,flags=CHAIN);p.read(0x710,4,burst=WRAP);p.read(0x720,2);p.idle(2)
    # A reset between vectors clears the memory and every reservation.
    p.read(0x604,1,ident=1,lock=1);p.reset('reset/vectors');p.write(0x604,[0xe00000ff],ident=1,lock=1,tag='excl/reset-clears')
    # The same with a request whose fields are all zero, which a reservation left valid by the reset would match.
    p.read(0x000,1,size=0,burst=FIXED,ident=0,lock=1);p.reset();p.write(0x000,[0x000000ee],size=0,burst=FIXED,ident=0,lock=1,tag='excl/reset-clears')
    p.read(0x600,4);p.read(0x100,2)
    return p.finish()


def random_vectors(seed,iterations):
    rng=random.Random(seed);p=Plan();kinds=[]
    for _ in range(iterations):
        choice=rng.random();ident=rng.randrange(4);stall=rng.choice((0,0,0,1,3));gap=rng.choice((0,0,1,2))
        if choice<0.06:
            p.idle(rng.randint(1,4));kinds.append(IDLE);continue
        if choice<0.07:
            p.reset();kinds.append(RESET);continue
        is_write=rng.random()<0.5
        if choice<0.30:  # exclusive attempts in a small pool, so that matches and collisions happen often
            size,beats=rng.choice(((2,1),(2,1),(2,2),(1,2),(0,4)));addr=0x700+4*rng.randrange(3)
            if rng.random()<0.15:addr+=rng.choice((1,2,4))
            burst=INCR;lock=int(rng.random()<0.8)
        elif choice<0.40:  # requests the target rejects
            burst,size,beats,addr=rng.choice(((3,2,2,0x100),(INCR,3,2,0x100),(WRAP,2,rng.choice((3,5,6)),0x100),(WRAP,2,4,0x102),
                                               (FIXED,2,rng.randint(17,20),0x100),(INCR,2,4,PAGE-4*rng.randint(1,3)),
                                               (INCR,0,rng.randint(2,5),PAGE-1),(INCR,2,4,MEMORY-4*rng.randint(1,3))))
            lock=0
        else:
            burst=rng.choice((FIXED,INCR,INCR,WRAP));size=rng.choice((0,1,2,2));width=1<<size;lock=0
            region=rng.choice((0x000,0x080,0x700,PAGE-0x40,PAGE,MEMORY-0x80))
            if burst==WRAP:
                beats=rng.choice((2,4,8,16));addr=region+width*rng.randrange(0x40//width)
            elif burst==FIXED:
                beats=rng.randint(1,16);addr=region+rng.randrange(0x40)
            elif rng.random()<0.04:
                beats=256;addr=rng.choice((0x000,0x400,0xc00,0x1c00))+(0 if size==2 else rng.randrange(4))
            else:
                beats=rng.randint(1,16);addr=region+rng.randrange(0x40)
                while problem(addr,beats,size,INCR):beats-=1
        if is_write:
            data=[rng.getrandbits(32) for _ in range(beats)];strobes=None
            if rng.random()<0.3:strobes=[rng.randrange(16) for _ in range(beats)]
            p.write(addr,data,size=size,burst=burst,ident=ident,lock=lock,strobes=strobes,gap=gap if beats<=16 else 0,stall=stall)
        else:
            p.read(addr,beats,size=size,burst=burst,ident=ident,lock=lock,stall=stall if beats<=16 else 0)
        kinds.append(WRITE if is_write else READ)
    heads=[r for r in p.rows if r[0] not in (WBEAT,RBEAT)]
    for row,kind,following in zip(heads,kinds,kinds[1:]+[IDLE]):
        if kind in (WRITE,READ) and following==kind and rng.random()<0.35:row[10]|=CHAIN
    for row,previous in zip(heads,[[IDLE]+[0]*11]+heads[:-1]):
        if row[0]==WRITE and not (previous[0]==WRITE and previous[10]&CHAIN) and rng.random()<0.1:row[10]|=W_FIRST
    return p.finish()


def counts(rows):
    heads=[r for r in rows if r[0] in (WRITE,READ)]
    return dict(writes=sum(r[0]==WRITE for r in rows),reads=sum(r[0]==READ for r in rows),
                write_beats=sum(r[0]==WBEAT for r in rows),read_beats=sum(r[0]==RBEAT for r in rows),
                slverr=sum(r[7]==SLVERR for r in heads),exokay=sum(r[7]==EXOKAY for r in heads))


def make_cases(args,parameters):
    baseline=boundary_vectors()
    result=[dict(id='boundaries',vectors=baseline,mutation=args.demo_bug,category='functional',expected_failure=None)]
    for seed in range(args.seed,args.seed+(3 if args.profile=='nightly' else 1)):
        result.append(dict(id=f'random-seed{seed}',vectors=random_vectors(seed,args.iterations),mutation=args.demo_bug,
                           category='functional',expected_failure=None))
    for mutation,label in LABELS.items():
        result.append(dict(id=f'detect-mutation{mutation}',vectors=baseline,mutation=mutation,category='mutation',expected_failure=label))
    for case in result:case['counts']=counts(case['vectors'])
    return result


if __name__=='__main__':
    spec=importlib.util.spec_from_file_location('local_runner',HERE.parent/'local-common/runner.py')
    support=importlib.util.module_from_spec(spec);spec.loader.exec_module(support)
    sys.exit(support.main(sys.modules[__name__]))

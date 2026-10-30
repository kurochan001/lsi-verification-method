"""Bit-pattern stimuli, independent expected results, and protocol diagnostics."""
from fractions import Fraction
import random
import reference as R
import reference_mp as M
from vectors import block


def beat(codes, width, scale=0):
    return R.pack(codes, width) | (scale << 128)


def bdp_vectors(seed, iterations, exhaustive=False):
    rng = random.Random(seed)
    rows = []
    def series(mode, pairs, scales=None, gap=0, stall=0, mismatch=False, wrong_mode=False, scale16=False):
        accumulator = 0
        pending = None
        sticky_error = 0
        for i, (a, b) in enumerate(pairs):
            debug = None
            if mode == M.FP4:
                a_bits, b_bits = a, b
                accumulator = R.accumulate(accumulator, a, b, i == 0)
            elif mode == M.FP16:
                a_bits = beat(a, 16, int(scale16))
                b_bits = beat(b, 16)
                accumulator = M.add32(accumulator, M.dot16(a, b))
                if scale16:
                    sticky_error |= 2
            else:
                sa, sb = (scales or [(127,127)]*len(pairs))[i]
                a_bits, b_bits = beat(a,8,sa), beat(b,8,sb)
                if i % 2 == 0:
                    pending = (a, b, sa, sb)
                else:
                    aa, bb, first_sa, first_sb = pending
                    if mismatch:
                        a_bits ^= 1 << 128
                    if a_bits>>128 != first_sa or b_bits>>128 != first_sb:
                        sticky_error |= 1
                    accumulator = M.add32(accumulator, M.dot8(aa+a, bb+b, first_sa, first_sb))
                    debug = M.coefficient8(aa+a, bb+b)
            driven_mode = mode
            if wrong_mode and i > 0:
                driven_mode = M.FP8 if mode != M.FP8 else M.FP16
                sticky_error |= 2
            rows.append([driven_mode, int(i==0), int(i==len(pairs)-1), a_bits, b_bits,
                         accumulator, sticky_error, gap, stall if i==len(pairs)-1 else 0,
                         debug or 0, int(debug is not None)])
    for a in range(16):
        for b in range(16):
            series(M.FP4, [(block(a),block(b))], stall=(a+b)%3)
    series(M.FP4, [(block(2,139),block(2,139)),(block(),block()),(block(10,139),block(2,139))],gap=2,stall=4)
    # Every E4M3 encoding is observed alone, including both NaNs and signed zeros.
    for a in range(256):
        series(M.FP8,[([a]+[0]*15,[0x38]+[0]*15),([0]*16,[0]*16)],gap=a%3,stall=a%4)
    if exhaustive:
        for a in range(256):
            for b in range(256):
                series(M.FP8,[([a]+[0]*15,[b]+[0]*15),([0]*16,[0]*16)])
    for sa, sb in [(0,0),(254,254),(255,0),(0,255),(63,64),(64,64),(190,190)]:
        series(M.FP8,[([0x7E]*16,[0xFE]*16),([0x7E]*16,[0xFE]*16)],scales=[(sa,sb)]*2,gap=3,stall=5)
    series(M.FP8,[([0x38]*16,[0x38]*16),([0x38]*16,[0x38]*16)],gap=3,mismatch=True)
    series(M.FP8,[([0x38]*16,[0x38]*16),([0x38]*16,[0x38]*16)],scales=[(127,127),(255,127)],gap=4)
    series(M.FP8,[([0x38]*16,[0x38]*16),([0x38]*16,[0x38]*16)],scales=[(255,127),(127,127)],gap=4)
    # A four-block stream exercises the FP8 partial sum and metadata with no bubbles.
    series(M.FP8,[([0x38+i]*16,[0x38]*16) for i in range(8)],stall=3)
    # Two distinct FP32 rounding points: block1=2^-24, block2=1+2^-24.
    # Rounding each block and then accumulating gives 1; one final round gives 1+2^-23.
    series(M.FP8,[([1]+[0]*15,[1]+[0]*15),([0]*16,[0]*16),
                  ([0x50,1]+[0]*14,[0x50,1]+[0]*14),([0]*16,[0]*16)],
           scales=[(124,124)]*4,gap=2,stall=3)
    series(M.FP8,[([0x38]*16,[0x38]*16)]*4,gap=1,wrong_mode=True)
    series(M.FP4,[(block(2),block(2))]*3,gap=1,wrong_mode=True)
    for odd in [0,1]:
        for small in [3,4,5]:
            series(M.FP8,[([0x7E,0x38,0x38]+[0]*13,[0x7E,small,8 if odd else 0]+[0]*13),([0]*16,[0]*16)])
    half_special = [0,0x8000,1,0x8001,0x03FF,0x0400,0x3C00,0xBC00,0x7BFF,0xFBFF,0x7C00,0xFC00,0x7E00,0x7C01]
    for a in half_special:
        for b in half_special:
            series(M.FP16,[([a]+[0]*7,[b]+[0]*7)],stall=(a+b)%3)
    series(M.FP16,[([0x3C00]*8,[0x3C00]*8)]*4,gap=2,wrong_mode=True)
    series(M.FP16,[([0x3C00]*8,[0x3C00]*8)],scale16=True)
    # A fixed balanced tree yields +0 here; a left fold would yield -1.
    series(M.FP16,[([0x6C00,0x3C00,0xEC00,0xBC00]+[0]*4,[0x6C00,0x3C00,0x6C00,0x3C00]+[0]*4)])
    for _ in range(iterations):
        mode = rng.randrange(3)
        if mode == M.FP4:
            pairs=[((rng.randrange(256)<<128)|rng.getrandbits(128),(rng.randrange(256)<<128)|rng.getrandbits(128)) for _ in range(rng.randrange(1,9))]
            series(mode,pairs,gap=rng.randrange(3),stall=rng.randrange(5))
        elif mode == M.FP8:
            pairs=[];scales=[]
            for _ in range(rng.randrange(1,5)):
                sa,sb=rng.randrange(256),rng.randrange(256)
                for _ in range(2):
                    pairs.append(([rng.randrange(256) for _ in range(16)],[rng.randrange(256) for _ in range(16)]))
                    scales.append((sa,sb))
            series(mode,pairs,scales,gap=rng.randrange(3),stall=rng.randrange(5))
        else:
            pairs=[([rng.randrange(65536) for _ in range(8)],[rng.randrange(65536) for _ in range(8)]) for _ in range(rng.randrange(1,9))]
            series(mode,pairs,gap=rng.randrange(3),stall=rng.randrange(5))
    return rows


def matrix_result(a_rows, b_cols, mode):
    output=[]
    for aa in a_rows:
        for bb in b_cols:
            accumulator=0
            for i in range(len(aa)):
                if mode==M.FP4:
                    accumulator=R.accumulate(accumulator,aa[i],bb[i],i==0)
                elif mode==M.FP16:
                    accumulator=M.add32(accumulator,M.dot16(R.unpack(aa[i],8,16),R.unpack(bb[i],8,16)))
                elif i%2:
                    av=R.unpack(aa[i-1],16,8)+R.unpack(aa[i],16,8)
                    bv=R.unpack(bb[i-1],16,8)+R.unpack(bb[i],16,8)
                    accumulator=M.add32(accumulator,M.dot8(av,bv,aa[i-1]>>128,bb[i-1]>>128))
            output.append(accumulator)
    return R.pack(output,32)


def gemm_vectors(seed, iterations, rows=4, cols=4, kblocks=4):
    rng=random.Random(seed)
    commands=[[4,3,0,0,0,1]]
    def execute(mode,aa,bb,error=0,reset=False):
        for op,mat in enumerate([aa,bb]):
            for lane,stream in enumerate(mat):
                for index,data in enumerate(stream):
                    commands.append([op,mode,lane*len(stream)+index,data,0,0])
        result=matrix_result(aa,bb,mode)
        commands.append([3 if reset else 2,mode,0,0,result,error])
        # A rejected start must preserve the previous result, including nonzero C.
        commands.append([4,3,0,0,result,1])
    def random_matrix(mode,lanes):
        streams=[]
        width={M.FP4:4,M.FP8:8,M.FP16:16}[mode]
        count=128//width
        for _ in range(lanes):
            stream=[]
            for _ in range(kblocks):
                scale=0 if mode==M.FP16 else rng.randrange(110,145)
                for _ in range({M.FP4:1,M.FP8:2,M.FP16:4}[mode]):
                    if mode==M.FP16:
                        codes=[(rng.randrange(2)<<15)|(rng.randrange(1,31)<<10)|rng.randrange(1024) for _ in range(count)]
                    else:
                        codes=[rng.randrange(16 if mode==M.FP4 else 256) for _ in range(count)]
                        if mode==M.FP8: codes=[c if c&127!=127 else c-1 for c in codes]
                    stream.append(beat(codes,width,scale))
            streams.append(stream)
        return streams
    for mode in [M.FP4,M.FP8,M.FP16,M.FP4]:
        width={M.FP4:4,M.FP8:8,M.FP16:16}[mode];count=128//width
        unit={M.FP4:2,M.FP8:0x38,M.FP16:0x3C00}[mode]
        aa=[]
        for r in range(rows):
            stream=[]
            for index in range(32*kblocks//count):
                stream.append(beat([unit if index*count+i==r else 0 for i in range(count)],width,0 if mode==M.FP16 else 127))
            aa.append(stream)
        bb=random_matrix(mode,cols)
        execute(mode,aa,bb,reset=True)
        for _ in range(iterations):execute(mode,random_matrix(mode,rows),random_matrix(mode,cols))
        if mode==M.FP8:
            aa=random_matrix(mode,rows);bb=random_matrix(mode,cols);aa[0][1]^=1<<128
            execute(mode,aa,bb,error=1)
        if mode==M.FP16:
            aa=random_matrix(mode,rows);bb=random_matrix(mode,cols);aa[0][0]|=1<<128
            execute(mode,aa,bb,error=1)
    return commands


def fp16_midpoint_samples(exhaustive=False):
    """FP32 neighbors and FP16 expectations derived from adjacent codes, not cast16."""
    if exhaustive:
        lower_codes=range(0x7BFF)  # All 31,743 adjacent nonnegative finite pairs.
    else:
        lower_codes=sorted({0,1,0x03FE,0x03FF,0x0400,0x0401,0x7BFE} |
                           {e*1024-1 for e in range(2,31)})
    for lower in lower_codes:
        midpoint=R.fp32((M.decode(lower,M.FP16)+M.decode(lower+1,M.FP16))/2)
        for delta,expected in [(-1,lower),(0,lower+(lower%2)),(1,lower+1)]:
            yield midpoint+delta,expected
            yield (midpoint+delta)|0x80000000,expected|0x8000


def encoder_vectors(seed, iterations, exhaustive=False):
    rows=[]
    def add(mode, values, stall=0,outputs=None):
        if outputs is None:outputs=M.encode(values,mode)
        rows.append([mode,R.pack(values,32),len(outputs),R.pack(outputs,136),stall])
    for mode in range(3):
        add(mode,[0x80000000,1,0x807FFFFF]+[0]*29,3)
        for special in [0x7FC00001,0x7F800000,0xFF800000]:
            add(mode,[special]+[0x3F800000]*31)
    # All FP16 codes round trip through exact FP32. NaNs are canonicalized.
    if exhaustive:
        for start in range(0,65536,32):
            add(M.FP16,[M.half_to_fp32(code) for code in range(start,start+32)])
    else:
        for start in [0,0x03E0,0x3BE0,0x7BE0,0x7C00,0x8000,0xFBE0,0xFC00]:
            add(M.FP16,[M.half_to_fp32(code) for code in range(start,start+32)],2)
    # All E4M3 finite midpoints, their neighboring FP32 encodings, and both signs.
    samples=[]
    for a,b in zip(M.FP8_POSITIVE,M.FP8_POSITIVE[1:]):
        midpoint=R.fp32((a+b)/2)
        for delta in [-1,0,1]:
            samples.extend([midpoint+delta,(midpoint+delta)|0x80000000])
    for offset in range(0,len(samples),31):
        values=[0x43E00000]+samples[offset:offset+31] # 448 anchors scale=127.
        add(M.FP8,values+[0]*(32-len(values)),2)
    for value in [Fraction(1,4),Fraction(3,4),Fraction(5,4),Fraction(7,4),Fraction(5,2),Fraction(7,2),Fraction(5)]:
        add(M.FP4,[0x40800000,R.fp32(value),R.fp32(-value)]+[0]*29,1)
    # Round trips do not exercise rounding. Check midpoint neighborhoods separately.
    samples=list(fp16_midpoint_samples(exhaustive))
    for offset in range(0,len(samples),32):
        chunk=samples[offset:offset+32]
        values=[bits for bits,_ in chunk]+[0]*(32-len(chunk))
        codes=[code for _,code in chunk]+[0]*(32-len(chunk))
        add(M.FP16,values,2,[R.pack(codes[i:i+8],16) for i in range(0,32,8)])
    # The finite/Inf boundary has no finite upper endpoint for a midpoint pair.
    for value in [Fraction(65520)]:
        bits=R.fp32(value)
        add(M.FP16,[bits-1,bits,bits+1,(bits-1)|0x80000000,bits|0x80000000,(bits+1)|0x80000000]+[0]*26,3)
    rng=random.Random(seed)
    for _ in range(iterations):
        for mode in range(3):
            add(mode,[rng.getrandbits(32) for _ in range(32)],rng.randrange(4))
    return rows

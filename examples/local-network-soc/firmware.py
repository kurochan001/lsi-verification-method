"""RV32I software builds ARP/UDP replies, computes both checksums and CRC-32, then DMA sends them.

Golden ROM bytes are used only after construction, to compare every output byte.
RX/TX RAM uses one byte per 32-bit word so the tiny CPU only needs LW/SW.
"""
import importlib.util
from pathlib import Path
import sys
HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('network_isa',HERE.parent/'local-riscv-iss/iss.py')
ISA=importlib.util.module_from_spec(spec);sys.modules[spec.name]=ISA;spec.loader.exec_module(ISA)
SUCCESS=0x600d600d;FAILURE=0xbad0bad0


def li(r,value):
    value&=0xffffffff;low=ISA.sext(value,12)
    return [('lui',r,(value-low)>>12),('addi',r,r,low)]


def rejected_accesses(scenario,max_frame,replies):
    """APB accesses that scenario 3 expects to end in PSLVERR, so the bench can match the exact count."""
    return len(idle_rejects(max_frame))+1+5+2+6*replies if scenario==3 else 0


def idle_rejects(max_frame):
    # Each write fails on one term: bad RX/TX pointers, RX_RELEASE and TX_START before RUN, then read-only registers.
    span=4*max_frame
    return ((8,0x1001),(8,0xfffffffc),(8,0xffc),(8,0x2000-span+4),(8,0x1400-span+4),
            (12,0x1402),(12,0x1000),(12,0xffc),(12,0x2000-span+4),(12,0x1000+span-4),
            (0,5),(0,3),(0,8),(0x34,1),(0x10,1),(0x18,1),(0x1c,1),(0x20,1),(0x24,1),(0x2c,1))


def source(replies,max_frame=128,drops=0,scenario=0,rx_base=0x1000,tx_base=0x1400):
    if max_frame not in (96,128) or scenario not in (0,1,2,3,4,5) or type(drops) is not int or not 0<=drops<=2047 or len(replies)>7 or any(not 64<=len(r)<=max_frame or any(type(v) is not int or not 0<=v<=255 for v in r) for r in replies):raise ValueError('invalid firmware contract')
    p=[('jal',0,'main'),'handler:',('lw',28,4,12),('or',31,31,28),('sw',28,4,12),('mret',),'main:']
    if rx_base%4 or tx_base%4 or not 0x1000<=min(rx_base,tx_base) or max(rx_base,tx_base)>0x2000-4*max_frame or abs(rx_base-tx_base)<4*max_frame:raise ValueError('invalid buffer placement')
    p+=li(10,rx_base)+li(11,tx_base)+li(12,0x40000000)+li(13,0x800)+li(16,0x1ffc)
    p+=[('lw',3,0,0),*li(2,0x0140006f),('bne',3,2,'fail'),('addi',31,0,0),('addi',1,0,4),('csrrw',0,'mtvec',1),*li(1,0x800),('csrrw',0,'mie',1),('csrrsi',0,'mstatus',8)]
    if scenario==3:
        # Bad address/alignment/overlap, release without ownership, undefined and read-only registers.
        for offset,value in idle_rejects(max_frame):
            p+=li(1,value)+[('sw',1,offset,12)]
        p+=[('lw',1,0x34,12),('lw',1,8,12),('bne',1,10,'fail'),('lw',1,12,12),('bne',1,11,'fail')]
        # Exactly adjacent and top-of-RAM placements are legal, then the defaults return.
        for offset,value,base in ((8,0x1400-4*max_frame,10),(8,0x2000-4*max_frame,10),(12,0x1000+4*max_frame,11),(12,0x2000-4*max_frame,11)):
            p+=li(1,value)+[('sw',1,offset,12),('lw',2,offset,12),('bne',2,1,'fail'),('sw',base,offset,12)]
        p+=[('addi',1,0,64),('sw',1,20,12)]
    if (rx_base,tx_base)!=(0x1000,0x1400):p+=[('sw',10,8,12),('sw',11,12,12)]
    p+=[('addi',1,0,8 if scenario==5 else 7),('sw',1,40,12),('addi',1,0,1),('sw',1,0,12),('addi',14,0,0),('addi',9,0,len(replies))]
    if scenario==3:
        # Running but not yet owning: start, release, stop and pointer writes are all refused.
        for value in (3,5,0):p+=[('addi',1,0,value),('sw',1,0,12)]
        p+=[('sw',10,8,12),('sw',11,12,12)]
        # Owned while RX DMA is still writing: neither TX_START nor RX_RELEASE may be taken.
        p+=['rx_window:',('lw',1,4,12),('andi',1,1,64),('beq',1,0,'rx_window'),('addi',1,0,3),('sw',1,0,12),('addi',1,0,5),('sw',1,0,12)]
    if scenario==4:
        # Keep writing W1C over each DROP event; the event must still be recorded on a same-edge collision.
        p+=['race:',('addi',1,0,8),('sw',1,4,12),('sw',1,4,12),('sw',1,4,12),('lw',1,24,12),('addi',2,0,drops),('bltu',1,2,'race')]
    if scenario==1:p+=wait('rx_error',4)+[('lw',1,36,12),('addi',2,0,1),('bne',1,2,'fail'),('jal',0,'release_finish')]
    p+=['next:',('beq',14,9,'finish')]+wait('rx_wait',1)+[('andi',31,31,-2),('lw',17,44,12),('lw',18,16,12)]
    # Zero output, including Ethernet padding and any odd UDP checksum padding byte.
    p+=[('addi',1,11,0),('addi',2,0,max_frame),'zero:',('sw',0,0,1),('addi',1,1,4),('addi',2,2,-1),('bne',2,0,'zero')]
    serial=0
    def copy(src,dst,count):
        nonlocal serial
        serial+=1;label='copy'+str(serial)
        return [('addi',1,10,4*src),('addi',2,11,4*dst),('addi',3,0,count),label+':',('lw',4,0,1),('sw',4,0,2),('addi',1,1,4),('addi',2,2,4),('addi',3,3,-1),('bne',3,0,label)]
    def put(offset,data):
        return [instruction for i,b in enumerate(data) for instruction in [('addi',1,0,b),('sw',1,4*(offset+i),11)]]
    p+=copy(6,0,6)+put(6,bytes.fromhex('020000000001'))+copy(12,12,2)
    p+=[('addi',1,0,1),('bne',17,1,'udp')]
    p+=put(14,bytes.fromhex('0001080006040002'))+put(22,bytes.fromhex('020000000001c0000201'))+copy(22,32,10)
    p+=[('addi',19,0,60),('jal',0,'crc')]
    p+=['udp:']+put(14,bytes((0x45,0)))+copy(16,16,6)+put(22,bytes((64,17)))+put(26,bytes((192,0,2,1)))+copy(26,30,4)+copy(36,34,2)+copy(34,36,2)+copy(38,38,2)
    p+=[('lw',21,152,10),('slli',21,21,8),('lw',1,156,10),('or',21,21,1),('addi',3,21,-8),('addi',1,10,168),('addi',2,11,168),('beq',3,0,'payload_done'),
        'payload:',('lw',4,0,1),('sw',4,0,2),('addi',1,1,4),('addi',2,2,4),('addi',3,3,-1),('bne',3,0,'payload'),'payload_done:']
    # Reusable inline one's-complement sum. Pointers advance by 8 RAM bytes per network word.
    def sum_words(label,offset,count=None,initial=None):
        q=[('addi',22,11,4*offset)]
        q+=[('addi',23,0,count)] if count is not None else [('addi',23,21,1),('srli',23,23,1)]
        q+=[('addi',25,0,0)] if initial is None else [('addi',25,initial,0)]
        q+=[label+':',('lw',24,0,22),('slli',24,24,8),('lw',26,4,22),('or',24,24,26),('add',25,25,24),('addi',22,22,8),('addi',23,23,-1),('bne',23,0,label)]
        return q
    def finish_sum(offset,udp=False):
        q=li(27,0xffff)
        for _ in range(2):q+=[('srli',26,25,16),('and',25,25,27),('add',25,25,26)]
        q+=[('xori',25,25,-1),('and',25,25,27)]
        if udp:q+=[('bne',25,0,'nonzero'),('addi',25,27,0),'nonzero:']
        return q+[('srli',24,25,8),('sw',24,4*offset,11),('andi',24,25,255),('sw',24,4*(offset+1),11)]
    p+=sum_words('ip_sum',14,10)+finish_sum(24)
    p+=sum_words('pseudo_sum',26,4)+[('addi',25,25,17),('add',25,25,21),('addi',5,25,0)]
    p+=sum_words('udp_sum',34,initial=5)+finish_sum(40,True)
    p+=[('addi',19,21,34),('addi',1,0,60),('bgeu',19,1,'crc'),('addi',19,0,60)]
    p+=['crc:',('addi',22,11,0),('addi',23,19,0),('addi',25,0,-1),*li(27,0xedb88320),'crc_byte:',('lw',24,0,22),('xor',25,25,24),('addi',26,0,8),
        'crc_bit:',('andi',24,25,1),('srli',25,25,1),('beq',24,0,'crc_shift'),('xor',25,25,27),'crc_shift:',('addi',26,26,-1),('bne',26,0,'crc_bit'),
        ('addi',22,22,4),('addi',23,23,-1),('bne',23,0,'crc_byte'),('xori',25,25,-1)]
    for i in range(4):p+=[('andi',24,25,255),('sw',24,4*i,22),('srli',25,25,8)]
    p+=[('addi',20,19,4),('lw',1,0,13),('bne',1,20,'fail'),('addi',13,13,4),('addi',22,11,0),('addi',23,20,0),
        'compare:',('lw',1,0,13),('lw',2,0,22),('bne',1,2,'fail'),('addi',13,13,4),('addi',22,22,4),('addi',23,23,-1),('bne',23,0,'compare')]
    if scenario==3:
        # Short and long TX_LEN are refused, as is TX_START together with RX_RELEASE.
        for length in (63,max_frame+1):p+=[('addi',1,0,length),('sw',1,20,12),('addi',1,0,3),('sw',1,0,12)]
    p+=[('sw',20,20,12)]
    if scenario==3:p+=[('addi',1,0,7),('sw',1,0,12)]
    p+=[('addi',1,0,3),('sw',1,0,12)]
    if scenario==3:
        # TX running: a second start, a release and a new TX_LEN are refused.
        p+=[('sw',1,0,12),('addi',1,0,5),('sw',1,0,12),('sw',20,20,12)]
    p+=wait('tx_wait',4 if scenario==2 else 2)
    if scenario==2:p+=[('lw',1,36,12),('addi',2,0,2),('bne',1,2,'fail'),('jal',0,'release_finish')]
    p+=[('andi',31,31,-3),('addi',1,0,5),('sw',1,0,12),('addi',14,14,1),('jal',0,'next'),
        'release_finish:',('addi',1,0,5),('sw',1,0,12),
        'finish:',('lw',1,24,12),('addi',2,0,drops),('bltu',1,2,'finish'),('bne',1,2,'fail'),
        # A DMA error must not reach the completion counters.
        ('lw',1,28,12),('addi',2,0,0 if scenario==1 else len(replies)),('bne',1,2,'fail'),('lw',1,32,12),('addi',2,0,0 if scenario in (1,2) else len(replies)),('bne',1,2,'fail')]
    if scenario==0 and drops and not replies:
        # Mask 7 leaves DROP out of the IRQ: the status bit is set, no handler ran, and W1C clears it.
        p+=[('lw',1,4,12),('andi',1,1,8),('beq',1,0,'fail'),('bne',31,0,'fail'),('addi',1,0,8),('sw',1,4,12),('lw',1,4,12),('andi',1,1,8),('bne',1,0,'fail')]
    if scenario==5:
        # Mask 8 unmasks DROP alone: the handler must run and clear it, within a bounded wait.
        p+=[('addi',2,0,64),'drop_wait:',('lw',1,4,12),('andi',1,1,8),('beq',1,0,'drop_done'),('addi',2,2,-1),('bne',2,0,'drop_wait'),('jal',0,'fail'),
            'drop_done:',('andi',1,31,8),('beq',1,0,'fail')]
    p+=[*li(1,SUCCESS),('sw',1,0,16),('ebreak',),
        'fail:',*li(1,FAILURE),('sw',1,0,16),('ebreak',)]
    return p


def compare_pc(replies,max_frame=128,drops=0,scenario=0,rx_base=0x1000,tx_base=0x1400):
    """Address of the compare loop, so the bench counts that loop and not every read of the TX buffer."""
    return ISA.label_addresses(source(replies,max_frame,drops,scenario,rx_base,tx_base))['compare']


def program(replies,max_frame=128,drops=0,scenario=0,rx_base=0x1000,tx_base=0x1400):
    binary=ISA.assemble(source(replies,max_frame,drops,scenario,rx_base,tx_base))
    if len(binary)>512:raise ValueError('code overlaps golden table')
    binary += [0x13]*(512-len(binary))
    for r in replies:binary += [len(r),*r]
    if len(binary)>1024:raise ValueError('ROM table capacity exceeded')
    return binary


def wait(label,flag):
    q=[label+':',('andi',1,31,flag),('beq',1,0,label)]
    if flag!=4:q+=[('andi',1,31,4),('bne',1,0,'fail')]
    return q

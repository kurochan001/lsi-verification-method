"""Build a small ROM program using the repository's RV32I assembler, without a cross compiler.

The CPU initializes both buffers, programs APB CSRs, runs unrelated RAM accesses while
DMA is active, handles the real external interrupt, and checks every successful pixel.
"""
import importlib.util
from pathlib import Path
import sys

HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('image_firmware_isa',HERE.parent/'local-riscv-iss/iss.py')
ISA=importlib.util.module_from_spec(spec);sys.modules[spec.name]=ISA;spec.loader.exec_module(ISA)
SUCCESS=0x600d600d
FAILURE=0xbad0bad0
SENTINEL=0xa5a50000


def li(register,value):
    value &= 0xffffffff
    low=ISA.sext(value,12)
    return [('lui',register,(value-low)>>12),('addi',register,register,low)]


REJECTED_APB=7  # scenario 4: SHAPE write, undefined write and read, and four writes refused while busy
REJECTED_AHB=4  # scenario 4: ROM write, unmapped stores above RAM and past the APB window, unmapped load


def buffers(scenario,pixels):
    """SRC and DST. Scenarios 7 and 8 end the frame pair exactly at the top of RAM, with the buffers touching."""
    span=4*pixels
    return {7:(0x2000-2*span,0x2000-span),8:(0x2000-span,0x2000-2*span)}.get(scenario,(0x1000,0x1400))


def program(frames,expected,scenario=0,shape=None):
    if scenario not in range(10) or not frames or len(frames)!=len(expected) or any(not a or len(a)!=len(b) or len(a)!=len(frames[0]) for a,b in zip(frames,expected)) or any(type(v) is not int or not 0<=v<=255 for frame in [*frames,*expected] for v in frame):
        raise ValueError('complete source and expected frames required')
    p=[('jal',0,'main'),'handler:',('lw',28,4,12),('addi',31,28,0),('sw',28,4,12),('mret',),'main:']
    source,destination=buffers(scenario,len(frames[0]))
    p+=li(10,source)+li(11,destination)+li(12,0x40000000)+li(15,0x1800)+li(16,0x1ffc)
    p+=[('lw',3,0,0),*li(2,0x0140006f),('bne',3,2,'fail')]
    p+=[('addi',1,0,4),('csrrw',0,'mtvec',1),*li(1,0x800),('csrrw',0,'mie',1),('csrrsi',0,'mstatus',8)]
    p+=[('addi',1,0,1),('sw',1,16,12)]  # IRQ mask
    if scenario==4:
        p+=[('sw',0,0,0)]  # read-only ROM must reject this, without changing code
        # Unmapped AHB addresses, then APB offsets the register map does not accept.
        for address in (0x2000,0x40000100):p+=li(3,address)+[('sw',0,0,3)]
        p+=li(3,0x2000)+[('lw',2,0,3),('sw',0,20,12),('sw',0,24,12),('lw',2,24,12)]
        if shape:p+=[('lw',2,20,12),*li(3,shape[1]<<16|shape[0]),('bne',2,3,'fail')]
    for frame,(pixels,golden) in enumerate(zip(frames,expected)):
        p+=li(2,SENTINEL)
        for i,pixel in enumerate(pixels):p+=[('addi',1,0,pixel),('sw',1,4*i,10),('sw',2,4*i,11)]
        p+=[('sw',10,8,12),('sw',11,12,12)]
        if scenario==3 and frame==0:
            # With IRQ_MASK off the rejected start only sets STATUS: no handler runs until the mask returns.
            p+=[('addi',31,0,0),('sw',0,16,12),*li(1,0x1001),('sw',1,8,12),('addi',1,0,1),('sw',1,0,12),
                'masked:',('lw',1,4,12),('andi',1,1,4),('beq',1,0,'masked'),('bne',31,0,'fail'),('addi',1,0,4),('sw',1,4,12),('addi',1,0,1),('sw',1,16,12)]
            for bad,bad_source,bad_destination in INVALID:
                p+=[('addi',31,0,0),*li(1,bad_source),('sw',1,8,12),*li(1,bad_destination),('sw',1,12,12),('addi',1,0,1),('sw',1,0,12)]
                p+=wait('invalid_'+bad,4)
            p+=[('sw',10,8,12),('sw',11,12,12)]
        p+=[('addi',31,0,0),('addi',1,0,1),('sw',1,0,12)]
        if scenario==4:
            # Configuration cannot be changed while busy; the old value must survive.
            p+=li(1,0xdead0000)+[('sw',1,8,12),('lw',2,8,12),('bne',2,10,'fail'),('sw',1,12,12),('lw',2,12,12),('bne',2,11,'fail'),
                ('sw',0,16,12),('lw',2,16,12),('addi',3,0,1),('bne',2,3,'fail'),('addi',1,0,1),('sw',1,0,12)]
        p+=wait(f'frame{frame}',4 if scenario in (1,2) else 2,scenario==9)
        if scenario not in (1,2):
            for i,pixel in enumerate(golden):p+=[('lw',4,4*i,11),*li(5,SENTINEL|pixel),('bne',4,5,'fail')]
    p+=li(1,SUCCESS)+[('sw',1,0,16),('ebreak',),'fail:',*li(1,FAILURE),('sw',1,0,16),('ebreak',)]
    binary=ISA.assemble(p)
    if len(binary)>1024:raise ValueError('ROM capacity exceeded')
    return binary


# Each start fails on one term of the check: alignment, RAM range low and high, or overlap either way.
INVALID=(('unaligned',0x1001,0x1400),('range',0x1ffc,0x1400),('overlap',0x1000,0x1000),
         ('dst_unaligned',0x1000,0x1402),('dst_range',0x1000,0x1ffc),('src_low',0xffc,0x1800),('dst_low',0x1800,0xffc),
         ('overlap_src',0x1000,0x1004),('overlap_dst',0x1004,0x1000))


def wait(label,status,slow=False):
    """Count in RAM until the handler has run. A slow wait also loads SHAPE through APB, so that the
    interrupt arrives while a load is still on the bus: the handler must still read STATUS, not that answer."""
    return [label+':',*([('lw',8,20,12)] if slow else []),('lw',6,0,15),('addi',6,6,1),('sw',6,0,15),('beq',31,0,label),
            ('addi',7,0,status),('bne',31,7,'fail')]

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


def program(frames,expected,scenario=0):
    if scenario not in range(7) or not frames or len(frames)!=len(expected) or any(not a or len(a)!=len(b) or len(a)!=len(frames[0]) for a,b in zip(frames,expected)) or any(type(v) is not int or not 0<=v<=255 for frame in [*frames,*expected] for v in frame):
        raise ValueError('complete source and expected frames required')
    p=[('jal',0,'main'),'handler:',('lw',28,4,12),('addi',31,28,0),('sw',28,4,12),('mret',),'main:']
    p+=li(10,0x1000)+li(11,0x1400)+li(12,0x40000000)+li(15,0x1800)+li(16,0x1ffc)
    p+=[('lw',3,0,0),*li(2,0x0140006f),('bne',3,2,'fail')]
    p+=[('addi',1,0,4),('csrrw',0,'mtvec',1),*li(1,0x800),('csrrw',0,'mie',1),('csrrsi',0,'mstatus',8)]
    p+=[('addi',1,0,1),('sw',1,16,12)]  # IRQ mask
    if scenario==4:p+=[('sw',0,0,0)]  # read-only ROM must reject this, without changing code
    for frame,(pixels,golden) in enumerate(zip(frames,expected)):
        p+=li(2,SENTINEL)
        for i,pixel in enumerate(pixels):p+=[('addi',1,0,pixel),('sw',1,4*i,10),('sw',2,4*i,11)]
        p+=[('sw',10,8,12),('sw',11,12,12)]
        if scenario==3 and frame==0:
            for bad,source,destination in (('unaligned',0x1001,0x1400),('range',0x1ffc,0x1400),('overlap',0x1000,0x1000)):
                p+=[('addi',31,0,0),*li(1,source),('sw',1,8,12),*li(1,destination),('sw',1,12,12),('addi',1,0,1),('sw',1,0,12)]
                p+=wait('invalid_'+bad,4)
            p+=[('sw',10,8,12),('sw',11,12,12)]
        p+=[('addi',31,0,0),('addi',1,0,1),('sw',1,0,12)]
        if scenario==4:
            # Configuration cannot be changed while busy; the old value must survive.
            p+=li(1,0xdead0000)+[('sw',1,8,12),('lw',2,8,12),('bne',2,10,'fail'),('addi',1,0,1),('sw',1,0,12)]
        p+=wait(f'frame{frame}',4 if scenario in (1,2) else 2)
        if scenario not in (1,2):
            for i,pixel in enumerate(golden):p+=[('lw',4,4*i,11),*li(5,SENTINEL|pixel),('bne',4,5,'fail')]
    p+=li(1,SUCCESS)+[('sw',1,0,16),('ebreak',),'fail:',*li(1,FAILURE),('sw',1,0,16),('ebreak',)]
    binary=ISA.assemble(p)
    if len(binary)>1024:raise ValueError('ROM capacity exceeded')
    return binary


def wait(label,status):
    return [label+':',('lw',6,0,15),('addi',6,6,1),('sw',6,0,15),('beq',31,0,label),
            ('addi',7,0,status),('bne',31,7,'fail')]

"""A small RV32I assembler, an instruction set simulator (ISS) and program generators.

The ISS executes one instruction at a time as the RISC-V Unprivileged ISA defines it and
knows nothing about the pipeline. It runs from address 0 until EBREAK and records, for
each retired instruction, what the core's retirement port must show. Loads and stores of
bytes, halfwords and words must be aligned, and instruction and data memories are separate.
"""
from dataclasses import dataclass

MASK = 0xffffffff
EBREAK = 0x00100073
DATA_WORDS = 256   # data memory, word addressed by bits 9:2
BASE = 64          # byte address held in x10 by every program: data words 16 to 31
OPS = {  # name: (format, opcode, funct3, funct7)
    'lui': ('U', 0x37, 0, 0), 'auipc': ('U', 0x17, 0, 0), 'jal': ('J', 0x6f, 0, 0), 'jalr': ('I', 0x67, 0, 0),
    'beq': ('B', 0x63, 0, 0), 'bne': ('B', 0x63, 1, 0), 'blt': ('B', 0x63, 4, 0), 'bge': ('B', 0x63, 5, 0),
    'bltu': ('B', 0x63, 6, 0), 'bgeu': ('B', 0x63, 7, 0), 'lw': ('I', 0x03, 2, 0), 'sw': ('S', 0x23, 2, 0),
    'addi': ('I', 0x13, 0, 0), 'slti': ('I', 0x13, 2, 0), 'sltiu': ('I', 0x13, 3, 0), 'xori': ('I', 0x13, 4, 0),
    'ori': ('I', 0x13, 6, 0), 'andi': ('I', 0x13, 7, 0), 'slli': ('I', 0x13, 1, 0), 'srli': ('I', 0x13, 5, 0),
    'srai': ('I', 0x13, 5, 0x20), 'add': ('R', 0x33, 0, 0), 'sub': ('R', 0x33, 0, 0x20), 'sll': ('R', 0x33, 1, 0),
    'slt': ('R', 0x33, 2, 0), 'sltu': ('R', 0x33, 3, 0), 'xor': ('R', 0x33, 4, 0), 'srl': ('R', 0x33, 5, 0),
    'sra': ('R', 0x33, 5, 0x20), 'or': ('R', 0x33, 6, 0), 'and': ('R', 0x33, 7, 0), 'ebreak': ('E', 0x73, 0, 0),
    # sub-word accesses, after the original 32 so that their numbers stay the same
    'lb': ('I', 0x03, 0, 0), 'lh': ('I', 0x03, 1, 0), 'lbu': ('I', 0x03, 4, 0), 'lhu': ('I', 0x03, 5, 0),
    'sb': ('S', 0x23, 0, 0), 'sh': ('S', 0x23, 1, 0),
    # machine-mode traps and CSRs (Zicsr), used when traps are enabled
    'ecall': ('E', 0x73, 0, 0), 'mret': ('E', 0x73, 0, 0x18),
    'csrrw': ('C', 0x73, 1, 0), 'csrrs': ('C', 0x73, 2, 0), 'csrrc': ('C', 0x73, 3, 0),
    'csrrwi': ('C', 0x73, 5, 0), 'csrrsi': ('C', 0x73, 6, 0), 'csrrci': ('C', 0x73, 7, 0)}
NAMES = list(OPS)
WORD_ONLY = NAMES[:32]  # the instructions of the ISS example, which uses word accesses only
LOAD_STORE = NAMES[:38]  # adds the byte and halfword accesses
ECALL, MRET = 0x00000073, 0x30200073
IRQ_WORD = DATA_WORDS - 1  # with traps, bit 0 of this data word drives the external interrupt line
CSRS = {'mstatus': 0x300, 'mie': 0x304, 'mtvec': 0x305, 'mscratch': 0x340, 'mepc': 0x341, 'mcause': 0x342,
        'mtval': 0x343, 'mip': 0x344}
# Coverage tags carried to the bench with each retired instruction.
TAGS = ['raw/distance-1', 'raw/distance-2', 'raw/distance-3', 'load/use', 'load/store-data', 'jalr/forwarded-base',
        'branch/taken', 'branch/not-taken', 'branch/forwarded-operand', 'branch/backward', 'x0/write-then-read',
        'halt/ebreak']


def name_of(insn):
    """Mnemonic of an encoded instruction, for the every-instruction goal; None if unknown."""
    special = {EBREAK: 'ebreak', ECALL: 'ecall', MRET: 'mret'}
    if insn in special:
        return special[insn]
    op, f3, f7 = insn & 0x7f, insn >> 12 & 7, insn >> 25
    for name, (fmt, opcode, funct3, funct7) in OPS.items():
        if opcode == op and fmt != 'E' and (fmt in 'UJ' or (funct3 == f3 and (
                funct7 == f7 or not (fmt == 'R' or (op == 0x13 and f3 == 5))))):
            return name
    return None


def sext(value, bits):
    value &= (1 << bits) - 1
    return value - (1 << bits) if value >> (bits - 1) else value


def signed(x):
    return sext(x, 32)


def encode(item, pc, labels):
    name, *args = item
    if name == 'word':  # any instruction word, such as an illegal one
        return args[0] & MASK
    if name in ('ecall', 'mret'):
        return ECALL if name == 'ecall' else MRET
    fmt, opcode, f3, f7 = OPS[name]

    def value(x):  # an immediate, a label, ('off', target, base) or ('abs', target) for JALR
        if isinstance(x, tuple):
            return labels[x[1]] - (labels[x[2]] if x[0] == 'off' else 0)
        return labels[x] - pc if isinstance(x, str) else x
    if fmt == 'R':
        rd, rs1, rs2 = args
        return f7 << 25 | rs2 << 20 | rs1 << 15 | f3 << 12 | rd << 7 | opcode
    if fmt == 'I':
        rd, rs1, imm = (args[0], args[2], value(args[1])) if opcode in (0x03, 0x67) else (args[0], args[1], args[2])
        if name in ('slli', 'srli', 'srai'):
            imm = f7 << 5 | imm
        return (imm & 0xfff) << 20 | rs1 << 15 | f3 << 12 | rd << 7 | opcode
    if fmt == 'S':
        rs2, imm, rs1 = args
        return (imm >> 5 & 0x7f) << 25 | rs2 << 20 | rs1 << 15 | f3 << 12 | (imm & 0x1f) << 7 | opcode
    if fmt == 'B':
        rs1, rs2, target = args
        off = value(target)
        return ((off >> 12 & 1) << 31 | (off >> 5 & 0x3f) << 25 | rs2 << 20 | rs1 << 15 | f3 << 12 |
                (off >> 1 & 0xf) << 8 | (off >> 11 & 1) << 7 | opcode)
    if fmt == 'U':
        rd, imm = args
        return (imm & 0xfffff) << 12 | rd << 7 | opcode
    if fmt == 'C':  # (rd, CSR name, rs1 or 5-bit immediate)
        rd, csr, source = args
        return CSRS[csr] << 20 | source << 15 | f3 << 12 | rd << 7 | opcode
    if fmt == 'J':
        rd, target = args
        off = value(target)
        return (off >> 20 & 1) << 31 | (off >> 1 & 0x3ff) << 21 | (off >> 11 & 1) << 20 | (off >> 12 & 0xff) << 12 | rd << 7 | opcode
    return EBREAK


def label_addresses(program):
    labels, address = {}, 0
    for item in program:
        if isinstance(item, str):
            labels[item[:-1]] = address
        else:
            address += 4
    return labels


def assemble(program):
    """Two passes: label addresses, then words. Labels are strings ending in ':'."""
    labels = label_addresses(program)
    words = []
    for item in program:
        if not isinstance(item, str):
            words.append(encode(item, 4 * len(words), labels))
    return words


@dataclass
class Retired:
    pc: int
    insn: int
    rd: int          # destination written, 0 when nothing is written
    wdata: int       # value written, 0 when nothing is written
    kind: int        # 0 none, 1 load, 2 store
    addr: int = 0
    data: int = 0    # loaded or stored word
    result: int = 0  # value computed even when rd is x0
    taken: bool = False  # a branch whose condition held
    tags: int = 0


def alu(f3, alt, a, b):
    shamt = b & 31
    return [(a - b if alt else a + b) & MASK, a << shamt & MASK, int(signed(a) < signed(b)), int(a < b), a ^ b,
            signed(a) >> shamt & MASK if alt else a >> shamt, a | b, a & b][f3]


_SPEC = None


def legal_rv32i(insn):
    """Whether a word is in the RV32I table of riscv-opcodes (the decoder example's specification)."""
    global _SPEC
    if _SPEC is None:
        import importlib.util
        from pathlib import Path
        path = Path(__file__).resolve().parent.parent / 'local-riscv-decoder/generate.py'
        spec = importlib.util.spec_from_file_location('rv32i_opcodes', path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        _SPEC = (module, module.table())
    return _SPEC[0].decode(_SPEC[1], insn) is not None


class Machine:
    """Machine-mode CSRs with the fields the core implements; other bits read as fixed values."""

    def __init__(self):
        self.mie = self.mpie = self.meie = 0
        self.tvec = self.epc = self.scratch = self.cause = self.tval = 0

    def read(self, address, line):
        return {0x300: 3 << 11 | self.mpie << 7 | self.mie << 3, 0x304: self.meie << 11, 0x305: self.tvec,
                0x340: self.scratch, 0x341: self.epc, 0x342: self.cause, 0x343: self.tval, 0x344: line << 11}[address]

    def write(self, address, value):
        if address == 0x300:
            self.mie, self.mpie = value >> 3 & 1, value >> 7 & 1
        elif address == 0x304:
            self.meie = value >> 11 & 1
        elif address == 0x305:
            self.tvec = value & ~3 & MASK
        elif address == 0x340:
            self.scratch = value
        elif address == 0x341:
            self.epc = value & ~3 & MASK
        elif address == 0x342:
            self.cause = value
        elif address == 0x343:
            self.tval = value

    def enter(self, pc, cause, tval):
        self.epc, self.cause, self.tval, self.mpie, self.mie = pc, cause, tval, self.mie, 0
        return self.tvec


def execute(words, data, limit=100000, traps=False):
    """Run from address 0 to EBREAK. With traps, illegal instructions, ECALL and misaligned
    accesses trap to mtvec, CSR instructions and MRET work, and an interrupt pending on the line
    with mstatus.MIE and mie.MEIE set is taken before the next instruction."""
    regs, pc, mem, trace = [0] * 32, 0, list(data), []
    m = Machine()

    def trap(record, cause, tval):
        record.kind, record.addr, record.data = 3, cause, tval
        trace.append(record)
        return m.enter(record.pc, cause, tval)
    for _ in range(limit):
        insn = words[pc >> 2]
        if traps and mem[IRQ_WORD] & 1 and m.mie and m.meie:
            pc = trap(Retired(pc, insn, 0, 0, 0), 0x80000000 | 11, 0)
            continue
        op, rd, f3, rs1, rs2, f7 = insn & 0x7f, insn >> 7 & 31, insn >> 12 & 7, insn >> 15 & 31, insn >> 20 & 31, insn >> 25
        a, b = regs[rs1], regs[rs2]
        imm_i = sext(insn >> 20, 12)
        imm_s = sext(f7 << 5 | rd, 12)
        imm_b = sext((insn >> 31) << 12 | (insn >> 7 & 1) << 11 | (insn >> 25 & 0x3f) << 5 | (insn >> 8 & 0xf) << 1, 13)
        imm_j = sext((insn >> 31) << 20 | (insn >> 12 & 0xff) << 12 | (insn >> 20 & 1) << 11 | (insn >> 21 & 0x3ff) << 1, 21)
        nxt, value, record = (pc + 4) & MASK, None, Retired(pc, insn, 0, 0, 0)
        if insn == EBREAK:
            trace.append(record)
            return trace
        if traps:
            csr = op == 0x73 and f3 & 3 and (insn >> 20) in CSRS.values()
            if not (csr or insn == MRET or legal_rv32i(insn)):
                pc = trap(record, 2, insn)
                continue
            if insn == ECALL:
                pc = trap(record, 11, 0)
                continue
            if insn == MRET:
                m.mie, m.mpie = m.mpie, 1
                trace.append(record)
                pc = m.epc
                continue
            if csr:
                address, source = insn >> 20, (rs1 if f3 >= 5 else a)
                old = m.read(address, mem[IRQ_WORD] & 1)
                if f3 & 3 == 1 or rs1:
                    m.write(address, [None, source, old | source, old & ~source & MASK][f3 & 3])
                if rd:
                    regs[rd], record.rd, record.wdata = old, rd, old
                record.result = old
                trace.append(record)
                pc = nxt
                continue
            if op in (0x03, 0x23):
                address = (a + (imm_i if op == 0x03 else imm_s)) & MASK
                size = 1 << (f3 & 3)
                if address % size:
                    pc = trap(record, 4 if op == 0x03 else 6, address)
                    continue
        if op == 0x37:
            value = insn & 0xfffff000
        elif op == 0x17:
            value = (pc + (insn & 0xfffff000)) & MASK
        elif op == 0x6f:
            value, nxt = nxt, (pc + imm_j) & MASK
        elif op == 0x67:
            value, nxt = nxt, (a + imm_i) & MASK & ~1
        elif op == 0x63:
            record.taken = bool([a == b, a != b, None, None, signed(a) < signed(b), signed(a) >= signed(b), a < b, a >= b][f3])
            if record.taken:
                nxt = (pc + imm_b) & MASK
        elif op == 0x03:
            record.addr = (a + imm_i) & MASK
            size, shift = 1 << (f3 & 3), 8 * (record.addr & 3)
            value = mem[check(record.addr, size)] >> shift & (1 << 8 * size) - 1
            if f3 < 4 and size < 4:
                value = sext(value, 8 * size) & MASK
            record.kind, record.data = 1, value
        elif op == 0x23:
            record.addr = (a + imm_s) & MASK
            size, shift = 1 << f3, 8 * (record.addr & 3)
            field = (1 << 8 * size) - 1
            index = check(record.addr, size)
            mem[index] = mem[index] & ~(field << shift) & MASK | (b & field) << shift
            record.kind, record.data = 2, b & field
        elif op == 0x13:
            value = alu(f3, f3 == 5 and f7 == 0x20, a, imm_i & MASK)
        elif op == 0x33:
            value = alu(f3, f7 == 0x20, a, b)
        else:
            raise ValueError(f'unsupported instruction {insn:08x} at {pc:#x}')
        if value is not None:
            record.result = value
            if rd:
                regs[rd], record.rd, record.wdata = value, rd, value
        trace.append(record)
        pc = nxt
    raise ValueError('program did not reach EBREAK')


def check(addr, size=4):
    if addr % size or not 0 <= addr >> 2 < DATA_WORDS:
        raise ValueError(f'data address {addr:#x} is unaligned for {size} bytes or outside the data memory')
    return addr >> 2


def sources(insn):
    op, rs1, rs2 = insn & 0x7f, insn >> 15 & 31, insn >> 20 & 31
    if op in (0x63, 0x23, 0x33):
        return {rs1, rs2}
    return {rs1} if op in (0x67, 0x03, 0x13) else set()


def tag(trace):
    """Program-order hazards of each retired instruction, independent of the pipeline."""
    bit = {name: 1 << i for i, name in enumerate(TAGS)}
    for i, r in enumerate(trace):
        op, srcs = r.insn & 0x7f, sources(r.insn)
        prev = trace[i - 1] if i else None
        for reg in srcs - {0}:
            for distance in (1, 2, 3):
                if i >= distance and trace[i - distance].rd == reg:
                    r.tags |= bit[f'raw/distance-{distance}']
                    break
        if prev and prev.kind == 1 and prev.rd and prev.rd in srcs:
            r.tags |= bit['load/use']
            if op == 0x23 and r.insn >> 20 & 31 == prev.rd:
                r.tags |= bit['load/store-data']
        if op == 0x67 and r.insn >> 15 & 31 in {t.rd for t in trace[max(0, i - 2):i]} - {0}:
            r.tags |= bit['jalr/forwarded-base']
        if op == 0x63:
            r.tags |= bit['branch/taken' if r.taken else 'branch/not-taken']
            if prev and prev.rd and prev.rd in srcs:
                r.tags |= bit['branch/forwarded-operand']
            if r.taken and trace[i + 1].pc < r.pc:
                r.tags |= bit['branch/backward']
        if (prev and prev.insn >> 7 & 31 == 0 and prev.result and prev.insn & 0x7f in (0x13, 0x33, 0x37, 0x17)
                and 0 in srcs):
            r.tags |= bit['x0/write-then-read']
        if r.insn == EBREAK:
            r.tags |= bit['halt/ebreak']
    return trace


def directed_program():
    """Every instruction, every forwarding distance, the load-use bubble, flushes and x0."""
    return [
        ('addi', 10, 0, BASE),
        # edge values: x1 = 0x80000000, x2 = -1, x3 = 0x7fffffff (distance 2 from x1), x4 = 1, x5 = 31
        ('lui', 1, 0x80000), ('addi', 2, 0, -1), ('addi', 3, 1, -1), ('addi', 4, 0, 1), ('addi', 5, 0, 31),
        # register-register operations; shift amounts come from the low five bits
        ('add', 6, 1, 2), ('sub', 7, 1, 4), ('sll', 8, 4, 5), ('slt', 9, 1, 3), ('sltu', 11, 1, 3),
        ('xor', 12, 2, 3), ('srl', 13, 1, 5), ('sra', 14, 1, 5), ('or', 15, 1, 4), ('and', 16, 2, 3),
        ('sll', 17, 4, 2), ('sra', 18, 2, 4),
        # immediates, including the most negative one and shifts by 0 and 31
        ('addi', 19, 3, -2048), ('slti', 20, 1, -1), ('sltiu', 21, 4, -1), ('xori', 22, 2, 0x555),
        ('ori', 23, 0, -1), ('andi', 24, 2, 0x7ff), ('slli', 25, 4, 31), ('srli', 26, 1, 31), ('srai', 27, 1, 31),
        ('srai', 28, 1, 0), ('lui', 29, 0xfffff), ('auipc', 30, 0x12345),
        # forwarding at distances 1, 2 and 3 on either operand; the younger producer wins
        ('addi', 6, 0, 5), ('add', 7, 6, 6), ('addi', 8, 0, 9), ('addi', 9, 0, 1), ('sub', 11, 9, 8),
        ('addi', 12, 0, 3), ('addi', 13, 0, 4), ('addi', 14, 0, 6), ('add', 15, 13, 12),
        ('addi', 6, 0, 1), ('addi', 6, 0, 2), ('add', 16, 0, 6),
        # writes to x0 are discarded and never forwarded
        ('addi', 0, 4, 7), ('add', 17, 0, 4), ('lw', 0, 0, 10), ('add', 18, 0, 0),
        # loads and stores: load-use, load to store data, store then load, load to branch
        ('sw', 3, 0, 10), ('lw', 19, 0, 10), ('add', 20, 19, 4),
        ('lw', 21, 4, 10), ('sw', 21, 8, 10), ('lw', 22, 8, 10), ('beq', 22, 21, 'eq1'), ('addi', 23, 0, 99), 'eq1:',
        # a value forwarded from WB while a load waits in MEM (waits are attached to these accesses)
        ('addi', 24, 0, 77), ('lw', 25, 12, 10), ('add', 26, 24, 4),
        ('addi', 27, 0, 55), ('sw', 4, 16, 10), ('add', 28, 27, 27),
        # each branch taken and not taken, operands forwarded; the skipped instruction must not retire
        ('addi', 6, 0, -3), ('blt', 6, 4, 'b1'), ('addi', 7, 0, 99), 'b1:',
        ('bltu', 6, 4, 'b2'), ('addi', 7, 0, 1), 'b2:',
        ('bge', 4, 6, 'b3'), ('addi', 7, 0, 99), 'b3:',
        ('bgeu', 4, 6, 'b4'), ('addi', 8, 0, 1), 'b4:',
        ('bne', 6, 4, 'b5'), ('addi', 7, 0, 99), 'b5:',
        ('beq', 6, 4, 'b6'), ('beq', 0, 0, 'b6'), ('addi', 7, 0, 99), 'b6:',
        ('blt', 4, 6, 'b7'), ('bge', 6, 4, 'b7'), ('bltu', 4, 6, 'b8'), ('addi', 7, 0, 99), 'b7:', 'b8:',
        # jumps: JAL links, JALR takes a base just written and clears bit 0 of the target
        ('jal', 1, 'j1'), ('addi', 7, 0, 99), ('addi', 7, 0, 98), 'j1:',
        'here:', ('auipc', 5, 0), ('jalr', 2, ('off', 'j2', 'here'), 5), ('addi', 7, 0, 99), 'j2:',
        'here2:', ('auipc', 5, 0), ('addi', 5, 5, 1), ('jalr', 3, ('off', 'j3', 'here2'), 5), ('addi', 7, 0, 99), 'j3:',
        ('lw', 6, 20, 10), ('jalr', 0, ('abs', 'j4'), 6), ('addi', 7, 0, 99), 'j4:',
        # a loop that branches backward three times
        ('addi', 6, 0, 3), 'loop:', ('addi', 6, 6, -1), ('bne', 6, 0, 'loop'),
        ('ebreak',)]


def directed_data():
    data = [0] * DATA_WORDS
    for i in range(16, 32):
        data[i] = (0x9e3779b9 * i) & MASK
    data[21] = 0  # word 20 bytes after BASE holds the jump target used by the last JALR
    return data


def random_program(rng, count, loops=False, subword=False):
    """Forward branches and jumps only, so every program ends; x10 keeps the data base. With
    loops, some counted loops (x11 counts down, a backward BNE) are added; nothing else writes
    x11 and nothing jumps into a loop, so they end too. With subword, loads and stores also use
    bytes and halfwords, always aligned."""
    pool, recent, program, due = [1, 2, 3, 4, 5, 6, 7, 8, 9], [], [('addi', 10, 0, BASE)], {}

    def dest():
        r = 0 if rng.random() < 0.04 else rng.choice(pool)
        recent.append(r)
        return r

    def src():
        if recent and rng.random() < 0.5:
            return rng.choice(recent[-3:])
        return 0 if rng.random() < 0.05 else rng.choice(pool)

    def imm():
        return rng.choice((0, 1, -1, 2047, -2048, rng.randrange(-2048, 2048)))

    def label(skip):
        name = f'L{len(program)}'
        due.setdefault(len(program) + skip, []).append(name + ':')
        return name
    for r in pool:
        program.append(('addi', r, 0, imm()))
    while len(program) - sum(isinstance(x, str) for x in program) < count:
        for position in sorted(p for p in due if p <= len(program)):  # labels whose skip has passed
            program.extend(due.pop(position))
        if loops and rng.random() < 0.06:
            top = f'P{len(program)}'
            program += [('addi', 11, 0, rng.randrange(2, 6)), top + ':']
            for _ in range(rng.randrange(1, 4)):
                program.append((rng.choice(['add', 'sub', 'xor', 'or', 'and']), dest(), src(), src()))
            program += [('addi', 11, 11, -1), ('bne', 11, 0, top)]
            continue
        roll = rng.random()
        if roll < 0.3:
            program.append((rng.choice(['add', 'sub', 'sll', 'slt', 'sltu', 'xor', 'srl', 'sra', 'or', 'and']), dest(), src(), src()))
        elif roll < 0.5:
            name = rng.choice(['addi', 'slti', 'sltiu', 'xori', 'ori', 'andi', 'slli', 'srli', 'srai'])
            program.append((name, dest(), src(), rng.choice((0, 1, 31, rng.randrange(32))) if name[1:3] in ('ll', 'rl', 'ra') else imm()))
        elif roll < 0.62:
            name, size = rng.choice((('lw', 4), ('lh', 2), ('lhu', 2), ('lb', 1), ('lbu', 1))) if subword else ('lw', 4)
            program.append((name, dest(), size * rng.randrange(64 // size), 10))
        elif roll < 0.72:
            name, size = rng.choice((('sw', 4), ('sh', 2), ('sb', 1))) if subword else ('sw', 4)
            program.append((name, src(), size * rng.randrange(64 // size), 10))
        elif roll < 0.86:
            program.append((rng.choice(['beq', 'bne', 'blt', 'bge', 'bltu', 'bgeu']), src(), src(), label(rng.randrange(1, 4))))
        elif roll < 0.89:
            program.append(('jal', dest(), label(rng.randrange(1, 4))))
        elif roll < 0.93:
            base = rng.choice(pool)
            here = f'B{len(program)}'
            program += [here + ':', ('auipc', base, 0)]
            recent.append(base)
            if rng.random() < 0.5:  # one instruction between, which leaves the base alone
                program.append(('addi', rng.choice([r for r in pool if r != base]), src(), imm()))
            target = label(rng.randrange(2, 4))
            program.append(('jalr', dest(), ('off', target, here), base))
        else:
            program.append((rng.choice(['lui', 'auipc']), dest(), rng.randrange(1 << 20)))
    for position in sorted(due):
        program.extend(due[position])
    program.append(('ebreak',))
    return program


def random_data(rng):
    return [rng.getrandbits(32) for _ in range(DATA_WORDS)]

"""Place the sections of one RV32 relocatable object at fixed addresses and apply its relocations.

This stands in for a linker: the fixed toolchain has an assembler (llvm-mc) but no ld.lld. It
handles one object file, the five sections the test environment uses and the relocation types
listed in RELOCATIONS. Anything else is an error, never a silent skip.
"""
import struct

SECTIONS = (('.text.init', 4), ('.tohost', 0x1000), ('.text', 0x1000), ('.data', 0x1000), ('.bss', 16))
SHT_PROGBITS, SHT_SYMTAB, SHT_RELA, SHT_NOBITS, SHT_REL = 1, 2, 4, 8, 9
SHF_ALLOC = 2
R_32, R_BRANCH, R_JAL, R_PCREL_HI20, R_PCREL_LO12_I, R_PCREL_LO12_S, R_HI20, R_LO12_I, R_LO12_S = 1, 16, 17, 23, 24, 25, 26, 27, 28
RELOCATIONS = {R_32: 'R_RISCV_32', R_BRANCH: 'R_RISCV_BRANCH', R_JAL: 'R_RISCV_JAL', R_PCREL_HI20: 'R_RISCV_PCREL_HI20',
               R_PCREL_LO12_I: 'R_RISCV_PCREL_LO12_I', R_PCREL_LO12_S: 'R_RISCV_PCREL_LO12_S', R_HI20: 'R_RISCV_HI20',
               R_LO12_I: 'R_RISCV_LO12_I', R_LO12_S: 'R_RISCV_LO12_S'}
FAULTS = ('lo12-off-by-four',)  # deliberate errors of this linker, for the negative checks


class LinkError(ValueError):
    pass


def _fits(value, bits):
    return -(1 << bits - 1) <= value < 1 << bits - 1


def link(obj, base=0, limit=1 << 16, fault=None):
    """Return (image bytes from base, symbol addresses, relocation counts by name)."""
    if fault is not None and fault not in FAULTS:
        raise LinkError('unknown fault ' + fault)
    if obj[:4] != b'\x7fELF' or obj[4] != 1 or obj[5] != 1:
        raise LinkError('not a 32-bit little-endian ELF file')
    kind, machine = struct.unpack_from('<HH', obj, 16)
    if kind != 1 or machine != 243:
        raise LinkError('not a relocatable RISC-V object')
    shoff, = struct.unpack_from('<I', obj, 32)
    shentsize, shnum, shstrndx = struct.unpack_from('<HHH', obj, 46)
    sec = [struct.unpack_from('<IIIIIIIIII', obj, shoff + i * shentsize) for i in range(shnum)]

    def text(table, offset):
        start = sec[table][4] + offset
        return obj[start:obj.index(b'\0', start)].decode()
    names = [text(shstrndx, s[0]) for s in sec]
    known = [name for name, _ in SECTIONS]
    for i, s in enumerate(sec):
        if s[2] & SHF_ALLOC and s[5] and names[i] not in known:
            raise LinkError('section not handled: ' + names[i])
        if s[1] == SHT_REL:
            raise LinkError('REL relocation sections are not handled')
    address, image, cursor = {}, bytearray(), base
    for name, align in SECTIONS:
        if names.count(name) > 1:
            raise LinkError('section appears twice: ' + name)
        if name not in names:
            continue
        i = names.index(name)
        align = max(align, sec[i][8] or 1)
        cursor = (cursor + align - 1) // align * align
        address[i] = cursor
        body = bytes(sec[i][5]) if sec[i][1] == SHT_NOBITS else obj[sec[i][4]:sec[i][4] + sec[i][5]]
        image += bytes(cursor - base - len(image)) + body
        cursor += len(body)
    if '.text.init' not in names or address[names.index('.text.init')] != base:
        raise LinkError('.text.init must exist and start the image')
    if len(image) > limit:
        raise LinkError(f'image of {len(image)} bytes exceeds the memory of {limit} bytes')
    tables = [i for i, s in enumerate(sec) if s[1] == SHT_SYMTAB]
    if len(tables) != 1:
        raise LinkError('exactly one symbol table expected')
    table = tables[0]
    raw = [struct.unpack_from('<IIIBBH', obj, sec[table][4] + 16 * k) for k in range(sec[table][5] // 16)]

    def symbol(k):
        name, value, _, info, _, shndx = raw[k]
        if shndx == 0:
            if info >> 4 == 2:
                return 0          # an undefined weak symbol is address 0
            raise LinkError('undefined symbol ' + text(sec[table][6], name))
        if shndx == 0xfff1:
            return value          # absolute
        if shndx not in address:
            raise LinkError('symbol in a section that is not placed: ' + text(sec[table][6], name))
        return address[shndx] + value
    symbols = {}
    for k, entry in enumerate(raw):
        label = text(sec[table][6], entry[0])
        if label and entry[5] != 0 and entry[3] & 15 != 3:
            if label in symbols and entry[3] >> 4 != 0:
                raise LinkError('duplicate symbol ' + label)
            symbols.setdefault(label, symbol(k))
    relocations = []
    for i, s in enumerate(sec):
        if s[1] == SHT_RELA:
            if s[7] not in address:
                if sec[s[7]][2] & SHF_ALLOC:
                    raise LinkError('relocations for a section that is not placed')
                continue
            relocations += [(address[s[7]],) + struct.unpack_from('<IIi', obj, s[4] + 12 * k) for k in range(s[5] // 12)]
    unknown = sorted({info & 255 for _, _, info, _ in relocations} - RELOCATIONS.keys())
    if unknown:
        raise LinkError(f'relocation types not handled: {unknown}')
    counts, high = {}, {}

    def patch(place, kind_, value):
        pos = place - base
        word, = struct.unpack_from('<I', image, pos)
        if kind_ == 'U':
            word = word & 0xfff | ((value + 0x800) >> 12 & 0xfffff) << 12
        elif kind_ == 'I':
            word = word & 0x000fffff | (value & 0xfff) << 20
        elif kind_ == 'S':
            word = word & 0x01fff07f | (value >> 5 & 0x7f) << 25 | (value & 31) << 7
        elif kind_ == 'B':
            word = word & 0x01fff07f | (value >> 12 & 1) << 31 | (value >> 5 & 0x3f) << 25 | (value >> 1 & 15) << 8 | (value >> 11 & 1) << 7
        elif kind_ == 'J':
            word = word & 0xfff | (value >> 20 & 1) << 31 | (value >> 1 & 0x3ff) << 21 | (value >> 11 & 1) << 20 | (value >> 12 & 0xff) << 12
        else:
            word = value & 0xffffffff
        struct.pack_into('<I', image, pos, word)
    # The high parts first: each low part names the address of its high part.
    for wanted in ((R_PCREL_HI20,), tuple(set(RELOCATIONS) - {R_PCREL_HI20})):
        for start, offset, info, addend in relocations:
            kind_, place = info & 255, start + offset
            if kind_ not in wanted:
                continue
            counts[RELOCATIONS[kind_]] = counts.get(RELOCATIONS[kind_], 0) + 1
            target = symbol(info >> 8) + addend
            if kind_ == R_PCREL_HI20:
                high[place] = target - place
                if not _fits(high[place], 32):
                    raise LinkError('pc-relative distance out of range')
                patch(place, 'U', high[place])
            elif kind_ in (R_PCREL_LO12_I, R_PCREL_LO12_S):
                if target not in high:
                    raise LinkError('low part without its high part')
                low = high[target] + (4 if fault == 'lo12-off-by-four' else 0)
                patch(place, 'I' if kind_ == R_PCREL_LO12_I else 'S', low)
            elif kind_ == R_HI20:
                patch(place, 'U', target)
            elif kind_ in (R_LO12_I, R_LO12_S):
                patch(place, 'I' if kind_ == R_LO12_I else 'S', target)
            elif kind_ in (R_BRANCH, R_JAL):
                distance = target - place
                if distance & 1 or not _fits(distance, 13 if kind_ == R_BRANCH else 21):
                    raise LinkError('branch or jump distance out of range')
                patch(place, 'B' if kind_ == R_BRANCH else 'J', distance)
            else:
                patch(place, 'W', target)
    image += bytes(-len(image) % 4)
    return bytes(image), symbols, counts


def words(image):
    return list(struct.unpack(f'<{len(image) // 4}I', image))

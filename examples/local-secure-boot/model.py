"""Firmware, boot images and expected outcomes of the secure boot example.

The ROM programs and the image are assembled with the RV32I assembler of local-riscv-iss.
The expected verdict comes from the image rules written here (magic, length, version,
digest) and the digest from hashlib, not from the circuit. Each scenario becomes the rows the
bench reads: ROM and flash words, the OTP values, timed events and the expectations.
"""
import hashlib
import importlib.util
from pathlib import Path
import random
import sys

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('secure_boot_isa', HERE.parent / 'local-riscv-iss/iss.py')
ISA = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = ISA
spec.loader.exec_module(ISA)

MAGIC = 0xB007
ENTRY = 0x1004
SUCCESS = 0x600D600D
FAILURE = 0xBAD0BAD0
EBREAK = 0x00100073
PASS_STATUS = 0x02
REASONS = {'magic': 1, 'length': 2, 'rollback': 3, 'digest': 4}
RAM_WORDS = ('count', 'mark', 'verdict', 'keysum', 'lcstat', 'leak', 'key2')
LIFECYCLES = {'test': 0, 'dev': 1, 'prod': 2, 'rma': 3}
MIN_VERSION = 3
KEY = (0x1F2E3D4C, 0x5B6A7988, 0x0123ABCD, 0x89EF4567)
# Row kinds of the vectors file: kind, a, b, c.
ROM, FLASH, DIGEST, KEYWORD, OTP, EVENT, EXPECT, RAM = range(1, 9)
EXPECT_IDS = dict(status=1, halt_pc=2, may_exec=3, exec_lo=4, exec_hi=5, debug=6, max_cycles=7)
AFTER_START, AFTER_IMAGE = 1, 2       # what an event's delay counts from
IRQ, RESET = 1, 2


def li(register, value):
    value &= 0xFFFFFFFF
    low = ISA.sext(value, 12)
    return [('lui', register, (value - low) >> 12), ('addi', register, register, low)]


def fail_status(reason):
    return REASONS[reason] << 4 | 0x04


# ---- firmware ----
GOOD_HANDLER = [('lw', 28, 0, 29), ('addi', 28, 28, 1), ('sw', 28, 0, 29), ('addi', 30, 0, 1), ('sw', 30, 8, 27), ('mret',)]
# A faulty handler that leaves for the image entry instead of returning: the fetch gate must stop it.
JUMP_HANDLER = [('lui', 30, 0x1), ('addi', 30, 30, 4), ('jalr', 0, 0, 30)]
JUMP_TO_IMAGE = [('csrrci', 0, 'mstatus', 8), ('lui', 1, 0x1), ('addi', 1, 1, 4), ('jalr', 0, 0, 1)]
# A ROM that, after PASS, jumps to the header word instead of the entry: the header is not code.
JUMP_TO_HEADER = [('csrrci', 0, 'mstatus', 8), ('lui', 1, 0x1), ('jalr', 0, 0, 1)]


def rom(kind='good'):
    """kind: good, jump (the handler jumps to the image), ignore (a ROM that ignores the verdict)
    or header (a ROM that jumps to the header word after PASS)."""
    handler = JUMP_HANDLER if kind == 'jump' else GOOD_HANDLER
    p = [('jal', 0, 'main'), 'handler:', *handler, 'main:', ('lui', 27, 0x40000), ('lui', 29, 0x2),
         *[('sw', 0, 4 * i, 29) for i in range(len(RAM_WORDS))],
         ('addi', 1, 0, 4), ('csrrw', 0, 'mtvec', 1), *li(1, 0x800), ('csrrw', 0, 'mie', 1), ('csrrsi', 0, 'mstatus', 8),
         ('addi', 1, 0, 1), ('sw', 1, 0, 27),
         'wait:', ('lw', 2, 4, 27), ('andi', 3, 2, 6), ('beq', 3, 0, 'wait'), ('sw', 2, 8, 29)]
    if kind == 'ignore':
        # Read the key and the lifecycle registers, forge the verdict, restart the check, read again, jump.
        p += [('lw', 4, 0x10, 27), ('lw', 5, 0x14, 27), ('lw', 6, 0x18, 27), ('lw', 7, 0x1C, 27),
              ('xor', 4, 4, 5), ('xor', 4, 4, 6), ('xor', 4, 4, 7), ('sw', 4, 12, 29),
              ('addi', 8, 27, 0x100), ('lw', 9, 0xC, 8), ('sw', 9, 16, 29),
              ('addi', 1, 0, PASS_STATUS), ('sw', 1, 4, 27), ('addi', 1, 0, 1), ('sw', 1, 0, 27),
              ('lw', 2, 4, 27), ('sw', 2, 8, 29), ('lw', 4, 0x10, 27), ('sw', 4, 24, 29), *JUMP_TO_IMAGE]
    else:
        p += [('andi', 3, 2, 2), ('beq', 3, 0, 'fail'), *(JUMP_TO_HEADER if kind == 'header' else JUMP_TO_IMAGE),
              'fail:', *li(1, FAILURE), ('sw', 1, 4, 29), ('ebreak',)]
    words = ISA.assemble(p)
    labels = ISA.label_addresses(p)
    return words, labels


def rom_fail_halt():
    _, labels = rom('good')
    return labels['fail'] + 12  # li (2 words) and sw, then EBREAK


# The image reads the key and a secure lifecycle register, then reports success.
IMAGE_CODE = [('lui', 10, 0x40000), ('lui', 11, 0x2),
              ('lw', 1, 0x10, 10), ('lw', 2, 0x14, 10), ('lw', 3, 0x18, 10), ('lw', 4, 0x1C, 10),
              ('xor', 1, 1, 2), ('xor', 1, 1, 3), ('xor', 1, 1, 4), ('sw', 1, 12, 11),
              ('addi', 5, 10, 0x100), ('lw', 6, 0xC, 5), ('sw', 6, 16, 11),
              *li(7, SUCCESS), ('sw', 7, 4, 11), ('ebreak',)]
IMAGE = ISA.assemble(IMAGE_CODE)
IMAGE_HALT = ENTRY + 4 * (len(IMAGE) - 1)
LEAK_STORE = ISA.assemble([('sw', 7, 20, 11)])[0]
PAD = (0x3C3C5A5A, 0xC3C3A5A5)


def header(length, version, magic=MAGIC):
    return magic << 16 | (version & 0xFF) << 8 | (length & 0xFF)


def payload(length, code=IMAGE):
    words = list(code) + [PAD[i % 2] ^ (i * 0x01010101) for i in range(64)]
    return words[:(length + 3) // 4]


FLASH_WORDS = 256


def hashed_bytes(words, length):
    """The header word and `length` payload bytes, in memory (little-endian) order. Flash words
    the image does not fill read as 0, as in the bench."""
    words = list(words) + [0] * (FLASH_WORDS - len(words))
    data = b''.join((w & 0xFFFFFFFF).to_bytes(4, 'little') for w in words)
    return data[:4 + length]


def digest_of(words, length):
    return hashlib.sha256(hashed_bytes(words, length)).digest()


def parse(word):
    """Length, version and magic of a header word."""
    return word & 0xFF, word >> 8 & 0xFF, word >> 16 & 0xFFFF


def verdict(words, otp_digest, max_len, min_version):
    """The rules in their order: magic, length, version, digest. The header is read from the flash."""
    length, version, magic = parse(words[0])
    if magic != MAGIC:
        return 'magic'
    if length == 0 or length > max_len or length % 4:
        return 'length'
    if version < min_version:
        return 'rollback'
    if digest_of(words, length) != otp_digest:
        return 'digest'
    return 'pass'


class Scenario:
    def __init__(self, name, max_len, length=76, version=MIN_VERSION + 2, magic=MAGIC, firmware='good',
                 lifecycle='test', key=KEY, min_version=MIN_VERSION, code=IMAGE, tail=False):
        self.name, self.max_len, self.firmware, self.lifecycle = name, max_len, firmware, lifecycle
        self.key, self.min_version, self.tail = key, min_version, tail
        self.length, self.version, self.magic = length, version, magic
        self.flash = [header(length, version, magic)] + payload(length, code)
        if tail:  # unverified words right after the verified payload
            self.flash += [LEAK_STORE, EBREAK]
        self.digest = digest_of(self.flash, length)  # what the OTP holds, unless a scenario changes it
        self.events = []

    def tamper(self, index, xor):
        """Change one flash byte after the digest was taken."""
        word, lane = divmod(index, 4)
        self.flash[word] ^= (xor & 0xFF) << (8 * lane)

    def event(self, ref, delay, kind):
        self.events.append((ref, delay, kind))

    def found(self):
        return verdict(self.flash, self.digest, self.max_len, self.min_version)

    def outcome(self):
        found = self.found()
        length = parse(self.flash[0])[0]
        irqs = sum(kind == IRQ for _, _, kind in self.events)
        if self.firmware == 'jump':
            irqs = min(irqs, 1)  # the first interrupt leaves for the image and the core stops there
        status = PASS_STATUS if found == 'pass' else fail_status(found)
        ram = dict.fromkeys(RAM_WORDS, 0)
        if self.firmware in ('good', 'header'):
            ram['count'] = irqs
            ram['verdict'] = status
            if found == 'pass' and self.firmware == 'header':
                halt = ENTRY - 4
            elif found == 'pass':
                ram['mark'] = SUCCESS
                ram['keysum'] = self.key[0] ^ self.key[1] ^ self.key[2] ^ self.key[3]
                halt = ENTRY + length if self.tail else IMAGE_HALT
            else:
                ram['mark'] = FAILURE
                halt = rom_fail_halt()
        elif self.firmware == 'ignore':
            ram['verdict'] = status
            halt = ENTRY
        else:  # jump: the first interrupt sends the ROM to the entry before the check ends
            halt = ENTRY
        allows = LIFECYCLES[self.lifecycle] in (0, 1)
        may_exec = self.firmware in ('good', 'header') and found == 'pass'
        starts = 2 if any(kind == RESET for _, _, kind in self.events) else 1
        errors = 2 if self.firmware == 'ignore' else 0
        return dict(verdict=found, status=status, halt_pc=halt, may_exec=int(may_exec), exec_lo=ENTRY,
                    exec_hi=ENTRY + length, debug=int(found == 'pass' and allows), ram=ram,
                    counts=dict(starts=starts, irqs=irqs, bus_errors=errors))

    def rows(self):
        out = self.outcome()
        words, _ = rom(self.firmware)
        rows = [[ROM, i, w, 0] for i, w in enumerate(words)]
        rows += [[FLASH, i, w & 0xFFFFFFFF, 0] for i, w in enumerate(self.flash)]
        rows += [[DIGEST, i, int.from_bytes(self.digest[4 * i:4 * i + 4], 'big'), 0] for i in range(8)]
        rows += [[KEYWORD, i, w, 0] for i, w in enumerate(self.key)]
        rows += [[OTP, self.min_version, LIFECYCLES[self.lifecycle], 0]]
        rows += [[EVENT, ref, delay, kind] for ref, delay, kind in self.events]
        for name in ('status', 'halt_pc', 'may_exec', 'exec_lo', 'exec_hi', 'debug'):
            rows.append([EXPECT, EXPECT_IDS[name], out[name], 0])
        rows.append([EXPECT, EXPECT_IDS['max_cycles'], 4000, 0])
        rows += [[RAM, i, out['ram'][name], 0] for i, name in enumerate(RAM_WORDS)]
        return rows, out


def find_low_byte_twin(s):
    """A one-byte change of the padding whose digest ends with the same byte as the original.
    A comparison of only that byte (mutation 1) accepts it; the full comparison does not."""
    target = s.digest[-1]
    first_pad = 4 + 4 * len(IMAGE)
    for index in range(first_pad, 4 + s.length):
        for xor in range(1, 256):
            data = bytearray(hashed_bytes(s.flash, s.length))
            data[index] ^= xor
            if hashlib.sha256(bytes(data)).digest()[-1] == target:
                return index, xor
    raise ValueError('no one-byte twin in the padding')


def directed(max_len):
    """The fixed scenarios, each breaking at most one rule."""
    S = []

    def add(name, **kw):
        s = Scenario(name, max_len, **kw)
        S.append(s)
        return s
    add('golden')
    s = add('tamper-payload')
    s.tamper(4 + s.length - 1, 0x01)
    s = add('tamper-low-byte')
    s.tamper(*find_low_byte_twin(s))
    s = add('tamper-version')
    s.tamper(1, 0x01)  # header version byte; the OTP digest is of the original header
    add('bad-magic', magic=MAGIC - 1)
    add('length-zero', length=0)
    add('length-unaligned', length=4 * len(IMAGE) + 2)
    add('length-max', length=max_len)
    add('length-over', length=max_len + 4)
    add('version-equal', version=MIN_VERSION)
    add('version-below', version=MIN_VERSION - 1)
    s = add('irq-during-check')
    for delay in (10, 70, 140):
        s.event(AFTER_START, delay, IRQ)
    add('reset-during-check').event(AFTER_START, 50, RESET)
    add('reset-during-image').event(AFTER_IMAGE, 3, RESET)
    add('lifecycle-prod', lifecycle='prod')
    add('lifecycle-rma', lifecycle='rma')
    add('irq-jumps-to-image', firmware='jump').event(AFTER_START, 20, IRQ)
    s = add('rom-ignores-verdict', firmware='ignore')
    s.tamper(4 + s.length - 1, 0x80)
    add('unverified-tail', length=4 * (len(IMAGE) - 1), code=IMAGE[:-1], tail=True)
    add('rom-jumps-to-header', firmware='header')
    return S


def random_scenario(seed, max_len):
    """One boot with a drawn image. The kind of image is drawn first (half of them valid), then
    its details; the expected outcome still comes from the rules in verdict(), not from the kind."""
    r = random.Random(seed)
    kind = r.choices(('pass', 'digest', 'rollback', 'length', 'magic'), weights=(10, 4, 2, 2, 2))[0]
    length = r.choice(range(4 * len(IMAGE), max_len + 1, 4))
    if kind == 'length':
        length = r.choice([0, max_len + 4, 4 * len(IMAGE) + r.choice((1, 2, 3))])
    version = MIN_VERSION + (r.randint(-3, -1) if kind == 'rollback' else r.randint(0, 3))
    magic = MAGIC ^ (1 << r.randrange(16)) if kind == 'magic' else MAGIC
    key = tuple(r.getrandbits(32) | 1 for _ in range(4))
    s = Scenario(f'random-{seed}', max_len, length=length, version=version, magic=magic, key=key,
                 lifecycle=r.choice(list(LIFECYCLES)))
    if kind == 'digest':  # any hashed byte, the header included
        s.tamper(r.randrange(4 + length), r.randrange(1, 256))
    # Interrupts only while a full check runs, so that every one of them lands inside it.
    if s.found() in ('pass', 'digest'):
        delay = 5
        for _ in range(r.randint(0, 2)):
            delay += r.randint(5, 50)
            s.event(AFTER_START, delay, IRQ)
            delay += 40
    return s

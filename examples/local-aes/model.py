"""Independent AES-128 reference written with the standard library only.

Written differently from the RTL on purpose:
- the S-box is a table built here by searching for each multiplicative inverse in GF(2^8)
  and applying the affine map bit by bit (the RTL raises the byte to the 254th power and
  uses rotated copies);
- the state is a 4x4 list indexed [row][column]; ShiftRows and MixColumns work on it with
  general field multiplication (the RTL uses bit slices and xtime);
- all 44 key words are expanded in advance (the RTL derives one round key per clock).
No table is copied from a document. FIPS 197 values are only used as published checks.
"""

POLY = 0x11b  # x^8 + x^4 + x^3 + x + 1


def gf_mul(a, b):
    """Multiply two bytes in GF(2^8) by shift-and-add with reduction by POLY."""
    product = 0
    while b:
        if b & 1:
            product ^= a
        b >>= 1
        a <<= 1
        if a & 0x100:
            a ^= POLY
    return product


def _inverse(a):
    if a == 0:
        return 0
    found = [b for b in range(1, 256) if gf_mul(a, b) == 1]
    assert len(found) == 1
    return found[0]


def _affine(b):
    c = 0x63
    out = 0
    for i in range(8):
        bit = ((b >> i) ^ (b >> ((i + 4) % 8)) ^ (b >> ((i + 5) % 8)) ^
               (b >> ((i + 6) % 8)) ^ (b >> ((i + 7) % 8)) ^ (c >> i)) & 1
        out |= bit << i
    return out


SBOX = [_affine(_inverse(a)) for a in range(256)]


def _round_constants(count):
    values, rc = [], 1
    for _ in range(count):
        values.append(rc)
        rc = gf_mul(rc, 2)
    return values


RCON = _round_constants(10)


def expand_key(key):
    """Return the 44 key words of a 128-bit key (each word a 32-bit integer)."""
    words = [(key >> (96 - 32 * i)) & 0xffffffff for i in range(4)]
    for i in range(4, 44):
        temp = words[i - 1]
        if i % 4 == 0:
            temp = ((temp << 8) | (temp >> 24)) & 0xffffffff  # rotate the bytes one place
            temp = sum(SBOX[(temp >> (24 - 8 * k)) & 0xff] << (24 - 8 * k) for k in range(4))
            temp ^= RCON[i // 4 - 1] << 24
        words.append(words[i - 4] ^ temp)
    return words


def round_keys(key):
    words = expand_key(key)
    return [(words[4 * r] << 96) | (words[4 * r + 1] << 64) | (words[4 * r + 2] << 32) | words[4 * r + 3]
            for r in range(11)]


def to_state(value):
    data = value.to_bytes(16, 'big')
    return [[data[r + 4 * c] for c in range(4)] for r in range(4)]


def from_state(state):
    return int.from_bytes(bytes(state[r][c] for c in range(4) for r in range(4)), 'big')


def add_round_key(state, key):
    k = to_state(key)
    return [[state[r][c] ^ k[r][c] for c in range(4)] for r in range(4)]


def sub_bytes(state):
    return [[SBOX[v] for v in row] for row in state]


def shift_rows(state):
    return [[state[r][(c + r) % 4] for c in range(4)] for r in range(4)]


MATRIX = [[2, 3, 1, 1], [1, 2, 3, 1], [1, 1, 2, 3], [3, 1, 1, 2]]


def mix_columns(state):
    out = [[0] * 4 for _ in range(4)]
    for c in range(4):
        for r in range(4):
            value = 0
            for k in range(4):
                value ^= gf_mul(MATRIX[r][k], state[k][c])
            out[r][c] = value
    return out


def encrypt_rounds(key, block):
    """States after the initial AddRoundKey and after each of the 10 rounds."""
    keys = round_keys(key)
    state = add_round_key(to_state(block), keys[0])
    states = [from_state(state)]
    for r in range(1, 11):
        state = shift_rows(sub_bytes(state))
        if r != 10:
            state = mix_columns(state)
        state = add_round_key(state, keys[r])
        states.append(from_state(state))
    return states


def encrypt(key, block):
    return encrypt_rounds(key, block)[-1]


# Published examples (FIPS 197, 2001 edition; quoted values only, recalled from the appendices and
# confirmed here only because this independent model reproduces them).
FIPS_APPENDIX_B = dict(key=0x2b7e151628aed2a6abf7158809cf4f3c, block=0x3243f6a8885a308d313198a2e0370734,
                       out=0x3925841d02dc09fbdc118597196a0b32)
FIPS_APPENDIX_C1 = dict(key=0x000102030405060708090a0b0c0d0e0f, block=0x00112233445566778899aabbccddeeff,
                        out=0x69c4e0d86a7b0430d8cdb78070b4c55a)
FIPS_APPENDIX_A1_ROUND_KEYS = {1: 0xa0fafe1788542cb123a339392a6c7605, 10: 0xd014f9a8c9ee2589e13f0cc8b6630ca6}
FIPS_SBOX_EXAMPLES = {0x00: 0x63, 0x01: 0x7c, 0x53: 0xed}

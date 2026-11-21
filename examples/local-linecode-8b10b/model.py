"""8b/10b reference model. The sub-block codes are generated from stated rules, not copied from a table.

Bit names follow the usual convention: the eight data bits are HGFEDCBA (A is bit 0), the ten code
bits are abcdei fghj, and a is sent first. A code is held as an integer whose most significant bit
is a, so its binary text reads in transmission order. Running disparity is 0 for minus, 1 for plus.
"""
MINUS, PLUS = 0, 1
K28 = 28
K_OTHER = (23, 27, 29, 30)                       # control characters that exist only as K.x.7
CONTROL = [(K28, y) for y in range(8)] + [(x, 7) for x in K_OTHER]
COMMAS = (0b0011111, 0b1100000)


def ones(value):
    return bin(value).count('1')


def bits_of(x, width):
    """x as transmitted: bit 0 first."""
    return [(x >> n) & 1 for n in range(width)]


def pack(bits):
    value = 0
    for bit in bits:
        value = (value << 1) | bit
    return value


def six(x, control=False):
    """5b/6b: the sub-block for running disparity minus and for plus.

    Rules, with abcde the five input bits:
      three ones  -> abcde 0, already balanced
      two ones    -> abcde 1, already balanced
      one one in abcd -> the plus form is abcd 1 0 and the minus form its complement
      four ones with e set -> the minus form is abcde 0 and the plus form its complement
    The values that these rules would give a run of four or more equal bits, an ambiguous code, or
    no code at all are assigned by hand: D.0, D.15, D.16, D.24, D.31, and D.7 whose balanced code
    111000 alternates with 000111. K.28 has its own code, the only one with five equal bits in a row
    once the next sub-block follows.
    """
    if control and x == K28:
        return 0b001111, 0b110000
    special = {0: 0b100111, 15: 0b010111, 16: 0b011011, 24: 0b110011, 31: 0b101011, 7: 0b111000}
    if x in special:
        minus = special[x]
        return minus, minus ^ 0b111111
    a, b, c, d, e = bits_of(x, 5)
    weight = a + b + c + d + e
    if weight == 3:
        code = pack([a, b, c, d, e, 0])
        return code, code
    if weight == 2:
        code = pack([a, b, c, d, e, 1])
        return code, code
    if weight == 1:                               # e alone is D.16, handled above
        plus = pack([a, b, c, d, 1, 0])
        return plus ^ 0b111111, plus
    minus = pack([a, b, c, d, e, 0])              # weight 4 with e set
    return minus, minus ^ 0b111111


def four(y, x, rd, control=False):
    """3b/4b for running disparity rd (as it stands after the 6-bit sub-block).

    Rules, with fgh the three input bits:
      one or two ones other than 011 -> fgh j with j making two ones; balanced
      011 -> 1100 for minus, 0011 for plus (balanced, but it alternates)
      000 -> 1011 / 0100,  001 (y = 4) -> 1101 / 0010
      111 -> 1110 / 0001, or the alternate 0111 / 1000 where the primary would give five equal
             bits in a row with the end of the 6-bit sub-block
    A control character uses the alternate for y = 7, and for y = 1, 2, 5, 6 the complement of the
    data code when the running disparity is minus, so that no control code equals a data code.
    """
    f, g, h = bits_of(y, 3)
    if y == 7:
        alternate = control or (rd == MINUS and x in (17, 18, 20)) or (rd == PLUS and x in (11, 13, 14))
        minus = 0b0111 if alternate else 0b1110
    elif y == 3:
        minus = 0b1100
    elif y == 0:
        minus = 0b1011
    elif y == 4:
        minus = 0b1101
    else:                                          # y in 1, 2, 5, 6: balanced
        code = pack([f, g, h, 0 if f + g + h == 2 else 1])
        if control and rd == MINUS:
            code ^= 0b1111
        return code
    return minus if rd == MINUS else minus ^ 0b1111


def step_rd(rd, block, width):
    """Running disparity after a sub-block: it follows the sign of an unbalanced block."""
    n = ones(block)
    return rd if 2 * n == width else int(2 * n > width)


def legal_control(x, y):
    return (x, y) in CONTROL


def encode(value, control, rd):
    """(code, running disparity after) for one byte. An illegal control request is the caller's error."""
    x, y = value & 31, value >> 5
    if control and not legal_control(x, y):
        raise ValueError('not a control character')
    first = six(x, control)[rd]
    middle = step_rd(rd, first, 6)
    second = four(y, x, middle, control)
    return (first << 4) | second, step_rd(middle, second, 4)


def codebook():
    """{code: [(value, control, rd_in, rd_out), ...]} over every legal character and both disparities."""
    book = {}
    for control in (0, 1):
        for value in range(256):
            if control and not legal_control(value & 31, value >> 5):
                continue
            for rd in (MINUS, PLUS):
                code, after = encode(value, control, rd)
                book.setdefault(code, []).append((value, control, rd, after))
    return book


BOOK = codebook()


def next_rd(rd, code):
    """The decoder's running disparity: the sign of the whole code if it is unbalanced."""
    n = ones(code)
    return rd if n == 5 else int(n > 5)


def decode(code, rd):
    """(value, control, code_error, disparity_error, rd_after).

    A code outside the codebook is a code error and gives value 0. A code that exists only for the
    other running disparity is decoded and flagged as a disparity error.
    """
    entries = BOOK.get(code)
    after = next_rd(rd, code)
    if not entries:
        return 0, 0, 1, 0, after
    value, control = entries[0][0], entries[0][1]
    return value, control, 0, int(all(e[2] != rd for e in entries)), after


def serial(code):
    return [(code >> n) & 1 for n in range(9, -1, -1)]


class Aligner:
    """Word alignment on the comma, bit by bit, with the registered outputs of the circuit."""

    def __init__(self):
        self.reset()

    def reset(self):
        self.window, self.filled, self.phase, self.aligned, self.word = 0, 0, 0, 0, 0

    def step(self, rst_n=1, enable=1, valid=0, bit=0):
        """One clock: (word_valid, word, aligned, realigned) as they stand after the edge."""
        if not rst_n:
            self.reset()
            return 0, 0, 0, 0
        if not valid:
            return 0, self.word, self.aligned, 0
        self.window = ((self.window << 1) | bit) & 0x3FF
        self.filled = min(10, self.filled + 1)
        comma = self.filled == 10 and (self.window >> 3) in COMMAS
        boundary = self.aligned and self.phase == 9
        if comma and enable and not boundary:      # a comma off the current boundary moves it
            realigned, self.aligned, self.phase, self.word = self.aligned, 1, 0, self.window
            return 1, self.word, 1, realigned
        if boundary:
            self.phase, self.word = 0, self.window
            return 1, self.word, 1, 0
        if self.aligned:
            self.phase += 1
        return 0, self.word, self.aligned, 0


def runs(bits):
    """Length of the longest run of equal bits."""
    longest = current = 0
    previous = None
    for bit in bits:
        current = current + 1 if bit == previous else 1
        previous = bit
        longest = max(longest, current)
    return longest

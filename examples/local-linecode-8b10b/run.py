#!/usr/bin/env python3
"""8b/10b line code: every character in both disparities, every received code, word alignment on the comma."""
import importlib.util
from pathlib import Path
import random
import sys

HERE = Path(__file__).resolve().parent
NAME = 'local-linecode-8b10b'
TOP = 'linecode_tb'
CONFIGS = {'codec': {}}
ITERATIONS = {'smoke': 400, 'nightly': 3000}
SOURCES = [HERE / 'rtl/enc_8b10b_comb.sv', HERE / 'rtl/enc_8b10b.sv', HERE / 'rtl/dec_8b10b_comb.sv',
           HERE / 'rtl/dec_8b10b.sv', HERE / 'rtl/comma_align.sv', HERE / 'tb/linecode_tb.sv']
EXTRA_INPUTS = [HERE / 'model.py']
MUTANTS = 9
LABELS = {1: 'LC_CODE', 2: 'LC_CODE', 3: 'LC_ENC_RD', 4: 'LC_CODE', 5: 'LC_DISP_ERR', 6: 'LC_CODE_ERR',
          7: 'LC_DEC_RD', 8: 'LC_WORD', 9: 'LC_WORD'}
CODEC, ALIGN, RAW = 0, 1, 2          # what a row drives: encoder into decoder, one serial bit, a raw code into the decoder
FLIP = 0x03                          # D.3.0 is unbalanced in both disparities, so it turns the encoder's disparity over
RAISE, LOWER = 0b1111110000, 0b0000001111   # raw codes with six and with four ones, to set the decoder's disparity

spec = importlib.util.spec_from_file_location('linecode_model', HERE / 'model.py')
M = importlib.util.module_from_spec(spec)
spec.loader.exec_module(M)
K28_1, K28_5, K28_7 = 0x3C, 0xBC, 0xFC


class Plan:
    """Rows of one clock each. Every row carries what all three circuits show, driven or idle."""

    def __init__(self):
        self.rows, self.enc_rd, self.dec_rd, self.aligner = [], 0, 0, M.Aligner()
        self.n_sent = self.n_raw = self.n_words = 0

    def _row(self, kind, rst_n, valid, k, data, extra, codec, align):
        self.rows.append([kind, rst_n, valid, k, data, extra, *codec, self.enc_rd, self.dec_rd, *align])

    def reset(self, n=1):
        for _ in range(n):
            self.enc_rd = self.dec_rd = 0
            self._row(CODEC, 0, 0, 0, 0, 0, (0, 0, 0, 0, 0, 0), self.aligner.step(rst_n=0))

    def idle(self, n=1, data=0, k=0):
        """No character and no bit: nothing moves, whatever stands on the data inputs."""
        for _ in range(n):
            self._row(CODEC, 1, 0, k, data, 0, (0, 0, 0, 0, 0, 0), self.aligner.step())

    def send(self, value, control=0, mask=0):
        """One character through the encoder; the decoder receives the code with the mask bits inverted."""
        if control and not M.legal_control(value & 31, value >> 5):
            self._row(CODEC, 1, 1, 1, value, mask, (0, 1, 0, 0, 0, 0), self.aligner.step())
            return None
        code, self.enc_rd = M.encode(value, control, self.enc_rd)
        got, got_k, code_err, disp_err, self.dec_rd = M.decode(code ^ mask, self.dec_rd)
        self.n_sent += 1
        self._row(CODEC, 1, 1, control, value, mask, (code, 0, got, got_k, code_err, disp_err), self.aligner.step())
        return code

    def raw(self, code):
        """A code straight into the decoder; the encoder idles."""
        got, got_k, code_err, disp_err, self.dec_rd = M.decode(code, self.dec_rd)
        self.n_raw += 1
        self._row(RAW, 1, 0, 0, 0, code, (0, 0, got, got_k, code_err, disp_err), self.aligner.step())

    def bit(self, value, enable=1, valid=1):
        out = self.aligner.step(enable=enable, valid=valid, bit=value)
        self.n_words += out[0]
        self._row(ALIGN, 1, valid, value, enable, 0, (0, 0, 0, 0, 0, 0), out)

    def word(self, code, enable=1):
        for value in M.serial(code):
            self.bit(value, enable)

    def encoder_to(self, rd):
        if self.enc_rd != rd:
            self.send(FLIP)

    def decoder_to(self, rd):
        if self.dec_rd != rd:
            self.raw(RAISE if rd else LOWER)

    def counts(self):
        return dict(characters=self.n_sent, raw_codes=self.n_raw, words=self.n_words)


def stream(symbols, rd=0):
    """Codes of a list of (value, control), each in the disparity left by the one before."""
    codes = []
    for value, control in symbols:
        code, rd = M.encode(value, control, rd)
        codes.append(code)
    return codes


def boundary_plan():
    p = Plan()
    p.reset(2)
    p.idle(2)
    # Every data character and every control character, in both running disparities.
    for rd in (0, 1):
        for value in range(256):
            p.encoder_to(rd)
            p.send(value)
        for x, y in M.CONTROL:
            p.encoder_to(rd)
            p.send((y << 5) | x, 1)
    # Every control request that is not a control character; the running disparity stays.
    for rd in (0, 1):
        p.encoder_to(rd)
        for value in range(256):
            if not M.legal_control(value & 31, value >> 5):
                p.send(value, 1)
    # No character: the disparity holds, in both states and with data and k standing on the inputs.
    for rd in (0, 1):
        p.encoder_to(rd)
        p.idle(2, data=FLIP)
        p.idle(1, data=K28_5, k=1)
    # The longest run, five equal bits, inside a code and across two codes.
    p.encoder_to(0)
    p.send(K28_5, 1)                  # 00 11111 010
    p.encoder_to(0)
    p.send(0x00)                      # D.0.0 minus ends in 1 1011, D.28.1 plus cannot follow with ones
    for first, second in runs_of_five():
        p.encoder_to(first[2])
        p.send(first[0], first[1])
        p.send(second[0], second[1])
    # Every ten-bit code into the decoder, in both running disparities.
    for rd in (0, 1):
        for code in range(1024):
            p.decoder_to(rd)
            p.raw(code)
    # One inverted bit in each position of one code, then a clean code: the decoder goes on.
    for position in range(10):
        p.send(0x4A, 0, 1 << position)
        p.send(0xB5)
    p.send(0x4A, 0, 0x3FF)            # the complement of a balanced code
    p.send(0xB5)
    # An inverted bit that gives a code of the other disparity is reported now; one that gives a code
    # valid for the present disparity is reported only when the disparity next disagrees.
    p.reset()
    p.send(0x03, 0, 0b0000000100)     # 110001 1011 -> 110001 1111 is no code
    p.send(0x4A)
    p.reset()
    late = late_error()
    p.send(late[0], 0, late[1])
    for value in late[2]:
        p.send(value)
    p.reset()
    # Word alignment. Nine received bits that would read as a comma only together with the zero
    # left by reset give no word: a comma needs ten received bits. More bits without a comma follow.
    for value in (0, 1, 1, 1, 1, 1, 0, 1, 0) + (1, 0, 1, 1, 0, 0, 1, 0, 1, 0, 1, 0):
        p.bit(value)
    codes = stream([(K28_5, 1), (0x4A, 0), (0xB5, 0), (K28_5, 1), (0x00, 0), (0xFF, 0), (0x55, 0)])
    for code in codes[:-1]:
        p.word(code)                  # the first comma aligns; the second arrives on the boundary
    for n, value in enumerate(M.serial(codes[-1])):
        if n in (0, 4):
            p.bit(1 - value, valid=0)  # a cycle without a bit, at the start of a word and inside it
        p.bit(value)
    # One bit lost: words are wrong until the next comma moves the boundary.
    p.reset()
    symbols = [(K28_5, 1), (0x12, 0), (0x34, 0), (K28_5, 1), (0x56, 0), (K28_1, 1), (0x78, 0)]
    codes = stream(symbols)
    p.word(codes[0])
    p.word(codes[1])
    for value in M.serial(codes[2])[1:]:
        p.bit(value)                  # the first bit of this code is lost
    for code in codes[3:]:
        p.word(code)
    # One bit doubled, with alignment disabled: the comma is ignored and the words stay wrong.
    p.reset()
    codes = stream([(K28_5, 1), (0x9A, 0), (K28_5, 1), (0xBC ^ 0x80, 0), (K28_5, 1), (0xDE, 0)])
    p.word(codes[0])
    p.bit(M.serial(codes[1])[0])
    p.word(codes[1])
    p.word(codes[2], enable=0)
    p.word(codes[3], enable=0)
    p.word(codes[4])                  # enabled again: this comma moves the boundary
    p.word(codes[5])
    # The comma in its other polarity aligns too.
    p.reset()
    codes = stream([(FLIP, 0), (K28_5, 1), (0x21, 0), (0x43, 0)])
    for value in M.serial(codes[0])[3:]:
        p.bit(value)
    for code in codes[1:]:
        p.word(code)
    # K.28.7 followed by some characters shows a comma across the two codes. With alignment left
    # enabled the boundary moves to a wrong place; this is why K.28.7 is kept out of normal traffic.
    p.reset()
    follower = false_comma_follower()
    codes = stream([(K28_5, 1), (0x4A, 0), (K28_7, 1), follower, (0xB5, 0), (0x4A, 0)])
    for code in codes:
        p.word(code)
    p.reset()
    for code in codes[:2]:
        p.word(code)
    for code in codes[2:]:
        p.word(code, enable=0)        # with alignment disabled the same bits keep their boundary
    # Reset in the middle of everything.
    p.send(FLIP)
    p.raw(RAISE)
    p.reset()
    p.send(0x00)
    p.idle(2)
    return p


def runs_of_five():
    """Pairs ((value, control, rd), (value, control)) whose two codes hold a run of five across them."""
    found = []
    for rd in (0, 1):
        for value in range(256):
            code, after = M.encode(value, 0, rd)
            for second in range(256):
                both = M.serial(code) + M.serial(M.encode(second, 0, after)[0])
                if M.runs(both[5:15]) == 5 and M.runs(M.serial(code)) < 5 and M.runs(both[10:]) < 5:
                    found.append(((value, 0, rd), (second, 0)))
                    break
            if len(found) == 2 * (rd + 1):
                break
    return found


def late_error():
    """A data value, a one-bit mask and following values: the damaged code is accepted, a later one is not."""
    for value in range(256):
        code, after = M.encode(value, 0, 0)
        for position in range(10):
            got = M.decode(code ^ (1 << position), 0)
            if not got[2] and not got[3] and got[4] != after:
                return value, 1 << position, (0x4A, 0xB5, 0x03, 0x4A)
    raise ValueError('no such error')


def false_comma_follower():
    """A data character after which K.28.7 (sent in minus) shows a comma off the boundary."""
    code, after = M.encode(K28_7, 1, 1)           # the disparity in which the fixed plan sends it
    for value in range(256):
        both = M.serial(code) + M.serial(M.encode(value, 0, after)[0])
        if any(M.pack(both[n:n + 7]) in M.COMMAS for n in range(1, 10)):
            return value, 0
    raise ValueError('no follower')


def random_plan(seed, iterations):
    rng = random.Random(seed)
    p = Plan()
    p.reset()
    normal = [(K28_5, 1), (K28_1, 1)] + [((y << 5) | x, 1) for x, y in M.CONTROL if (x, y) != (28, 7)]
    while len(p.rows) < iterations * 4:
        roll = rng.random()
        if roll < 0.35:
            for _ in range(rng.randrange(1, 12)):
                control = rng.random() < 0.1
                value = rng.choice(normal)[0] if control else rng.randrange(256)
                mask = 0 if rng.random() < 0.8 else rng.choice((1 << rng.randrange(10), rng.getrandbits(10)))
                p.send(value, int(control), mask)
                if rng.random() < 0.2:
                    p.idle(rng.randrange(1, 3), data=rng.randrange(256), k=rng.randrange(2))
        elif roll < 0.4:
            p.send(rng.randrange(256), 1)             # mostly not a control character
        elif roll < 0.55:
            for _ in range(rng.randrange(1, 20)):
                p.raw(rng.getrandbits(10))
        elif roll < 0.58:
            p.reset()
        else:
            # A serial stream: commas now and then, sometimes a lost or doubled bit, sometimes alignment off.
            symbols = [rng.choice(normal) if rng.random() < 0.25 else (rng.randrange(256), 0)
                       for _ in range(rng.randrange(3, 10))]
            enable = int(rng.random() < 0.8)
            for code in stream(symbols, rng.randrange(2)):
                bits = M.serial(code)
                slip = rng.random()
                if slip < 0.1:
                    bits = bits[1:]
                elif slip < 0.2:
                    bits = bits[:1] + bits
                for value in bits:
                    p.bit(value, enable)
                    if rng.random() < 0.05:
                        p.bit(rng.randrange(2), enable, valid=0)
    p.reset()
    p.idle()
    return p


def make_cases(args, parameters):
    base = boundary_plan()
    cases = [dict(id='boundaries', plan=base, mutation=args.demo_bug, category='functional', expected_failure=None)]
    for seed in range(args.seed, args.seed + (3 if args.profile == 'nightly' else 1)):
        cases.append(dict(id=f'random-seed{seed}', plan=random_plan(seed, args.iterations), mutation=args.demo_bug,
                          category='functional', expected_failure=None))
    for mutation in range(1, MUTANTS + 1):
        cases.append(dict(id=f'detect-mutation{mutation}', plan=base, mutation=mutation, category='mutation',
                          expected_failure=LABELS[mutation]))
    for case in cases:
        plan = case.pop('plan')
        case['vectors'], case['counts'] = plan.rows, plan.counts()
    return cases


if __name__ == '__main__':
    spec = importlib.util.spec_from_file_location('local_runner', HERE.parent / 'local-common/runner.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    sys.exit(module.main(sys.modules[__name__]))

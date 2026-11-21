"""Reference model of secret_block, the policy table, and the scenarios.

The model is written from the README, cycle by cycle, with integers. It is used twice per
scenario, once with each secret, to give the expected outputs of both copies in the testbench.
The policy table (which output may depend on the key, and when) is written separately in
`allowed`, so that the testbench and the self-test can check the table against the model.
"""
import random

STATUS, CT, RD, ERR, SO = range(5)
INPUTS = ('rst_n', 'lc', 'key_we', 'key0', 'key1', 'start', 'din', 'zeroize', 'dbg_req', 'dbg_addr',
          'err_clr', 'scan_en', 'scan_in')
E_NOKEY, E_DENIED = 1, 2


class Block:
    def __init__(self, kw):
        if kw < 4:
            raise ValueError('KW must be at least 4')
        self.kw, self.mask = kw, (1 << kw) - 1
        self.started = False
        self.lc = self.key_valid = self.ct_valid = self.scan_mode = 0
        self.key = self.shadow = self.ct_q = self.rd = self.err = self.so = 0

    def status(self):
        return self.scan_mode << 3 | self.lc << 2 | self.ct_valid << 1 | self.key_valid

    def ct(self):
        return self.ct_q if self.ct_valid else 0

    def outputs(self):
        return [self.status(), self.ct(), self.rd, self.err, self.so]

    def read(self, addr):
        if addr == 0:
            return self.status()
        if addr == 1:
            return 0 if self.lc else self.shadow
        if addr == 2:
            return self.ct()
        return self.err >> self.kw

    def step(self, rst_n=1, lc=0, key_we=0, key=0, start=0, din=0, zeroize=0, dbg_req=0, dbg_addr=0,
             err_clr=0, scan_en=0, scan_in=0):
        """One clock edge. Returns the outputs after it."""
        if not self.started and rst_n:
            raise ValueError('the first cycle must be a reset')
        if not 0 <= key <= self.mask or not 0 <= din <= self.mask or not 0 <= dbg_addr <= 3:
            raise ValueError('input out of range')
        self.started = True
        if not rst_n:
            self.__init__(self.kw)
            self.started, self.lc = True, lc
            return self.outputs()
        if zeroize:
            self.key_valid = self.ct_valid = 0
            self.key = self.shadow = self.ct_q = self.rd = self.so = 0
            self.scan_mode = scan_en
            return self.outputs()
        entry = scan_en and not self.scan_mode and self.lc
        rd = self.read(dbg_addr) if dbg_req and not entry else 0
        if dbg_req and dbg_addr == 1 and self.lc:
            err = E_DENIED << self.kw | dbg_addr
        elif not scan_en and not key_we and start and not self.key_valid:
            err = E_NOKEY << self.kw
        elif err_clr:
            err = 0
        else:
            err = self.err
        if scan_en:
            if entry:
                self.key_valid = self.ct_valid = 0
                self.key = self.shadow = self.ct_q = self.so = 0
            else:
                self.so = self.key >> (self.kw - 1)
                chain = ((self.key << self.kw | self.ct_q) << 1 | scan_in) & ((1 << 2 * self.kw) - 1)
                self.key = self.shadow = chain >> self.kw
                self.ct_q = chain & self.mask
            self.scan_mode = 1
        else:
            self.scan_mode = self.so = 0
            if key_we:
                self.key = self.shadow = key
                self.key_valid, self.ct_valid, self.ct_q = 1, 0, 0
            elif start and self.key_valid:
                self.ct_q, self.ct_valid = din ^ self.key, 1
        self.rd, self.err = rd, err
        return self.outputs()


def allowed(before, row):
    """The policy table, from the public state before the edge and the inputs.

    Returns which outputs after the edge may differ between two secrets. `before` is the
    status before the edge (public), `row` the inputs of the cycle.
    """
    prod, ct_valid = before >> 2 & 1, before >> 1 & 1
    read = (row['rst_n'] and not row['zeroize'] and row['dbg_req'] and
            ((row['dbg_addr'] == 1 and not prod) or (row['dbg_addr'] == 2 and ct_valid)))
    return dict(read=bool(read))


def vectors(kw, steps):
    """Rows for the testbench: inputs, then the outputs of copy a and of copy b. And the counts."""
    a, b = Block(kw), Block(kw)
    rows, counts = [], dict(loads=0, zeroizes=0, denied=0, results=0)
    for s in steps:
        row = {name: s.get(name, 1 if name == 'rst_n' else 0) for name in INPUTS}
        before = a.status()
        common = {k: row[k] for k in INPUTS if k not in ('key0', 'key1')}
        out_a = a.step(key=row['key0'], **{k: v for k, v in common.items()})
        out_b = b.step(key=row['key1'], **{k: v for k, v in common.items()})
        if row['rst_n'] and not row['zeroize']:
            counts['loads'] += row['key_we'] and not row['scan_en']
            counts['denied'] += row['dbg_req'] and row['dbg_addr'] == 1 and before >> 2 & 1
            counts['results'] += (not row['scan_en'] and not row['key_we'] and row['start'] and before & 1)
        elif row['rst_n']:
            counts['zeroizes'] += 1
        rows.append([int(row[k]) for k in INPUTS] + out_a + out_b)
    return rows, {k: int(v) for k, v in counts.items()}


def patterns(kw):
    """Two secrets that differ in every bit, and a third one."""
    mask = (1 << kw) - 1
    a = int('a5' * (kw // 8 + 1), 16) & mask
    return a, a ^ mask, int('3c' * (kw // 8 + 1), 16) & mask


def boundaries(kw, equal=False):
    """The fixed scenario. Each leak of the mutants first shows on a row where the two secrets differ.

    With equal=True both copies get the same secret, so that no flow can be seen between them.
    """
    mask = (1 << kw) - 1
    a, b, c = patterns(kw)
    zero_pair = (0, b)                 # one secret is zero: "key loaded" taken from the value differs
    pair = lambda x, y: dict(key0=y if equal else x, key1=y)
    s = []
    add = lambda **k: s.append(k)
    # Production.
    add(rst_n=0, lc=1), add(rst_n=0, lc=1)
    add(start=1, din=0x11 & mask)                         # no key: error 1
    add(dbg_req=1, dbg_addr=3)                            # read the error code
    add(err_clr=1)
    add(key_we=1, **pair(*zero_pair))
    add(dbg_req=1, dbg_addr=0)                            # status
    add(start=1, din=0x96 & mask)                         # result, differs between the secrets
    add(dbg_req=1, dbg_addr=2)                            # result read: allowed to differ
    add(dbg_req=1, dbg_addr=1)                            # key read: refused, error 2
    add(dbg_req=1, dbg_addr=1, err_clr=1)                 # event on the same edge as a clear wins
    add(err_clr=1)
    add(key_we=1, start=1, din=0x0f & mask, **pair(a, b))  # write wins, start ignored
    add(start=1, din=0x0f & mask)
    add(scan_en=1, dbg_req=1, dbg_addr=2)                 # production entry erases, read squashed
    for i in range(2 * kw + 1):                           # one more shift than the chain is long
        add(scan_en=1, scan_in=(0b1011 >> (i % 4)) & 1, start=i == 3, key_we=i == 5, **pair(c, a))
    add(scan_en=1, zeroize=1)                             # erase while scanning
    add(scan_en=1, scan_in=1)
    add()                                                 # leave scan
    add(start=1, din=1)                                   # no valid key after the production entry
    add(err_clr=1)
    add(key_we=1, **pair(c, a))
    add(start=1, din=2)
    add(rst_n=0, lc=0)                                    # reset with a key loaded
    # Development.
    add(rst_n=0, lc=0)
    add(key_we=1, **pair(a, b))
    add(dbg_req=1, dbg_addr=1)                            # development key read: allowed to differ
    add(start=1, din=0x5a & mask)
    add(zeroize=1)
    add(dbg_req=1, dbg_addr=1)                            # after the erase: must not differ
    add(dbg_req=1, dbg_addr=2)
    add(key_we=1, **pair(a, b))
    for i in range(3):                                    # development scan shows the key bits
        add(scan_en=1, scan_in=i & 1)
    add()
    add(dbg_req=1, dbg_addr=1)
    add(start=1, din=0x3c & mask)                         # a result to be erased with the key
    add(zeroize=1)
    for i in range(2 * kw + 1):                           # development scan after an erase, through the chain
        add(scan_en=1, scan_in=i & 1)
    add()
    add(dbg_req=1, dbg_addr=1)
    return s


def random_steps(kw, seed, count):
    """Random operations, with resets that pick the lifecycle, and independent random secrets."""
    rng = random.Random(seed)
    mask = (1 << kw) - 1
    s = [dict(rst_n=0, lc=rng.randrange(2))]
    scanning = False
    for _ in range(count):
        if rng.random() < 0.03:
            s.append(dict(rst_n=0, lc=rng.randrange(2)))
            scanning = False
            continue
        if rng.random() < 0.06:
            scanning = not scanning
        k0, k1 = rng.randrange(mask + 1), rng.randrange(mask + 1)
        if rng.random() < 0.1:
            k1 = k0
        s.append(dict(key_we=int(rng.random() < 0.12), key0=k0, key1=k1, start=int(rng.random() < 0.3),
                      din=rng.randrange(mask + 1), zeroize=int(rng.random() < 0.04),
                      dbg_req=int(rng.random() < 0.5), dbg_addr=rng.randrange(4), err_clr=int(rng.random() < 0.1),
                      scan_en=int(scanning), scan_in=rng.randrange(2)))
    return s

"""What a debugger does, bit by bit, and what the hart must answer: independent of the RTL.

Three parts. Script turns debug module accesses into JTAG scans for the bench and records the
value each scan must return. Debugger is called by the ISS before every instruction and plays
the debugger at the stops whose place in the program is known (the halt before the first
instruction, EBREAK with dcsr.ebreakm, single steps): there it may write registers and dpc, so
the ISS continues with what it wrote. Halt requests at other times change nothing the program
can see; their checks compare with the next expected retirement instead (see asynchronous)."""

EBREAK = 0x00100073
# JTAG instructions of the TAP (four bits) and the registers behind them
IDCODE_IR, DTMCS_IR, DMI_IR = 0x1, 0x8, 0x9
IDCODE = 0x12345679
DTMCS = 0x00001071                     # idle 1, abits 7, version 1
DATA0, DMCONTROL, DMSTATUS, ABSTRACTCS, COMMAND = 0x04, 0x10, 0x11, 0x16, 0x17
HALTREQ, RESUMEREQ, DMACTIVE = 1 << 31, 1 << 30, 1
ALLHALTED, ALLRUNNING, ALLRESUMEACK = 3 << 8, 3 << 10, 3 << 16   # the any and all bits together
STATUS_FIXED = 0x83                    # authenticated, version 3 (specification 1.0)
ABSTRACT_IDLE = 0x1                    # one data register, not busy, no error
BUSY = 1 << 12
CMDERR = {'busy': 1, 'not-supported': 2, 'halt-resume': 4}
DCSR, DPC, GPR = 0x7b0, 0x7b1, 0x1000
CAUSE = {'ebreak': 1, 'haltreq': 3, 'step': 4}
SCAN_CLOCKS = 4 * 47                   # one dmi scan of the bench: 47 TCK periods of four clocks
CMD_CYCLES = 512                       # duration of an abstract command in the bench
# Row kinds of the bench. 0 to 5 load memories and expected retirements, the rest is the script.
IMEM, DMEM, LIMIT, RETIRE, FINAL = 0, 1, 2, 3, 5
SCAN_IR, SCAN_DR, POLL, WAIT_RETIRED, IDLE, RELEASE, COVER, SHADOW = 8, 9, 10, 11, 12, 13, 14, 16
LABELS = ['DBG_DATA', 'DBG_DPC', 'DBG_CMDERR', 'DBG_STATUS', 'DBG_DTM']
GOALS = ['dtm/idcode', 'dtm/dtmcs', 'halt/before-first-instruction', 'halt/request-while-running', 'halt/ebreak',
         'halt/ebreak-again', 'resume/ack', 'resume/dpc-moved', 'step/sequential', 'step/taken-branch', 'step/load',
         'step/exception', 'step/interrupt-masked', 'step/after-request', 'reg/gpr-read', 'reg/gpr-write-visible',
         'reg/x0', 'reg/dcsr', 'reg/dpc', 'abstract/busy', 'abstract/not-supported', 'abstract/unknown-register',
         'abstract/running-hart', 'abstract/sticky-error', 'abstract/clear']
BENCH_GOALS = ['halt/at-branch-flush', 'halt/at-exception', 'halt/at-interrupt', 'halt/after-memory-wait']


def dcsr_value(cause, step, ebreakm):
    """debugver 4, ebreakm (bit 15), cause (8:6), step (2), prv 3."""
    return 4 << 28 | ebreakm << 15 | cause << 6 | step << 2 | 3


def access(regno, write=False, size=2, transfer=True, cmdtype=0, postexec=False, increment=False):
    """The command register for Access Register."""
    return cmdtype << 24 | size << 20 | increment << 19 | postexec << 18 | transfer << 17 | write << 16 | regno


def dmi(address, data=0, op=0):
    """The 41 bits shifted into dmi, least significant first: operation, data, address."""
    if not (0 <= address < 128 and 0 <= data < 1 << 32 and op in (0, 1, 2)):
        raise ValueError('dmi field out of range')
    return address << 34 | data << 2 | op


class Script:
    """Rows of the debugger's side. Every row has eight columns."""

    def __init__(self):
        self.rows, self.goals, self.scans = [], [], 0

    def row(self, kind, *fields):
        self.rows.append([kind, *fields, *[0] * (7 - len(fields))])

    def instruction(self, value):
        self.row(SCAN_IR, value)

    def scan(self, length, tdi, expect=0, mask=0, mode=0, aux=0, label='DBG_DTM'):
        self.scans += 1
        self.row(SCAN_DR, length, tdi, expect, mask, mode, aux, LABELS.index(label))

    def write(self, address, data):
        self.scan(41, dmi(address, data, 2))

    def read(self, address, expect, mask=0xffffffff, label='DBG_DATA', mode=0, aux=0):
        """A read takes two scans: the request, then one that returns address, data and status 0."""
        self.scan(41, dmi(address, 0, 1))
        self.scan(41, dmi(0), dmi(address, expect & mask), 127 << 34 | mask << 2 | 3, mode, aux, label)

    def poll(self, address, expect, mask=0xffffffff, tries=40, label='DBG_STATUS'):
        self.row(POLL, 41, dmi(address, 0, 1), dmi(address, expect & mask), 127 << 34 | mask << 2 | 3, tries, 0, LABELS.index(label))

    def cover(self, goal):
        self.goals.append(goal)
        self.row(COVER, GOALS.index(goal))

    # --- what a debugger does with those accesses ---
    def start(self):
        """Check the transport, activate the module and request a halt before the core starts."""
        self.instruction(IDCODE_IR)
        self.scan(32, 0, IDCODE, 0xffffffff)
        self.cover('dtm/idcode')
        self.instruction(DTMCS_IR)
        self.scan(32, 0, DTMCS, 0xffffffff)
        self.cover('dtm/dtmcs')
        self.instruction(DMI_IR)
        self.write(DMCONTROL, DMACTIVE | HALTREQ)
        self.read(DMCONTROL, DMACTIVE | HALTREQ, label='DBG_STATUS')
        self.read(DMSTATUS, STATUS_FIXED | ALLRUNNING, label='DBG_STATUS')
        self.row(RELEASE)

    def wait_halted(self):
        self.poll(DMSTATUS, ALLHALTED, ALLHALTED | ALLRUNNING)

    def command(self, value, error=None):
        """Start a command and wait for it; cmderr must be the given error, or none."""
        self.write(COMMAND, value)
        self.poll(ABSTRACTCS, ABSTRACT_IDLE | (CMDERR[error] << 8 if error else 0), label='DBG_CMDERR')

    def clear_error(self):
        self.write(ABSTRACTCS, 7 << 8)
        self.read(ABSTRACTCS, ABSTRACT_IDLE, label='DBG_CMDERR')

    def read_register(self, regno, expect, label='DBG_DATA', mode=0, aux=0):
        self.command(access(regno))
        self.read(DATA0, expect, label=label, mode=mode, aux=aux)

    def write_register(self, regno, value):
        self.write(DATA0, value)
        self.command(access(regno, write=True))

    def resume(self, acknowledged=True):
        self.write(DMCONTROL, DMACTIVE | RESUMEREQ)
        if acknowledged:
            self.poll(DMSTATUS, ALLRESUMEACK, ALLRESUMEACK)


class Debugger:
    """The debugger at the stops whose place is known; execute() of the ISS calls boundary()
    before every instruction and asks masks_interrupts() before taking an interrupt.

    plans is a list of action lists, one for each stop in order, or a function that returns the
    actions of the next stop. Actions: ('write', n, value), ('read', n), ('zero',) for x0,
    ('dpc', address or None for the next instruction), ('ebreakm', bit), ('step', count),
    ('errors',) for the command errors, ('cover', goal); the resume at the end is implied."""

    def __init__(self, script, plans, labels=None):
        self.script, self.plans, self.labels = script, plans, labels or {}
        self.ebreakm = self.step = 0
        self.stops = self.elapsed = 0
        self.started = False
        self.written = set()        # registers known to hold a value
        self.kinds = []             # for the scenario's own bookkeeping: cause of each stop
        self.data0 = 0

    def masks_interrupts(self):
        return bool(self.step)

    def boundary(self, pc, regs, words, trace):
        while True:
            self.written.update(r.rd for r in trace[-2:] if r.rd)
            if not self.started:
                cause = 'haltreq'
            elif self.step and self.elapsed:
                cause = 'step'
            elif self.ebreakm and words[pc >> 2] == EBREAK:
                cause = 'ebreak'
            else:
                self.elapsed += 1
                return pc
            first, self.started = not self.started, True
            pc = self.stop(cause, pc, regs, words, trace, first)

    def actions(self, cause, pc, regs):
        if callable(self.plans):
            return self.plans(self, cause, pc, regs)
        if self.stops > len(self.plans):
            raise ValueError('the program stops more often than the plan says')
        return self.plans[self.stops - 1]

    def stop(self, cause, pc, regs, words, trace, first=False):
        """Returns the pc to resume at. A single step returns into the ISS and comes back here
        through boundary(), so the remaining actions wait in self.pending."""
        s = self.script
        if cause == 'step':
            actions, self.pending = self.pending, None
        else:
            self.stops += 1
            self.kinds.append(cause)
            if not first:
                s.row(WAIT_RETIRED, len(trace))
            actions = list(self.actions(cause, pc, regs))
        s.wait_halted()
        s.read_register(DCSR, dcsr_value(CAUSE[cause], self.step, self.ebreakm), label='DBG_STATUS')
        s.read_register(DPC, pc, label='DBG_DPC')
        if cause == 'haltreq':
            s.cover('halt/before-first-instruction')
        elif cause == 'ebreak':
            s.cover('halt/ebreak-again' if getattr(self, 'last_stop', None) == (pc, len(trace)) else 'halt/ebreak')
            self.last_stop = (pc, len(trace))
        else:
            self.cover_step(trace[-1], pc)
        dpc = pc
        while actions:
            action = actions.pop(0)
            name = action[0]
            if name == 'write':
                _, n, value = action
                s.write_register(GPR + n, value)
                regs[n] = value
                self.written.add(n)
                s.row(SHADOW, n, value)
            elif name == 'read':
                s.read_register(GPR + action[1], regs[action[1]])
                s.cover('reg/gpr-read')
            elif name == 'zero':
                s.write_register(GPR, 0xdeadbeef)
                s.read_register(GPR, 0)
                s.cover('reg/x0')
            elif name == 'dpc':
                target = action[1]
                dpc = (pc + 4) if target is None else self.labels.get(target, target)
                s.write_register(DPC, dpc | 3)          # the low two bits are not kept
                s.read_register(DPC, dpc, label='DBG_DPC')
                s.cover('reg/dpc')
            elif name == 'ebreakm':
                self.ebreakm = action[1]
                self.write_dcsr()
            elif name == 'errors':
                self.errors(regs)
            elif name == 'cover':
                s.cover(action[1])
            elif name == 'step':
                if action[1] > 1:
                    actions.insert(0, ('step', action[1] - 1))
                if not self.step:
                    self.step = 1
                    self.write_dcsr()
                self.pending = actions
                s.resume()
                self.elapsed = 0
                return dpc
            elif name != 'resume':
                raise ValueError(f'unknown action {name}')
        if self.step:
            self.step = 0
            self.write_dcsr()
        s.resume()
        s.cover('resume/ack')
        if dpc != pc:
            s.cover('resume/dpc-moved')
        self.elapsed = 0
        return dpc

    def write_dcsr(self):
        """With every other bit that could be writable set, to see that only these two are kept."""
        self.script.write_register(DCSR, 0x0fff7ff8 | self.ebreakm << 15 | self.step << 2 | 3)
        self.script.cover('reg/dcsr')

    def cover_step(self, record, pc):
        s, op = self.script, record.insn & 0x7f
        if record.kind == 3:
            s.cover('step/exception')
        elif op in (0x63, 0x6f, 0x67) and pc != record.pc + 4:
            s.cover('step/taken-branch')
        elif record.kind == 1:
            s.cover('step/load')
        else:
            s.cover('step/sequential')

    def errors(self, regs):
        """Commands the module does not have, a register the core does not have, a command and a
        data write while another command runs, and an error that stays until it is cleared."""
        s = self.script
        probe = next(iter(sorted(self.written)))
        for bad in (access(GPR + probe, cmdtype=1), access(GPR + probe, size=3), access(GPR + probe, postexec=True),
                    access(GPR + probe, increment=True)):
            s.command(bad, 'not-supported')
            s.clear_error()
        s.cover('abstract/not-supported')
        s.command(access(0x300), 'not-supported')      # mstatus: not a register this core gives the debugger
        # while the error stands, a good command does nothing and data0 keeps its value
        s.write(DATA0, 0x600dda7a)
        s.command(access(GPR + probe), 'not-supported')
        s.read(DATA0, 0x600dda7a)
        s.cover('abstract/sticky-error')
        s.clear_error()
        s.cover('abstract/unknown-register')
        s.read_register(GPR + probe, regs[probe])
        s.cover('abstract/clear')
        # a second command and a data write arrive while the first command runs
        if CMD_CYCLES <= 2 * SCAN_CLOCKS:
            raise ValueError('a command must last longer than two scans')
        s.write(COMMAND, access(GPR + probe))
        s.write(COMMAND, access(DPC))
        s.write(DATA0, 0x0badbad0)
        s.poll(ABSTRACTCS, ABSTRACT_IDLE | CMDERR['busy'] << 8, label='DBG_CMDERR')
        s.read(DATA0, regs[probe])                     # the first command finished; nothing else happened
        s.clear_error()
        s.cover('abstract/busy')


def asynchronous(script, at, idle, steps=0, register=None, ebreakm=1, thorough=False):
    """A halt request while the program runs, once `at` instructions have retired and `idle`
    more clock cycles have passed. Where the hart stops is not known here: the bench compares dpc
    with the address of its next expected retirement, and a register with the value the retired
    instructions gave it. Steps are for stretches without interrupts only."""
    script.row(WAIT_RETIRED, at)
    script.row(IDLE, idle)
    if thorough:   # costs the program some hundred instructions, so not every time
        script.read(DMSTATUS, STATUS_FIXED | ALLRUNNING, STATUS_FIXED | ALLRUNNING | ALLHALTED, label='DBG_STATUS')
    script.write(DMCONTROL, DMACTIVE | HALTREQ)
    script.wait_halted()
    script.read_register(DCSR, dcsr_value(CAUSE['haltreq'], 0, ebreakm), label='DBG_STATUS')
    script.read_register(DPC, 0, label='DBG_DPC', mode=1)
    if register is not None:
        script.read_register(GPR + register, 0, mode=2, aux=register)
    script.cover('halt/request-while-running')
    if steps:
        script.write(DMCONTROL, DMACTIVE)               # withdraw the request, or every step would report it
        script.write_register(DCSR, dcsr_value(0, 1, ebreakm))
        for _ in range(steps):
            script.resume()
            script.wait_halted()
            script.read_register(DCSR, dcsr_value(CAUSE['step'], 1, ebreakm), label='DBG_STATUS')
            script.read_register(DPC, 0, label='DBG_DPC', mode=1)
        script.write_register(DCSR, dcsr_value(0, 0, ebreakm))
        script.cover('step/after-request')
    script.resume(acknowledged=thorough)


def running_command(script, at, register):
    """An abstract command while the hart runs is refused."""
    script.row(WAIT_RETIRED, at)
    script.command(access(GPR + register), 'halt-resume')
    script.clear_error()
    script.cover('abstract/running-hart')

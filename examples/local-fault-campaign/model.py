"""Independent model of the referenced lockstep monitor, its workload and injected faults.

The circuit model is written from the specification table of local-lockstep-monitor, not from its
RTL. The workload model mirrors tb/fault_campaign_tb.sv decision by decision, so that a golden or
faulty run of the RTL and of this model must produce the same per-cycle trace.
"""
from dataclasses import dataclass

ADD, XOR, LOAD, ILLEGAL = 0, 1, 2, 3

# Architectural state of the referenced circuit, written from its specification. The runner checks
# that the flip-flops extracted from the RTL by Yosys are exactly these names and widths.
STATE = {'acc0': 8, 'acc1': 8, 'result': 8, 'error': 1, 'safe': 1, 'error_code': 2, 'done': 1}
# Outputs the classification observes: the functional outputs and the safety mechanism's alarm.
FUNCTIONAL = ('result', 'done')
ALARM = 'error'
OBSERVED = (*FUNCTIONAL, ALARM)

# The workload: (idle cycles before the operation, operation, operand).
OPS = [
    (0, LOAD, 0x35), (0, ADD, 0x11), (2, XOR, 0xff), (0, ADD, 0x80), (1, LOAD, 0x0f), (0, ADD, 0xf1),
    (0, ILLEGAL, 0x00), (0, XOR, 0x5a), (2, ADD, 0x01), (0, LOAD, 0xc3), (0, ADD, 0x3c), (1, XOR, 0x81),
]
WAIT_LIMIT = 4    # cycles the workload waits for done before it reports a stall
MAX_RETRY = 2     # re-executions of one operation after alarms before the workload gives up
DRAIN = 2         # idle cycles after the last operation
CAP = 96          # cycle limit of one run; reaching it is a timeout

NONE, FLIP, STUCK = 0, 1, 2


@dataclass(frozen=True)
class Fault:
    register: str
    bit: int
    kind: int        # FLIP: one-cycle inversion; STUCK: the bit holds `value` from `time` on
    time: int        # injected just after the rising edge of this cycle
    value: int = 0

    def key(self):
        return (self.register, self.bit, self.kind, self.time, self.value)

    def name(self):
        kind = 'flip' if self.kind == FLIP else f'sa{self.value}'
        return f'{self.register}[{self.bit}]-{kind}-t{self.time}'


def apply(acc, op, operand):
    if op == ADD:
        return (acc + operand) & 0xff
    if op == XOR:
        return acc ^ operand
    if op == LOAD:
        return operand
    return acc


def reset_state():
    return {name: 0 for name in STATE}


def step(s, op_valid, op, operand, recover):
    """One rising edge, from the specification table of the lockstep monitor."""
    n = dict(s)
    n['done'] = 0
    if recover and s['error']:
        n.update(acc1=s['acc0'], error=0, safe=0, error_code=0, result=s['acc0'])
    elif op_valid and not s['safe']:
        n['done'] = 1
        if op == ILLEGAL:
            n.update(error=1, safe=1, error_code=2, result=0)
        else:
            a, b = apply(s['acc0'], op, operand), apply(s['acc1'], op, operand)
            if a != b:
                n.update(error=1, safe=1, error_code=1, result=0)
            else:
                n.update(acc0=a, acc1=b, result=a)
    return n


class Workload:
    """The test bench's reactive driver: issue, wait for done, recover and retry after an alarm."""

    def __init__(self, ops=OPS):
        self.ops = ops
        self.idx = 0
        self.gap = ops[0][0]
        self.waiting = False
        self.wait_cnt = 0
        self.retries = 0
        self.drain = DRAIN
        self.status = 'run'
        self.alarms = 0

    def decide(self, out):
        idle = (0, 0, 0, 0)
        if out['error']:
            self.alarms += 1
            if self.waiting:
                if self.ops[self.idx][1] == ILLEGAL:
                    self.idx += 1
                    self.retries = 0
                    self.gap = self.ops[self.idx][0] if self.idx < len(self.ops) else 0
                else:
                    self.retries += 1
                    if self.retries > MAX_RETRY:
                        self.status = 'abandon'
                        return idle
                    self.gap = 0
            self.waiting = False
            return (0, 0, 0, 1)
        if self.waiting:
            if out['done']:
                self.waiting = False
                self.idx += 1
                self.retries = 0
                self.gap = self.ops[self.idx][0] if self.idx < len(self.ops) else 0
            else:
                self.wait_cnt += 1
                if self.wait_cnt >= WAIT_LIMIT:
                    self.status = 'stall'
                    return idle
                _, op, operand = self.ops[self.idx]
                return (1, op, operand, 0)
        if self.idx >= len(self.ops):
            if self.drain == 0:
                self.status = 'done'
                return idle
            self.drain -= 1
            return idle
        if self.gap > 0:
            self.gap -= 1
            return idle
        _, op, operand = self.ops[self.idx]
        self.waiting = True
        self.wait_cnt = 0
        return (1, op, operand, 0)


def run(fault=None, ops=OPS):
    """Rows (cycle, op_valid, op, operand, recover, result, done, error, safe, error_code) and the end status."""
    s = reset_state()
    w = Workload(ops)
    inputs = w.decide(s)
    rows = []
    cycle = 0
    while w.status == 'run':
        s = step(s, *inputs)
        if fault is not None:
            mask = 1 << fault.bit
            if fault.kind == FLIP and cycle == fault.time:
                s[fault.register] ^= mask
            elif fault.kind == STUCK and cycle >= fault.time:
                s[fault.register] = (s[fault.register] & ~mask) | (fault.value << fault.bit)
        rows.append((cycle, *inputs, s['result'], s['done'], s['error'], s['safe'], s['error_code']))
        cycle += 1
        inputs = w.decide(s)
        if w.status == 'run' and cycle >= CAP:
            w.status = 'cap'
    return dict(rows=rows, status=w.status, alarms=w.alarms)


def population(golden_cycles, registers=STATE):
    """Every single fault of the campaign: each bit, each kind and each injection cycle of the golden run."""
    faults = []
    for register, width in registers.items():
        for bit in range(width):
            for time in range(golden_cycles):
                faults.append(Fault(register, bit, FLIP, time))
                faults.append(Fault(register, bit, STUCK, time, 0))
                faults.append(Fault(register, bit, STUCK, time, 1))
    return faults

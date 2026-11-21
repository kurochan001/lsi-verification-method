#!/usr/bin/env python3
"""CAN 2.0A: three controllers with unequal clocks on one bus, checked against a bit-level model."""
import copy
import importlib.util
from pathlib import Path
import random
import sys

HERE = Path(__file__).resolve().parent
NAME = 'local-can'
TOP = 'can_tb'
# SKEW is the clock error of the two unequal nodes in units of 0.1 %; PATTERN says which ones.
CONFIGS = {
    'skew8': dict(TSEG1=13, TSEG2=6, SJW=4, SKEW=8, PATTERN=0),
    'skew5-late': dict(TSEG1=14, TSEG2=5, SJW=3, SKEW=5, PATTERN=1),
}
ITERATIONS = {'smoke': 10, 'nightly': 20}
SOURCES = [HERE / 'rtl/can_node.sv', HERE / 'tb/can_tb.sv']
EXTRA_INPUTS = [HERE / 'model.py']
MUTANTS = 10
LABELS = {1: 'CAN_RUN', 2: 'CAN_RUN', 3: 'CAN_RUN', 4: 'CAN_RUN', 5: 'CAN_STATE', 6: 'CAN_RUN', 7: 'CAN_RUN',
          8: 'CAN_RUN', 9: 'CAN_STATE', 10: 'CAN_RUN'}
# The fixed case whose scenarios expose each mutant.
SEEN_BY = {1: 'protocol', 2: 'protocol', 3: 'confinement', 4: 'protocol', 5: 'protocol', 6: 'confinement',
           7: 'confinement', 8: 'protocol', 9: 'protocol', 10: 'confinement'}
RESET, NODE, START, INJ, TXREQ, RUN, RX, ERR, DONE, END, STATE, LOST, WAIT = range(13)
EDGE_LIMIT = 12       # a disturbance is placed at most this many bits after the last bus edge

spec = importlib.util.spec_from_file_location('local_can_model', HERE / 'model.py')
M = importlib.util.module_from_spec(spec)
spec.loader.exec_module(M)
BUS_DOM, RX_DOM, RX_REC = M.BUS_DOM, M.RX_DOM, M.RX_REC


def frame(identifier, dlc=0, data=0, rtr=0):
    """data is an integer of the payload bytes, first byte most significant."""
    count = M.payload_bytes(rtr, dlc)
    return (identifier, rtr, dlc, (data << (64 - 8 * count)) & ((1 << 64) - 1) if count else 0)


def wire_index(bits):
    """Position on the bus of each destuffed bit, and the positions and values of the stuff bits."""
    places, stuff, value, length, position = [], [], None, 0, 0
    for bit in bits:
        places.append(position)
        position += 1
        value, length = (value, length + 1) if bit == value else (bit, 1)
        if length == 5:
            stuff.append((position, 1 - bit))
            position += 1
            value, length = 1 - bit, 1
    return places, stuff


class Script:
    """Builds the rows of one test case while advancing the model in step."""

    def __init__(self):
        self.bus, self.rows = M.Bus(), []
        self.counts = dict(frames=0, errors=0, done=0, runs=0)
        self.reset()

    def clone(self):
        other = Script.__new__(Script)
        other.bus, other.rows, other.counts = copy.deepcopy(self.bus), [], dict(self.counts)
        return other

    def row(self, op, a=0, b=0, c=0, d=0, e=0):
        self.rows.append([op, a, b, c, d, e])

    def idle(self, bits):
        for _ in range(bits):
            self.bus.step()
        if M.DOM in self.bus.levels[-bits:]:
            raise ValueError('the bus was expected to stay idle')

    def reset(self):
        self.row(RESET)
        for node in self.bus.nodes:
            node.queue.clear()
            node.online = True
            node.reset()
        self.idle(14)

    def online(self, index, value):
        """Take a node off the bus or bring it back, between scenarios."""
        node = self.bus.nodes[index]
        self.row(NODE, index, int(value))
        node.online = bool(value)
        if value:
            node.reset()
        self.row(WAIT, 16)
        self.idle(14)

    def scenario(self, requests, injections=(), late=(), on_step=None, limit=20000):
        """requests: (node, frame) issued together on an idle bus.
        injections: (kind, node, bit, length), bit counted from the first dominant bit.
        late: ('req', run, node, frame) or ('online', run, node), acted on when that run has ended.
        on_step(bus, sof): may return more injections while the model advances."""
        bus = self.bus
        if not bus.quiet():
            raise ValueError('a scenario starts on a quiet bus')
        if late:        # find, without the late actions, the bit at which each chosen run ends
            trial = copy.deepcopy(bus)
            first = self.simulate(trial, requests, injections, {}, on_step, limit=max(r[1] for r in late) * 40 + 400,
                                  finish=False)[0]
            if max(r[1] for r in late) >= len(first) - 1:
                raise ValueError('late action after the last run of the trial')
        actions = {}
        for item in late:
            # The test bench sees the end of a run most of a bit later, so a node released then first
            # samples the following bit. A request only has to be there before the bus is free again.
            time = sum(count for _, count in first[:item[1] + 1]) + (item[0] == 'online')
            actions.setdefault(time, []).append(item)
        events = [len(node.events) for node in bus.nodes]
        runs, sof, placed = self.simulate(bus, requests, injections, actions, on_step, limit, finish=True)
        if late and runs[:max(r[1] for r in late) + 1] != first[:max(r[1] for r in late) + 1]:
            raise ValueError('a late action changed bits before it was issued')
        levels = bus.levels[sof:]
        for kind, node, bit, length in placed:
            previous = max((k for k in range(1, bit + 1) if levels[k] != levels[k - 1]), default=0)
            if bit - previous > EDGE_LIMIT:
                raise ValueError(f'injection at bit {bit} is too far from the last edge')
        self.row(START)
        placed = sorted(placed, key=lambda item: item[2])
        if any(b[2] < a[2] + a[3] for a, b in zip(placed, placed[2:])):
            raise ValueError('more than two disturbances overlap')
        for kind, node, bit, length in placed:
            self.row(INJ, kind, node, bit, length)
        for node, item in requests:
            self.row(TXREQ, node, *item)
        after = {}
        for item in late:
            after.setdefault(item[1], []).append(item)
        for index, (level, count) in enumerate(runs):
            self.row(RUN, level, count)
            for item in after.get(index, []):
                if item[0] == 'req':
                    self.row(TXREQ, item[2], *item[3])
                else:
                    self.row(NODE, item[2], 1)
        done = [0] * len(bus.nodes)
        for index, node in enumerate(bus.nodes):
            for event in node.events[events[index]:]:
                if event[0] == 'rx':
                    self.row(RX, index, *event[1:])
                    self.counts['frames'] += 1
                elif event[0] == 'err':
                    self.row(ERR, index, event[1])
                    self.counts['errors'] += 1
                elif event[0] == 'lost':
                    self.row(LOST, index, event[1])
                else:
                    done[index] += 1
                    self.counts['done'] += 1
        for index, count in enumerate(done):
            self.row(DONE, index, count)
        self.counts['runs'] += len(runs)
        self.row(END, bus.time - sof - sum(count for _, count in runs) + 12)
        for index, node in enumerate(bus.nodes):
            if node.online:
                self.row(STATE, index, node.tec, node.rec, node.mode)
        self.idle(4)
        return runs

    @staticmethod
    def simulate(bus, requests, injections, actions, on_step, limit, finish):
        sof = bus.time
        placed = list(injections)
        for node, item in requests:
            bus.nodes[node].queue.append(item)
        for kind, node, bit, length in injections:
            bus.inject(sof + bit, kind, node, length)
        while bus.time - sof < limit:
            for item in actions.get(bus.time - sof, []):
                if item[0] == 'req':
                    bus.nodes[item[2]].queue.append(item[3])
                else:
                    bus.nodes[item[2]].online = True
                    bus.nodes[item[2]].reset()
            bus.step()
            if on_step:
                for kind, node, bit, length in on_step(bus, sof) or []:
                    bus.inject(sof + bit, kind, node, length)
                    placed.append((kind, node, bit, length))
            pending = any(time >= bus.time for time in bus.injections) or any(t >= bus.time - sof for t in actions)
            if finish and bus.quiet() and not pending:
                break
        else:
            if finish:
                raise ValueError('the scenario did not come to rest')
        if bus.levels[sof] != M.DOM:
            raise ValueError('no start of frame on the first bit')
        return M.runs(bus.levels[sof:]), sof, placed


def find_frame(predicate, node=0):
    """The first small frame whose bits satisfy the predicate; the search order is fixed."""
    for identifier in range(0x100, 0x700):
        for value in range(256):
            item = frame(identifier, 1, value)
            if predicate(M.frame_bits(*item)):
                return item
    raise ValueError('no frame found')


def tail_stuff_frame():
    def ends_with_five(bits):
        _, stuff = wire_index(bits)
        return bool(stuff) and stuff[-1][0] == len(bits) + len(stuff) - 1
    return find_frame(ends_with_five)


def find_view_fault(script, requests, node, wanted, reporter=None):
    """A single disturbed bit in one node's view that makes the reporter (that node unless given) report the wanted error first."""
    bits = M.frame_bits(*requests[0][1])
    length = len(M.stuffed(bits))
    for bit in range(20, length):
        for kind in (RX_DOM, RX_REC):
            trial = copy.deepcopy(script.bus)
            watch = node if reporter is None else reporter
            before = len(trial.nodes[watch].events)
            try:
                Script.simulate(trial, requests, [(kind, node, bit, 1)], {}, None, 2000, True)
            except ValueError:
                continue
            errors = [e for e in trial.nodes[watch].events[before:] if e[0] == 'err']
            if errors and errors[0][1] == M.KIND[wanted]:
                return kind, node, bit, 1
    raise ValueError('no disturbance found')


def error_delimiter(script, requests, injections):
    """The first bit of the error delimiter that follows the given disturbance."""
    trial = copy.deepcopy(script.bus)
    runs, _, _ = Script.simulate(trial, requests, injections, {}, None, 2000, True)
    position = 0
    for level, count in runs:
        if level == M.DOM and count >= 6:
            return position + count
        position += count
    raise ValueError('no error flag')


def error_flag_run(script, item, which):
    """The run that is the which-th error flag of a lone sender."""
    trial = copy.deepcopy(script.bus)
    trial.nodes[0].queue.append(item)
    start = trial.time
    for _ in range(400 * which):
        trial.step()
    flags = [index for index, (level, count) in enumerate(M.runs(trial.levels[start:])) if level == M.DOM and count >= 6]
    return flags[which - 1]


def third_suspend(script, item):
    """The run after which a lone sender has started its third suspended transmission."""
    trial = copy.deepcopy(script.bus)
    trial.nodes[0].queue.append(item)
    start, marks = trial.time, []
    while len(marks) < 3:
        trial.step()
        if trial.nodes[0].state == 'susp' and trial.nodes[0].count == 1:
            marks.append(trial.time - start)
        if trial.time - start > 5000:
            raise ValueError('the lone sender never suspended')
    ends, position = [], 0
    for _, count in M.runs(trial.levels[start:]):
        position += count
        ends.append(position)
    return max(index for index, end in enumerate(ends) if end <= marks[2])


class Repeat:
    """Disturb the same place of the first attempts of node 0 as transmitter."""

    def __init__(self, kind, node, offset, times):
        self.kind, self.node, self.offset, self.times, self.used = kind, node, offset, times, 0

    def __call__(self, bus, sof):
        sender = bus.nodes[0]
        if not (sender.state == 'body' and sender.role_tx and len(sender.bits) == 1) or self.used >= self.times:
            return None
        self.used += 1
        return [(self.kind, self.node, bus.time - sof - 1 + self.offset, 1)]


def protocol_rows():
    s = Script()
    zero = [(i, 0, 0, 0) for i in range(3)]

    def state():
        return [(i, n.tec, n.rec, n.mode) for i, n in enumerate(s.bus.nodes)]

    # ---- frames
    s.scenario([(0, frame(0x123, 8, 0x0123456789ABCDEF))])
    s.scenario([(1, frame(0x555, 0))])
    s.scenario([(2, frame(0x2AA, 3, rtr=1))])
    s.scenario([(0, frame(0x031, 12, 0x00FF00FF1F00E0FF))])        # length code above 8, long runs of both levels
    s.scenario([(1, tail_stuff_frame())])
    s.scenario([(2, frame(0x1C4, 2, 0xBEEF)), (2, frame(0x1C5, 1, 0x7E)), (2, frame(0x1C6, 0))])
    # ---- arbitration
    s.scenario([(0, frame(0x101, 1, 0x11)), (1, frame(0x180, 2, 0x2222)), (2, frame(0x100, 3, 0x333333))])
    s.scenario([(0, frame(0x0F0, 2, 0xA55A)), (1, frame(0x0F0, 2, rtr=1))])
    s.scenario([(0, frame(0x3A5, 8, 0xFEDCBA9876543210))], late=[('req', 9, 1, frame(0x010, 1, 0x99))])
    s.scenario([(1, frame(0x222, 1, 0x01)), (2, frame(0x223, 1, 0x02)), (1, frame(0x221, 1, 0x03))],
               late=[('req', 20, 0, frame(0x001, 0))])
    if state() != zero:
        raise ValueError('undisturbed traffic left a counter')
    # ---- one error of each kind, each followed by the retransmission
    quiet = frame(0x555, 2, 0x5AA5)                                  # no stuff bits before the data field
    places, _ = wire_index(M.frame_bits(*quiet))
    s.scenario([(0, quiet)], [(RX_REC, 0, places[14], 1)])           # the sender misreads its own dominant bit
    stuffy = frame(0x2B0, 2, 0x07C1)
    places, stuff = wire_index(M.frame_bits(*stuffy))
    recessive = next(position for position, value in stuff if value == M.REC and position > places[18])
    s.scenario([(0, stuffy)], [(RX_DOM, 2, recessive, 1)])           # one receiver misses a stuff bit
    s.scenario([(1, frame(0x2B1, 2, 0x1234))], [find_view_fault(s, [(1, frame(0x2B1, 2, 0x1234))], 2, 'crc')])
    body = len(M.stuffed(M.frame_bits(*quiet)))
    s.scenario([(0, quiet)], [(RX_DOM, 2, body, 1)])                 # CRC delimiter read as dominant
    s.scenario([(0, quiet)], [(RX_DOM, 1, body + 2, 1)])             # ACK delimiter
    s.scenario([(0, quiet)], [(RX_DOM, 2, body + 5, 1)])             # third bit of the end of frame
    s.scenario([(0, quiet)], [(RX_DOM, 1, body + 9, 1)])             # last bit of the end of frame, at a receiver
    s.scenario([(0, quiet)], [(RX_DOM, 0, body + 9, 1)])             # the same bit at the sender
    s.scenario([(0, quiet)], [(BUS_DOM, 0, body + 10, 1)])           # first bit of the intermission
    s.scenario([(0, quiet)], [(BUS_DOM, 0, body + 11, 1)])           # second bit of the intermission
    s.scenario([(0, quiet), (1, frame(0x556, 0))], [(BUS_DOM, 0, body + 12, 1)])   # third bit: a start of frame
    s.scenario([(0, quiet)], [(RX_REC, 0, places[14], 1), (RX_REC, 0, places[14] + 3, 1)])   # and its flag disturbed
    s.scenario([(1, quiet)], [(RX_REC, 1, places[14], 1), (RX_REC, 2, places[14] + 6, 1)])   # a receiver's flag disturbed
    early = frame(0x00F, 1, 0x3C)                                    # four dominant identifier bits after the start bit
    s.scenario([(2, early)], [(BUS_DOM, 0, 5, 1)])                   # the recessive stuff bit in the identifier
    s.scenario([(2, early)], [(RX_REC, 2, 0, 1)])                    # a start bit the sender does not see
    delimiter = error_delimiter(s, [(0, quiet)], [(RX_REC, 0, places[14], 1)])
    s.scenario([(0, quiet)], [(RX_REC, 0, places[14], 1), (RX_DOM, 1, delimiter + 1, 1)])   # second bit of the error delimiter
    s.scenario([(0, quiet)], [(RX_REC, 0, places[14], 1), (BUS_DOM, 0, delimiter + 7, 1)])  # its last bit
    return s


def confinement_rows():
    s = Script()
    quiet = frame(0x555, 2, 0x5AA5)
    places, _ = wire_index(M.frame_bits(*quiet))
    stuffy = frame(0x2B0, 2, 0x07C1)
    data_start, stuff = wire_index(M.frame_bits(*stuffy))
    recessive = next(position for position, value in stuff if value == M.REC and position > data_start[18])
    # ---- joining the bus: eleven recessive bits, not ten
    # A node released at the end of an error flag sees ten recessive bits before the next attempt. It must
    # let that attempt go unacknowledged and join after the eleven bits that follow the next error flag.
    lone = frame(0x555, 1, 0xA5)
    s.online(1, 0)
    s.online(2, 0)
    s.scenario([(0, lone)], late=[('online', error_flag_run(s, lone, 2), 1)])
    if s.bus.nodes[0].tec != 23:
        raise ValueError('the late node was expected to acknowledge the fourth attempt')
    # ---- no acknowledgement: error passive, and no further count
    s.reset()
    s.online(1, 0)
    s.online(2, 0)
    alone = s.scenario([(0, lone)], late=[('online', third_suspend(s, lone), 1)])
    if s.bus.nodes[0].tec != 127:
        raise ValueError('the lone sender was expected to stop at 128 and come down by one')
    # ---- two nodes: the only receiver has a CRC error, so nobody acknowledges
    s.reset()
    s.online(2, 0)
    pair = frame(0x2B1, 2, 0x1234)
    s.scenario([(0, pair)], [find_view_fault(s, [(0, pair)], 1, 'ack', reporter=0)])
    s.online(2, 1)
    s.scenario([(1, frame(0x321, 1, 0x42))])
    # ---- bus off and recovery
    s.reset()
    s.scenario([(0, quiet)], on_step=Repeat(RX_REC, 0, places[14], 32))
    s.scenario([(0, frame(0x700, 1, 0x55))])
    # ---- a receiver becomes error passive, and comes back to 127
    s.reset()
    # Its flag is disturbed for 16 bits, eight counts each. The retransmission is disturbed for it again:
    # now it sends a passive flag, which leaves the frame intact for the others.
    s.scenario([(0, stuffy)], [(RX_REC, 2, recessive + 2, 16)], on_step=Repeat(RX_DOM, 2, recessive, 2))
    if s.bus.nodes[2].rec < 128 or s.bus.nodes[0].tec != 7:
        raise ValueError('the receiver was expected to stay error passive without disturbing the second attempt')
    s.scenario([(1, frame(0x654, 4, 0x0BADF00D))])
    if s.bus.nodes[2].rec != 127:
        raise ValueError('a good frame was expected to bring the receiver to 127')
    del alone, places
    return s


def random_rows(seed, scenarios):
    rng = random.Random(seed)
    s = Script()
    for number in range(scenarios):
        if number and rng.random() < 0.15:
            s.reset()
        senders = rng.sample(range(3), rng.choice((1, 1, 2, 2, 3)))
        used, requests = set(), []
        for node in senders:
            for _ in range(rng.choice((1, 1, 2))):
                identifier = rng.choice([i for i in (rng.randrange(0x7F0) for _ in range(8)) if i not in used] or [0x400])
                while identifier in used:
                    identifier = (identifier + 1) % 0x7F0
                used.add(identifier)
                rtr, dlc = int(rng.random() < 0.15), rng.choice((0, 1, 2, 3, 4, 8, 8, rng.randrange(16)))
                count = M.payload_bytes(rtr, dlc)
                pattern = rng.choice((rng.getrandbits(64), 0, (1 << 64) - 1, 0xF0F0F0F0F0F0F0F0, rng.getrandbits(64) & rng.getrandbits(64)))
                requests.append((node, frame(identifier, dlc, pattern >> (64 - 8 * count) if count else 0, rtr)))
        rng.shuffle(requests)
        injections = []
        if rng.random() < 0.6:
            length = len(M.wire_bits(*requests[0][1]))
            for _ in range(20):
                candidate = (rng.choice((BUS_DOM, RX_DOM, RX_REC)), rng.randrange(3), rng.randrange(1, length + 14), 1)
                trial = s.clone()
                try:
                    trial.scenario(requests, [candidate], limit=6000)
                except ValueError:
                    continue
                if any(node.mode for node in trial.bus.nodes):
                    continue                     # keep the random traffic away from long recoveries
                injections = [candidate]
                break
        s.scenario(requests, injections, limit=6000)
    return s


def counts(script):
    return dict(script.counts)


def make_cases(args, parameters):
    del parameters      # the bits on the bus do not depend on the clocks or the bit timing
    fixed = dict(protocol=protocol_rows(), confinement=confinement_rows())
    cases = [dict(id=name, category='functional', mutation=args.demo_bug, expected_failure=None,
                  vectors=item.rows, counts=counts(item)) for name, item in fixed.items()]
    for seed in range(args.seed, args.seed + (3 if args.profile == 'nightly' else 1)):
        item = random_rows(seed, args.iterations)
        cases.append(dict(id=f'random-seed{seed}', category='functional', mutation=args.demo_bug,
                          expected_failure=None, vectors=item.rows, counts=counts(item)))
    if not args.demo_bug:
        for mutation in range(1, MUTANTS + 1):
            cases.append(dict(id=f'detect-mutation{mutation}', category='mutation', mutation=mutation,
                              expected_failure=LABELS[mutation], vectors=fixed[SEEN_BY[mutation]].rows, counts={}))
    return cases


if __name__ == '__main__':
    sys.dont_write_bytecode = True
    spec = importlib.util.spec_from_file_location('local_runner', HERE.parent / 'local-common/runner.py')
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)
    sys.exit(runner.main(sys.modules[__name__]))

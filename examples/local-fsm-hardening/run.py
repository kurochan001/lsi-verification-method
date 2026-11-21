#!/usr/bin/env python3
"""Hardened access lock: every single bit flip of the state and the failure counter is detected, never grants."""
import importlib.util
from itertools import combinations
from pathlib import Path
import random
import sys

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('fsm_hardening_model', HERE / 'model.py')
M = importlib.util.module_from_spec(spec)
spec.loader.exec_module(M)

NAME = 'local-fsm-hardening'
TOP = 'fsm_hardening_tb'
CONFIGS = {'tries3': dict(MAX_TRIES=3), 'tries2': dict(MAX_TRIES=2)}
ITERATIONS = {'smoke': 300, 'nightly': 3000}
SOURCES = [HERE / 'rtl/hardened_lock.sv', HERE / 'tb/fsm_hardening_tb.sv']
EXTRA_INPUTS = [HERE / 'model.py']
MUTANTS = 8
LABELS = {1: 'FSM_ESCALATE', 2: 'FSM_ESCALATE', 3: 'FSM_ESCAPE', 4: 'FSM_ESCALATE',
          5: 'FSM_STATE', 6: 'FSM_UNDETECTED', 7: 'FSM_FAILS', 8: 'FSM_ESCALATE'}
EXACT, FIRST, AFTER, AGAIN = range(4)   # how the test bench checks the outputs after a row
FW = 10                                 # flip mask: state [9:4], counter [3:2], its copy [1:0]
STATE_BITS, COUNT_BITS, COPY_BITS = tuple(range(4, 10)), (2, 3), (0, 1)
# Inputs at the flipping edge: staying in the state, and the transition out of it.
VARIANTS = {M.LOCKED: (dict(), dict(start=1)), M.CHECK: (dict(key_ok=0), dict(key_ok=1)),
            M.OPEN: (dict(), dict(relock=1)), M.LOCKOUT: (dict(), dict(start=1, key_ok=1, relock=1))}


class Plan:
    """Rows for the test bench. The expected outputs are those of the lock without faults."""

    def __init__(self, max_tries):
        self.max_tries, self.lock, self.rows, self.dirty = max_tries, M.Lock(max_tries), [], False

    def edge(self, rst_n=1, start=0, key_ok=0, relock=0, fault=0):
        if fault and not rst_n:
            raise ValueError('reset wins over a flip; a flip in a reset row tests nothing')
        if not 0 <= fault < 1 << FW:
            raise ValueError('flip mask out of range')
        outputs = self.lock.step(rst_n, start, key_ok, relock)
        if not rst_n:
            self.dirty, mode = False, EXACT
        elif fault:
            mode = AGAIN if self.dirty else FIRST
            self.dirty = True
        else:
            mode = AFTER if self.dirty else EXACT
        self.rows.append([rst_n, start, key_ok, relock, fault, mode, *outputs])

    def reset(self, n=1):
        for _ in range(n):
            self.edge(rst_n=0)

    def reach(self, state, fails):
        """From reset, bring the lock to state with this many failures."""
        if state == M.LOCKOUT:
            fails = self.max_tries
        for _ in range(fails):
            self.edge(start=1)
            self.edge()                                  # a wrong key
        if state == M.CHECK:
            self.edge(start=1)
        elif state == M.OPEN:
            self.edge(start=1)
            self.edge(key_ok=1)
        if (self.lock.state, self.lock.fails) != (state, fails if state != M.OPEN else 0):
            raise ValueError(f'could not reach {state} with {fails} failures')

    def follow(self, again=0):
        """Rows after a flip: one idle edge by which the lock must be in ERROR, optionally a
        second flip while in ERROR, then the requests that would leave each working state."""
        self.edge()
        if again:
            self.edge(fault=again)
        self.edge(start=1)
        self.edge(key_ok=1)
        self.edge(relock=1)
        self.edge(start=1, key_ok=1, relock=1)
        self.edge()


def contexts(max_tries):
    """Every working state, with every failure count it can hold."""
    found = [(M.LOCKED, k) for k in range(max_tries)] + [(M.CHECK, k) for k in range(max_tries)]
    return found + [(M.OPEN, 0), (M.LOCKOUT, max_tries)]


def scenario_rows(max_tries):
    """The lock without faults: requests in every state, the failure limit and its neighbours."""
    p = Plan(max_tries)
    p.reset(2)
    p.edge(key_ok=1)                     # a key without start is ignored
    p.edge(relock=1)
    p.edge(start=1, relock=1)            # start wins in LOCKED; relock means nothing there
    p.edge(key_ok=1)                     # OPEN
    p.edge(start=1)                      # ignored while open
    p.edge()
    p.edge(relock=1)
    for _ in range(max_tries - 1):       # one short of the limit: back to LOCKED each time
        p.edge(start=1)
        p.edge()
    p.edge(start=1)
    p.edge(key_ok=1, relock=1)           # success on the last try clears the failures
    p.edge(relock=1, start=1)            # relock wins in OPEN
    for _ in range(max_tries):           # exactly the limit: LOCKOUT
        p.edge(start=1)
        p.edge()
    p.edge(start=1, key_ok=1, relock=1)  # nothing leaves LOCKOUT
    p.edge(start=1)
    p.edge(key_ok=1)
    p.reset()                            # reset from LOCKOUT
    p.edge(start=1)
    p.edge(key_ok=1)
    p.edge()
    p.reset()                            # reset from OPEN
    p.edge(start=1)
    p.reset()                            # reset while checking
    p.edge(start=1)
    p.edge()
    p.reset()                            # reset after a failure clears it
    p.edge()
    return p.rows


def fault_rows(max_tries):
    """Every single bit of the 10 stored bits, flipped in every working state and failure
    count, both while the state holds and on the edge that leaves it. A flip that holds OPEN,
    or LOCKED without failures, is followed by a second flip of the same bit while in ERROR:
    once where the lock without faults grants and once where it does not."""
    p = Plan(max_tries)
    for state, fails in contexts(max_tries):
        for index, inputs in enumerate(VARIANTS[state]):
            for bit in range(FW):
                p.reset()
                p.reach(state, fails)
                p.edge(fault=1 << bit, **inputs)
                second = index == 0 and (state == M.OPEN or (state, fails) == (M.LOCKED, 0))
                p.follow(again=1 << bit if second else 0)
    p.reset()
    return p.rows


def double_state_rows(max_tries):
    """Outside the guarantee: two state bits at once. The codes are three bits apart, so the
    word still cannot be another valid code."""
    p = Plan(max_tries)
    for state in M.STATES:
        for a, b in combinations(STATE_BITS, 2):
            p.reset()
            p.reach(state, 0)
            p.edge(fault=(1 << a) | (1 << b), **VARIANTS[state][0])
            p.follow()
    p.reset()
    return p.rows


def double_counter_rows(max_tries):
    """Outside the guarantee: the same bit of the counter and of its copy at once. The pair
    still agrees, the failures shrink, and a key tried past the limit opens the lock."""
    p = Plan(max_tries)
    p.reset(2)
    for _ in range(max_tries - 1):
        p.edge(start=1)
        p.edge()
    high = (max_tries - 1) & 2                   # the set bit of the failure count to take back
    bit = 1 if high else 0
    p.edge(fault=(1 << (COUNT_BITS[0] + bit)) | (1 << (COPY_BITS[0] + bit)))
    p.edge(start=1)
    p.edge()                                     # the limit: the lock without faults locks out
    p.edge(start=1)
    p.edge(key_ok=1)
    p.edge()
    p.reset()
    return p.rows


def random_rows(max_tries, seed, iterations):
    """Random requests; now and then a flip of a random bit on a random edge, a few rows with
    random requests, sometimes a second flip while in ERROR, then reset."""
    rng = random.Random(seed)
    p = Plan(max_tries)
    p.reset(2)
    left = 0
    for _ in range(iterations):
        inputs = dict(start=int(rng.random() < 0.4), key_ok=int(rng.random() < 0.5), relock=int(rng.random() < 0.2))
        if p.dirty:
            if left == 0:
                p.reset()
                continue
            again = 1 << rng.randrange(FW) if left >= 2 and rng.random() < 0.15 else 0
            p.edge(fault=again, **inputs)
            left -= 1
        elif rng.random() < 0.02:
            p.reset()
        elif rng.random() < 0.05:
            p.edge(fault=1 << rng.randrange(FW), **inputs)
            left = rng.randint(2, 6)
        else:
            p.edge(**inputs)
    if p.dirty:
        p.edge()       # a flip on the last rows still gets the edge by which it must be in ERROR
    p.reset()
    return p.rows


def check_rows(rows):
    """Every flip must reach a plain row before the reset that closes it: that row is where the
    test bench demands ERROR. Without it a correct lock would be reported as undetected."""
    pending = False
    for mode in (r[5] for r in rows):
        if mode in (FIRST, AGAIN):
            pending = True
        elif mode == AFTER:
            pending = False
        elif pending:
            raise ValueError('a flip is closed by reset before the edge that must show ERROR')
    if pending:
        raise ValueError('the plan ends on a flip')


def counts(rows):
    return dict(flips=sum(r[5] == FIRST for r in rows), again=sum(r[5] == AGAIN for r in rows))


def make_cases(args, parameters):
    max_tries = parameters['MAX_TRIES']
    scenarios, faults = scenario_rows(max_tries), fault_rows(max_tries)
    cases = [dict(id='scenarios', vectors=scenarios, mutation=args.demo_bug, category='functional', expected_failure=None),
             dict(id='single-flips', vectors=faults, mutation=args.demo_bug, category='functional', expected_failure=None)]
    for seed in range(args.seed, args.seed + (3 if args.profile == 'nightly' else 1)):
        cases.append(dict(id=f'random-seed{seed}', vectors=random_rows(max_tries, seed, args.iterations),
                          mutation=args.demo_bug, category='functional', expected_failure=None))
    cases += [dict(id='double-state-flips', vectors=double_state_rows(max_tries), mutation=0,
                   category='diagnostic', expected_failure=None),
              dict(id='double-counter-flip', vectors=double_counter_rows(max_tries), mutation=0,
                   category='diagnostic', expected_failure='FSM_ESCALATE')]
    for mutation in range(1, MUTANTS + 1):
        cases.append(dict(id=f'detect-mutation{mutation}', vectors=scenarios + faults, mutation=mutation,
                          category='mutation', expected_failure=LABELS[mutation]))
    for case in cases:
        check_rows(case['vectors'])
        case['counts'] = counts(case['vectors'])
    return cases


if __name__ == '__main__':
    spec = importlib.util.spec_from_file_location('local_runner', HERE.parent / 'local-common/runner.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    sys.exit(module.main(sys.modules[__name__]))

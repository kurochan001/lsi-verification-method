#!/usr/bin/env python3
"""Outstanding-transaction performance monitor with independent cycle model."""
import importlib.util
from pathlib import Path
import random
import sys

HERE = Path(__file__).resolve().parent
NAME = 'local-performance-monitor'
TOP = 'perf_monitor_tb'
CONFIGS = {'slots2': {'SLOTS': 2}, 'slots4': {'SLOTS': 4}}
ITERATIONS = {'smoke': 200, 'nightly': 1000}
SOURCES = [HERE / 'rtl/perf_monitor.sv', HERE / 'tb/perf_monitor_tb.sv']


class Plan:
    def __init__(self, slots):
        self.slots = slots
        self.rows = []
        self.reset()

    def reset(self):
        self.cycle = 0
        self.outstanding = [None] * 4
        self.start_time = [0] * 4
        self.total_done = 0
        self.total_max = 0
        self.window_done = 0
        self.window_cycles = 0
        self.window_max = 0
        self.window_active = 0
        self.error = 0

    def active(self):
        return sum(x is not None for x in self.outstanding[:self.slots])

    def step(self, rst=1, start=0, stop=0, req_valid=0, req_tag=0, resp_valid=0, resp_tag=0):
        req_tag &= 3
        resp_tag &= 3
        if not rst:
            self.rows.append([rst, start, stop, req_valid, req_tag, resp_valid, resp_tag,
                              0, 0, 0, 0, 0, 0, 0, 0])
            self.reset()
            return
        req_ready = int(self.outstanding[req_tag] is None)
        self.rows.append([rst, start, stop, req_valid, req_tag, resp_valid, resp_tag,
                          req_ready, self.total_done, self.total_max, self.window_done,
                          self.window_cycles, self.window_max, self.active(), self.error])
        window_count = self.window_active and not start
        if start:
            self.window_done = self.window_cycles = self.window_max = 0
            self.window_active = 1
        else:
            if self.window_active:
                self.window_cycles = (self.window_cycles + 1) & 0xffff
            if stop:
                self.window_active = 0
        if resp_valid:
            if self.outstanding[resp_tag] is not None:
                latency = (self.cycle - self.start_time[resp_tag]) & 0xffff
                latency8 = latency & 0xff
                self.outstanding[resp_tag] = None
                self.total_done = (self.total_done + 1) & 0xffff
                self.total_max = max(self.total_max, latency8)
                if window_count:
                    self.window_done = (self.window_done + 1) & 0xffff
                    self.window_max = max(self.window_max, latency8)
            else:
                self.error = 1
        if req_valid and req_ready:
            self.outstanding[req_tag] = self.cycle
            self.start_time[req_tag] = self.cycle
        if start:
            self.error = 0
        self.cycle = (self.cycle + 1) & 0xffff

    def fixed(self):
        tags = list(range(self.slots))
        self.step(rst=0)
        self.step(start=1)
        # Two accepts in consecutive cycles, out-of-order completions.
        self.step(req_valid=1, req_tag=tags[0])
        self.step(req_valid=1, req_tag=tags[1])
        self.step()
        self.step()
        self.step(resp_valid=1, resp_tag=tags[1])
        self.step(resp_valid=1, resp_tag=tags[0])
        # Fill every slot, stall on a busy tag, then drain in reverse order.
        for tag in tags:
            self.step(req_valid=1, req_tag=tag)
        self.step(req_valid=1, req_tag=tags[0])
        for tag in reversed(tags):
            self.step(resp_valid=1, resp_tag=tag)
        # Long latency raises the maximum.
        self.step(req_valid=1, req_tag=tags[0])
        for _ in range(12):
            self.step()
        self.step(resp_valid=1, resp_tag=tags[0])
        # Invalid response is reported and remains visible.
        self.step(resp_valid=1, resp_tag=tags[-1])
        self.step()
        # Start clears the error and resets the window; stop at a completion boundary.
        self.step(start=1)
        self.step(req_valid=1, req_tag=tags[0])
        self.step()
        self.step(stop=1, resp_valid=1, resp_tag=tags[0])
        self.step()
        # Reset and recover with a fresh window.
        self.step(rst=0)
        self.step(start=1)
        self.step(req_valid=1, req_tag=tags[0])
        self.step(resp_valid=1, resp_tag=tags[0])

    def random(self, rng, count):
        tags = list(range(self.slots))
        self.step(rst=0)
        self.step(start=1)
        for _ in range(count):
            if rng.randrange(200) == 0:
                self.step(rst=0)
                self.step(start=1)
                continue
            active = [tag for tag in tags if self.outstanding[tag] is not None]
            resp_valid = int(rng.randrange(3) == 0)
            resp_tag = rng.choice(active) if active and rng.randrange(4) != 0 else rng.choice(tags)
            self.step(start=int(rng.randrange(120) == 0), stop=int(rng.randrange(90) == 0),
                      req_valid=int(rng.randrange(2)), req_tag=rng.choice(tags),
                      resp_valid=resp_valid, resp_tag=resp_tag)


def vectors(seed, iterations, parameters, boundary=False):
    p = Plan(parameters['SLOTS'])
    p.fixed()
    if not boundary:
        p.random(random.Random(seed), iterations)
    return p.rows


def make_cases(args, parameters):
    base = vectors(args.seed, 0, parameters, True)
    cases = [dict(id='boundaries', vectors=base, mutation=args.demo_bug,
                  category='functional', expected_failure=None)]
    for seed in range(args.seed, args.seed + (3 if args.profile == 'nightly' else 1)):
        cases.append(dict(id=f'random-seed{seed}', vectors=vectors(seed, args.iterations, parameters),
                          mutation=args.demo_bug, category='functional', expected_failure=None))
    for mutation, label in ((1, 'PERF_LATENCY'), (2, 'PERF_ERROR'),
                            (3, 'PERF_WINDOW'), (4, 'PERF_COUNT')):
        cases.append(dict(id=f'detect-mutation{mutation}', vectors=base, mutation=mutation,
                          category='mutation', expected_failure=label))
    for case in cases:
        case['counts'] = {'steps': len(case['vectors'])}
    return cases


if __name__ == '__main__':
    spec = importlib.util.spec_from_file_location('local_runner', HERE.parent / 'local-common/runner.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    sys.exit(module.main(sys.modules[__name__]))

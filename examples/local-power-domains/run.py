#!/usr/bin/env python3
"""Two switched power domains: X injection and isolation checks generated from a power intent table (not UPF)."""
import importlib.util
from pathlib import Path
import random
import sys

HERE = Path(__file__).resolve().parent
NAME = 'local-power-domains'
TOP = 'pd_tb'
MUTANTS = 7
CONFIGS = {'settle2': {'SETTLE': 2}, 'settle4': {'SETTLE': 4}}
ITERATIONS = {'smoke': 60, 'nightly': 400}
INTENT = HERE / 'power_intent.json'
RTL = [HERE / 'rtl' / name for name in ('pd_domain_a.sv', 'pd_domain_b.sv', 'pd_ctrl.sv', 'pd_top.sv')]
SOURCES = [*RTL, HERE / 'tb/pd_tb.sv']
EXTRA_INPUTS = [INTENT, HERE / 'gen.py', HERE / 'model.py']
LABELS = {1: 'PD_XLEAK', 2: 'PD_ISO', 3: 'PD_RETAIN', 4: 'PD_INIT', 5: 'PD_STATE', 6: 'PD_SEQ', 7: 'PD_ACCEPT'}
RESET, OP, POWER, POWER_OP, POWER_REFUSE, POWER_BACK = range(6)


def load(name):
    spec = importlib.util.spec_from_file_location('power_domains_' + name, HERE / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


GEN = load('gen')
MODEL = load('model')


def intent():
    return GEN.load(INTENT)


def power_model_text(table=None, drop_injection=()):
    """Audit the table against the RTL of the domains, then generate the module."""
    table = table or intent()
    rtl = {'u_a': RTL[0].read_text(), 'u_b': RTL[1].read_text()}
    GEN.audit_registers(table, rtl)
    return GEN.generate(table, drop_injection)


def build_sources(args, configuration, parameters, mutation, directory):
    """The power model is generated for every build, so it cannot be older than the table."""
    directory.mkdir()
    execution = dict(command=[], returncode=0, error=None, seconds=0)
    generated = directory / 'pd_power_model.sv'
    try:
        generated.write_text(power_model_text())
    except (OSError, ValueError, KeyError) as exc:
        execution['error'] = f'power model not generated: {exc}'
        return [], execution
    return [*SOURCES, generated], execution


class Plan:
    """Rows for the bench; the expected columns come from the model after each row."""

    def __init__(self):
        self.model = MODEL.PowerModel(intent())
        self.rows = []
        self.counts = dict(ops_accepted=0, ops_refused=0, power_requests=0, resets=0)

    def _row(self, kind, a=0, b=0, c=0):
        seen = self.model.outputs()
        self.rows.append([kind, a, b, c, seen['a_sum'], seen['a_idle_n'], seen['a_last'], seen['b_count'],
                          seen['b_mode'], self.model.on['a'], self.model.on['b']])

    def _count(self, accepted):
        self.counts['ops_accepted' if accepted else 'ops_refused'] += 1

    def reset(self, a, b):
        self.model.reset()
        self.model.power(dict(a=a, b=b))
        self.counts['resets'] += 1
        self._row(RESET, a, b)

    def operate(self, select, data):
        accepted = self.model.operate(select, data)
        self._count(accepted)
        self._row(OP, select, data, int(accepted))

    def power(self, a, b):
        self.model.power(dict(a=a, b=b))
        self.counts['power_requests'] += 1
        self._row(POWER, a, b)

    def single_step(self, a, b):
        """The one domain that a request switches, or None when it switches none or both."""
        before = dict(self.model.on)
        after = self.model.target(dict(a=a, b=b))
        changed = [key for key in before if before[key] != after[key]]
        return (changed[0], after[changed[0]]) if len(changed) == 1 else None

    def power_with_operand(self, a, b, data):
        """A power-down request and, in the same cycle, an operand for that domain: it is accepted."""
        key, value = self.single_step(a, b)
        if value:
            raise ValueError('the operand in the request cycle needs a domain that goes down')
        select = int(key == 'b')
        if not self.model.operate(select, data):
            raise ValueError('domain is not on')
        self.model.power(dict(a=a, b=b))
        self._count(True)
        self.counts['power_requests'] += 1
        self._row(POWER_OP, a, b, select << 8 | data)

    def power_then_refused(self, a, b, data):
        """An operand one cycle after the request, for the domain that is switching: refused."""
        key, _ = self.single_step(a, b)
        self.model.power(dict(a=a, b=b))
        self._count(False)
        self.counts['power_requests'] += 1
        self._row(POWER_REFUSE, a, b, int(key == 'b') << 8 | data)

    def power_and_back(self, a, b, delay):
        """Switch one domain off and ask for it again `delay` cycles later: it still goes fully off first."""
        key, value = self.single_step(a, b)
        if value or not 1 <= delay <= 15:
            raise ValueError('needs a domain that goes down and a delay of 1..15 cycles')
        back = dict(self.model.on)
        self.model.power(dict(a=a, b=b))
        self.model.power(back)
        self.counts['power_requests'] += 2
        self._row(POWER_BACK, a, b, delay << 2 | back['a'] << 1 | back['b'])


def boundary_plan():
    p = Plan()
    p.reset(1, 1)                       # both domains come up from off, A first
    p.operate(0, 0x35)
    p.operate(0, 0x21)                  # acc 0x56, scratch 0x21
    p.operate(1, 0x8a)                  # mode 0xa
    p.operate(1, 0x05)
    p.operate(1, 0x0f)                  # count 0x14
    p.power(1, 0)                       # B off: count shows 0, mode holds 0xa
    p.operate(1, 0x03)                  # refused: B is off
    p.power(1, 1)                       # B on: mode retained, count back at reset
    p.operate(1, 0x03)
    p.power(0, 0)                       # both off, B first: a_last holds 0x21
    p.power(1, 1)                       # both on, A first: acc retained, scratch back at reset
    p.operate(0, 0x11)                  # acc 0x67: bit 0 now adds to the counter of B
    p.operate(1, 0x02)
    p.power_with_operand(1, 0, 0x83)    # mode 3 is written in the request cycle and must be saved
    p.power(1, 1)
    p.power(1, 0)
    p.power_with_operand(0, 0, 0x09)    # acc 0x70 and scratch 9 in the request cycle
    p.power_then_refused(1, 0, 0x44)    # A comes up: not ready one cycle later
    p.power_then_refused(0, 0, 0x45)    # A goes down: no longer ready
    p.power(0, 1)                       # B without A: nothing is powered
    p.operate(0, 0x01)                  # refused: A is off
    p.power(1, 0)
    p.operate(0, 0x02)
    p.power_and_back(0, 0, 2)           # A asked back during its power-down
    p.power(1, 1)
    p.operate(1, 0x07)
    p.operate(1, 0x8c)
    p.power_and_back(1, 0, 1)           # B asked back during its power-down
    p.reset(1, 0)                       # global reset while both are on: retained values are gone
    p.operate(0, 0x10)
    p.power(0, 0)
    p.reset(1, 1)                       # global reset while both are off
    p.operate(0, 0x7f)
    p.operate(1, 0x0e)
    return p


def random_plan(seed, operations):
    rng = random.Random(seed)
    p = Plan()
    p.reset(rng.randrange(2), rng.randrange(2))
    while len(p.rows) <= operations:
        roll = rng.random()
        a, b = rng.randrange(2), rng.randrange(2)
        data = rng.choice((0x00, 0x01, 0x0f, 0x80, 0x8f, 0xff)) if rng.random() < 0.2 else rng.randrange(256)
        step = p.single_step(a, b)
        if roll < 0.5:
            p.operate(rng.randrange(2), data)
        elif roll < 0.53:
            p.reset(a, b)
        elif roll < 0.63 and step and not step[1]:
            p.power_with_operand(a, b, data)
        elif roll < 0.73 and step:
            p.power_then_refused(a, b, data)
        elif roll < 0.83 and step and not step[1]:
            p.power_and_back(a, b, rng.choice((1, 1, 2, 3, 4, 6, 9)))
        else:
            p.power(a, b)
    return p


def make_cases(args, parameters):
    base = boundary_plan()
    plans = [('boundaries', base, args.demo_bug, 'functional', None)]
    for seed in range(args.seed, args.seed + (3 if args.profile == 'nightly' else 1)):
        plans.append((f'random-seed{seed}', random_plan(seed, args.iterations), args.demo_bug, 'functional', None))
    for mutation in range(1, MUTANTS + 1):
        plans.append((f'detect-mutation{mutation}', base, mutation, 'mutation', LABELS[mutation]))
    return [dict(id=name, vectors=plan.rows, mutation=mutation, category=category, expected_failure=label,
                 counts=dict(plan.counts)) for name, plan, mutation, category, label in plans]


if __name__ == '__main__':
    spec = importlib.util.spec_from_file_location('local_runner', HERE.parent / 'local-common/runner.py')
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)
    sys.exit(runner.main(sys.modules[__name__]))

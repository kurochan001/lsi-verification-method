#!/usr/bin/env python3
"""Noise source health tests: repetition count, adaptive proportion, start-up, suppression and the false alarm rate."""
import importlib.util
import itertools
import math
from pathlib import Path
import random
import sys

HERE = Path(__file__).resolve().parent
NAME = 'local-trng-health'
TOP = 'trng_tb'
SOURCES = [HERE / 'rtl/trng_health.sv', HERE / 'tb/trng_tb.sv']
MUTANTS = 8
LABELS = {1: 'TRNG_RCT', 2: 'TRNG_APT', 3: 'TRNG_RCT', 4: 'TRNG_APT', 5: 'TRNG_OUTPUT',
          6: 'TRNG_READY', 7: 'TRNG_APT', 8: 'TRNG_RCT'}
ITERATIONS = {'smoke': 200, 'nightly': 600}     # statistic trials of the teaching configuration
MAXC = 8192                                     # cycles one trial row holds (the bench's register width)
TAIL = 0.0005                                   # each side of an acceptance range


# --- Cutoffs from the false alarm probability -------------------------------------------------
# The source is binary and assessed at full entropy (H = 1 bit per sample), so a sample equals
# any given value with probability 1/2. Both cutoffs are the smallest count whose probability
# under that source is at most 2**-alpha.

def rct_cutoff(alpha):
    """A run of C equal samples starts at a given sample with probability 2**-(C-1)."""
    return 1 + alpha


def apt_tail(window, cutoff):
    """P(count >= cutoff): the count is 1 (the window's first sample) + Binomial(window-1, 1/2)."""
    return sum(math.comb(window - 1, k) for k in range(max(cutoff - 1, 0), window)) / 2 ** (window - 1)


def apt_cutoff(window, alpha):
    total = 1 << (window - 1)
    for cutoff in range(2, window + 1):
        if sum(math.comb(window - 1, k) for k in range(cutoff - 1, window)) << alpha <= total:
            return cutoff
    raise ValueError('no cutoff reaches the false alarm probability')


# A teaching configuration with false alarm probabilities high enough to count, and one with the
# probabilities of a product design. STARTUP is one APT window in both.
DESIGN = {
    'fast': dict(W=64, rct_alpha=8, apt_alpha=4, trial=256, degrade=2048, biases=(1.0, 0.9, 0.75)),
    'std': dict(W=1024, rct_alpha=20, apt_alpha=20, trial=2048, degrade=MAXC, biases=(1.0, 0.75, 0.6)),
}
CONFIGS = {name: dict(W=d['W'], RCT_CUTOFF=rct_cutoff(d['rct_alpha']), APT_CUTOFF=apt_cutoff(d['W'], d['apt_alpha']),
                      STARTUP=d['W']) for name, d in DESIGN.items()}


def name_of(parameters):
    return next(name for name, config in CONFIGS.items() if config == parameters)


def statistic_trials(name, iterations):
    return iterations if name == 'fast' else max(4, iterations // 8)


# --- Exact false alarm probability of one trial ----------------------------------------------

def p_run(length, cutoff):
    """P(a fair binary sequence of this length contains a run of at least cutoff equal values)."""
    ways = [0] * cutoff               # ways[r]: sequences so far whose last run has length r < cutoff
    ways[1] = 2
    for _ in range(length - 1):
        nxt = [0] * cutoff
        nxt[1] = sum(ways)            # the next value differs
        for r in range(1, cutoff - 1):
            nxt[r + 1] += ways[r]     # the next value repeats
        ways = nxt
    return 1 - sum(ways) / 2 ** length


def trial_probabilities(name):
    d, p = DESIGN[name], CONFIGS[name]
    if d['trial'] % p['W']:
        raise ValueError('a statistic trial must hold whole APT windows')
    windows = d['trial'] // p['W']
    return p_run(d['trial'], p['RCT_CUTOFF']), 1 - (1 - apt_tail(p['W'], p['APT_CUTOFF'])) ** windows


def acceptance(trials, q, tail=TAIL):
    """Narrowest count range with at most `tail` probability outside on each side."""
    pmf = [math.comb(trials, k) * q ** k * (1 - q) ** (trials - k) for k in range(trials + 1)]
    low, below = 0, 0.0
    while below + pmf[low] <= tail:
        below += pmf[low]
        low += 1
    high, above = trials, 0.0
    while above + pmf[high] <= tail:
        above += pmf[high]
        high -= 1
    return low, high


# --- Independent model -----------------------------------------------------------------------
# Written over the list of accepted samples, not as a clocked machine: runs from groupby, windows
# by slicing. It returns the indices (1-based, 0 for none) the bench needs.

def evaluate(trial, parameters):
    w, cr, ca, startup = (parameters[k] for k in ('W', 'RCT_CUTOFF', 'APT_CUTOFF', 'STARTUP'))
    samples = [bit for valid, bit in trial if valid]
    rct, start = 0, 0
    for _, group in itertools.groupby(samples):
        length = len(list(group))
        if length >= cr:
            rct = start + cr
            break
        start += length
    apt = 0
    for first in range(0, len(samples), w):
        window = samples[first:first + w]
        hits = [i for i, bit in enumerate(window) if bit == window[0]]
        if len(hits) >= ca:
            apt = first + hits[ca - 1] + 1
            break
    failure = min([x for x in (rct, apt) if x], default=0)
    ready = startup if failure == 0 or failure > startup else 0
    last = failure - 1 if failure else len(samples)
    outputs = max(0, last - startup) if ready else 0
    return dict(samples=len(samples), ready=ready, rct=rct, apt=apt, outputs=outputs)


def row(trial, parameters, tag=0):
    if len(trial) > MAXC:
        raise ValueError('trial longer than the bench holds')
    e = evaluate(trial, parameters)
    vmask = sum(valid << i for i, (valid, _) in enumerate(trial))
    dmask = sum(bit << i for i, (_, bit) in enumerate(trial))
    return [1, len(trial), vmask, dmask, e['ready'], e['rct'], e['apt'], e['outputs'], tag], e


# Scenario tags (bits of the last column): what a trial was built to show.
STUCK, BIASED, ALTERNATING, STATISTIC, AFTER_RCT_TAIL, WINDOW_EDGE, AFTER_APT_TAIL, POWER_ON = (1 << i for i in range(8))


class Plan:
    def __init__(self, parameters):
        self.p = parameters
        self.rows = []
        self.cycles = []
        self.tag = 0

    def start(self, tag=0):
        self.cycles, self.tag = [], tag

    def bits(self, values):
        self.cycles += [(1, b) for b in values]

    def idle(self, count, bit):
        self.cycles += [(0, bit)] * count

    def end(self, **expect):
        r, e = row(self.cycles, self.p, self.tag)
        for key, value in expect.items():          # the scenario is checked against its intent
            got = e[key] if key != 'ready' else bool(e['ready'])
            if got != value:
                raise ValueError(f'scenario intent differs: {key} expected {value}, model gives {got}')
        self.rows.append(r)
        return e


def alt(count, last):
    """Alternating values ending with `last`."""
    return [(last + count - 1 - i) % 2 for i in range(count)]


def spread(ref, matches, length, end_on_match=False):
    """`length` samples starting with ref, holding `matches` ref values spread evenly."""
    if end_on_match:
        places = {round(k * (length - 1) / (matches - 1)) for k in range(matches)}
    else:
        places = {k * length // matches for k in range(matches)}
    if len(places) != matches or 0 not in places:
        raise ValueError('cannot spread the matches')
    return [ref if i in places else 1 - ref for i in range(length)]


def dense(first, length):
    """`first`, then three ones in every four samples: short runs, many ones."""
    return [first] + [0 if i % 4 == 3 else 1 for i in range(length - 1)]


def boundary_vectors(parameters):
    """Every rule on purpose, each at the cutoff and one below it."""
    p = Plan(parameters)
    w, cr, ca, s = (parameters[k] for k in ('W', 'RCT_CUTOFF', 'APT_CUTOFF', 'STARTUP'))
    # Runs one below the cutoff, with idle cycles inside one of them, after a power-on reset.
    p.start(POWER_ON)
    p.bits(alt(s, 1) + [0])
    p.bits([1] * 3)
    p.idle(2, 0)                                   # idle cycles carry the other value; they are not samples
    p.bits([1] * (cr - 4))
    p.idle(1, 1)                                   # an idle cycle carrying the run's value is no repetition
    p.bits([0] * (cr - 1) + alt(w, 0))
    p.end(ready=True, rct=0, apt=0)
    # A run at the cutoff after start-up; the alarm stays while the samples keep changing.
    p.start()
    p.bits(alt(s, 0) + [1] * cr + alt(2 * w, 0))
    p.end(ready=True, rct=s + cr, apt=0)
    # After an alarm, a restart and a long alternating source: no test fails.
    p.start(ALTERNATING)
    p.bits(alt(6 * w, 1))
    p.end(ready=True, rct=0, apt=0)
    # A run of zeros at the cutoff with idle cycles inside it.
    p.start()
    p.bits(alt(s, 1) + [0] * 3)
    p.idle(2, 1)
    p.bits([0] * (cr - 3) + alt(w, 0))
    p.end(ready=True, rct=s + cr, apt=0)
    # Windows one below the APT cutoff; the next window starts with the same value.
    # An idle cycle carrying the reference value follows the last match of the first window.
    p.start(WINDOW_EDGE)
    first = spread(1, ca - 1, w)
    cut = max(i for i, bit in enumerate(first) if bit == 1) + 1
    p.bits(alt(s, 0) + first[:cut])
    p.idle(2, 1)
    p.bits(first[cut:] + spread(1, ca - 1, w) + spread(0, ca - 1, w) + alt(w, 1))
    p.end(ready=True, rct=0, apt=0)
    # The APT cutoff reached on the last sample of a window, reference value 1.
    p.start()
    p.bits(alt(s, 0) + spread(1, ca, w, end_on_match=True) + alt(w, 0))
    p.end(ready=True, rct=0, apt=s + w)
    # The APT cutoff reached in the middle of a window, reference value 0.
    p.start()
    p.bits(alt(s, 1) + spread(0, ca, 3 * w // 4) + alt(w // 4, 0) + alt(w, 0))
    e = p.end(ready=True, rct=0)
    if not s < e['apt'] < s + 3 * w // 4:
        raise ValueError('the mid-window APT failure is not in the middle of the window')
    # Start-up failures: the RCT, the APT, and the RCT on the very last start-up sample.
    p.start()
    p.bits([1] * cr + alt(w, 0))
    p.end(ready=False, rct=cr)
    p.start()
    p.bits(spread(1, ca, w) + alt(w, 0))
    e = p.end(ready=False, rct=0)
    if not 0 < e['apt'] <= s:
        raise ValueError('the start-up APT failure is not in start-up')
    p.start()
    p.bits(alt(s - cr, 0) + [1] * cr + alt(w, 0))
    p.end(ready=False, rct=s)
    # The first sample after start-up fails: ready rises, nothing is ever output.
    p.start()
    p.bits(alt(s - cr + 1, 0) + [1] * cr + alt(w, 0))
    p.end(ready=True, rct=s + 1, outputs=0)
    # A stuck source after start-up: both tests fail.
    p.start(STUCK)
    p.bits(alt(s, 0) + [1] * w + alt(w, 0))
    p.end(ready=True, rct=s + cr, apt=s + ca)
    # A trial ends on a run one below the cutoff; the next starts with the same value.
    p.start()
    p.bits(alt(s, 0) + alt(w, 0) + [1] * (cr - 1))
    p.end(ready=True, rct=0, apt=0)
    p.start(AFTER_RCT_TAIL)
    p.bits([1] + alt(s + w - 1, 0))
    p.end(ready=True, rct=0, apt=0)
    # A trial ends in the middle of a window full of ones; the next starts with many ones.
    p.start()
    p.bits(alt(s, 0) + dense(1, w // 2))
    p.end(ready=True, rct=0, apt=0)
    p.start(AFTER_APT_TAIL)
    p.bits(dense(0, w) + alt(w, 1))
    p.end(ready=True, rct=0, apt=0)
    return p.rows


def fair_bits(rng, count):
    value = rng.getrandbits(count)
    return [(value >> i) & 1 for i in range(count)]


def statistic_vectors(name, seed, trials, parameters=None):
    """Independent trials of an ideal source, then the judge row with the acceptance ranges."""
    parameters = parameters or CONFIGS[name]
    rng = random.Random(f'{NAME}-{name}-statistic-{seed}')
    rows = [row([(1, b) for b in fair_bits(rng, DESIGN[name]['trial'])], parameters, STATISTIC)[0]
            for _ in range(trials)]
    q_rct, q_apt = trial_probabilities(name)        # from the design cutoffs, never from `parameters`
    (lr, hr), (la, ha) = acceptance(trials, q_rct), acceptance(trials, q_apt)
    return rows + [[2, lr, hr, la, ha, trials, 0, 0, 0]]


def degrade_vectors(name, seed):
    """A healthy source that turns stuck or biased after start-up; the bias value is random."""
    d, parameters = DESIGN[name], CONFIGS[name]
    rng = random.Random(f'{NAME}-{name}-degrade-{seed}')
    w = parameters['W']
    rows = []
    for bias in d['biases']:
        for _ in range(2):
            value = rng.randrange(2)
            healthy = fair_bits(rng, parameters['STARTUP'] + 2 * w)
            while evaluate([(1, b) for b in healthy], parameters)['outputs'] != 2 * w:
                healthy = fair_bits(rng, len(healthy))     # redraw until the healthy part raises no alarm
            bad = [value if rng.random() < bias else 1 - value for _ in range(d['degrade'] - len(healthy))]
            rows.append(row([(1, b) for b in healthy + bad], parameters, STUCK if bias == 1.0 else BIASED)[0])
    return rows


def counts(rows):
    trials = [r for r in rows if r[0] == 1]
    return dict(trials=len(trials), samples=sum(bin(r[2]).count('1') for r in trials),
                outputs=sum(r[7] for r in trials), rct_alarms=sum(r[5] != 0 for r in trials),
                apt_alarms=sum(r[6] != 0 for r in trials))


def make_cases(args, parameters):
    name = name_of(parameters)
    trials = statistic_trials(name, args.iterations)
    seeds = range(args.seed, args.seed + (3 if args.profile == 'nightly' else 1))
    baseline = boundary_vectors(parameters)
    cases = [dict(id='boundaries', vectors=baseline, mutation=args.demo_bug, category='functional', expected_failure=None)]
    for seed in seeds:
        cases.append(dict(id=f'statistic-seed{seed}', vectors=statistic_vectors(name, seed, trials),
                          mutation=args.demo_bug, category='functional', expected_failure=None))
    for seed in seeds:
        cases.append(dict(id=f'degrade-seed{seed}', vectors=degrade_vectors(name, seed),
                          mutation=args.demo_bug, category='functional', expected_failure=None))
    for mutation in range(1, MUTANTS + 1):
        cases.append(dict(id=f'detect-mutation{mutation}', vectors=baseline, mutation=mutation,
                          category='mutation', expected_failure=LABELS[mutation]))
    # The RCT cutoff one too low in both the hardware and the model: every cycle agrees, and only
    # the alarm count against the designed false alarm probability shows it. With the
    # probabilities of a product design the count cannot show it in this many trials.
    shared = dict(parameters, RCT_CUTOFF=parameters['RCT_CUTOFF'] - 1)
    common = statistic_vectors(name, args.seed, trials, shared)
    if name == 'fast':
        cases.append(dict(id='detect-mutation1-common-mode', vectors=common, mutation=1,
                          category='mutation', expected_failure='TRNG_RATE'))
    else:
        cases.append(dict(id='survive-mutation1-common-mode', vectors=common, mutation=1,
                          category='diagnostic', expected_failure=None))
    for case in cases:
        case['counts'] = counts(case['vectors'])
    return cases


if __name__ == '__main__':
    spec = importlib.util.spec_from_file_location('local_runner', HERE.parent / 'local-common/runner.py')
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)
    sys.exit(runner.main(sys.modules[__name__]))

"""Fault list, structural exclusion, injector generation, classification and statistics.

Nothing here depends on the simulator: the functions read a Yosys JSON netlist, write a generated
include file for the test bench, and classify a faulty trace against the golden trace.
"""
from collections import deque
import functools
import math
import re

CLASSES = ('no_effect', 'detected', 'undetected', 'timeout')
CLASS_NAMES = {'no_effect': '影響なし', 'detected': '安全機構が検出', 'undetected': '検出されず出力が相違', 'timeout': '時間切れ'}
FF_TYPES = re.compile(r'^\$(a?dff|dffe|adffe|sdff|sdffe|sdffce|dffsr|dffsre|aldff|aldffe)$')


# ----- the circuit ---------------------------------------------------------------------------

def module(netlist, top):
    return netlist['modules'][top]


def bit_name(m, bit):
    """The register name of a flip-flop output bit. A Q bit can carry several visible names when it
    also drives an output port under another name; the name that is not a port is the register."""
    candidates = [(name, net['bits'].index(bit)) for name, net in m['netnames'].items()
                  if not net.get('hide_name') and bit in net['bits']]
    if len(candidates) > 1:
        candidates = [c for c in candidates if c[0] not in m['ports']] or candidates
    if len(candidates) != 1:
        raise ValueError(f'flip-flop bit without a unique name: {candidates}')
    return candidates[0]


def flip_flops(netlist, top):
    """[(register, width)] from the flip-flop cells of the netlist, named by the nets their Q bits drive.

    A combinational `reg` (an always @* variable) has no flip-flop cell and does not appear."""
    m = module(netlist, top)
    width = {}
    total = 0
    for cell in m['cells'].values():
        if not FF_TYPES.match(cell['type']):
            continue
        for bit in cell['connections']['Q']:
            name, index = bit_name(m, bit)
            width[name] = max(width.get(name, 0), index + 1)
            total += 1
    if sum(width.values()) != total:
        raise ValueError('flip-flop bits are not contiguous registers')
    return sorted(width.items())


def declared_regs(text):
    """The naive list: every name declared with `reg`, including combinational variables."""
    text = re.sub(r'//[^\n]*', '', text)
    found = {}
    for match in re.finditer(r'\breg\b\s*(?:\[(\d+):(\d+)\])?', text):
        width = int(match[1]) - int(match[2]) + 1 if match[1] else 1
        rest = re.split(r'[;)]', text[match.end():], maxsplit=1)[0]
        for piece in rest.split(','):
            if re.search(r'\b(input|output|inout|wire|reg)\b', piece):
                break
            name = re.match(r'\s*([A-Za-z_]\w*)', piece)
            if name:
                found[name[1]] = width
    return sorted(found.items())


def cones(netlist, top):
    """For every flip-flop bit, the set of output ports its value can reach through any cell.

    Every cell input is taken to influence every cell output, so the result over-approximates the
    real dependence: a bit reported as unreachable cannot influence that output."""
    m = module(netlist, top)
    fanout = {}
    for cell in m['cells'].values():
        directions = cell.get('port_directions', {})
        sources = [b for p, bits in cell['connections'].items() if directions.get(p) == 'input' for b in bits if isinstance(b, int)]
        sinks = [b for p, bits in cell['connections'].items() if directions.get(p) == 'output' for b in bits if isinstance(b, int)]
        for s in sources:
            fanout.setdefault(s, set()).update(sinks)
    outputs = {}
    for port, info in m['ports'].items():
        if info['direction'] == 'output':
            for bit in info['bits']:
                if isinstance(bit, int):
                    outputs.setdefault(bit, set()).add(port)
    result = {}
    for cell in m['cells'].values():
        if not FF_TYPES.match(cell['type']):
            continue
        for bit in cell['connections']['Q']:
            seen, queue, reached = {bit}, deque([bit]), set()
            while queue:
                b = queue.popleft()
                reached |= outputs.get(b, set())
                for nxt in fanout.get(b, ()):
                    if nxt not in seen:
                        seen.add(nxt)
                        queue.append(nxt)
            result[bit_name(m, bit)] = sorted(reached)
    return result


def exclusions(cone_map, observed):
    """Bits whose cone reaches none of the observed outputs, with the outputs they do reach."""
    return sorted((reg, bit, reached) for (reg, bit), reached in cone_map.items() if not set(reached) & set(observed))


# ----- the injector --------------------------------------------------------------------------

def injector(registers, bug=0):
    """Generated include for the bench: flip, force, release and read back each register bit.

    bug 1 swaps the first two registers in every task; bug 2 makes the flip write the old value."""
    names = [name for name, _ in registers]
    target = list(names)
    if bug == 1:
        target[0], target[1] = target[1], target[0]
    width = dict(registers)

    def ref(i, bit=None):
        name = target[i]
        if width[name] == 1:
            return f'dut.{name}'
        return f'dut.{name}[{bit}]' if bit is not None else f'dut.{name}[b]'

    lines = ['// Generated by campaign.py from the flip-flops Yosys extracted; do not edit.',
             f'localparam integer NREG = {len(names)};',
             'task automatic flip_bit(input integer r, input integer b);', '    case (r)']
    for i, name in enumerate(names):
        lines.append(f'        {i}: {ref(i)} = {ref(i) if bug == 2 else "~" + ref(i)};  // {name}')
    lines += ['        default: $fatal(1, "bad register %0d", r);', '    endcase', 'endtask',
              'task automatic force_bit(input integer r, input integer b, input integer v);', '    case (r * 64 + b)']
    for i, name in enumerate(names):
        for bit in range(width[name]):
            r = ref(i, bit)
            lines.append(f"        {i * 64 + bit}: if (v != 0) force {r} = 1'b1; else force {r} = 1'b0;  // {name}[{bit}]")
    lines += ['        default: $fatal(1, "bad bit %0d %0d", r, b);', '    endcase', 'endtask',
              'task automatic release_all;', '    begin']
    for i, name in enumerate(names):
        for bit in range(width[name]):
            lines.append(f'        release {ref(i, bit)};')
    lines += ['    end', 'endtask', 'function automatic integer read_bit(input integer r, input integer b);', '    case (r)']
    for i, name in enumerate(names):
        lines.append(f'        {i}: read_bit = {ref(i)};')
    lines += ['        default: read_bit = -1;', '    endcase', 'endfunction', '']
    return '\n'.join(lines)


# ----- classification ------------------------------------------------------------------------

def first_differences(golden, faulty):
    """(first cycle the alarm rose although the golden run had none, first cycle a functional output
    differed, a golden alarm was missing, or one trace ended before the other)."""
    alarm = functional = None
    for cycle, (g, f) in enumerate(zip(golden, faulty)):
        g_result, g_done, g_error = g[5], g[6], g[7]
        f_result, f_done, f_error = f[5], f[6], f[7]
        if alarm is None and f_error and not g_error:
            alarm = cycle
        if functional is None and ((g_result, g_done) != (f_result, f_done) or (g_error and not f_error)):
            functional = cycle
    if functional is None and len(golden) != len(faulty):
        functional = min(len(golden), len(faulty))
    return alarm, functional


def classify(golden, faulty, status, bug=0):
    """One of CLASSES for a faulty run.

    bug 1 counts a timeout as no effect; bug 2 ignores whether the alarm came before the wrong output;
    bug 3 compares only the last row; bug 5 counts a missing golden alarm as a detection."""
    if status in ('stall', 'cap') and bug != 1:
        return 'timeout'
    if bug == 3:
        same = (golden[-1][5:8] == faulty[-1][5:8]) if golden and faulty else golden == faulty
        alarm = next((c for c, row in enumerate(faulty) if row[7] and (c >= len(golden) or not golden[c][7])), None)
        if alarm is not None:
            return 'detected'
        return 'no_effect' if same else 'undetected'
    alarm, functional = first_differences(golden, faulty)
    if bug == 5:
        missing = next((c for c, (g, f) in enumerate(zip(golden, faulty)) if g[7] and not f[7]), None)
        if missing is not None and (alarm is None or missing < alarm):
            alarm = missing
    if alarm is not None and (bug == 2 or functional is None or alarm <= functional):
        return 'detected'
    if functional is not None:
        return 'undetected'
    return 'no_effect'


# ----- statistics and accounting ---------------------------------------------------------------

def _log_binom_pmf(k, n, p):
    if p <= 0.0:
        return 0.0 if k == 0 else -math.inf
    if p >= 1.0:
        return 0.0 if k == n else -math.inf
    return math.lgamma(n + 1) - math.lgamma(k + 1) - math.lgamma(n - k + 1) + k * math.log(p) + (n - k) * math.log1p(-p)


def binom_cdf(k, n, p):
    """P(X <= k) for X ~ Binomial(n, p), summing the shorter tail."""
    if k < 0:
        return 0.0
    if k >= n:
        return 1.0
    if k <= n // 2:
        return min(1.0, sum(math.exp(_log_binom_pmf(i, n, p)) for i in range(k + 1)))
    return max(0.0, 1.0 - sum(math.exp(_log_binom_pmf(i, n, p)) for i in range(k + 1, n + 1)))


@functools.lru_cache(maxsize=None)
def exact_interval(k, n, alpha):
    """Two-sided Clopper-Pearson interval with alpha/2 in each tail, by bisection on the binomial tails."""
    if n <= 0 or not 0 <= k <= n:
        raise ValueError('need 0 <= k <= n and n > 0')

    def solve(f):
        lo, hi = 0.0, 1.0
        for _ in range(60):
            mid = (lo + hi) / 2
            if f(mid):
                hi = mid
            else:
                lo = mid
        return (lo + hi) / 2
    lower = 0.0 if k == 0 else solve(lambda p: 1.0 - binom_cdf(k - 1, n, p) >= alpha / 2)
    upper = 1.0 if k == n else solve(lambda p: binom_cdf(k, n, p) <= alpha / 2)
    return lower, upper


def tally(records, bug=0):
    """Counts and rates with named denominators. records: dicts with `cls` and `excluded`.

    detection_rate  = detected / affected, affected = detected + undetected + timeout (target faults only)
    no_effect_share = no_effect / target
    bug 4 lets excluded faults into the denominators."""
    target = [r for r in records if bug == 4 or not r['excluded']]
    counts = {c: sum(r['cls'] == c for r in target) for c in CLASSES}
    affected = counts['detected'] + counts['undetected'] + counts['timeout']
    return dict(all=len(records), excluded=sum(r['excluded'] for r in records), target=len(target), counts=counts,
                affected=affected,
                detection_rate=counts['detected'] / affected if affected else None,
                no_effect_share=counts['no_effect'] / len(target) if target else None)

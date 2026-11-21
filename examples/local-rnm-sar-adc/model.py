"""Independent expectations for the SAR ADC example.

Three things live here, each written differently from the circuit it judges:

* `exact_code` finds the conversion result from its definition (the one code whose every bit
  agrees with the comparison it stands for), with exact rational arithmetic.  The RTL and the
  SPICE driver use the usual bit-by-bit search instead.
* `Timeline` lays the expected pins of the SAR logic out on a clock axis, conversion by
  conversion.  The RTL is a state machine.
* The settling formulas are the closed-form solution of the sampling network (two poles) and of
  one trial step (one pole).  ngspice integrates the same network numerically.
"""
from fractions import Fraction
import math
import random

VREF_UV = 1_024_000          # reference voltage, microvolts
UNIT_AF = 100_000            # unit capacitor, attofarads (100 fF)
TAU_S = 1.0e-9               # switch resistance times its capacitor, every branch (seconds)
RON_OHM = 50.0               # top-plate sampling switch while closed
CP_RATIO = Fraction(1, 5)    # top-plate parasitic as a fraction of the nominal array
SLOW_S = 40.0e-9             # clock period used for the model comparison
FAST_S = 2.0e-9              # clock period that is far too short to settle
SWEEP_SMOKE = (0.5, 1.25)    # further periods, as multiples of the computed minimum period
SWEEP_NIGHTLY = (0.25, 0.5, 0.75, 1.1, 1.25, 2.0)
# Real-number model against settled ngspice, top-plate voltage.  What can separate them at the
# slow clock: the sampling shortfall (below 0.1 uV), the solver tolerance (reltol 1e-6 of at
# most 0.45 V) and the 1 nV rounding of the trace.  2 uV leaves a factor of three.
VTOP_TOLERANCE_V = 2e-6
# ngspice waveform against the closed forms, with the tight solver settings (measured 3-8 uV).
ANALYTIC_TOLERANCE_V = 20e-6


class Mismatch(Exception):
    def __init__(self, label, message):
        super().__init__(message)
        self.label = label


def nominal_caps(bits):
    """Binary-weighted array plus one terminating unit, in attofarads.  Index = bit number;
    the last entry is the terminating capacitor, which no code bit ever switches."""
    return [UNIT_AF << k for k in range(bits)] + [UNIT_AF]


def parasitic(bits):
    return int(CP_RATIO * sum(nominal_caps(bits)))


def threshold(code, caps):
    """Input voltage (microvolts, exact) at which the comparator flips for this DAC code."""
    switched = sum(c for k, c in enumerate(caps[:-1]) if code >> k & 1)
    return Fraction(VREF_UV * switched, sum(caps))


def exact_code(vin_uv, caps):
    """The conversion result, found from its definition rather than by searching bit by bit:
    the code in which bit j is set exactly when the input exceeds the threshold of that bit
    placed on top of the bits above it.  Exactly one code satisfies this."""
    bits = len(caps) - 1
    vin = Fraction(vin_uv)
    found = []
    for code in range(1 << bits):
        consistent = True
        for j in range(bits):
            above = code >> (j + 1) << (j + 1)
            keeps = vin > threshold(above | 1 << j, caps)
            if keeps != bool(code >> j & 1):
                consistent = False
                break
        if consistent:
            found.append(code)
    if len(found) != 1:
        raise ValueError(f'definition does not select one code: {found}')
    return found[0]


def trials(code, bits):
    """DAC codes presented in the trial cycles of a conversion that ends in `code`."""
    return [(code >> (j + 1) << (j + 1)) | 1 << j for j in reversed(range(bits))]


def decisions(code, bits):
    return [code >> j & 1 for j in reversed(range(bits))]


def margin_uv(vin_uv, caps):
    """Distance from the input to the nearest threshold of any code, in microvolts."""
    bits = len(caps) - 1
    return min(abs(Fraction(vin_uv) - threshold(code, caps)) for code in range(1, 1 << bits))


def guard_uv(bits):
    """Inputs are kept this far from every threshold: one eighth of a nominal step."""
    return VREF_UV // (8 << bits)


def ramp(caps, points_per_step=4, extra=()):
    """Evenly spaced inputs that never sit closer than the guard to a threshold.  For the
    nominal array this is every quarter step, offset by an eighth."""
    bits = len(caps) - 1
    step = VREF_UV // (points_per_step << bits)
    values = [step // 2 + step * n for n in range(points_per_step << bits)]
    values += list(extra)
    guard = guard_uv(bits)
    return [v for v in values if margin_uv(v, caps) >= guard]


def edges(caps):
    """Just below and just above every threshold of the nominal ordering, plus the ends."""
    bits = len(caps) - 1
    guard = guard_uv(bits)
    values = []
    for code in range(1, 1 << bits):
        level = threshold(code, caps)
        for candidate in (math.floor(level) - guard, math.ceil(level) + guard):
            if margin_uv(candidate, caps) >= guard:
                values.append(candidate)
    return values


def outside(bits):
    """Inputs beyond the two rails; the ideal switches clamp nothing, the code saturates."""
    return [-VREF_UV // 10, VREF_UV + VREF_UV // 10]


# --------------------------------------------------------------------------- SAR logic timeline

class Timeline:
    """Expected pins of sar_logic on a clock axis.

    Row r holds the inputs applied before clock edge r and the outputs seen after it.  A
    conversion accepted at edge a occupies: a+0 sample, a+1 .. a+bits one trial each,
    a+bits+1 done.  Rows are written conversion by conversion; nothing here steps a state."""
    FIELDS = ('rst_n', 'start', 'vin', 'cmp_ext', 'ready', 'sample', 'dac', 'busy', 'done',
              'result', 'cmp', 'check_cmp')

    def __init__(self, bits, caps):
        self.bits, self.caps = bits, caps
        self.rows = []
        self.result = 0          # value on the result pins
        self.free = 0            # first edge at which a start can be accepted
        self.conversions = []    # (accept edge, sampled input, code)
        self.goals = set()

    def _row(self, index):
        while len(self.rows) <= index:
            self.rows.append(dict(rst_n=1, start=0, vin=0, cmp_ext=0, ready=1, sample=0, dac=0,
                                  busy=0, done=0, result=self.result, cmp=0, check_cmp=0))
        return self.rows[index]

    def idle(self, cycles, vin=0):
        for _ in range(cycles):
            self._row(self.free)['vin'] = vin & 0xffffffff
            self.free += 1
        if cycles:
            self.goals.add('start/idle-gap')

    def convert(self, vin_uv, hold_start=False, later_vin=None, external=None, early_vin=None):
        """One conversion starting at the next free edge.  `external` replaces the decisions
        (used when replaying the comparator answers that ngspice produced).  `early_vin` is a
        different input shown while the start is taken; the array tracks the pin until the end
        of the sample cycle, so only `vin_uv` counts."""
        bits = self.bits
        code = exact_code(vin_uv, self.caps)
        answers = decisions(code, bits) if external is None else list(external)
        final = 0
        shown = []
        for j, answer in zip(reversed(range(bits)), answers):
            shown.append(final | 1 << j)
            final |= answer << j
        a = self.free
        if a and self.rows[a - 1]['done']:
            self.goals.add('start/back-to-back')
        first = self._row(a)
        first.update(start=1, vin=(vin_uv if early_vin is None else early_vin) & 0xffffffff,
                     ready=0, sample=1, busy=1)
        if early_vin is not None and early_vin != vin_uv:
            self.goals.add('input/track-until-sample-end')
        for offset in range(1, bits + 2):
            row = self._row(a + offset)
            # The array samples at the edge that ends the sample cycle (row a+1), so the input
            # may only move from the row after that.
            row.update(ready=0, busy=1, result=self.result,
                       vin=(vin_uv if later_vin is None or offset < 2 else later_vin) & 0xffffffff)
            if hold_start:
                row['start'] = 1
        if hold_start:
            self.goals.add('start/held-while-busy')
        if later_vin is not None and later_vin != vin_uv:
            self.goals.add('input/change-after-sample')
        for index, (dac, answer) in enumerate(zip(shown, answers)):
            row = self._row(a + 1 + index)
            row.update(dac=dac, cmp=answer, check_cmp=1)
            # The comparator answer for this trial is what the logic reads at the next edge.
            self._row(a + 2 + index)['cmp_ext'] = answer
            self.goals.add('sar/keep' if answer else 'sar/drop')
        end = self._row(a + bits + 1)
        self.result = final
        end.update(ready=1, busy=0, done=1, result=final, dac=0)
        self.free = a + bits + 2
        self.conversions.append((a, vin_uv, final))
        self.goals.update({'sar/sample-then-msb', 'sar/done-pulse'})
        if final == (1 << bits) - 1:
            self.goals.add('sar/all-ones')
        if final == 0:
            self.goals.add('sar/all-zeros')
        return final

    def reset_during(self, vin_uv, after_trials):
        """Start a conversion and pull reset low after some trial cycles."""
        bits = self.bits
        code = exact_code(vin_uv, self.caps)
        a = self.free
        self._row(a).update(start=1, vin=vin_uv & 0xffffffff, ready=0, sample=1, busy=1)
        for index, (dac, answer) in enumerate(zip(trials(code, bits), decisions(code, bits))):
            if index >= after_trials:
                break
            self._row(a + 1 + index).update(ready=0, busy=1, dac=dac, cmp=answer, check_cmp=1,
                                            vin=vin_uv & 0xffffffff)
            self._row(a + 2 + index)['cmp_ext'] = answer
        self.result = 0
        row = self._row(a + 1 + after_trials)
        row.update(rst_n=0, start=1, ready=1, sample=0, dac=0, busy=0, done=0, result=0, cmp=0,
                   check_cmp=0, vin=vin_uv & 0xffffffff)
        self.free = a + 2 + after_trials
        self.goals.add('reset/mid-conversion')

    def finish(self):
        self.idle(2)
        return self.rows

    def text(self, cp_af):
        """Vector file: analogue values first (kind 0: capacitors, parasitic, reference),
        then one row per clock (kind 1)."""
        lines = [f'0 {k:x} {c:x} 0 0 0 0 0 0 0 0 0 0' for k, c in enumerate(self.caps)]
        lines.append(f'0 ff {cp_af:x} 0 0 0 0 0 0 0 0 0 0')
        lines.append(f'0 fe {VREF_UV:x} 0 0 0 0 0 0 0 0 0 0')
        for row in self.rows:
            lines.append('1 ' + ' '.join(format(row[name], 'x') for name in self.FIELDS))
        return '\n'.join(lines) + '\n'


def fixed_timeline(bits, caps, inputs):
    """Every listed input once, with the handshake and reset situations in between."""
    line = Timeline(bits, caps)
    line.idle(2)
    for after in (0, 2, bits):   # in the sample cycle, mid-way, and where done would appear
        line.reset_during(inputs[len(inputs) // 2], after_trials=after)
        line.idle(1)
    for index, vin in enumerate(inputs):
        kind = index % 7
        if kind == 3:
            line.idle(1 + index % 3, vin=vin)
        line.convert(vin, hold_start=kind == 1,
                     later_vin=(VREF_UV - vin if kind in (2, 5) else None),
                     early_vin=(VREF_UV - vin if kind in (4, 5) else None))
    line.finish()
    return line


def random_timeline(bits, caps, seed, count):
    rng = random.Random(seed)
    guard = guard_uv(bits)
    line = Timeline(bits, caps)
    line.idle(1)
    made = 0
    while made < count:
        vin = rng.randrange(-VREF_UV // 16, VREF_UV + VREF_UV // 16)
        if margin_uv(vin, caps) < guard:
            continue
        action = rng.randrange(8)
        if action == 0:
            line.idle(rng.randrange(1, 4), vin=vin)
        elif action == 1:
            line.reset_during(vin, rng.randrange(0, bits + 1))
            line.idle(1)
        else:
            line.convert(vin, hold_start=action == 2,
                         later_vin=rng.randrange(0, VREF_UV) if action == 3 else None,
                         early_vin=rng.randrange(0, VREF_UV) if action == 4 else None)
            made += 1
    line.finish()
    return line


def replay_timeline(bits, caps, inputs, answers):
    """The same conversions with the comparator answers taken from ngspice."""
    line = Timeline(bits, caps)
    line.idle(1)
    for vin, answer in zip(inputs, answers, strict=True):
        line.convert(vin, external=answer)
    line.finish()
    return line


# --------------------------------------------------------------------------- analogue reference

def ideal_top(vin_uv, dac, caps, cp_af):
    """Settled top-plate voltage in volts for a sampled input and a DAC code."""
    switched = sum(c for k, c in enumerate(caps[:-1]) if dac >> k & 1)
    total = sum(caps)
    return (-vin_uv * total + VREF_UV * switched) / (total + cp_af) * 1e-6


def sampling_poles(total_f, cp_f):
    """Poles of the sampling network (1/s).  Bottom plates see the input through switches with
    R*C = TAU_S each; the top plate goes to ground through RON, with the parasitic across it:
        v_top(s) = V_in * s*C*RON / (TAU*Cp*RON*s^2 + (TAU + Cp*RON + C*RON)*s + 1)."""
    a = TAU_S * cp_f * RON_OHM
    b = TAU_S + cp_f * RON_OHM + total_f * RON_OHM
    root = math.sqrt(b * b - 4 * a)
    return (-b + root) / (2 * a), (-b - root) / (2 * a), a


def sampling_top(t, vin_v, total_f, cp_f):
    """Top-plate voltage during the sample cycle, starting from a discharged array."""
    s1, s2, a = sampling_poles(total_f, cp_f)
    return vin_v * total_f * RON_OHM / a * (math.exp(s1 * t) - math.exp(s2 * t)) / (s1 - s2)


def sampling_shortfall(period, total_f, cp_f):
    """Fraction of the input charge that has not reached the array when the top switch opens.
    It is the remaining integral of the top-plate current: K(0) = 1, K(inf) = 0."""
    s1, s2, a = sampling_poles(total_f, cp_f)
    return (math.exp(s1 * period) / -s1 - math.exp(s2 * period) / -s2) / (a * (s1 - s2))


def trial_tau(total_f, cp_f):
    """Time constant of the top plate after a bottom plate switches.  With equal R*C in every
    branch the only pole is at -(C + Cp)/(Cp * TAU): the parasitic alone slows the top plate."""
    return TAU_S * cp_f / (total_f + cp_f)


def minimum_period(bits, total_f, cp_f):
    """Shortest sample time after which the shortfall moves no input across the guard band:
    K(T) * V_ref <= guard."""
    limit = guard_uv(bits) / VREF_UV
    low, high = 0.0, 1e-6
    for _ in range(80):
        middle = (low + high) / 2
        if sampling_shortfall(middle, total_f, cp_f) > limit:
            low = middle
        else:
            high = middle
    return high


def predicted_code(vin_uv, caps, shortfall):
    """Code expected from a sample that is short by the given fraction, or None when the
    shortened input lands inside the guard band and the answer cannot be predicted safely."""
    effective = vin_uv * (1 - shortfall)
    if margin_uv(Fraction(effective), caps) < guard_uv(len(caps) - 1) / 2:
        return None
    return exact_code(Fraction(effective), caps)


def linearity(codes_by_input, bits):
    """Missing codes and monotonicity of a ramp given as (input, code) pairs."""
    ordered = [code for _, code in sorted(codes_by_input)]
    return dict(missing=sorted(set(range(1 << bits)) - set(ordered)),
                monotonic=all(b >= a for a, b in zip(ordered, ordered[1:])),
                hits={code: ordered.count(code) for code in sorted(set(ordered))})


def mismatched_caps(bits):
    """The most significant capacitor two units short: enough to lose codes below mid-scale."""
    caps = nominal_caps(bits)
    caps[bits - 1] -= 2 * UNIT_AF
    return caps


def circuit(bits, caps):
    """Element values for the netlist.  Switch resistances follow the nominal capacitors, so
    a mismatched capacitor keeps the switch that was drawn for the nominal one."""
    return dict(vref_v=VREF_UV * 1e-6, caps_f=[c * 1e-18 for c in caps],
                switch_ohm=[TAU_S / (c * 1e-18) for c in nominal_caps(bits)],
                cp_f=parasitic(bits) * 1e-18, ron_ohm=RON_OHM, roff_ohm=1e13)


def check_solution(answer, bits, count):
    """Refuse a solver result that is incomplete, inconsistent or not finite."""
    if not isinstance(answer, list) or len(answer) != count:
        raise ValueError('solver returned a different number of conversions')
    for item in answer:
        if (not isinstance(item, dict) or type(item.get('code')) is not int
                or not 0 <= item['code'] < 1 << bits):
            raise ValueError('solver result has no valid code')
        answers, tops = item.get('answers'), item.get('tops')
        if (not isinstance(answers, list) or not isinstance(tops, list) or len(answers) != bits
                or len(tops) != bits or any(a not in (0, 1) for a in answers)):
            raise ValueError('solver result has no complete trial record')
        values = [*tops, item.get('sample_top')]
        if any(type(v) is not float or not math.isfinite(v) for v in values):
            raise ValueError('solver result has a value that is not finite')
        if sum(a << j for j, a in zip(reversed(range(bits)), answers)) != item['code']:
            raise ValueError('solver code differs from its own comparator answers')
    return answer


def compare_models(inputs, solution, rnm_tops, caps, label_prefix='MODEL'):
    """Real-number model against settled ngspice: same codes, same top-plate voltage in every
    trial cycle within VTOP_TOLERANCE_V.  Returns the largest difference seen."""
    bits = len(caps) - 1
    worst = 0.0
    for vin, item in zip(inputs, solution, strict=True):
        expected = exact_code(vin, caps)
        model = rnm_tops.get(vin)
        if model is None:
            raise ValueError(f'no real-number model record for input {vin}')
        if item['code'] != model['code']:
            raise Mismatch(label_prefix + '_CODE', f"input {vin} uV: model {model['code']}, "
                                                   f"ngspice {item['code']}, exact {expected}")
        for index, (a, b) in enumerate(zip(model['tops'], item['tops'], strict=True)):
            worst = max(worst, abs(a - b))
            if abs(a - b) > VTOP_TOLERANCE_V:
                raise Mismatch(label_prefix + '_VTOP', f'input {vin} uV trial {index}: model '
                                                       f'{a:.9f} V, ngspice {b:.9f} V')
    return worst


def rnm_records(trace_rows, timeline):
    """Per input: the code and the top-plate voltage of every trial cycle, read from the
    testbench trace of the run in which the real-number model closed the loop."""
    bits = timeline.bits
    records = {}
    for accept, vin, code in timeline.conversions:
        rows = trace_rows[accept + 1:accept + 1 + bits]
        done = trace_rows[accept + 1 + bits]
        if len(rows) != bits or done['done'] != 1 or done['result'] != code:
            raise ValueError('trace does not contain the planned conversion')
        records[vin] = dict(code=done['result'], tops=[row['top_nv'] * 1e-9 for row in rows])
    return records

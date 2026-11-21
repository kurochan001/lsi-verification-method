#!/usr/bin/env python3
"""Sigma-delta modulator (real-number model) and CIC decimator: bit-exact checks of the bit
stream and the decimated output, then SNR, idle-tone and overload checks with derived limits."""
import importlib.util
import json
from pathlib import Path
import random
import re
import sys
import xml.etree.ElementTree as ET

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('sigma_delta_model', HERE / 'model.py')
M = importlib.util.module_from_spec(spec)
spec.loader.exec_module(M)

NAME = 'local-sigma-delta'
TOP = 'sd_tb'
CONFIGS = {'order1': dict(ORDER=1, STAGES=2), 'order2': dict(ORDER=2, STAGES=3)}
ITERATIONS = {'smoke': 2000, 'nightly': 6000}
SOURCES = [HERE / 'tb/sd_tb.sv', HERE / 'tb/sd_modulator_rnm.sv', HERE.parent / 'local-cic-decimator/rtl/cic_decimator.sv']
EXTRA_INPUTS = [HERE / 'model.py']
MUTANTS = 8
LABELS = {1: 'SD_BITS', 2: 'SD_BITS', 3: 'SD_BITS', 4: 'SD_BITS',
          5: 'SD_CIC', 6: 'SD_CIC', 7: 'SD_VALID', 8: 'SD_CIC'}
FEWER_STAGES = 8                # the mutation that builds the CIC with one stage fewer
LAST_ARGS = None


class Plan:
    """Rows of [rst_n, code, y, out_valid, out_data, mark] from the independent models."""

    def __init__(self, order, stages):
        self.mod = M.Modulator(order)
        self.cic = M.Cic(stages)
        self.mask = (1 << self.cic.width) - 1
        self.rows, self.index = [], []
        self.pending, self.produced = None, 0

    def cycle(self, rst_n, code):
        if not rst_n:               # both blocks reset asynchronously
            self.mod.reset()
            self.cic.reset()
            self.pending, self.produced = None, 0
        y = self.mod.decide()
        shown = self.pending
        self.rows.append([rst_n, code & 0xffff, int(y > 0), int(shown is not None), (shown or 0) & self.mask, 0])
        self.index.append(None if shown is None else self.produced)
        if shown is not None:
            self.produced += 1
        self.pending = None
        if rst_n:
            self.mod.advance(code, y)
            self.pending = self.cic.accept(int(y))

    def reset(self, cycles=2):
        for _ in range(cycles):
            self.cycle(0, 0)

    def codes(self, codes):
        for code in codes:
            self.cycle(1, code)

    def flush(self):
        self.codes([0] * (2 * M.RATE + 2))

    def mark(self, first, count):
        """Marks the rows from the one showing output `first` to the one showing first+count-1."""
        rows = [i for i, k in enumerate(self.index) if k is not None and first <= k < first + count]
        if len(rows) != count:
            raise ValueError('measurement window does not fit the plan')
        for i in range(rows[0], rows[-1] + 1):
            self.rows[i][5] = 1


def measurement(order, stages, codes):
    p = Plan(order, stages)
    p.reset()
    p.codes(codes)
    p.codes([codes[-1]] * (2 * M.RATE + 2))   # hold the last input while the last output appears
    p.mark(M.settle(stages), M.WINDOW)
    return p.rows


def boundary_vectors(order, stages):
    """Zero start, both full-scale codes, a DC that wraps every integrator, a reset with
    history, and a short tone after it."""
    p = Plan(order, stages)
    p.reset()
    p.codes([0] * (4 * M.RATE))                         # the first decision is on a state of exactly 0
    p.codes([M.CODE_MAX] * (8 * M.RATE))                # most positive input
    p.codes([M.CODE_MIN] * (8 * M.RATE))                # most negative input
    p.codes([M.CODE_MAX // 2] * (24 * M.RATE))          # DC 0.5: the integrators of the CIC wrap
    p.codes([-(M.SCALE // 3)] * (12 * M.RATE))          # a negative DC after the wrap
    p.codes([1, -1, 3, -3] * (2 * M.RATE))              # tiny alternating input
    p.codes([M.CODE_MAX // 4] * (M.RATE + 5))           # leave part way through a period
    p.reset(1)                                          # reset with history
    p.codes([M.CODE_MAX // 2] * (4 * M.RATE))
    tone = M.sine_codes(0.4, stages, signal_bin=17)[:12 * M.RATE]
    p.codes(tone)
    p.flush()
    return p.rows


def mutation_vectors(order, stages):
    """The part of the boundaries that every mutant needs: a decision on a state of exactly 0,
    both full-scale codes, and a DC long enough for every CIC integrator to wrap."""
    p = Plan(order, stages)
    p.reset()
    p.codes([0] * (4 * M.RATE))
    p.codes([M.CODE_MAX] * (4 * M.RATE))
    p.codes([M.CODE_MIN] * (4 * M.RATE))
    p.codes([M.CODE_MAX // 2] * (16 * M.RATE))
    p.flush()
    return p.rows


def random_vectors(seed, iterations, order, stages):
    rng = random.Random(seed)
    p = Plan(order, stages)
    p.reset()
    while len(p.rows) < iterations:
        kind = rng.randrange(12)
        length = rng.randrange(1, 3 * M.RATE)
        if kind == 0:
            p.reset(rng.randrange(1, 3))
        elif kind < 4:
            p.codes([rng.randrange(-29000, 29000)] * length)         # holds
        elif kind < 7:
            p.codes([rng.randrange(M.CODE_MIN, M.CODE_MAX + 1) for _ in range(length)])
        else:
            amplitude, bin_ = rng.uniform(0.05, 0.85), rng.choice([3, 7, 13, 29, 61])
            phase = rng.uniform(0, 6.28)
            p.codes(M.sine_codes(amplitude, stages, bin_, phase)[:length])
    p.flush()
    return p.rows


def counts(rows):
    return dict(accepted=sum(r[0] for r in rows), outputs=sum(r[3] for r in rows))


def make_cases(args, parameters):
    global LAST_ARGS
    LAST_ARGS = args
    order, stages = parameters['ORDER'], parameters['STAGES']
    baseline = boundary_vectors(order, stages)
    short = mutation_vectors(order, stages)
    cases = [dict(id='boundaries', vectors=baseline, mutation=args.demo_bug, category='functional', expected_failure=None),
             dict(id='sine-nominal', vectors=measurement(order, stages, M.sine_codes(M.NOMINAL_AMPLITUDE, stages)),
                  mutation=args.demo_bug, category='functional', expected_failure=None),
             dict(id='dc-idle', vectors=measurement(order, stages, M.dc_codes(M.IDLE_DC_CODE, stages)),
                  mutation=args.demo_bug, category='functional', expected_failure=None),
             dict(id='overload', vectors=measurement(order, stages, M.sine_codes(M.OVERLOAD_AMPLITUDE, stages)),
                  mutation=args.demo_bug, category='functional', expected_failure=None)]
    for seed in range(args.seed, args.seed + (3 if args.profile == 'nightly' else 1)):
        cases.append(dict(id=f'random-seed{seed}', vectors=random_vectors(seed, args.iterations, order, stages),
                          mutation=args.demo_bug, category='functional', expected_failure=None))
    for mutation in range(1, MUTANTS + 1):
        cases.append(dict(id=f'detect-mutation{mutation}', vectors=short, mutation=mutation,
                          category='mutation', expected_failure=LABELS[mutation]))
    # The same design error in the circuit and in the model: one CIC stage fewer in both.
    # Every bit still matches; only the SNR check after the run can see it.
    cases.append(dict(id='shared-fewer-stages', mutation=FEWER_STAGES, category='diagnostic', expected_failure=None,
                      vectors=measurement(order, stages - 1, M.sine_codes(M.NOMINAL_AMPLITUDE, stages - 1))))
    for case in cases:
        case['counts'] = counts(case['vectors'])
    return cases


def add_arguments(parser):
    # A measurement case is about 8,400 clocks of real arithmetic; leave room on a busy machine.
    parser.set_defaults(timeout=30.0)


# ---- after the shared runner: SNR, idle tone and overload, from the simulated outputs ---------

def observed(out, case):
    log = (out / case / 'simulation.log').read_text(errors='replace')
    window = [int(v) for v in re.findall(r'^OBS SD y=(-?\d+)$', log, re.M)]
    peaks = [int(v) for v in re.findall(r'^OBS SD peak_milli=(-?\d+)$', log, re.M)]
    if len(window) != M.WINDOW or len(peaks) != 1:
        raise ValueError(f'{case}: window of {len(window)} outputs and {len(peaks)} peak records')
    return window, peaks[0] / 1000.0


def model_window(order, stages, codes):
    return M.decimate(M.modulate(codes, order), stages)[M.settle(stages):M.settle(stages) + M.WINDOW]


def judge(name, parameters, out):
    order, stages = parameters['ORDER'], parameters['STAGES']
    low, high = M.snr_limits(order, stages, M.NOMINAL_AMPLITUDE)
    report, checks = {}, {}

    def same_as_model(window, expected, label):
        return [] if window == expected else [f'{label}: logged window differs from the model']

    window, peak = observed(out, f'{name}-sine-nominal')
    snr = M.snr_db(window)
    problems = same_as_model(window, model_window(order, stages, M.sine_codes(M.NOMINAL_AMPLITUDE, stages)), 'nominal')
    if not low <= snr <= high:
        problems.append(f'SNR {snr:.2f} dB outside [{low:.2f}, {high:.2f}]')
    report['nominal'] = dict(snr=snr, lower=low, upper=high, theory=M.theory_db(order, M.NOMINAL_AMPLITUDE),
                             linear=M.linear_db(order, stages, M.NOMINAL_AMPLITUDE), peak_state=peak)
    checks['snr-nominal'] = problems

    window, peak = observed(out, f'{name}-dc-idle')
    spur = M.spur_dbfs(window, stages)
    problems = same_as_model(window, model_window(order, stages, M.dc_codes(M.IDLE_DC_CODE, stages)), 'idle')
    if order in M.IDLE_TONE_AT_LEAST and spur < M.IDLE_TONE_AT_LEAST[order]:
        problems.append(f'idle tone {spur:.1f} dBFS below the expected {M.IDLE_TONE_AT_LEAST[order]} dBFS')
    if order in M.IDLE_TONE_AT_MOST and spur > M.IDLE_TONE_AT_MOST[order]:
        problems.append(f'idle tone {spur:.1f} dBFS above {M.IDLE_TONE_AT_MOST[order]} dBFS')
    report['idle'] = dict(spur_dbfs=spur, at_least=M.IDLE_TONE_AT_LEAST.get(order), at_most=M.IDLE_TONE_AT_MOST.get(order))
    checks['idle-tone'] = problems

    window, peak = observed(out, f'{name}-overload')
    snr = M.snr_db(window)
    problems = same_as_model(window, model_window(order, stages, M.sine_codes(M.OVERLOAD_AMPLITUDE, stages)), 'overload')
    if order == 1:
        if not peak < M.FIRST_ORDER_STATE_LIMIT:
            problems.append(f'first-order state {peak:.3f} not below {M.FIRST_ORDER_STATE_LIMIT}')
        if snr < low:
            problems.append(f'SNR {snr:.2f} dB fell below the nominal lower limit {low:.2f}')
    else:
        if not peak > M.OVERLOAD_STATE:
            problems.append(f'state {peak:.3f} did not grow past {M.OVERLOAD_STATE}')
        if not snr < low:
            problems.append(f'SNR {snr:.2f} dB did not collapse below the nominal lower limit {low:.2f}')
    report['overload'] = dict(amplitude=M.OVERLOAD_AMPLITUDE, snr=snr, peak_state=peak)
    checks['overload'] = problems

    window, peak = observed(out, f'{name}-shared-fewer-stages')
    snr = M.snr_db(window)
    problems = same_as_model(window, model_window(order, stages - 1, M.sine_codes(M.NOMINAL_AMPLITUDE, stages - 1)), 'fewer')
    if not snr < low:
        problems.append(f'one CIC stage fewer kept SNR {snr:.2f} dB above the lower limit {low:.2f}')
    report['shared_fewer_stages'] = dict(stages=stages - 1, snr=snr, caught_by_snr=snr < low)
    checks['shared-fewer-stages'] = problems
    return report, checks


def judge_all(out, configurations):
    """Adds four checks per configuration to the evidence the shared runner wrote."""
    reports, verdicts = {}, {}
    for name, parameters in configurations.items():
        reports[name], checks = judge(name, parameters, out)
        # The JUnit names of these checks must not repeat a simulation case name (for example order1-overload),
        # or the repository runner cannot tell which case a summary entry refers to.
        verdicts.update({f'{name}-check-{k}': v for k, v in checks.items()})
    (out / 'snr.json').write_text(json.dumps(reports, indent=2) + '\n')
    success = all(not v for v in verdicts.values())
    summary = json.loads((out / 'summary.json').read_text())
    summary['snr'] = {k: dict(success=not v, problems=v) for k, v in verdicts.items()}
    summary['success'] = bool(summary['success'] and success)
    (out / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')
    tree = ET.parse(out / 'junit.xml')
    suite = tree.getroot()
    for old in [n for n in suite.findall('testcase') if n.get('classname') == 'local.' + NAME + '.tolerance']:
        suite.remove(old)
    for case, problems in verdicts.items():
        node = ET.SubElement(suite, 'testcase', name=case, classname='local.' + NAME + '.tolerance')
        if problems:
            ET.SubElement(node, 'failure', message='; '.join(problems)).text = 'snr.json'
    for name, r in reports.items():
        n = r['nominal']
        print(f"SNR {name}: {n['snr']:.2f} dB in [{n['lower']:.2f}, {n['upper']:.2f}] (theory {n['theory']:.2f}, "
              f"linear {n['linear']:.2f}); idle tone {r['idle']['spur_dbfs']:.1f} dBFS; overload SNR "
              f"{r['overload']['snr']:.2f} dB, state {r['overload']['peak_state']:.3f}; one stage fewer "
              f"{r['shared_fewer_stages']['snr']:.2f} dB")
    suite.set('tests', str(len(suite.findall('testcase'))))
    suite.set('failures', str(len(suite.findall('testcase/failure'))))
    ET.indent(suite)
    tree.write(out / 'junit.xml', encoding='utf-8', xml_declaration=True)
    return success


def main():
    spec = importlib.util.spec_from_file_location('local_runner', HERE.parent / 'local-common/runner.py')
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)
    code = runner.main(sys.modules[__name__])
    if code != 0 or LAST_ARGS is None:
        return code
    names = CONFIGS if LAST_ARGS.configuration == 'all' else {LAST_ARGS.configuration: CONFIGS[LAST_ARGS.configuration]}
    try:
        success = judge_all(LAST_ARGS.out.resolve(), names)
    except (OSError, ValueError, KeyError) as exc:
        print('RUNNER_ERROR SNR: ' + str(exc), file=sys.stderr)
        return 1
    print('SNR, idle tone and overload: ' + ('PASS' if success else 'FAIL'))
    return 0 if success else 1


if __name__ == '__main__':
    sys.exit(main())

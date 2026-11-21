#!/usr/bin/env python3
"""Fault injection campaign on the referenced lockstep monitor: a fault list from the circuit,
structural exclusion with a ledger, four-way classification and rates with exact intervals."""
import hashlib
import importlib.util
import json
from pathlib import Path
import random
import shutil
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


E = load('fault_campaign_evidence', HERE.parent / 'local-exploration-common/evidence.py')
P = E.P
M = load('fault_campaign_model', HERE / 'model.py')
C = load('fault_campaign_core', HERE / 'campaign.py')

NAME = 'local-fault-campaign'
TOP = 'lockstep_monitor'
RTL = HERE.parent / 'local-lockstep-monitor/rtl/lockstep_monitor.sv'
TB = HERE / 'tb/fault_campaign_tb.sv'
LEDGER = HERE / 'exclusions.json'
REQUIREMENTS = HERE / 'requirements.json'
INPUTS = [Path(__file__), HERE / 'model.py', HERE / 'campaign.py', TB, RTL, LEDGER, REQUIREMENTS]
ALPHA = 0.001                 # two-sided, alpha/2 in each tail of each interval
SAMPLE = 300                  # faults drawn without replacement from the target set per seed
CALIBRATION_SEEDS = 2000      # fixed seeds of the model-only check of the interval method
CALIBRATION_LIMIT = 12        # misses allowed in those seeds (design rate <= 0.002, see README)
STATUS = {1: 'done', 2: 'stall', 3: 'abandon', 4: 'cap'}
F = M.Fault

# Hand-picked faults with the class and end status derived by hand from the workload (see README).
# The cycle numbers refer to the golden run: 0 LOAD, 1 ADD, 2-3 idle, 4 XOR, 5 ADD, 6 idle, 7 LOAD,
# 8 ADD, 9 ILLEGAL, 10 recover, 11 XOR, 12-13 idle, 14 ADD, 15 LOAD, 16 ADD, 17 idle, 18 XOR, 19-20 drain.
FIXED = [
    (F('acc1', 3, M.FLIP, 6), 'no_effect', 'done', ['scenario/masked-overwrite']),
    (F('acc1', 2, M.FLIP, 2), 'detected', 'done', ['scenario/detected-recovered']),
    (F('done', 0, M.FLIP, 1), 'undetected', 'done', ['scenario/undetected-handshake']),
    (F('safe', 0, M.FLIP, 2), 'timeout', 'stall', ['scenario/timeout-stall']),
    (F('acc1', 0, M.STUCK, 0, 1), 'detected', 'abandon', ['scenario/stuck-abandon']),
    (F('error', 0, M.FLIP, 2), 'detected', 'done', ['scenario/false-alarm']),
    (F('acc0', 4, M.FLIP, 9), 'undetected', 'done', ['scenario/undetected-resync']),
    (F('result', 5, M.FLIP, 12), 'undetected', 'done', []),
    (F('error_code', 1, M.FLIP, 9), 'no_effect', 'done', []),
    (F('error', 0, M.STUCK, 3, 1), 'timeout', 'cap', ['scenario/timeout-livelock']),
    (F('acc0', 0, M.FLIP, 0), 'detected', 'done', []),
    (F('acc1', 0, M.FLIP, 2), 'detected', 'done', []),
    (F('done', 0, M.STUCK, 0, 0), 'timeout', 'stall', []),
    (F('result', 7, M.STUCK, 0, 1), 'undetected', 'done', []),
    (F('acc0', 6, M.FLIP, 19), 'no_effect', 'done', []),
    (F('acc1', 5, M.FLIP, 1), 'detected', 'done', []),
    (F('acc0', 3, M.STUCK, 0, 1), 'detected', 'done', ['scenario/detected-wrong-after-recovery']),
]


def row(result, done=0, error=0):
    return (0, 0, 0, 0, 0, result, done, error, 0, 0)


G = [row(1, 1), row(2, 1), row(3, 1), row(4, 1), row(5, 1)]
# Synthetic trace pairs with the class written by hand from the rules; the classifier must agree.
KNOWN = [
    ('identical', G, G, 'done', 'no_effect'),
    ('stall', G, G[:3], 'stall', 'timeout'),
    ('containment', G, [row(1, 1), row(2, 1), row(0, 1, 1), row(0), row(4, 1)], 'done', 'detected'),
    ('late-alarm', G, [row(1, 1), row(9, 1), row(3, 1), row(0, 1, 1), row(5, 1)], 'done', 'undetected'),
    ('transient', G, [row(1, 1), row(9, 1), row(3, 1), row(4, 1), row(5, 1)], 'done', 'undetected'),
    ('missing-alarm', [row(1, 1), row(0, 1, 1), row(3, 1)], [row(1, 1), row(0, 1, 0), row(3, 1)], 'done', 'undetected'),
    ('shorter', G, G[:4], 'done', 'undetected'),
    ('cap-with-alarm', G, [row(1, 1), row(2, 1, 1), row(2, 0, 1)], 'cap', 'timeout'),
    ('alarm-first', G, [row(1, 1), row(2, 1), row(3, 1, 1), row(4, 1, 1), row(0, 1)], 'done', 'detected'),
]
# A synthetic campaign with hand-computed accounting: 2 excluded, 8 in the target set.
ACCOUNT_RECORDS = ([dict(cls='no_effect', excluded=True)] * 2 + [dict(cls='no_effect', excluded=False)] * 2 +
                   [dict(cls='detected', excluded=False)] * 3 + [dict(cls='undetected', excluded=False)] * 2 +
                   [dict(cls='timeout', excluded=False)])
ACCOUNT_EXPECTED = dict(all=10, excluded=2, target=8, affected=6, detection_rate=0.5, no_effect_share=0.25)

RTL_MUTATIONS = {1: 'FC_MODEL', 2: 'FC_MODEL', 3: 'FC_GOLDEN', 4: 'FC_GOLDEN'}
INJECTOR_BUGS = {1: 'FC_MODEL', 2: 'FC_INJECT', 3: 'FC_INVENTORY'}
CLASSIFIER_BUGS = {1: 'FC_CLASSIFY', 2: 'FC_CLASSIFY', 3: 'FC_CLASSIFY', 4: 'FC_ACCOUNT', 5: 'FC_CLASSIFY'}


def seeds(args):
    return list(range(args.seed, args.seed + (3 if args.profile == 'nightly' else 1)))


def plan(args):
    ids = ['toolchain', 'inventory', 'exclusion-ledger', 'exclusion-confirm', 'golden', 'classifier-known-answers',
           'accounting-known-answers', 'fixed-faults']
    for s in seeds(args):
        ids += [f'sample-seed{s}', f'sample-interval-seed{s}']
    ids.append('interval-calibration')
    if args.profile == 'nightly':
        ids += ['exhaustive', 'mutation1-rate-drop']
    ids += [f'rtl-mutation{k}' for k in RTL_MUTATIONS] + [f'injector-bug{k}' for k in INJECTOR_BUGS]
    ids += [f'classifier-bug{k}' for k in CLASSIFIER_BUGS] + ['ledger-unsound', 'report', 'requirements']
    return ids


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


class Campaign:
    def __init__(self, e, args):
        self.e, self.a, self.out = e, args, e.out
        self.builds = {}
        self.batches = []
        self.model_runs = {}
        self.golden = M.run()
        self.cycles = len(self.golden['rows'])

    # --- the circuit -----------------------------------------------------------------------
    def synthesize(self):
        d = self.out / 'yosys'
        d.mkdir()
        shutil.copy2(RTL, d / RTL.name)
        # Relative names: the YoWASP tools cannot see absolute paths below /tmp.
        script = f'read_verilog -sv {RTL.name}; hierarchy -top {TOP}; proc; opt_clean; write_json netlist.json'
        execution = P.execute([self.a.yosys, '-q', '-p', script], d / 'yosys.log', self.a.timeout, d)
        if execution['error'] or execution['returncode'] != 0 or not (d / 'netlist.json').is_file():
            raise ValueError('yosys failed: ' + str(execution['error'] or execution['returncode']))
        return json.loads((d / 'netlist.json').read_text())

    # --- simulation -----------------------------------------------------------------------
    def build(self, registers, mutation=0, injector_bug=0):
        key = (tuple(registers), mutation, injector_bug)
        if key in self.builds:
            return self.builds[key]
        d = self.out / f'build-m{mutation}-i{injector_bug}'
        d.mkdir()
        (d / 'injector.svh').write_text(C.injector(registers, injector_bug))
        params = dict(MUTATION=mutation, WAIT_LIMIT=M.WAIT_LIMIT, MAX_RETRY=M.MAX_RETRY, DRAIN=M.DRAIN, CAP=M.CAP)
        command = [self.a.iverilog, '-g2012', '-s', 'fault_campaign_tb', '-I', str(d),
                   *[f'-Pfault_campaign_tb.{k}={v}' for k, v in params.items()], '-o', str(d / 'sim.vvp'), str(RTL), str(TB)]
        execution = P.execute(command, d / 'build.log', self.a.timeout, d)
        self.builds[key] = (d, execution)
        return self.builds[key]

    def simulate(self, name, registers, faults, mutation=0, injector_bug=0):
        """{index: dict(rows, status, cycles, alarms, injection)} for [None (golden)] + faults."""
        d, build = self.build(registers, mutation, injector_bug)
        run = self.out / 'runs' / name
        run.mkdir(parents=True)
        index = {reg: i for i, (reg, _) in enumerate(registers)}
        (run / 'ops.txt').write_text(''.join(f'{g} {o} {a}\n' for g, o, a in M.OPS))
        lines = ['0 0 0 0 0 0\n']
        for i, f in enumerate(faults, 1):
            lines.append(f'{i} {index[f.register]} {f.bit} {f.kind} {f.value} {f.time}\n')
        (run / 'faults.txt').write_text(''.join(lines))
        record = dict(name=name, mutation=mutation, injector_bug=injector_bug, faults=len(faults), build=build)
        if build['error'] or build['returncode'] != 0:
            record.update(error='build failed')
            self.batches.append(record)
            raise ValueError(f'{name}: build failed')
        execution = P.execute([self.a.vvp, '-n', str(d / 'sim.vvp'), '+OPS=' + str(run / 'ops.txt'),
                               '+FAULTS=' + str(run / 'faults.txt'), '+TRACE=' + str(run / 'trace.txt')],
                              run / 'simulation.log', self.a.timeout, run)
        record.update(execution=execution)
        self.batches.append(record)
        log = (run / 'simulation.log').read_text(errors='replace')
        if execution['error'] or execution['returncode'] != 0 or 'RESULT PASS faults' not in log:
            raise ValueError(f'{name}: simulation did not complete ({execution["error"] or execution["returncode"]})')
        return parse_trace((run / 'trace.txt').read_text(), len(faults))

    def model(self, fault):
        key = None if fault is None else fault.key()
        if key not in self.model_runs:
            self.model_runs[key] = M.run(fault)
        return self.model_runs[key]

    def compare(self, faults, results):
        """Labels for differences between RTL and model runs, and per-fault records."""
        labels, records = set(), []
        golden_rtl = results[0]
        if golden_rtl['rows'] != self.golden['rows'] or golden_rtl['status'] != self.golden['status']:
            labels.add('FC_GOLDEN')
        for i, f in enumerate(faults, 1):
            r, m = results[i], self.model(f)
            match = r['rows'] == m['rows'] and r['status'] == m['status']
            if not match:
                labels.add('FC_MODEL')
            inj = r['injection']
            expected_after = 1 - inj[0] if inj and f.kind == M.FLIP else f.value
            readback = inj is not None and inj[0] in (0, 1) and inj[1] == expected_after
            if not readback:
                labels.add('FC_INJECT')
            records.append(dict(fault=f.name(), match=match, readback=readback, status_rtl=r['status'], status_model=m['status'],
                                cls_rtl=C.classify(golden_rtl['rows'], r['rows'], r['status']),
                                cls_model=C.classify(self.golden['rows'], m['rows'], m['status'])))
        return labels, records


def parse_trace(text, faults):
    """{index: dict(rows, status, cycles, alarms, injection)}; every run 0..faults must be complete."""
    results = {}
    for line in text.splitlines():
        parts = line.split()
        values = [int(v) for v in parts[1:]]   # an X or Z in the trace is not an integer: a ValueError
        item = results.setdefault(values[0], dict(rows=[], status=None, injection=None))
        if parts[0] == 'R' and len(values) == 11:
            item['rows'].append(tuple(values[1:]))
        elif parts[0] == 'I' and len(values) == 3:
            item['injection'] = tuple(values[1:])
        elif parts[0] == 'E' and len(values) == 4 and values[1] in STATUS:
            item.update(status=STATUS[values[1]], cycles=values[2], alarms=values[3])
        else:
            raise ValueError('malformed trace line: ' + line)
    if sorted(results) != list(range(faults + 1)) or any(r['status'] is None or r['cycles'] != len(r['rows'])
                                                          for r in results.values()):
        raise ValueError('trace is missing or truncating runs')
    return results


def check_inventory(registers):
    expected = sorted(M.STATE.items())
    return registers == expected, dict(extracted=registers, model=expected)


def check_ledger(ledger, cone_map):
    computed = [dict(register=r, bit=b, reaches=reached) for r, b, reached in C.exclusions(cone_map, M.OBSERVED)]
    listed = [dict(register=x['register'], bit=x['bit'], reaches=x['reaches']) for x in ledger['excluded']]
    problems = []
    if ledger.get('rtl_sha256') != sha256(RTL):
        problems.append('RTL changed since the ledger was reviewed')
    if ledger.get('observed_outputs') != list(M.OBSERVED):
        problems.append('observed outputs differ')
    if sorted(map(json.dumps, computed)) != sorted(map(json.dumps, listed)):
        problems.append('ledger differs from the computed cones')
    if any(not x.get('reason') for x in ledger['excluded']):
        problems.append('an exclusion has no reason')
    return not problems, dict(problems=problems, computed=computed, listed=listed)


def known_answers(bug=0):
    wrong = [name for name, g, f, status, cls in KNOWN if C.classify(g, f, status, bug) != cls]
    return not wrong, wrong


def accounting(bug=0):
    t = C.tally(ACCOUNT_RECORDS, bug)
    got = {k: t[k] for k in ACCOUNT_EXPECTED}
    return got == ACCOUNT_EXPECTED, got


def run(a):
    ids = plan(a)
    e = E.Evidence(NAME, a, INPUTS, dict(rtl=str(RTL.relative_to(ROOT)), workload=M.OPS, alpha=ALPHA, sample=SAMPLE,
                                         seeds=seeds(a), demo_bug=a.demo_bug, observed=list(M.OBSERVED)), ids)
    c = Campaign(e, a)
    goals = set()
    probes = {n: P.execute([getattr(a, n), '-V'], e.out / f'{n}-version.log', a.timeout, e.out) for n in ('iverilog', 'vvp', 'yosys')}
    P.write_json(e.out / 'tools.json', probes)
    e.check('toolchain', all(not p['error'] and p['returncode'] == 0 for p in probes.values()), probes)

    netlist = c.synthesize()
    registers = C.flip_flops(netlist, TOP)
    naive = C.declared_regs(RTL.read_text())
    ok, detail = check_inventory(registers)
    combinational = sorted(set(dict(naive)) - set(dict(registers)))
    detail.update(declared_regs=naive, combinational=combinational)
    if ok:
        goals.add('inventory/circuit')
        if combinational and set(dict(registers)) <= set(dict(naive)):
            goals.add('inventory/no-combinational')
    e.check('inventory', ok, detail)
    if not ok:
        raise ValueError('the circuit does not have the modelled state; nothing else can be compared')

    cone_map = C.cones(netlist, TOP)
    ledger = json.loads(LEDGER.read_text())
    ok, detail = check_ledger(ledger, cone_map)
    P.write_json(e.out / 'cones.json', {f'{r}[{b}]': v for (r, b), v in sorted(cone_map.items())})
    if ok:
        goals |= {'exclusion/ledger'} | ({'exclusion/structural'} if ledger['excluded'] else set())
    e.check('exclusion-ledger', ok, detail)
    excluded = {(x['register'], x['bit']) for x in ledger['excluded']}

    population = M.population(c.cycles, dict(registers))
    target = [f for f in population if (f.register, f.bit) not in excluded]
    excluded_faults = [f for f in population if (f.register, f.bit) in excluded]
    pop_class = {f.key(): C.classify(c.golden['rows'], c.model(f)['rows'], c.model(f)['status']) for f in population}
    pop_records = [dict(cls=pop_class[f.key()], excluded=(f.register, f.bit) in excluded) for f in population]
    pop_tally = C.tally(pop_records)

    samples = {s: random.Random(s).sample(target, SAMPLE) for s in seeds(a)}
    fixed = [f for f, *_ in FIXED]
    batch = list(dict.fromkeys([*fixed, *excluded_faults, *(f for s in samples.values() for f in s),
                                *(population if a.profile == 'nightly' else [])]))
    results = c.simulate('clean', registers, batch, mutation=a.demo_bug)
    labels, records = c.compare(batch, results)
    by_fault = {f.key(): rec for f, rec in zip(batch, records)}
    P.write_json(e.out / 'faults.json', records)
    if all(r['readback'] for r in records):
        goals.add('inject/readback')
    if not labels:
        goals.add('inject/model-match')

    confirm = [by_fault[f.key()] for f in excluded_faults]
    e.check('exclusion-confirm', all(r['match'] and r['cls_rtl'] == 'no_effect' for r in confirm) and confirm != [],
            dict(faults=len(confirm), classes=sorted({r['cls_rtl'] for r in confirm})))
    if confirm and all(r['match'] and r['cls_rtl'] == 'no_effect' for r in confirm):
        goals.add('exclusion/confirmed')
    e.check('golden', 'FC_GOLDEN' not in labels, dict(cycles=c.cycles, status=results[0]['status']))

    ok, wrong = known_answers()
    if ok:
        goals.add('classifier/known-answers')
    e.check('classifier-known-answers', ok, dict(cases=len(KNOWN), wrong=wrong))
    ok, got = accounting()
    if ok:
        goals.add('accounting/known-answers')
    e.check('accounting-known-answers', ok, got)

    problems = []
    for (f, cls, status, tags), rec in ((item, by_fault[item[0].key()]) for item in FIXED):
        if not (rec['match'] and rec['readback'] and rec['cls_rtl'] == cls == rec['cls_model'] and rec['status_rtl'] == status):
            problems.append(dict(rec, expected_class=cls, expected_status=status))
            continue
        goals.add('class/' + cls.replace('_', '-'))
        run_rtl = results[batch.index(f) + 1]
        final_same = run_rtl['rows'][-1][5] == c.golden['rows'][-1][5]
        for tag in tags:
            if tag == 'scenario/detected-recovered' and not final_same:
                continue
            if tag == 'scenario/detected-wrong-after-recovery' and (final_same or run_rtl['alarms'] < 3):
                continue
            goals.add(tag)
    e.check('fixed-faults', not problems, dict(faults=len(FIXED), problems=problems))

    for s, sample in samples.items():
        recs = [by_fault[f.key()] for f in sample]
        bad = [r for r in recs if not (r['match'] and r['readback'] and r['cls_rtl'] == r['cls_model'])]
        e.check(f'sample-seed{s}', not bad, dict(faults=len(recs), problems=bad[:10]))
        t = C.tally([dict(cls=r['cls_rtl'], excluded=False) for r in recs])
        det = C.exact_interval(t['counts']['detected'], t['affected'], ALPHA)
        noe = C.exact_interval(t['counts']['no_effect'], t['target'], ALPHA)
        inside = det[0] <= pop_tally['detection_rate'] <= det[1] and noe[0] <= pop_tally['no_effect_share'] <= noe[1]
        if inside and not bad:
            goals.add('rate/interval')
        e.check(f'sample-interval-seed{s}', inside and not bad,
                dict(sample=t, detection_interval=det, no_effect_interval=noe, population=dict(
                    detection_rate=pop_tally['detection_rate'], no_effect_share=pop_tally['no_effect_share'])))

    target_classes = [pop_class[f.key()] for f in target]
    misses = 0
    for s in range(CALIBRATION_SEEDS):
        picked = random.Random(1_000_000 + s).sample(target_classes, SAMPLE)
        t = C.tally([dict(cls=x, excluded=False) for x in picked])
        det = C.exact_interval(t['counts']['detected'], t['affected'], ALPHA)
        noe = C.exact_interval(t['counts']['no_effect'], t['target'], ALPHA)
        misses += not (det[0] <= pop_tally['detection_rate'] <= det[1] and noe[0] <= pop_tally['no_effect_share'] <= noe[1])
    if misses <= CALIBRATION_LIMIT:
        goals.add('rate/calibration')
    e.check('interval-calibration', misses <= CALIBRATION_LIMIT, dict(seeds=CALIBRATION_SEEDS, misses=misses, limit=CALIBRATION_LIMIT))

    if a.profile == 'nightly':
        recs = [by_fault[f.key()] for f in population]
        bad = [r for r in recs if not (r['match'] and r['readback'] and r['cls_rtl'] == r['cls_model'])]
        e.check('exhaustive', not bad and len(recs) == len(population), dict(faults=len(recs), problems=bad[:10]))
        weak = c.simulate('mutation1-population', registers, target, mutation=1)
        weak_t = C.tally([dict(cls=C.classify(weak[0]['rows'], weak[i]['rows'], weak[i]['status']), excluded=False)
                          for i in range(1, len(target) + 1)])
        e.check('mutation1-rate-drop', weak_t['detection_rate'] < pop_tally['detection_rate'],
                dict(correct=pop_tally, comparator_ignores_bit0=weak_t))

    for k, label in RTL_MUTATIONS.items():
        try:
            got, _ = c.compare(fixed, c.simulate(f'rtl-mutation{k}', registers, fixed, mutation=k))
        except ValueError as exc:
            got = {'FC_RUN'}
            print('note', exc)
        e.check(f'rtl-mutation{k}', label in got, dict(expected=label, labels=sorted(got)))
    for k, label in INJECTOR_BUGS.items():
        if k == 3:
            ok, detail = check_inventory(naive)
            got = set() if ok else {'FC_INVENTORY'}
        else:
            try:
                got, _ = c.compare(fixed, c.simulate(f'injector-bug{k}', registers, fixed, injector_bug=k))
            except ValueError as exc:
                got = {'FC_RUN'}
                print('note', exc)
        e.check(f'injector-bug{k}', label in got, dict(expected=label, labels=sorted(got)))
    for k, label in CLASSIFIER_BUGS.items():
        got = set()
        if not known_answers(k)[0]:
            got.add('FC_CLASSIFY')
        if not accounting(k)[0]:
            got.add('FC_ACCOUNT')
        e.check(f'classifier-bug{k}', label in got, dict(expected=label, labels=sorted(got)))
    bad_ledger = dict(ledger, excluded=[*ledger['excluded'], dict(register='done', bit=0, reaches=['done'], reason='wrong on purpose')])
    ok, detail = check_ledger(bad_ledger, cone_map)
    claimed = [f for f in population if (f.register, f.bit) == ('done', 0)]
    unsafe = sum(pop_class[f.key()] != 'no_effect' for f in claimed)
    e.check('ledger-unsound', not ok and unsafe > 0, dict(problems=detail['problems'], claimed=len(claimed), not_no_effect=unsafe))

    report = dict(
        population=dict(definition='every flip-flop bit x {one-cycle flip, stuck-at-0, stuck-at-1} x every cycle of the golden run',
                        registers=registers, cycles=c.cycles, faults=len(population)),
        excluded=dict(faults=len(excluded_faults), bits=sorted(f'{r}[{b}]' for r, b in excluded), reason='structural, see exclusions.json'),
        target=len(target), exhaustive_model=pop_tally,
        rates=dict(detection_rate='detected / (detected + undetected + timeout), target faults only',
                   no_effect_share='no_effect / target faults'),
        samples={s: C.tally([dict(cls=by_fault[f.key()]['cls_rtl'], excluded=False) for f in samples[s]]) for s in samples},
        interval=dict(method='Clopper-Pearson, two-sided', alpha=ALPHA),
        note='A teaching campaign. Not a diagnostic coverage or ASIL claim under ISO 26262.')
    P.write_json(e.out / 'campaign.json', report)
    consistent = (sum(pop_tally['counts'].values()) == pop_tally['target'] == len(target) and
                  pop_tally['affected'] == pop_tally['counts']['detected'] + pop_tally['counts']['undetected'] + pop_tally['counts']['timeout'] and
                  pop_tally['excluded'] == len(excluded_faults) and pop_tally['all'] == len(population))
    if consistent:
        goals.add('rate/denominator')
    e.check('report', consistent, report['exhaustive_model'])

    catalog = json.loads(REQUIREMENTS.read_text())
    required = {g for r in catalog['requirements'] for g in r['goals']}
    P.write_json(e.out / 'coverage.json', dict(required=sorted(required), hit=sorted(goals & required),
                                               missing=sorted(required - goals), unplanned=sorted(goals - required)))
    P.write_json(e.out / 'batches.json', c.batches)
    e.check('requirements', required == goals, dict(missing=sorted(required - goals), unplanned=sorted(goals - required)))
    return e.finish()


def main():
    p = E.parser(__doc__, NAME)
    p.add_argument('--yosys', default='yowasp-yosys')
    p.add_argument('--demo-bug', type=int, choices=range(len(RTL_MUTATIONS) + 1), default=0,
                   help='run the clean campaign on lockstep_monitor MUTATION=N; the run must then fail')
    a = p.parse_args()
    E.validate(p, a)
    try:
        return run(a)
    except (OSError, ValueError, KeyError, TypeError, IndexError) as exc:
        print('RUNNER_ERROR', exc, file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())

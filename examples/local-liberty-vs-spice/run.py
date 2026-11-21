#!/usr/bin/env python3
"""Measure a transistor-level flip-flop with ngspice and tie the numbers to a Liberty table."""
import importlib.util
import json
import math
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


MODEL = load('liberty_vs_spice_model', HERE / 'model.py')
CELLS = load('liberty_vs_spice_cells', HERE / 'cells.py')
E = load('liberty_vs_spice_evidence', HERE.parent / 'local-exploration-common/evidence.py')
N = load('ngspice_installation', ROOT / 'tools/ngspice.py')
NAME = 'local-liberty-vs-spice'
EXISTING = {'local-sta/slow': HERE.parent / 'local-sta/design/slow.lib',
            'local-sta/fast': HERE.parent / 'local-sta/design/fast.lib',
            'local-gate-timing': HERE.parent / 'local-gate-timing/cells/teaching.lib'}
LOW, HIGH = -300e-12, 500e-12        # the bracket every search starts from
TIGHT = dict(reltol=1e-5, step=0.5e-12, max_step=0.5e-12)
EDGES = {'rise': 1, 'fall': 0}
DETECT = {  # negative case -> the label that must reject it
    'detect-table-delay': 'TABLE_DELAY', 'detect-table-setup': 'TABLE_SETUP', 'detect-table-hold': 'TABLE_HOLD',
    'detect-weak-output': 'TABLE_DELAY', 'detect-slow-master': 'TABLE_SETUP',
    'detect-no-operating-point': 'SPICE_ERROR', 'detect-stuck-clock': 'MEAS_MISSING',
    'detect-timeout': 'SPICE_TIMEOUT', 'detect-nan': 'MEAS_INVALID', 'detect-truncated': 'MEAS_MISSING',
}
REJECT_GOAL = {'TABLE_DELAY': 'reject/table', 'TABLE_SETUP': 'reject/table', 'TABLE_HOLD': 'reject/table',
               'SPICE_ERROR': 'reject/spice-error', 'MEAS_MISSING': 'reject/missing',
               'SPICE_TIMEOUT': 'reject/timeout', 'MEAS_INVALID': 'reject/invalid'}


def delay_jobs(table, tag='grid', fault=None, settings=None, corners=False):
    slews, loads = table['clock_slew_ps'], table['load_ff']
    if corners:
        slews, loads = [slews[0], slews[-1]], [loads[0], loads[-1]]
    return [dict(id=MODEL.delay_id(edge, slew, load_, tag), kind='delay', new=new, clock_slew=slew * 1e-12,
                 data_slew=table['delay_data_slew_ps'] * 1e-12, load=load_ * 1e-15, fault=fault, settings=settings)
            for slew in slews for load_ in loads for edge, new in EDGES.items()]


def check_jobs(table, tag='grid', fault=None, settings=None, kinds=('setup', 'hold'), first_only=False):
    data, clock = table['data_slew_ps'], table['clock_slew_check_ps']
    if first_only:
        data, clock = data[:1], clock[:1]
    return [dict(id=MODEL.check_id(kind, edge, d, k, tag), kind=kind, new=new, clock_slew=k * 1e-12,
                 data_slew=d * 1e-12, load=table['check_load_ff'] * 1e-15, low=LOW, high=HIGH,
                 fault=fault, settings=settings)
            for d in data for k in clock for kind in kinds for edge, new in EDGES.items()]


def device_jobs():
    jobs = [dict(id=i, kind='device', device=k, vgs=g, vds=d) for i, k, g, d in MODEL.DEVICE_POINTS]
    return jobs + [dict(id='threshold', kind='threshold')]


def point_jobs(table):
    """Captures placed around the table values: just inside, just outside, and far outside."""
    d, k = table['data_slew_ps'][0], table['clock_slew_check_ps'][0]
    base = dict(kind='point', clock_slew=k * 1e-12, data_slew=d * 1e-12, load=table['check_load_ff'] * 1e-15)
    jobs = []
    for edge, new in EDGES.items():
        setup, hold = table['setup_' + edge][0][0] * 1e-12, table['hold_' + edge][0][0] * 1e-12
        for name, shift in (('inside', 6e-12), ('outside', -6e-12), ('violation', -60e-12)):
            jobs.append(dict(base, id=f'point/setup-{edge}/{name}', new=new, offset=setup + shift,
                             trace=f'setup-{edge}-{name}.csv'))
            jobs.append(dict(base, id=f'point/hold-{edge}/{name}', new=new, offset=CELLS_REFERENCE, back=hold + shift))
    return jobs


CELLS_REFERENCE = 1.0e-9   # the data offset used when only the return edge is varied


def random_points(table, seed, count=4):
    rng = random.Random(seed)
    slews, loads = table['clock_slew_ps'], table['load_ff']
    points = []
    for index in range(count):
        slew = round(rng.uniform(slews[0], slews[-1]), 1)
        load_ = round(rng.uniform(loads[0], loads[-1]), 1)
        edge = ('rise', 'fall')[index % 2]
        points.append(dict(id=f'random{seed}/{index}', kind='delay', new=EDGES[edge], edge=edge, slew=slew, load_ff=load_,
                           clock_slew=slew * 1e-12, data_slew=table['delay_data_slew_ps'] * 1e-12, load=load_ * 1e-15))
    return points


def sweep_jobs(table):
    d, k = table['data_slew_ps'][0], table['clock_slew_check_ps'][0]
    values = [v * 1e-12 for v in range(-120, 161, 20)]
    return [dict(id=f'sweep/{kind}-{edge}', kind='sweep-' + kind, new=new, clock_slew=k * 1e-12, data_slew=d * 1e-12,
                 load=table['check_load_ff'] * 1e-15, values=values)
            for kind in ('setup', 'hold') for edge, new in EDGES.items()]


def loose_job(table):
    job = check_jobs(table, 'loose', kinds=('setup',), first_only=True)[0]
    return dict(job, id='loose/setup-rise', criterion='captures')


class Bench:
    def __init__(self, evidence, args, prefix):
        self.e, self.args, self.prefix = evidence, args, prefix

    def measure(self, name, jobs, timeout=None):
        """Run one batch in a child process. Any failure of the batch itself is labelled, never ignored."""
        directory = self.e.out / name
        directory.mkdir()
        (directory / 'jobs.json').write_text(json.dumps(jobs, indent=1) + '\n')
        output = directory / 'results.json'
        command = [sys.executable, str(HERE / 'measure.py'), str(self.prefix), str(directory / 'jobs.json'), str(output)]
        execution = E.P.execute(command, directory / 'ngspice.log', timeout or self.args.timeout, directory)
        if execution['error']:
            label = 'SPICE_TIMEOUT' if 'timeout' in execution['error'] else 'SPICE_ERROR'
            MODEL.fail(label, f"{name}: {execution['error']}")
        if execution['returncode'] != 0 or not output.is_file():
            MODEL.fail('SPICE_ERROR', f'{name}: the measurement process failed; see ngspice.log')
        return read_results(output, jobs)


def read_results(path, jobs):
    data = json.loads(Path(path).read_text())
    results = {r['id']: r for r in data['results']}
    if len(results) != len(data['results']):
        MODEL.fail('MEAS_INVALID', 'duplicate result id')
    missing = [j['id'] for j in jobs if j['id'] not in results]
    if missing:
        MODEL.fail('MEAS_MISSING', 'no result for ' + ', '.join(missing[:3]))
    return results


def judge_grid(results, table, tag='grid'):
    """Delay, then setup, then hold, against the table. Returns the measured tables."""
    delays = MODEL.measured_delays(results, table, tag)
    worst = dict(delay=MODEL.compare_delays(delays, table))
    checks = MODEL.measured_checks(results, table, tag)
    worst['setup'] = MODEL.compare_checks(checks, table, 'setup')
    worst['hold'] = MODEL.compare_checks(checks, table, 'hold')
    return delays, checks, worst


def run(args):
    table = MODEL.load_table()
    seeds = list(range(args.seed, args.seed + (3 if args.profile == 'nightly' else 1)))
    nightly = args.profile == 'nightly'
    requirements = HERE / 'requirements.json'
    _, goals = E.C.catalog(requirements)
    ids = ['ngspice-installation', 'model/devices', 'delay/table', 'delay/trends', 'delay/load-slope',
           'delay/estimate', 'setup/table', 'hold/table', 'constraint/trends', 'search/evidence',
           'criterion/loose', 'boundary/setup', 'boundary/hold', 'violation/setup', 'violation/hold',
           'settings/robust', 'liberty/round-trip', 'liberty/existing']
    ids += [f'interpolation/seed{seed}' for seed in seeds]
    ids += ['sweep/setup', 'sweep/hold'] if nightly else []
    ids += [*DETECT, 'coverage', 'source-freshness']
    sources = [Path(__file__), Path(MODEL.__file__), Path(CELLS.__file__), HERE / 'measure.py', MODEL.TABLE,
               MODEL.LIBERTY, requirements, Path(N.__file__), N.CONFIG, ROOT / N.spec()['patch']['file'], *EXISTING.values()]
    plan = dict(table=table, seeds=seeds, criterion='CLK->Q within 110 % of the settled delay',
                search=dict(low_ps=LOW * 1e12, high_ps=HIGH * 1e12, resolution_ps=MODEL.RESOLUTION),
                solver=dict(CELLS.OPTIONS, step=CELLS.STEP, max_step=CELLS.MAX_STEP), tight=TIGHT, negative=DETECT)
    e = E.Evidence(NAME, args, sources, plan, ids)
    prefix_log = e.out / 'ngspice-prefix.log'
    probe = E.P.execute([args.ngspice_config, '--prefix'], prefix_log, args.timeout, e.out)
    if probe['error'] or probe['returncode'] != 0:
        raise ValueError('ngspice configuration unavailable; run tools/setup_ngspice.py')
    prefix = Path(prefix_log.read_text().strip()).resolve()
    snapshot = N.snapshot(prefix)
    E.P.write_json(e.out / 'ngspice-source.json', snapshot)
    probe = N.probe(prefix)
    e.check('ngspice-installation', probe['success'], probe)
    bench = Bench(e, args, prefix)
    hits = set()

    def check(name, action, goal_names=()):
        """A normal check: passes when the action returns, and credits its goals only then."""
        try:
            detail = action()
            hits.update(goal_names)
            return e.check(name, True, detail)
        except MODEL.Mismatch as exc:
            print(f'CHECK_FAIL {exc.label} {name}: {exc}', flush=True)
            return e.check(name, False, dict(label=exc.label, detail=str(exc)))
        except (OSError, ValueError, KeyError, TypeError, ArithmeticError) as exc:
            return e.check(name, False, dict(error=str(exc)))

    randoms = [p for seed in seeds for p in random_points(table, seed)]
    jobs = (device_jobs() + delay_jobs(table) + check_jobs(table) + [loose_job(table)] + point_jobs(table) +
            delay_jobs(table, 'tight', settings=TIGHT, corners=True) +
            check_jobs(table, 'tight', settings=TIGHT, first_only=True) + randoms + (sweep_jobs(table) if nightly else []))
    try:
        results = bench.measure('main', jobs)
    except MODEL.Mismatch as exc:
        print(f'CHECK_FAIL {exc.label} main: {exc}', flush=True)
        results = {}
    state = {}

    check('model/devices', lambda: MODEL.check_devices(results), ['model/current', 'model/threshold'])

    def delay_table():
        state['delays'] = MODEL.measured_delays(results, table)
        return dict(worst_ps=MODEL.compare_delays(state['delays'], table), measured=state['delays'])
    check('delay/table', delay_table, ['delay/table'])
    check('delay/trends', lambda: MODEL.check_trends(state['delays']), ['delay/load', 'delay/slew'])
    check('delay/load-slope', lambda: MODEL.check_slope(state['delays'], table), ['delay/load-slope'])
    check('delay/estimate', lambda: MODEL.check_estimate(state['delays']), ['delay/estimate'])

    def constraint(kind):
        state.setdefault('checks', MODEL.measured_checks(results, table))
        worst = MODEL.compare_checks(state['checks'], table, kind)
        return dict(worst_ps=worst, measured={n: v for n, v in state['checks'].items() if n.startswith(kind)})
    check('setup/table', lambda: constraint('setup'), ['setup/table'])
    check('hold/table', lambda: constraint('hold'), ['hold/table'])

    def trends():
        MODEL.check_constraint_trends(state['checks'])
        negative = min(v for name in ('hold_rise', 'hold_fall') for row in state['checks'][name] for v in row)
        if negative < 0:
            hits.add('hold/negative')
        return dict(smallest_hold_ps=negative)
    check('constraint/trends', trends, ['setup/data-slew', 'hold/clock-slew'])

    def evidence():
        counts = [MODEL.check_search(MODEL.need(results, j['id'], 'value', 'fails_at')) for j in check_jobs(table)]
        return dict(searches=len(counts), probes=sum(counts), most=max(counts))
    check('search/evidence', evidence, ['search/evidence'])

    def loose():
        strict = MODEL.ps(MODEL.need(results, MODEL.check_id('setup', 'rise', table['data_slew_ps'][0],
                                                            table['clock_slew_check_ps'][0]), 'value')['value'])
        relaxed = MODEL.ps(MODEL.need(results, 'loose/setup-rise', 'value')['value'])
        if relaxed > strict - MODEL.LOOSE_GAP:
            MODEL.fail('CRITERION', f'loose criterion {relaxed:.2f} ps is not clearly below {strict:.2f} ps')
        return dict(degrade_10_percent_ps=strict, captures_at_all_ps=relaxed)
    check('criterion/loose', loose, ['search/criterion'])

    def points(kind, names):
        report = {}
        for edge in EDGES:
            for name in names:
                record = MODEL.need(results, f'point/{kind}-{edge}/{name}', 'final_q', 'reference')
                target = EDGES[edge] * CELLS.VDD
                took = abs(record['final_q'] - target) < 0.1 * CELLS.VDD
                report[f'{edge}/{name}'] = dict(captured=record['captured'], final_q=round(record['final_q'], 3),
                                                delay_ps=None if record['delay'] is None else MODEL.ps(record['delay']))
                if name == 'inside' and not record['captured']:
                    MODEL.fail('BOUNDARY', f'{kind} {edge}: a capture 6 ps inside the table value failed')
                if name == 'outside' and record['captured']:
                    MODEL.fail('BOUNDARY', f'{kind} {edge}: a capture 6 ps outside the table value passed')
                if name == 'violation' and (took or record['captured']):
                    MODEL.fail('VIOLATION', f'{kind} {edge}: Q took the new value 60 ps outside the table value')
        return report
    check('boundary/setup', lambda: points('setup', ('inside', 'outside')), ['setup/boundary'])
    check('boundary/hold', lambda: points('hold', ('inside', 'outside')), ['hold/boundary'])
    check('violation/setup', lambda: points('setup', ('violation',)), ['setup/violation'])
    check('violation/hold', lambda: points('hold', ('violation',)), ['hold/violation'])

    def settings():
        worst = dict(delay=0.0, constraint=0.0)
        for job in delay_jobs(table, 'tight', corners=True):
            tight = MODEL.ps(MODEL.need(results, job['id'], 'delay')['delay'])
            normal = MODEL.ps(MODEL.need(results, job['id'].replace('tight/', 'grid/', 1), 'delay')['delay'])
            worst['delay'] = max(worst['delay'], abs(tight - normal))
        for job in check_jobs(table, 'tight', first_only=True):
            tight = MODEL.ps(MODEL.need(results, job['id'], 'value')['value'])
            normal = MODEL.ps(MODEL.need(results, job['id'].replace('tight/', 'grid/', 1), 'value')['value'])
            worst['constraint'] = max(worst['constraint'], abs(tight - normal))
        if worst['delay'] > MODEL.SETTINGS_DELAY or worst['constraint'] > MODEL.SETTINGS_CONSTRAINT:
            MODEL.fail('SETTINGS', f'tighter solver settings move the result: {worst}')
        return worst
    check('settings/robust', settings, ['settings/robust'])

    check('liberty/round-trip', lambda: MODEL.round_trip(table, MODEL.LIBERTY.read_text()) and
          (MODEL.LIBERTY.read_text() == MODEL.liberty(table) or MODEL.fail('LIBERTY_TABLE', 'ff_measured.lib is stale')),
          ['liberty/round-trip'])

    def existing():
        report = {name: MODEL.compare_existing(table, path.read_text()) for name, path in EXISTING.items()}
        if not all(v['existing_is_constant'] for r in report.values() for v in r.values()):
            MODEL.fail('EXISTING', 'an existing teaching table is no longer constant; reread the comparison')
        spread = max(max(r) for r in table['cell_rise']) / min(min(r) for r in table['cell_rise'])
        if spread < 1.2:
            MODEL.fail('EXISTING', 'the measured table shows no dependence either')
        return dict(measured_spread=spread, libraries=report)
    check('liberty/existing', existing, ['liberty/existing-constant'])

    for seed in seeds:
        def interpolation(seed=seed):
            worst, rows = 0.0, []
            for point in random_points(table, seed):
                measured = MODEL.ps(MODEL.need(results, point['id'], 'delay')['delay'])
                expected = MODEL.interpolate(table['clock_slew_ps'], table['load_ff'], table['cell_' + point['edge']],
                                             point['slew'], point['load_ff'])
                rows.append(dict(edge=point['edge'], slew_ps=point['slew'], load_ff=point['load_ff'],
                                 measured_ps=measured, interpolated_ps=expected))
                worst = max(worst, abs(measured - expected))
                if abs(measured - expected) > MODEL.INTERPOLATION_ABS + MODEL.INTERPOLATION_REL * expected:
                    MODEL.fail('INTERPOLATION', f'{point}: measured {measured:.2f} ps, interpolated {expected:.2f} ps')
            return dict(worst_ps=worst, points=rows)
        check(f'interpolation/seed{seed}', interpolation, ['delay/interpolated'])

    if nightly:
        for kind in ('setup', 'hold'):
            check(f'sweep/{kind}', lambda kind=kind: {
                edge: MODEL.check_sweep(MODEL.need(results, f'sweep/{kind}-{edge}'), table[f'{kind}_{edge}'][0][0])
                for edge in EDGES}, [])

    # ---- negative cases: each must be rejected, and with the planned label -------------
    def tampered(name, row, column, change):
        copy = json.loads(json.dumps(table))
        copy[name][row][column] = change(copy[name][row][column])
        return copy

    def faulty(fault, with_checks):
        jobs = delay_jobs(table, fault=fault) + (check_jobs(table, fault=fault, kinds=('setup',)) if with_checks else [])
        measured = bench.measure(fault, jobs)
        delays = MODEL.measured_delays(measured, table)
        MODEL.compare_delays(delays, table)
        if with_checks:
            checks = {n: [] for n in MODEL.CHECK_TABLES}
            for d in table['data_slew_ps']:
                row = {n: [] for n in MODEL.CHECK_TABLES}
                for k in table['clock_slew_check_ps']:
                    for edge in EDGES:
                        row['setup_' + edge].append(MODEL.ps(MODEL.need(measured, MODEL.check_id('setup', edge, d, k), 'value')['value']))
                for n in ('setup_rise', 'setup_fall'):
                    checks[n].append(row[n])
            checks['hold_rise'], checks['hold_fall'] = table['hold_rise'], table['hold_fall']
            MODEL.compare_checks(checks, table, 'setup')

    def single(fault):
        job = dict(delay_jobs(table)[0], fault=fault, id='single')
        MODEL.need(bench.measure(fault, [job]), 'single', 'delay')

    def broken_copy(change):
        data = json.loads((e.out / 'main/results.json').read_text())
        change(data['results'])
        path = e.out / f'tampered-{len(list(e.out.glob("tampered-*")))}.json'
        path.write_text(json.dumps(data) + '\n')
        judge_grid(read_results(path, delay_jobs(table) + check_jobs(table)), table)

    def poison(rows):
        next(r for r in rows if r['id'] == delay_jobs(table)[3]['id'])['delay'] = float('nan')

    actions = {
        'detect-table-delay': lambda: judge_grid(results, tampered('cell_rise', 1, 1, lambda v: v * 1.08)),
        'detect-table-setup': lambda: judge_grid(results, tampered('setup_fall', 0, 1, lambda v: v + 10)),
        'detect-table-hold': lambda: judge_grid(results, tampered('hold_rise', 1, 0, lambda v: v - 10)),
        'detect-weak-output': lambda: faulty('weak-output', False),
        'detect-slow-master': lambda: faulty('slow-master', True),
        'detect-no-operating-point': lambda: single('double-supply'),
        'detect-stuck-clock': lambda: single('stuck-clock'),
        'detect-timeout': lambda: bench.measure('timeout', jobs, timeout=0.2),
        'detect-nan': lambda: broken_copy(poison),
        'detect-truncated': lambda: broken_copy(lambda rows: rows.pop(len(device_jobs()) + 5)),
    }
    for name, expected in DETECT.items():
        try:
            actions[name]()
            e.check(name, False, dict(expected=expected, actual=None, detail='the negative case was accepted'))
        except MODEL.Mismatch as exc:
            if exc.label == expected:
                hits.add(REJECT_GOAL[expected])
            print(f'CHECK_FAIL {exc.label} {name}: {exc}', flush=True)
            e.check(name, exc.label == expected, dict(expected=expected, actual=exc.label, detail=str(exc)))
        except (OSError, ValueError, KeyError, TypeError, ArithmeticError) as exc:
            e.check(name, False, dict(expected=expected, error=str(exc)))

    e.check('coverage', goals <= hits, dict(hit=sorted(hits), missing=sorted(goals - hits), unplanned=sorted(hits - goals)))
    frozen = json.loads((e.out / 'manifest.json').read_text())['source_sha256']
    changed = [name for name, sha in frozen.items() if N.digest(ROOT / name) != sha]
    N.verify(snapshot)
    e.check('source-freshness', not changed, changed)
    return e.finish()


def main():
    parser = E.parser(__doc__, NAME)
    parser.add_argument('--ngspice-config', default='lsi-ngspice-config')
    args = parser.parse_args()
    E.validate(parser, args)
    config_command = shutil.which(args.ngspice_config)
    if config_command:
        args.ngspice_config = str(Path(config_command).absolute())
    try:
        return run(args)
    except (OSError, ValueError, TypeError, KeyError) as exc:
        print('RUNNER_ERROR', exc, file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())

#!/usr/bin/env python3
"""Judge ngspice runs automatically: analytic values, expected ranges, corners, Monte Carlo and failures."""
import argparse
from datetime import datetime, timezone
import importlib.util
import json
import math
from pathlib import Path
import shutil
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


M = load('spice_regression_model', HERE / 'model.py')
E = load('spice_regression_evidence', HERE.parent / 'local-exploration-common/evidence.py')
N = load('ngspice_installation', ROOT / 'tools/ngspice.py')
P = E.P
NAME = 'local-spice-regression'
EXPECTED = HERE / 'expected.json'
REQUIREMENTS = HERE / 'requirements.json'
SOLVER = HERE / 'solve.py'
ENDLESS_LIMIT = 3.0   # seconds allowed to the analysis that is built not to finish


# ---------------------------------------------------------------- jobs

def inverter_job(name, process, temp, vdd, measures=('tphl', 'tplh', 'swing'), tool=True, dump=None, **options):
    job = M.inverter_deck(process, temp, vdd, **options)
    job['dump'] = dump
    half = vdd / 2
    available = dict(
        tphl=dict(name='tphl', kind='delay', source='v(in)', target='v(out)', level=half, source_rising=True),
        tplh=dict(name='tplh', kind='delay', source='v(in)', target='v(out)', level=half, source_rising=False),
        swing=dict(name='swing', kind='swing_ratio', source='v(in)', target='v(out)'))
    job.update(id=name, measure=[available[m] for m in measures])
    if tool:
        job['tool_measure'] = dict(
            tphl=f'meas tran tphl trig v(in) val={half:g} rise=1 targ v(out) val={half:g} fall=1',
            tplh=f'meas tran tplh trig v(in) val={half:g} fall=1 targ v(out) val={half:g} rise=1')
    return job


def ring_job(name, process, temp, vdd, dump=None, **options):
    job = M.ring_deck(process, temp, vdd, **options)
    job['dump'] = dump
    half = vdd / 2
    job.update(id=name, measure=[dict(name='period', kind='period', signal='v(n0)', level=half)],
               tool_measure=dict(six_periods=f'meas tran six_periods trig v(n0) val={half:g} rise=3 '
                                             f'targ v(n0) val={half:g} rise=9'))
    return job


def rc_job(name, resistance, capacitance, tau=None, dump=None, **options):
    job = M.rc_deck(resistance, capacitance, **options)
    job['dump'] = dump
    tau = tau or resistance * capacitance
    job.update(id=name, measure=[dict(name='t50', kind='crossing', signal='v(vout)', level=0.5),
                                 dict(name='rise', kind='rise', signal='v(vout)', low=0.1, high=0.9),
                                 dict(name='error', kind='rc_error', signal='v(vout)', tau=tau)],
               tool_measure=dict(t50='meas tran t50 when v(vout)=0.5',
                                 rise='meas tran rise trig v(vout) val=0.1 rise=1 targ v(vout) val=0.9 rise=1'))
    return job


class Solver:
    def __init__(self, evidence, args, prefix):
        self.e, self.args, self.prefix, self.calls = evidence, args, prefix, 0

    def run(self, name, jobs, timeout=None):
        """Run the jobs in one worker process. Every job comes back with a status, never silently."""
        directory = self.e.out / name
        directory.mkdir(parents=True)
        for job in jobs:
            if job.get('dump'):
                job['dump'] = str(directory / job['dump'])
        P.write_json(directory / 'jobs.json', jobs)
        result = directory / 'results.json'
        execution = P.execute([sys.executable, str(SOLVER), str(self.prefix), str(directory / 'jobs.json'), str(result)],
                              directory / 'solver.log', timeout or self.args.timeout, directory)
        self.calls += 1
        if execution['error'] or execution['returncode'] != 0 or not result.is_file():
            label = 'SPICE_TIMEOUT' if 'timeout' in str(execution['error']) else 'SPICE_FATAL'
            return {job['id']: dict(id=job['id'], status=label, detail=str(execution['error'] or 'worker failed'),
                                    values={}, tool={}, points=0) for job in jobs}
        records = {r['id']: r for r in json.loads(result.read_text())}
        if set(records) != {job['id'] for job in jobs}:
            raise ValueError('the worker returned a different set of jobs')
        return records


def good(record):
    """A job must have finished and measured everything before any value is judged."""
    if record['status'] != 'ok':
        raise M.Mismatch(record['status'], f"{record['id']}: {record['detail']}")
    return record


def agree(label, name, a, b, tolerance):
    M.finite(name, a)
    M.finite(name, b)
    if abs(a - b) > tolerance * abs(b):
        raise M.Mismatch(label, f'{name}: {a:.6g} and {b:.6g} differ by more than {tolerance:g}')


def shown(values):
    return {k: float(f'{v:.6g}') for k, v in values.items()}


# ---------------------------------------------------------------- checks

class Checks:
    def __init__(self, solver, expected, profile, seed):
        self.s, self.x, self.profile, self.seed = solver, expected, profile, seed
        self.t = expected['tolerance']
        self.cache = {}

    # RC: analytic values
    def rc(self, item, resistance=None, key=None):
        tau = item['r'] * item['c']
        record = good(self.s.run(key or 'rc-' + item['name'], [rc_job('rc', resistance or item['r'], item['c'], tau=tau,
                                                                     dump='waveform.csv')])['rc'])
        reference = M.rc_reference(tau)
        if record['values']['error'] > self.t['rc_waveform']:
            raise M.Mismatch('RC_TAU', f"waveform differs from 1-exp(-t/RC) by {record['values']['error']:.3g} V")
        for name in ('t50', 'rise'):
            agree('RC_TAU', name, record['values'][name], reference[name], self.t['rc_time'])
            agree('RC_TAU', name + ' by ngspice', record['tool'][name], reference[name], self.t['rc_time'])
        return dict(tau=tau, reference=shown(reference), measured=shown(record['values']), tool=shown(record['tool']),
                    points=record['points'])

    # inverter: two measurement methods, expected range, a hand estimate
    def inverter_values(self, corner, key, **options):
        process, temp, vdd = M.CORNERS[corner]
        record = good(self.s.run(key, [inverter_job('inv', process, temp, vdd, dump='waveform.csv', **options)])['inv'])
        for name in ('tphl', 'tplh'):
            agree('MEAS_METHOD', name, record['values'][name], record['tool'][name], self.t['method'])
        return record

    def inverter(self, corner, key=None, **options):
        record = self.inverter_values(corner, key or 'inv-' + corner, **options)
        process, _, vdd = M.CORNERS[corner]
        for name in ('tphl', 'tplh'):
            M.in_range('INV_DELAY', name, record['values'][name], self.x['inverter'][corner][name], self.t['range'])
        low, high = self.t['swing']
        if not low <= record['values']['swing'] <= high:
            raise M.Mismatch('INV_SWING', f"output swing is {record['values']['swing']:.4g} of the input swing")
        ratio = record['values']['tphl'] / M.drive_estimate(process, vdd, M.LOAD)
        low, high = self.t['estimate']
        if not low <= ratio <= high:
            raise M.Mismatch('INV_ESTIMATE', f'tphl is {ratio:.3g} times the hand estimate')
        if not key:
            self.cache['inv-' + corner] = record['values']
        return dict(measured=shown(record['values']), tool=shown(record['tool']), estimate_ratio=float(f'{ratio:.4g}'))

    # ring oscillator
    def ring(self, corner, key=None, **options):
        process, temp, vdd = M.CORNERS[corner]
        record = good(self.s.run(key or 'ring-' + corner, [ring_job('ring', process, temp, vdd, dump='waveform.csv',
                                                                     **options)])['ring'])
        period = record['values']['period']
        agree('MEAS_METHOD', 'period', period, record['tool']['six_periods'] / 6, self.t['method'])
        M.in_range('RING_FREQ', 'period', period, self.x['ring'][corner]['period'], self.t['range'])
        stage = self.cache['inv-' + corner]
        ratio = period / (M.STAGES * (stage['tphl'] + stage['tplh']))
        low, high = self.t['ring_stage']
        if not low <= ratio <= high:
            raise M.Mismatch('RING_STAGE', f'period is {ratio:.3g} times the stage delays')
        if not key:
            self.cache['ring-' + corner] = period
        return dict(period=float(f'{period:.6g}'), frequency_hz=float(f'{1/period:.6g}'),
                    stage_ratio=float(f'{ratio:.4g}'))

    # corners
    def order(self):
        for name in ('tphl', 'tplh'):
            fast, typ, slow = (self.cache['inv-' + c][name] for c in ('fast', 'typ', 'slow'))
            if not fast < typ < slow:
                raise M.Mismatch('CORNER_ORDER', f'{name} is not ordered fast < typ < slow')
        fast, typ, slow = (self.cache['ring-' + c] for c in ('fast', 'typ', 'slow'))
        if not fast < typ < slow:
            raise M.Mismatch('CORNER_ORDER', 'ring period is not ordered fast < typ < slow')
        return dict(ring_periods=shown(dict(fast=fast, typ=typ, slow=slow)))

    def grid(self):
        """All 27 corners. Slower process and lower supply must be slower; temperature has no fixed sign."""
        jobs = [inverter_job(f'{p}/{t:g}/{v:g}', p, t, v, measures=('tphl', 'tplh'), tool=False)
                for p in M.PROCESS for t in M.TEMPERATURES for v in M.SUPPLIES]
        records = self.s.run('corner-grid', jobs)
        value = {key: good(r)['values'] for key, r in records.items()}
        processes = list(M.PROCESS)
        for name in ('tphl', 'tplh'):
            for t in M.TEMPERATURES:
                for v in M.SUPPLIES:
                    series = [value[f'{p}/{t:g}/{v:g}'][name] for p in processes]
                    if not series[0] < series[1] < series[2]:
                        raise M.Mismatch('CORNER_ORDER', f'{name} at {t:g} C, {v:g} V is not ordered by process')
                for p in processes:
                    series = [value[f'{p}/{t:g}/{v:g}'][name] for v in M.SUPPLIES]
                    if not series[0] < series[1] < series[2]:
                        raise M.Mismatch('CORNER_ORDER', f'{name} at {p}, {t:g} C is not ordered by supply')
        worst = {name: max(value, key=lambda k: value[k][name]) for name in ('tphl', 'tplh')}
        for name in ('tphl', 'tplh'):
            M.in_range('CORNER_WORST', 'worst ' + name, value[worst[name]][name], self.x['grid_worst'][name],
                       self.t['range'])
        # The sign of the temperature effect depends on the supply. Both facts are part of the record.
        cold_low, hot_low = value['ss/-40/1.08']['tplh'], value['ss/125/1.08']['tplh']
        cold_high, hot_high = value['ss/-40/1.32']['tphl'], value['ss/125/1.32']['tphl']
        margin = 1 + self.x['temperature_inversion_margin']
        if not (cold_low > margin * hot_low and hot_high > margin * cold_high):
            raise M.Mismatch('CORNER_INVERSION', 'the expected temperature inversion is not present')
        return dict(corners=len(value), worst={n: dict(corner=worst[n], value=float(f'{value[worst[n]][n]:.6g}'))
                                               for n in worst},
                    low_supply_tplh=shown(dict(cold=cold_low, hot=hot_low)),
                    high_supply_tphl=shown(dict(cold=cold_high, hot=hot_high)))

    # numerical settings
    def settings(self, kind):
        if kind == 'rc':
            item = self.x['rc'][0]
            records = self.s.run('settings-rc', [rc_job('default', item['r'], item['c']),
                                                 rc_job('strict', item['r'], item['c'], settings=M.STRICT)])
            pairs = [('t50', 't50'), ('rise', 'rise')]
        elif kind == 'inverter':
            records = self.s.run('settings-inverter', [inverter_job('default', 'tt', 25.0, 1.2),
                                                       inverter_job('strict', 'tt', 25.0, 1.2, settings=M.STRICT)])
            pairs = [('tphl', 'tphl'), ('tplh', 'tplh')]
        else:
            records = self.s.run('settings-ring', [ring_job('default', 'tt', 25.0, 1.2),
                                                   ring_job('strict', 'tt', 25.0, 1.2, settings=M.STRICT)])
            pairs = [('period', 'period')]
        default, strict = good(records['default']), good(records['strict'])
        if kind != 'rc' and strict['points'] <= default['points']:
            raise M.Mismatch('SETTINGS_SENSITIVE', 'the strict run did not use a finer step')
        for name, _ in pairs:
            agree('SETTINGS_SENSITIVE', name, default['values'][name], strict['values'][name], self.t['settings'])
        return dict(default=shown(default['values']), strict=shown(strict['values']),
                    points=dict(default=default['points'], strict=strict['points']))

    # Monte Carlo
    def monte_carlo_count(self, key, seed, trials, mean_shift=0.0):
        draws = M.draws(seed, trials, mean_shift=mean_shift)
        jobs = [inverter_job(f't{i}', 'tt', 25.0, 1.2, measures=('tphl', 'tplh'), tool=False,
                             load=M.LOAD * d['load'], shift=d) for i, d in enumerate(draws)]
        records = self.s.run(key, jobs)
        P.write_json(self.s.e.out / key / 'draws.json', draws)
        delays = []
        for i in range(trials):
            values = good(records[f't{i}'])['values']
            delays.append((values['tphl'] + values['tplh']) / 2)
        return delays

    def monte_carlo(self, seed, key=None, mean_shift=0.0):
        mc = self.x['monte_carlo']
        trials = mc['trials'][self.profile]
        delays = self.monte_carlo_count(key or f'mc-seed{seed}', seed, trials, mean_shift)
        passes = sum(d <= mc['limit'] for d in delays)
        low, high = acceptance_region(mc, trials)
        interval = M.clopper_pearson(passes, trials, mc['interval_confidence'])
        detail = dict(trials=trials, passes=passes, accepted=[low, high], pass_rate=round(passes / trials, 4),
                      interval=[round(x, 4) for x in interval], limit=mc['limit'],
                      slowest=float(f'{max(delays):.6g}'), median=float(f'{sorted(delays)[trials // 2]:.6g}'))
        if not low <= passes <= high:
            raise M.Mismatch('MC_YIELD', f'{passes} of {trials} trials pass; accepted {low}..{high}')
        return detail

    def reproducible(self):
        first, again, other = M.draws(self.seed, 20), M.draws(self.seed, 20), M.draws(self.seed + 1, 20)
        if first != again or first == other:
            raise M.Mismatch('MC_REPRODUCE', 'the draws do not depend on the seed alone')
        a = self.monte_carlo_count('mc-repeat-a', self.seed, 20)
        b = self.monte_carlo_count('mc-repeat-b', self.seed, 20)
        if a != b:
            raise M.Mismatch('MC_REPRODUCE', 'two runs of the same trials differ')
        return dict(trials=20, identical=True)

    # failures that must never be a pass
    def failing(self, key, job, timeout=None):
        record = self.s.run(key, [job], timeout)[job['id']]
        good(record)
        return dict(unexpected='the job finished and measured', values=shown(record['values']))

    def abort_returns_zero(self):
        """ngspice returns zero from the transient it aborted; only the messages and the end time show it."""
        job = inverter_job('abort', 'tt', 25.0, 1.2, settings=dict(reltol=1e-12, method='gear', step=5e-12),
                           extra='itl4=2 abstol=1e-18 vntol=1e-12')
        directory = self.s.e.out / 'diagnose-return-code'
        directory.mkdir()
        script = ("import sys,json\nsys.argv=['solve.py']\nimport importlib.util\n"
                  f"spec=importlib.util.spec_from_file_location('w',{str(SOLVER)!r});w=importlib.util.module_from_spec(spec);"
                  "spec.loader.exec_module(w)\n"
                  f"lib=w.Library({str(self.s.prefix)!r});job=json.load(open('job.json'))\n"
                  "lib.messages.clear();assert lib.circuit(job['deck'])==0\ncode=lib.command(job['tran'])\n"
                  "t=lib.vector('time')\n"
                  "print(json.dumps(dict(code=code,end=t[-1] if t else None,stop=job['stop'],"
                  "aborted=any('aborted' in m for m in lib.messages))))\n")
        P.write_json(directory / 'job.json', job)
        (directory / 'probe.py').write_text(script)
        execution = P.execute([sys.executable, 'probe.py'], directory / 'probe.log', self.s.args.timeout, directory)
        if execution['error'] or execution['returncode'] != 0:
            raise M.Mismatch('SPICE_FATAL', 'the return-code probe did not run')
        observed = json.loads((directory / 'probe.log').read_text().strip().splitlines()[-1])
        if observed['code'] != 0 or not observed['aborted'] or observed['end'] >= observed['stop']:
            raise M.Mismatch('DIAGNOSIS', f'the aborted analysis no longer returns zero: {observed}')
        return observed


def acceptance_region(mc, trials):
    reference = mc['reference']
    low, high = M.clopper_pearson(reference['passes'], reference['trials'], mc['reference_confidence'])
    return M.acceptance(trials, low, high, mc['alpha'])


def plan(checks, args):
    """(id, function, label a negative case must end with, goals a pass earns)."""
    x, seed = checks.x, args.seed
    slow = M.CORNERS['slow']
    fast = M.CORNERS['fast']
    cases = []
    for i, item in enumerate(x['rc']):
        cases.append(('rc/' + item['name'], lambda item=item: checks.rc(item), None,
                      ['rc/analytic-waveform', 'rc/t50', 'rc/rise'] + (['rc/three-time-constants'] if i == 2 else [])))
    for corner in M.CORNERS:
        cases.append(('inverter/' + corner, lambda c=corner: checks.inverter(c), None,
                      ['meas/two-methods-delay', 'meas/gross-estimate', 'range/inverter', 'corner/' + corner]))
    for corner in M.CORNERS:
        cases.append(('ring/' + corner, lambda c=corner: checks.ring(c), None,
                      ['meas/two-methods-period', 'meas/ring-vs-stage', 'range/ring']))
    cases += [('corners/order', checks.order, None, ['corner/order']),
              ('corners/grid', checks.grid, None, ['corner/grid-monotonic', 'corner/temperature-inversion']),
              ('settings/rc', lambda: checks.settings('rc'), None, ['settings/rc']),
              ('settings/inverter', lambda: checks.settings('inverter'), None, ['settings/inverter']),
              ('settings/ring', lambda: checks.settings('ring'), None, ['settings/ring'])]
    for s in range(seed, seed + (3 if args.profile == 'nightly' else 1)):
        cases.append((f'monte-carlo/seed{s}', lambda s=s: checks.monte_carlo(s), None, ['mc/accept', 'mc/interval']))
    cases.append(('monte-carlo/reproducible', checks.reproducible, None, ['mc/reproducible']))
    first = x['rc'][0]
    cases += [
        ('detect-rc-resistance', lambda: checks.rc(first, resistance=2 * first['r'], key='detect-rc-resistance'),
         'RC_TAU', ['detect/rc']),
        ('detect-inverter-load', lambda: checks.inverter('typ', key='detect-inverter-load', load=1.15 * M.LOAD),
         'INV_DELAY', ['detect/inverter']),
        ('detect-ring-stage', lambda: checks.ring('typ', key='detect-ring-stage', weak_stage=2),
         'RING_FREQ', ['detect/ring']),
        ('detect-corner-supply', lambda: corner_with(checks, 'slow', (slow[0], slow[1], 1.2), 'detect-corner-supply'),
         'INV_DELAY', ['detect/corner']),
        ('detect-corner-temperature',
         lambda: corner_with(checks, 'fast', (fast[0], 25.0, fast[2]), 'detect-corner-temperature'),
         'INV_DELAY', []),
        ('detect-yield-shift', lambda: checks.monte_carlo(seed, key='detect-yield-shift',
                                                         mean_shift=x['monte_carlo']['shift_for_negative']),
         'MC_YIELD', ['detect/yield-low']),
        ('detect-yield-too-good', lambda: checks.monte_carlo(seed, key='detect-yield-too-good',
                                                            mean_shift=-x['monte_carlo']['shift_for_negative']),
         'MC_YIELD', ['detect/yield-high']),
        ('detect-no-convergence',
         lambda: checks.failing('detect-no-convergence',
                                inverter_job('j', 'tt', 25.0, 1.2, settings=dict(reltol=1e-12, method='gear', step=5e-12),
                                             extra='itl4=2 abstol=1e-18 vntol=1e-12')),
         'SPICE_CONVERGENCE', ['fail/convergence']),
        ('detect-endless-analysis',
         lambda: checks.failing('detect-endless-analysis',
                                endless_job(),
                                timeout=min(ENDLESS_LIMIT, args.timeout)),
         'SPICE_TIMEOUT', ['fail/timeout']),
        ('detect-no-crossing',
         lambda: checks.failing('detect-no-crossing', inverter_job('j', 'tt', 25.0, 1.2, hold_input=True)),
         'SPICE_MEASURE', ['fail/measure']),
        ('detect-not-finite',
         lambda: checks.failing('detect-not-finite', inverter_job('j', 'tt', 25.0, 1.2, measures=('swing',), tool=False,
                                                                 hold_input=True)),
         'SPICE_NONFINITE', ['fail/nonfinite']),
        ('detect-bad-netlist',
         lambda: checks.failing('detect-bad-netlist', broken_netlist()), 'SPICE_NETLIST', ['fail/netlist']),
        ('diagnose-return-code', checks.abort_returns_zero, None, ['fail/return-code-not-enough']),
    ]
    return cases


def corner_with(checks, corner, actual, key):
    """Judge one named corner against a deck that was built for a different condition."""
    process, temp, vdd = actual
    record = good(checks.s.run(key, [inverter_job('inv', process, temp, vdd)])['inv'])
    for name in ('tphl', 'tplh'):
        M.in_range('INV_DELAY', name, record['values'][name], checks.x['inverter'][corner][name], checks.t['range'])
    return dict(measured=shown(record['values']))


def endless_job():
    """The print step stays normal, so nothing is preallocated, but the solver may only move 1e-18 s at a time."""
    job = inverter_job('j', 'tt', 25.0, 1.2)
    job['tran'] = 'tran 5p 5n 0 1e-18'
    return job


def broken_netlist():
    job = inverter_job('j', 'tt', 25.0, 1.2)
    job['deck'] = [line.replace(' nch ', ' missing_model ') if line.startswith('Mn') else line for line in job['deck']]
    return job


def run(args):
    expected = json.loads(EXPECTED.read_text())
    _, goals = E.C.catalog(REQUIREMENTS)
    sources = [Path(__file__), Path(M.__file__), SOLVER, EXPECTED, REQUIREMENTS, Path(N.__file__), N.CONFIG,
               ROOT / N.spec()['patch']['file']]
    mc = expected['monte_carlo']
    ids = ['ngspice-installation']
    # The plan needs the checks object; build it with a solver that is filled in after the evidence exists.
    solver = Solver(None, args, None)
    checks = Checks(solver, expected, args.profile, args.seed)
    cases = plan(checks, args)
    ids += [case[0] for case in cases] + ['requirements', 'source-freshness']
    e = E.Evidence(NAME, args, sources, dict(
        corners={k: list(v) for k, v in M.CORNERS.items()}, settings=M.SETTINGS, strict=M.STRICT, sigma=M.SIGMA,
        monte_carlo=dict(trials=mc['trials'][args.profile], limit=mc['limit'],
                         accepted=list(acceptance_region(mc, mc['trials'][args.profile]))),
        cases=[dict(id=c[0], expected=c[2], goals=c[3]) for c in cases]), ids)
    solver.e = e
    log = e.out / 'ngspice-prefix.log'
    probe = P.execute([args.ngspice_config, '--prefix'], log, args.timeout, e.out)
    if probe['error'] or probe['returncode'] != 0:
        raise ValueError('ngspice configuration unavailable; run tools/setup_ngspice.py')
    solver.prefix = Path(log.read_text().strip()).resolve()
    snapshot = N.snapshot(solver.prefix)
    P.write_json(e.out / 'ngspice-source.json', snapshot)
    installation = N.probe(solver.prefix)
    e.check('ngspice-installation', installation['success'], installation)
    hits = set()
    for name, function, label, earned in cases:
        try:
            detail = function()
            e.check(name, label is None, dict(expected=label, **detail))
            if label is None:
                hits.update(earned)
        except M.Mismatch as exc:
            print(f'CHECK_FAIL {exc.label} {name}: {exc}', flush=True)
            e.check(name, exc.label == label, dict(expected=label, actual=exc.label, detail=str(exc)))
            if exc.label == label:
                hits.update(earned)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            e.check(name, False, dict(expected=label, error=str(exc)))
    e.check('requirements', goals <= hits, dict(goals=len(goals), hit=sorted(hits & goals), missing=sorted(goals - hits)))
    frozen = json.loads((e.out / 'manifest.json').read_text())['source_sha256']
    changed = [name for name, sha in frozen.items() if N.digest(ROOT / name) != sha]
    N.verify(snapshot)
    e.check('source-freshness', not changed, changed)
    P.write_json(e.out / 'solver-calls.json', dict(worker_processes=solver.calls))
    return e.finish()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--profile', choices=('smoke', 'nightly'), default='smoke')
    parser.add_argument('--seed', type=int, default=17)
    parser.add_argument('--timeout', type=float, default=30)
    parser.add_argument('--ngspice-config', default='lsi-ngspice-config')
    parser.add_argument('--out', type=Path,
                        default=Path('artifacts') / datetime.now(timezone.utc).strftime(NAME + '-%Y%m%dT%H%M%S%fZ'))
    args = parser.parse_args()
    if args.seed < 0 or not math.isfinite(args.timeout) or args.timeout <= 0:
        parser.error('nonnegative seed and finite positive timeout required')
    if args.out.exists():
        parser.error('output exists; choose a new --out')
    command = shutil.which(args.ngspice_config)
    if command:
        args.ngspice_config = str(Path(command).absolute())
    try:
        return run(args)
    except (OSError, ValueError, TypeError, KeyError) as exc:
        print('RUNNER_ERROR', exc, file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())

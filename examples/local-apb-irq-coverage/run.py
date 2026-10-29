#!/usr/bin/env python3
"""Apply the interaction-coverage proposal to the real APB/IRQ example locally."""
import argparse
import hashlib
import importlib.util
import os
from pathlib import Path
import re
import resource
import signal
import sys
import time

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


M = load('apb_interaction_model', HERE / 'model.py')
APB = load('apb_interaction_existing', HERE.parent / 'gitlab-apb-irq/run.py')
REDUCTION = load('apb_interaction_selection', HERE.parent / 'gitlab-reduction/run.py')
E = load('apb_interaction_evidence', HERE.parent / 'local-exploration-common/evidence.py')
P = APB.SUPPORT
# (integration mutation, register-block mutation, required checker)
MUTATIONS = {
    'masked-storage': (1, 0, 'APB_IRQ_PENDING'),
    'mask-bypass': (2, 0, 'APB_IRQ_OUTPUT'),
    'sticky-irq': (3, 0, 'APB_IRQ_RELEASE'),
    'clear-priority': (0, 2, 'APB_IRQ_PENDING'),
    'early-write': (0, 1, 'APB_STATE'),
    'error-side-effect': (0, 3, 'APB_ERROR_SIDE_EFFECT'),
}


def make_candidates(wait, profile, seed, transactions):
    args = argparse.Namespace(wait=wait, profile=profile, seed=seed,
                              transactions=transactions, demo_bug=0)
    cases = [dict(id='existing-' + c['id'].split('-', 1)[1], vectors=c['vectors'],
                  origin='existing') for c in APB.make_plan(args)
             if c['category'] == 'functional']
    for bit in range(4):
        value = 1 << bit
        for pending in (0, 1):
            for mask in (0, 1):
                for clear in (0, 1):
                    for event in (0, 1):
                        rows = [[0, 0, 0, 0, 0, 0, 0],
                                [1, 0, 0, 0, 0, 0, value if pending else 0]]
                        rows += APB.transfer(wait, 0, 1, value if mask else 0)
                        rows += APB.transfer(wait, 8, 1, value if clear else 0,
                                             value if event else 0)
                        rows += APB.transfer(wait, 8, 0) + [[1, 0, 0, 0, 0, 0, 0]]
                        cases.append(dict(id=f'atomic-b{bit}-p{pending}-m{mask}-c{clear}-e{event}',
                                          origin='atomic', vectors=rows))
                for offset in (-1, 0, 1):
                    rows = [[0, 0, 0, 0, 0, 0, 0],
                            [1, 0, 0, 0, 0, 0, value if pending else 0]]
                    rows += APB.transfer(wait, 0, 1, value if mask else 0)
                    transaction = APB.transfer(wait, 8, 1, value)
                    if offset <= 0:
                        transaction[len(transaction) - 1 + offset][-1] = value
                    rows += transaction + [[1, 0, 0, 0, 0, 0, value if offset == 1 else 0]]
                    rows += APB.transfer(wait, 8, 0) + [[1, 0, 0, 0, 0, 0, 0]]
                    cases.append(dict(id=f'time-b{bit}-p{pending}-m{mask}-offset{offset}',
                                      origin='temporal', vectors=rows))
    for case in cases:
        case['checks'] = len(case['vectors'])
        case['planned_goals'] = sorted(M.collect(M.project_vectors(case['vectors'], wait)))
    return cases


def full4_goals():
    from itertools import product
    return {f'full4/bit{b}/pending{p}/mask{m}/clear{c}/event{e}'
            for b in range(4) for p, m, c, e in product((0, 1), repeat=4)}


def metrics(cases, results, required):
    planned = {g for c in cases for g in c['planned_goals']}
    observed = {g for r in results for g in r['observed_goals']}
    passed = {g for r in results if r['status'] == 'pass'
              and r.get('probe') is None and r.get('injected_mutation') is None
              for g in r['credited_goals']}
    groups = {}
    for name, goals in dict(required, full4_diagnostic=full4_goals()).items():
        groups[name] = dict(required=len(goals), planned=len(goals & planned),
                            observed=len(goals & observed), passed=len(goals & passed),
                            missing=sorted(goals - passed), mandatory=name != 'full4_diagnostic')
    complete = [r['case_id'] for r in results] == [c['id'] for c in cases]
    clean = complete and all(r['status'] == 'pass' for r in results)
    return dict(success=clean and all(not groups[g]['missing'] for g in required),
                executions_complete=complete, all_cases_pass=clean, groups=groups,
                case_ids=[c['id'] for c in cases], case_count=len(cases),
                planned_cycles=sum(c['checks'] for c in cases),
                observed_cycles=sum(r['observed_cycles'] for r in results),
                simulation_wall_seconds=sum(r['seconds'] for r in results),
                simulation_cpu_seconds=sum(r['cpu_seconds'] for r in results))


class Simulator:
    def __init__(self, evidence):
        self.e = evidence
        self.args = evidence.args
        self.builds = {}
        self.runs = []
        self.tools = {}
        for name in ('iverilog', 'vvp'):
            log = self.e.out / f'{name}-version.log'
            result = P.execute([getattr(self.args, name), '-V'], log, self.args.timeout, self.e.out)
            self.tools[name] = dict(result, output=log.read_text(errors='replace'))
        P.write_json(self.e.out / 'tools.json', self.tools)

    def execute(self, case, wait, phase, probe=None):
        injection = probe or self.args.demo_bug
        integration, register, label = MUTATIONS[injection] if injection else (0, 0, None)
        key = (wait, integration, register)
        if key not in self.builds:
            binary = self.e.out / f'wait{wait}-m{integration}-r{register}.vvp'
            command = [self.args.iverilog, '-g2012', '-s', 'apb_irq_tb',
                       f'-Papb_irq_tb.WAIT_CYCLES={wait}', f'-Papb_irq_tb.MUTATION={integration}',
                       f'-Papb_irq_tb.REGISTER_MUTATION={register}', '-o', str(binary),
                       str(HERE.parent / 'gitlab-apb/rtl/apb_regs.sv'),
                       str(HERE.parent / 'gitlab-apb-irq/rtl/apb_irq.sv'),
                       str(HERE.parent / 'gitlab-apb-irq/tb/apb_irq_tb.sv')]
            build = P.execute(command, self.e.out / f'build-w{wait}-m{integration}-r{register}.log',
                              self.args.timeout, self.e.out)
            self.builds[key] = (binary, build)
        binary, build = self.builds[key]
        run_id = f'wait{wait}/{phase}/{case["id"]}'
        directory = self.e.out / run_id
        directory.mkdir(parents=True, exist_ok=False)
        vector_path = directory / 'vectors.txt'
        vector_path.write_text(''.join(' '.join(str(v) if i < 4 else f'{v:x}'
                                              for i, v in enumerate(row)) + '\n'
                                       for row in case['vectors']))
        trace = directory / 'trace.txt'
        log = directory / 'simulation.log'
        usage = resource.getrusage(resource.RUSAGE_CHILDREN)
        cpu_start = usage.ru_utime + usage.ru_stime
        if build['error'] or build['returncode'] != 0:
            execution = dict(returncode=None, error='build failed', seconds=0, command=[])
            log.write_text('build failed\n')
        else:
            execution = P.execute([self.args.vvp, str(binary), '+VECTORS=' + str(vector_path),
                                   '+TRACE=' + str(trace), '+WAVE=' + str(directory / 'wave.vcd')],
                                  log, self.args.timeout, directory)
        usage = resource.getrusage(resource.RUSAGE_CHILDREN)
        cpu = max(0, usage.ru_utime + usage.ru_stime - cpu_start)
        output = log.read_text(errors='replace')
        if probe:
            status, message = REDUCTION.classify_probe(case, execution, output, (label,))
        else:
            status, message = P.classify(dict(case, expected_failure=None), execution, output)
        records = []
        trace_error = None
        try:
            records = M.read_trace(trace, case['vectors'], complete=status in ('pass', 'survived'))
            wave = directory / 'wave.vcd'
            if not wave.is_file() or '$enddefinitions' not in wave.read_text():
                raise ValueError('missing waveform')
        except (OSError, ValueError) as exc:
            trace_error = str(exc)
            status, message = 'error', 'invalid observation evidence: ' + str(exc)
        observed = M.collect(records) if trace_error is None else {}
        legacy = {'legacy/' + g: [] for g in re.findall(r'^COVER (\S+)$', output, re.M)}
        observed.update(legacy)
        # Even completed earlier cycles in a failed case do not complete a normal goal.
        credited = sorted(observed) if status == 'pass' and injection is None else []
        record = dict(id=run_id, case_id=case['id'], wait=wait, phase=phase, probe=probe, injected_mutation=injection,
                      status=status, message=message, checks=case['checks'],
                      observed_cycles=len(records), observed_goals=sorted(observed),
                      credited_goals=credited, evidence=observed,
                      log=str(log.relative_to(self.e.out)), cpu_seconds=cpu,
                      trace_sha256=hashlib.sha256(trace.read_bytes()).hexdigest() if trace.exists() else None,
                      trace_error=trace_error, **execution)
        P.write_json(directory / 'result.json', record)
        self.runs.append(record)
        return record

    def save(self):
        P.write_json(self.e.out / 'executions.json', self.runs)
        P.write_json(self.e.out / 'builds.json',
                     {str(key): dict(binary=str(binary), **build)
                      for key, (binary, build) in self.builds.items()})


def run(args):
    runner_started = time.monotonic()
    model = M.load_model(args.model)
    waits = (0, 1, 3) if args.wait == 'all' else (int(args.wait),)
    plans = {}
    for wait in waits:
        catalog, applicable, excluded = APB.load_catalog(args.requirements, wait)
        legacy = {g for requirement in applicable for g in requirement['goals']}
        required = M.required_groups(model, legacy)
        cases = make_candidates(wait, args.profile, args.seed, args.transactions)
        # Legacy plan declares the original boundary recipe's intended catalogue coverage.
        cases[0]['planned_goals'] += sorted(required['legacy'])
        plans[wait] = dict(cases=cases, required={g: sorted(v) for g, v in required.items()},
                           legacy_excluded=excluded,
                           mandatory=[c['id'] for c in cases if c['origin'] == 'existing'])
    suffixes = ['learning', 'existing-baseline', 'selection', 'full/coverage', 'selected/coverage',
                'selected/fresh', 'selected/mandatory', 'comparison']
    suffixes += [f'{strategy}/detect/{name}' for strategy in ('full', 'selected') for name in MUTATIONS]
    checks = ['tool-versions'] + [f'wait{wait}/{name}' for wait in waits for name in suffixes]
    inputs = [Path(__file__), HERE / 'model.py', args.model, args.requirements,
              Path(APB.__file__), Path(REDUCTION.__file__),
              HERE.parent / 'gitlab-apb-irq/rtl/apb_irq.sv',
              HERE.parent / 'gitlab-apb-irq/tb/apb_irq_tb.sv',
              HERE.parent / 'gitlab-apb/rtl/apb_regs.sv']
    e = E.Evidence('local-apb-irq-coverage', args, inputs,
                   dict(configurations={str(k): v for k, v in plans.items()},
                        mutation_policy='stable candidate order; stop after first expected detection',
                        mutations=MUTATIONS), checks)
    P.write_json(e.out / 'model.json', model)
    P.write_json(e.out / 'requirements.json', catalog)
    planning_seconds = time.monotonic() - runner_started
    sim = Simulator(e)
    e.check('tool-versions', all(not r['error'] and r['returncode'] == 0
                               for r in sim.tools.values()), sim.tools)
    reports = {}
    for wait in waits:
        plan = plans[wait]
        cases = plan['cases']
        required = {g: set(v) for g, v in plan['required'].items()}
        required_union = set().union(*required.values())
        lookup = {c['id']: c for c in cases}
        learning = [sim.execute(c, wait, 'learning') for c in cases]
        learned = metrics(cases, learning, required)
        report = dict(model_revision=model['revision'], legacy_excluded=plan['legacy_excluded'],
                      learning=learned, measurements={})
        reports[str(wait)] = report
        e.check(f'wait{wait}/learning', learned['success'], learned['groups'])
        if not learned['success']:
            continue
        existing = [lookup[cid] for cid in plan['mandatory']]
        existing_runs = [r for r in learning if r['case_id'] in plan['mandatory']]
        baseline = metrics(existing, existing_runs, required)
        report['existing'] = baseline
        e.check(f'wait{wait}/existing-baseline', baseline['all_cases_pass'] and
                not baseline['groups']['legacy']['missing'], baseline['groups'])
        observations = [dict(id=r['case_id'], checks=r['checks'], status=r['status'],
                             observed_coverage=r['credited_goals']) for r in learning]
        selected, decisions = REDUCTION.greedy_select(observations, required_union, plan['mandatory'])
        if args.omit_additions:
            selected = list(plan['mandatory'])
        selected_cases = [lookup[cid] for cid in selected]
        learned_hits = {g for r in learning if r['case_id'] in selected for g in r['credited_goals']}
        selection_ok = required_union <= learned_hits and set(plan['mandatory']) <= set(selected)
        report['selection'] = dict(case_ids=selected, added_case_ids=sorted(set(selected)-set(plan['mandatory'])),
                                   decisions=decisions, success=selection_ok,
                                   criterion='new observed mandatory goals / planned cycles; deterministic greedy')
        e.check(f'wait{wait}/selection', selection_ok, report['selection'])
        for strategy, chosen in (('full', cases), ('selected', selected_cases)):
            normal = [sim.execute(c, wait, f'{strategy}/normal') for c in chosen]
            measurement = metrics(chosen, normal, required)
            report['measurements'][strategy] = measurement
            e.check(f'wait{wait}/{strategy}/coverage', measurement['success'], measurement['groups'])
            if strategy == 'selected':
                e.check(f'wait{wait}/selected/fresh', all(r['phase'] == 'selected/normal' for r in normal)
                        and len(normal) == len(chosen), [r['id'] for r in normal])
                e.check(f'wait{wait}/selected/mandatory', set(plan['mandatory']) <= set(selected),
                        plan['mandatory'])
            measurement['mutations'] = {}
            for probe in MUTATIONS:
                attempts = []
                # Existing cases go first in both strategies. Observations never guide mutation selection.
                order = sorted(chosen, key=lambda c: (c['origin'] != 'existing', c['id']))
                for case in order:
                    result = sim.execute(case, wait, f'{strategy}/mutation-{probe}', probe)
                    attempts.append(result)
                    if result['status'] in ('detected', 'error'):
                        break
                valid = all(r['status'] in ('detected', 'survived') for r in attempts)
                detected = valid and any(r['status'] == 'detected' for r in attempts)
                measurement['mutations'][probe] = dict(detected=detected, valid=valid,
                                                        attempted=[r['id'] for r in attempts],
                                                        detected_by=[r['id'] for r in attempts
                                                                     if r['status'] == 'detected'])
                e.check(f'wait{wait}/{strategy}/detect/{probe}', detected,
                        measurement['mutations'][probe])
        full, selected_metrics = (report['measurements'][s] for s in ('full', 'selected'))
        comparison_ok = full['success'] and selected_metrics['success']
        report['cost_comparison'] = dict(
            normal_comparison_valid=comparison_ok,
            selected_over_full_cycles=(selected_metrics['observed_cycles'] / full['observed_cycles']
                                       if comparison_ok and full['observed_cycles'] else None),
            selected_over_full_cases=(selected_metrics['case_count'] / full['case_count']
                                      if comparison_ok else None),
            learning_wall_seconds=learned['simulation_wall_seconds'],
            learning_cpu_seconds=learned['simulation_cpu_seconds'],
            license_usage=None, license_note='No commercial EDA tool; license usage not measured',
            peak_collection_memory=None, peak_collection_memory_note='not measured',
            analysis_cost=None, analysis_cost_note='manual analysis cost not measured')
        e.check(f'wait{wait}/comparison', comparison_ok, report['cost_comparison'])
        print(f"wait{wait}: full={full['case_count']} cases/{full['observed_cycles']} cycles; "
              f"selected={selected_metrics['case_count']} cases/{selected_metrics['observed_cycles']} cycles",
              flush=True)
    sim.save()
    P.write_json(e.out / 'coverage.json', reports)
    P.write_json(e.out / 'selection.json', {w: r.get('selection') for w, r in reports.items()})
    P.write_json(e.out / 'costs.json', dict(
        runner_wall_seconds=time.monotonic()-runner_started,
        model_and_manifest_wall_seconds=planning_seconds,
        tool_version_wall_seconds=sum(r["seconds"] for r in sim.tools.values()),
        build_wall_seconds=sum(b['seconds'] for _, b in sim.builds.values()),
        all_simulation_wall_seconds=sum(r['seconds'] for r in sim.runs),
        all_simulation_cpu_seconds=sum(r['cpu_seconds'] for r in sim.runs),
        note='learning, fresh normal comparison, builds and sensitivity probes are distinct costs'))
    return e.finish()


def main():
    parser = E.parser(__doc__, 'local-apb-irq-coverage')
    parser.add_argument('--wait', choices=('all', '0', '1', '3'), default='all')
    parser.add_argument('--transactions', type=int)
    parser.add_argument('--model', type=Path, default=HERE / 'model.json')
    parser.add_argument('--requirements', type=Path, default=HERE.parent / 'gitlab-apb-irq/requirements.json')
    parser.add_argument('--demo-bug', choices=tuple(MUTATIONS), help='diagnostic: inject a defect into normal runs')
    parser.add_argument('--omit-additions', action='store_true', help='diagnostic: retain only existing cases')
    args = parser.parse_args()
    E.validate(parser, args)
    if args.transactions is None:
        args.transactions = 2000 if args.profile == 'nightly' else 200
    if os.name != 'posix' or not 1 <= args.transactions <= 10000:
        parser.error('POSIX and 1..10000 random transactions per seed required')
    previous = signal.signal(signal.SIGTERM, P.interrupted)
    try:
        return run(args)
    except P.RunInterrupted as exc:
        return 128 + exc.signum
    except KeyboardInterrupt:
        return 130
    except (OSError, ValueError, TypeError, KeyError) as exc:
        print('RUNNER_ERROR', exc, file=sys.stderr)
        return 1
    finally:
        signal.signal(signal.SIGTERM, previous)


if __name__ == '__main__':
    sys.exit(main())

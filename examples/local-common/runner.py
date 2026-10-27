"""Local-only Icarus regression support; no GitLab API or CI integration."""
import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import re
import signal
import sys
import xml.etree.ElementTree as ET

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
PROCESS_PATH = HERE.parent / 'gitlab-regression/run.py'
spec = importlib.util.spec_from_file_location('local_process_support', PROCESS_PATH)
PROCESS = importlib.util.module_from_spec(spec)
spec.loader.exec_module(PROCESS)


def catalog(path):
    data = json.loads(path.read_text())
    if (data.get('schema_version') != 1 or type(data.get('revision')) is not int or data['revision'] < 1):
        raise ValueError('unsupported schema_version or invalid revision')
    ids, goals = set(), set()
    requirements = data['requirements']
    if not isinstance(requirements, list) or not requirements:
        raise ValueError('requirements must be a nonempty list')
    for item in requirements:
        rid, names = item['id'], item['goals']
        if (not isinstance(rid, str) or not rid or rid in ids or
                not isinstance(names, list) or not names or
                any(not isinstance(g, str) or not re.fullmatch(r'[A-Za-z0-9_./-]+', g) for g in names) or
                len(set(names)) != len(names) or goals.intersection(names)):
            raise ValueError('invalid or duplicate requirement/goal')
        ids.add(rid)
        goals.update(names)
    return data, goals


def run(plugin, args):
    requirements, required = catalog(args.requirements)
    configurations = (plugin.CONFIGS if args.configuration == 'all' else
                      {args.configuration: plugin.CONFIGS[args.configuration]})
    cases = []
    for configuration, parameters in configurations.items():
        for case in plugin.make_cases(args, parameters):
            case = dict(case, id=configuration + '-' + case['id'], configuration=configuration)
            case['checks'] = len(case['vectors'])
            cases.append(case)
    if not cases or len({c['id'] for c in cases}) != len(cases):
        raise ValueError('empty or duplicate execution plan')
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=False)
    source_paths = [Path(plugin.__file__), Path(__file__), PROCESS_PATH, args.requirements.resolve(), *plugin.SOURCES, *getattr(plugin, 'EXTRA_INPUTS', [])]
    PROCESS.write_json(out / 'manifest.json', dict(
        schema_version=1, created_at=datetime.now(timezone.utc).isoformat(),
        example=plugin.NAME, profile=args.profile, seed=args.seed, iterations=args.iterations,
        configurations=configurations, demo_bug=args.demo_bug, timeout_seconds=args.timeout,
        python=sys.version, cases=cases,
        source_sha256={str(p.relative_to(ROOT) if p.is_relative_to(ROOT) else p):
                       hashlib.sha256(p.read_bytes()).hexdigest() for p in source_paths}))
    PROCESS.write_json(out / 'requirements.json', requirements)
    tools = {}
    for name, command in (('iverilog', [args.iverilog, '-V']), ('vvp', [args.vvp, '-V'])):
        log = out / (name + '-version.log')
        tools[name] = dict(PROCESS.execute(command, log, args.timeout, out),
                           output=log.read_text(errors='replace'))
    PROCESS.write_json(out / 'tools.json', tools)
    builds = {}
    for configuration, parameters in configurations.items():
        for mutation in sorted({c['mutation'] for c in cases if c['configuration'] == configuration}):
            key = f'{configuration}-m{mutation}'
            command = [args.iverilog, '-g2012', '-s', plugin.TOP, '-o', str(out / (key + '.vvp')),
                       f'-P{plugin.TOP}.MUTATION={mutation}']
            command += [f'-P{plugin.TOP}.{name}={value}' for name, value in parameters.items()]
            command += [str(p) for p in plugin.SOURCES]
            builds[key] = PROCESS.execute(command, out / (key + '-build.log'), args.timeout, out)
    PROCESS.write_json(out / 'builds.json', builds)
    results, hits = [], {name: {} for name in configurations}
    for case in cases:
        directory = out / case['id']
        directory.mkdir()
        vectors = directory / 'vectors.txt'
        vectors.write_text(''.join(' '.join(format(value, 'x') for value in row) + '\n' for row in case['vectors']))
        key = f"{case['configuration']}-m{case['mutation']}"
        log = directory / 'simulation.log'
        command = [args.vvp, str(out / (key + '.vvp')), f'+VECTORS={vectors}',
                   f"+WAVE={directory / 'wave.vcd'}"]
        build = builds[key]
        if build['error'] or build['returncode'] != 0:
            execution = dict(command=command, returncode=None, seconds=0,
                             error='build failed; see ' + key + '-build.log')
            log.write_text(execution['error'] + '\n')
        else:
            execution = PROCESS.execute(command, log, args.timeout, directory)
        output = log.read_text(errors='replace')
        status, message = PROCESS.classify(case, execution, output)
        counts = {}
        if status == 'pass':
            message = f"{case['checks']} checked vectors"
            matches = re.findall(r'^COUNT ([a-z_]+)=(\d+)$', output, re.M)
            counts = {name: int(value) for name, value in matches}
            if len(matches) != len(counts) or counts != case['counts']:
                status, message = 'error', 'missing, duplicate or incorrect completion counts'
        observed = sorted(set(re.findall(r'^COVER (\S+)$', output, re.M)))
        credited = observed if status == 'pass' and case['category'] == 'functional' else []
        for goal in credited:
            hits[case['configuration']].setdefault(goal, []).append(case['id'])
        result = dict(id=case['id'], configuration=case['configuration'], category=case['category'],
                      status=status, message=message, counts=counts, observed_coverage=observed,
                      credited_coverage=credited, log=str(log.relative_to(out)), **execution)
        results.append(result)
        PROCESS.write_json(directory / 'result.json', result)
        print(f"{status.upper():8} {case['id']}: {message}", flush=True)
    coverage = {name: dict(success=required <= goals.keys(), required=len(required),
                            hit=len(required.intersection(goals)), missing=sorted(required - goals.keys()),
                            hits=goals, requirements=[dict(r, passed=set(r['goals']) <= goals.keys())
                                                      for r in requirements['requirements']])
                for name, goals in hits.items()}
    complete = [r['id'] for r in results] == [c['id'] for c in cases]
    success = complete and all(c['success'] for c in coverage.values()) and all(
        r['status'] in ('pass', 'detected') for r in results)
    summary = dict(success=success, complete=complete, planned=len(cases), results=len(results),
                   functional_pass=sum(r['category'] == 'functional' and r['status'] == 'pass' for r in results),
                   mutations_detected=sum(r['status'] == 'detected' for r in results),
                   diagnostics_pass=sum(r['category'] == 'diagnostic' and r['status'] == 'pass' for r in results))
    PROCESS.write_json(out / 'coverage.json', coverage)
    PROCESS.write_json(out / 'summary.json', summary)
    suite = ET.Element('testsuite', name='local.' + plugin.NAME, tests=str(len(results) + len(coverage)),
                       failures=str(sum(r['status'] == 'fail' for r in results) + sum(not c['success'] for c in coverage.values())),
                       errors=str(sum(r['status'] == 'error' for r in results)))
    for result in results:
        node = ET.SubElement(suite, 'testcase', name=result['id'],
                             classname='local.' + plugin.NAME + '.' + result['configuration'] + '.' + result['category'],
                             time=f"{result['seconds']:.6f}")
        if result['status'] in ('fail', 'error'):
            ET.SubElement(node, 'failure' if result['status'] == 'fail' else 'error',
                          message=result['message']).text = result['log']
    for name, item in coverage.items():
        node = ET.SubElement(suite, 'testcase', name=name + '-requirements-and-coverage',
                             classname='local.' + plugin.NAME + '.gate')
        if not item['success']:
            ET.SubElement(node, 'failure', message='required goals missing').text = ', '.join(item['missing'])
        print(f"Coverage {name}: {item['hit']}/{item['required']}")
    ET.indent(suite)
    ET.ElementTree(suite).write(out / 'junit.xml', encoding='utf-8', xml_declaration=True)
    print(f"Artifacts: {out}\nRegression: {'PASS' if success else 'FAIL'}")
    return 0 if success else 1


def main(plugin):
    parser = argparse.ArgumentParser(description=plugin.__doc__)
    parser.add_argument('--configuration', choices=['all', *plugin.CONFIGS], default='all')
    parser.add_argument('--profile', choices=('smoke', 'nightly'), default='smoke')
    parser.add_argument('--seed', type=int, default=17)
    parser.add_argument('--iterations', type=int, help='random operations per seed; see example README')
    parser.add_argument('--demo-bug', type=int, choices=(0, 1, 2, 3, 4), default=0)
    parser.add_argument('--iverilog', default='iverilog')
    parser.add_argument('--vvp', default='vvp')
    parser.add_argument('--requirements', type=Path, default=Path(plugin.__file__).parent / 'requirements.json')
    parser.add_argument('--timeout', type=float, default=10.0)
    parser.add_argument('--out', type=Path, default=Path('artifacts') / datetime.now(timezone.utc).strftime(plugin.NAME + '-%Y%m%dT%H%M%S%fZ'))
    args = parser.parse_args()
    if args.iterations is None:
        args.iterations = plugin.ITERATIONS[args.profile]
    if os.name != 'posix' or args.seed < 0 or not 1 <= args.iterations <= 10000 or not math.isfinite(args.timeout) or args.timeout <= 0:
        parser.error('requires POSIX, nonnegative seed, 1..10000 iterations and finite positive timeout')
    if args.out.exists():
        parser.error('output directory already exists; choose a new --out')
    previous = signal.signal(signal.SIGTERM, PROCESS.interrupted)
    try:
        return run(plugin, args)
    except PROCESS.RunInterrupted as exc:
        return 128 + exc.signum
    except KeyboardInterrupt:
        return 130
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print('RUNNER_ERROR ' + str(exc), file=sys.stderr)
        return 1
    finally:
        signal.signal(signal.SIGTERM, previous)

"""Reuse the repository's process/evidence gates for memory integration lessons."""
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


E = load('memory_evidence', HERE.parent / 'local-exploration-common/evidence.py')


class Simulator:
    def __init__(self, plugin, args, out):
        self.plugin, self.args, self.out = plugin, args, Path(out).resolve()
        self.builds = {}

    def execute(self, case):
        p, a = self.plugin, self.args
        directory = self.out / case['id']
        directory.mkdir(parents=True)
        (directory / 'vectors.txt').write_text(case.get('text', ''))
        parameters = dict(case['parameters'], MUTATION=case.get('mutation', 0))
        key = '-'.join(f'{k}{v}' for k, v in sorted(parameters.items()))
        if key not in self.builds:
            binary = self.out / (key + '.vvp')
            build = E.P.execute([a.iverilog, '-g2012', '-s', p.TOP, '-o', str(binary),
                *[f'-P{p.TOP}.{k}={v}' for k, v in sorted(parameters.items())],
                *map(str, p.SOURCES)], self.out / (key + '-build.log'), a.timeout, self.out)
            self.builds[key] = binary, build
        binary, build = self.builds[key]
        if build['error'] or build['returncode'] != 0:
            execution = dict(error='build failed', returncode=None)
            (directory / 'simulation.log').write_text('build failed\n')
        else:
            command = [a.vvp, str(binary), '+VECTORS=' + str(directory / 'vectors.txt'),
                '+CSV=' + str(directory / 'trace.csv'), f"+SEED={case['seed']}",
                f"+CHECKS={case['checks']}", '+CASE=' + case['id']]
            if a.waves:
                command += ['+WAVE=' + str(directory / 'trace.vcd')]
            execution = E.P.execute(command, directory / 'simulation.log', a.timeout, directory)
        log = (directory / 'simulation.log').read_text(errors='replace')
        expected = case.get('expected_failure')
        status, message = E.P.classify(dict(checks=case['checks'], expected_failure=None), execution, log)
        if status == 'pass':
            try:
                if re.findall(r'^COUNT steps=(\d+)$', log, re.M) != [str(case['checks'])]:
                    raise ValueError('missing or duplicate completion count')
                if 'WARNING:' in log:
                    raise ValueError('unexpected simulation warning')
                if a.waves and '$enddefinitions' not in (directory / 'trace.vcd').read_text():
                    raise ValueError('missing waveform')
                if hasattr(p, 'postcheck'):
                    comparison = p.postcheck(case, directory)
                    E.P.write_json(directory / 'comparison.json', comparison)
                    if not comparison['success']:
                        status, message = 'fail', comparison['message']
                        print(f"CHECK_FAIL {p.LABEL} {case['id']} {message}", flush=True)
                        if expected == p.LABEL:
                            status = 'detected'
            except (ValueError, OSError, KeyError) as exc:
                status, message = 'error', str(exc)
            if expected and status == 'pass':
                status, message = 'fail', 'mutation escaped the checker'
        elif expected:
            status, message = E.P.classify(dict(checks=case['checks'], expected_failure=expected), execution, log)
        result = dict(id=case['id'], status=status, message=message, parameters=parameters,
            seed=case['seed'], build=build, execution=execution,
            goals=sorted(set(re.findall(r'^COVER (\S+)$', log, re.M))) if status == 'pass' else [])
        E.P.write_json(directory / 'result.json', result)
        return result


def run(plugin, args):
    catalog_path = Path(plugin.__file__).with_name('requirements.json')
    _, goals = E.C.catalog(catalog_path)
    if goals != set(plugin.GOALS):
        raise ValueError('required goals differ from the reviewed catalog')
    cases = plugin.cases(args)
    normal = [c for c in cases if not c.get('expected_failure')]
    configs = sorted({c['configuration'] for c in normal})
    ids = ['toolchain', *[c['id'] for c in cases], *[c + '/coverage' for c in configs], 'source-freshness']
    inputs = [Path(plugin.__file__), Path(__file__), catalog_path, *plugin.SOURCES, *plugin.INPUTS]
    evidence = E.Evidence(plugin.NAME, args, inputs, dict(cases=cases), ids)
    probes = {n: E.P.execute([getattr(args, n), '-V'], evidence.out / (n + '-version.log'),
        args.timeout, evidence.out) for n in ('iverilog', 'vvp')}
    E.P.write_json(evidence.out / 'tools.json', probes)
    evidence.check('toolchain', all(not r['error'] and r['returncode'] == 0 for r in probes.values()), probes)
    simulator = Simulator(plugin, args, evidence.out)
    results = []
    for case in cases:
        result = simulator.execute(case)
        result['configuration'] = case['configuration']
        results.append(result)
        evidence.check(case['id'], result['status'] == ('detected' if case.get('expected_failure') else 'pass'), result)
    coverage = {}
    for config in configs:
        hits = {g for r in results if r['configuration'] == config for g in r['goals']}
        required = set(plugin.GOALS)
        coverage[config] = dict(required=sorted(required), hit=sorted(hits), missing=sorted(required-hits))
        evidence.check(config + '/coverage', not (required-hits), coverage[config])
    E.P.write_json(evidence.out / 'coverage.json', coverage)
    frozen = json.loads((evidence.out / 'manifest.json').read_text())['source_sha256']
    changed = [f for f, sha in frozen.items() if hashlib.sha256((ROOT/f).read_bytes()).hexdigest() != sha]
    evidence.check('source-freshness', not changed, changed)
    return evidence.finish()


def main(plugin):
    parser = E.parser(plugin.__doc__, plugin.NAME)
    parser.add_argument('--waves', action='store_true')
    args = parser.parse_args()
    E.validate(parser, args)
    if args.seed > 2**30:
        parser.error('seed must be at most 2**30')
    try:
        return run(plugin, args)
    except (OSError, ValueError, TypeError, KeyError) as exc:
        print('RUNNER_ERROR', exc, file=sys.stderr)
        return 1

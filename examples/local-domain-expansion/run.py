#!/usr/bin/env python3
"""Run the twelve domain examples and audit their simulation evidence."""
import importlib.util
import json
import math
from pathlib import Path
import sys
import xml.etree.ElementTree as ET

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
NAME = HERE.name
REGISTRY = ROOT / 'tools/regressions.json'
spec = importlib.util.spec_from_file_location(
    'domain_evidence', HERE.parent / 'local-exploration-common/evidence.py')
E = importlib.util.module_from_spec(spec)
spec.loader.exec_module(E)
R = E.load('domain_regression', ROOT / 'tools/run_regression.py')


def verify_child(directory, entry, entries, args):
    """Check both configurations, the seed, every planned case and its source."""
    audit = R.inspect_output(directory, entry, entries, ROOT, args.profile)
    manifest = json.loads((directory / 'manifest.json').read_text())
    summary = json.loads((directory / 'summary.json').read_text())
    coverage = json.loads((directory / 'coverage.json').read_text())
    configs = manifest['configurations']
    normal = 8 if args.profile == 'nightly' else 4
    if (manifest['example'] != entry['id'] or manifest['seed'] != args.seed
            or len(configs) != 2 or set(coverage) != set(configs)
            or audit['junit'] != normal + 10 or summary['planned'] != normal + 8
            or summary['functional_pass'] != normal or summary['mutations_detected'] != 8):
        raise ValueError('child identity, seed, configuration or case counts differ')
    for config, result in coverage.items():
        if (result['success'] is not True or result['required'] <= 0
                or result['hit'] != result['required'] or result['missing']):
            raise ValueError(f'incomplete coverage: {config}')
    return audit


def run(args):
    entries = R.load_registry(REGISTRY)
    children = entries[NAME]['children']
    evidence = E.Evidence(NAME, args, [Path(__file__), REGISTRY, Path(R.__file__)],
                          dict(children=list(children)), children)
    executions = {}
    for name, relative in children.items():
        command = [sys.executable, str(ROOT / entries[name]['script']),
                   '--profile', args.profile, '--seed', str(args.seed),
                   '--out', str(evidence.out / relative)]
        executions[name] = E.P.execute(command, evidence.out / (name + '.log'),
                                       args.child_timeout, evidence.out)
        E.P.write_json(evidence.out / (name + '-execution.json'), executions[name])

    # Audit after the last execution so an edit while a later child runs is visible.
    for name, relative in children.items():
        result = executions[name]
        if result['error'] or result['returncode'] != 0:
            evidence.check(name, False, result)
            continue
        try:
            detail = verify_child(evidence.out / relative, entries[name], entries, args)
        except (KeyError, OSError, TypeError, ValueError, ET.ParseError) as exc:
            evidence.check(name, False, str(exc))
        else:
            evidence.check(name, True, detail)
    return evidence.finish()


def main():
    parser = E.parser(__doc__, NAME)
    parser.add_argument('--child-timeout', type=float, default=1800)
    args = parser.parse_args()
    E.validate(parser, args)
    if not math.isfinite(args.child_timeout) or args.child_timeout <= 0 or args.seed > 2**31 - 4:
        parser.error('invalid child timeout or seed')
    return run(args)


if __name__ == '__main__':
    sys.exit(main())

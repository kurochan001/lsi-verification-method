#!/usr/bin/env python3
"""Six local gap examples: security, performance, CDC, JTAG, address map and lockstep."""
import importlib.util
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('gap_evidence', HERE.parent / 'local-exploration-common/evidence.py')
E = importlib.util.module_from_spec(spec)
spec.loader.exec_module(E)
CORE = ['local-secure-lifecycle', 'local-performance-monitor', 'local-cdc-handshake',
        'local-jtag-tap', 'local-address-map', 'local-lockstep-monitor']


def child_success(summary):
    if not isinstance(summary, dict) or summary.get('success') is not True or summary.get('complete') is not True:
        return False
    planned = summary.get('planned')
    results = summary.get('results')
    if type(planned) is not int or planned <= 0:
        return False
    if type(results) is int:
        return results == planned
    if not isinstance(results, list) or len(results) != planned:
        return False
    if not all(isinstance(r, dict) and r.get('status') == 'pass' and isinstance(r.get('id'), str) and r['id'].strip()
               for r in results):
        return False
    return len({r['id'] for r in results}) == len(results)


def run(args):
    names = CORE if args.stage in ('all', 'core') else []
    e = E.Evidence('local-gap-regression', args, [Path(__file__)],
                   dict(children=names, parent_cases='child regression gates; child checks are separate'), names)
    for name in names:
        command = [sys.executable, str(HERE.parent / name / 'run.py'), '--profile', args.profile,
                   '--seed', str(args.seed), '--out', str(e.out / name)]
        execution = E.P.execute(command, e.out / (name + '.log'), args.child_timeout, e.out)
        ok = False
        detail = execution['error'] or execution['returncode']
        try:
            summary = json.loads((e.out / name / 'summary.json').read_text())
            ok = not execution['error'] and execution['returncode'] == 0 and child_success(summary)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            detail = str(exc)
        E.P.write_json(e.out / (name + '-execution.json'), execution)
        e.check(name, ok, detail)
    return e.finish()


def main():
    p = E.parser(__doc__, 'local-gap-regression')
    p.add_argument('--stage', choices=('all', 'core'), default='all')
    p.add_argument('--child-timeout', type=float, default=1800)
    args = p.parse_args()
    E.validate(p, args)
    import math
    if not math.isfinite(args.child_timeout) or args.child_timeout <= 0 or args.seed > 2**31 - 4:
        p.error('invalid timeout/seed')
    try:
        return run(args)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print('RUNNER_ERROR', exc, file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())

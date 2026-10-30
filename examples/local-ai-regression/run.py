#!/usr/bin/env python3
"""Six AI circuit examples: systolic array, requantization, activation, conv window, top-K and MXFP4."""
import importlib.util
import json
import math
import os
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('ai_evidence', HERE.parent / 'local-exploration-common/evidence.py')
E = importlib.util.module_from_spec(spec)
spec.loader.exec_module(E)
SIMULATIONS = ['local-systolic-array', 'local-requantize', 'local-activation', 'local-conv-window']
FORMALS = ['local-topk']
VERILATOR = ['local-mxfp4']
STAGES = {'all': SIMULATIONS + FORMALS + VERILATOR, 'simulation': SIMULATIONS, 'formal': FORMALS, 'mxfp4': VERILATOR}


def child_success(summary):
    """Accept the three child summary forms only when every planned case finished and passed."""
    if not isinstance(summary, dict) or summary.get('success') is not True:
        return False
    planned = summary.get('planned')
    results = summary.get('results')
    if type(planned) is not int or planned <= 0:
        return False
    if type(results) is int:  # common Icarus runner
        return results == planned and summary.get('complete') is True
    if not isinstance(results, list) or len(results) != planned:
        return False
    if not all(isinstance(r, dict) and isinstance(r.get('id'), str) and r['id'].strip() for r in results):
        return False
    if len({r['id'] for r in results}) != len(results):
        return False
    if all('outcome' in r for r in results):  # formal runner: proofs pass, mutants are detected
        return all(r['outcome'] in ('pass', 'detected') for r in results)
    return summary.get('complete') is True and all(r.get('status') == 'pass' for r in results)


def command(args, name, out):
    if name in FORMALS:
        # Re-enter through this file so the formal interpreter's bin directory is on PATH.
        return [args.formal_python, str(Path(__file__).resolve()), '--formal-child',
                str(HERE.parent / name / 'run.py'), '--timeout', str(args.formal_timeout), '--out', str(out)]
    return [args.python, str(HERE.parent / name / 'run.py'), '--profile', args.profile,
            '--seed', str(args.seed), '--out', str(out)]


def run(args):
    names = STAGES[args.stage]
    e = E.Evidence('local-ai-regression', args, [Path(__file__)],
                   dict(children=names, parent_cases='child regression gates; child checks are separate'), names)
    for name in names:
        execution = E.P.execute(command(args, name, e.out / name), e.out / (name + '.log'), args.child_timeout, e.out)
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
    p = E.parser(__doc__, 'local-ai-regression')
    p.add_argument('--stage', choices=tuple(STAGES), default='all')
    p.add_argument('--python', default=sys.executable)
    p.add_argument('--formal-python', default=sys.executable)
    p.add_argument('--formal-timeout', type=float, default=600)
    p.add_argument('--child-timeout', type=float, default=3600)
    args = p.parse_args()
    E.validate(p, args)
    if any(not math.isfinite(t) or t <= 0 for t in (args.formal_timeout, args.child_timeout)) or args.seed > 2**31 - 4:
        p.error('invalid timeout/seed')
    try:
        return run(args)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print('RUNNER_ERROR', exc, file=sys.stderr)
        return 1


if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] == '--formal-child':
        os.environ['PATH'] = str(Path(sys.executable).parent) + os.pathsep + os.environ.get('PATH', '')
        os.execv(sys.executable, [sys.executable, *sys.argv[2:]])
    sys.exit(main())

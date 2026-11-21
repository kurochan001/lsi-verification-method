#!/usr/bin/env python3
"""Apply a reusable property library by bind and compare Verilator with SBY on the same traces."""
from concurrent.futures import ThreadPoolExecutor
import importlib.util
import json
import math
from pathlib import Path
import re
import shutil
import sys

HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location('sva_patterns_evidence', HERE.parent / 'local-exploration-common/evidence.py')
E = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(E)
M = E.load('sva_patterns_model', HERE / 'model.py')
P = E.P

NAME = 'local-sva-patterns'
LIBRARY = sorted((HERE / 'sva').glob('pat_*.sv'))
REPORT = HERE / 'sva/pat_report.svh'
BIND = HERE / 'sva/bind_patterns.sv'
RTL = {'tagged_queue': HERE / 'rtl/tagged_queue.sv', 'event_cross': HERE / 'rtl/event_cross.sv'}
ASSERTION_FORMS = ('hold', 'onehot', 'within', 'nodup', 'pipe')     # patterns that also have a bound assertion form
MUTANTS = {1: 'hold', 2: 'onehot', 3: 'within', 4: 'nodup', 5: 'order', 6: 'cross', 7: 'pipe'}
PROVED = ('hold', 'onehot', 'within', 'pipe')                       # k-induction; the others are bounded
EVAL_CASES = ('RANGE_CONSEQUENT', 'LOCALVAR_FIXED', 'GOTO_FIRST_CYCLE', 'RANGE_ANTECEDENT', 'UNBOUNDED_CONSEQUENT', 'LOCALVAR_GOTO')
ACCEPT_CASES = ('concurrent', 'immediate', 'bind', 'multiclock', 'localvar_fixed', 'localvar_sequence')
HALF_B = (7, 3, 13)
BIND_RE = re.compile(r'^bind\s+(\w+)\s+(\w+\s+(?:#\(.*?\)\s+)?(u_\w+)\s*\(.*\);)\s*$', re.M)
INPUTS = [Path(__file__), HERE / 'model.py', HERE / 'expected.json', HERE / 'requirements.json', HERE / 'probes/expected.json',
          HERE / 'probes/eval.sv', *[HERE / f'probes/accept_{n}.sv' for n in ACCEPT_CASES], *LIBRARY, REPORT, BIND, *RTL.values(),
          *[HERE / 'tb' / n for n in ('trace_harness.sv', 'trace_tb.sv', 'dut_tb.sv', 'queue_formal.sv', 'cross_formal.sv', 'queue_invariants.svh')]]


def profile(args):
    nightly = args.profile == 'nightly'
    return dict(seeds=list(range(args.seed, args.seed + (3 if nightly else 1))), traces=20, cycles=2000 if nightly else 400,
                depth=dict(nodup=28 if nightly else 24, order=16 if nightly else 14, cross=46 if nightly else 40))


def plan_ids(args):
    seeds = profile(args)['seeds']
    ids = ['tool-versions', 'build', 'tool-acceptance', 'tool-evaluation', 'diagnose-order-local-variable']
    ids += [f'trace-{p}-{k}' for p in M.PATTERNS for k in M.KINDS]
    ids += [f'sby-{p}-{k}' for p in M.PATTERNS for k in M.KINDS]
    ids += [f'random-{p}-seed{s}' for p in M.PATTERNS for s in seeds]
    ids += ['dut-clean-fixed', *[f'dut-clean-seed{s}' for s in seeds], *[f'dut-mutant{m}' for m in MUTANTS]]
    ids += ['formal-bind-rewrite', *[f'formal-clean-{p}' for p in M.PATTERNS], *[f'formal-mutant{m}' for m in MUTANTS], 'requirements']
    return ids


def bindings(formal):
    """Parse sva/bind_patterns.sv: the part before the simulation-only guard is what Yosys gets."""
    text = BIND.read_text(encoding='utf-8')
    head, guard, tail = text.partition('`ifndef FORMAL')
    if not guard or '`endif' not in tail:
        raise ValueError('bind file lost its simulation-only section')
    found = [(m[1], m[2], m[3]) for m in BIND_RE.finditer(head if formal else tail)]
    if len(found) != len(re.findall(r'^bind\b', head if formal else tail, re.M)) or len({f[2] for f in found}) != len(found):
        raise ValueError('unparsed or duplicate bind statement')
    return found


def rewrite(target, keep=None, invariants=False):
    """Yosys reads no bind: turn the statements for one module into instances before its endmodule."""
    chosen = [(body, name) for module, body, name in bindings(True) if module == target and (keep is None or name in keep)]
    if not chosen:
        raise ValueError('no binding selected for ' + target)
    source = RTL[target].read_text(encoding='utf-8')
    if source.count('endmodule') != 1:
        raise ValueError('bind rewrite expects one module per file')
    cut = source.rindex('endmodule')
    extra = (HERE / 'tb/queue_invariants.svh').read_text(encoding='utf-8') if invariants else ''
    return (source[:cut] + '  // Instances rewritten from sva/bind_patterns.sv\n' + ''.join(f'  {body}\n' for body, _ in chosen) +
            extra + source[cut:]), [name for _, name in chosen]


def reports(log, tick=None):
    """PAT_FAIL / PAT_HIT lines as {(pattern, form, kind): [times or ticks]}."""
    found = {}
    for kind, path, time in re.findall(r'^PAT_(FAIL|HIT) (\S+) (\d+)$', log, re.M):
        match = re.search(r'\.u_(\w+)_(aux|sva)(?:\.|$)', path)
        if not match:
            raise ValueError('report from an unknown instance: ' + path)
        found.setdefault((match[1], match[2], kind), []).append(tick(int(time)) if tick else int(time))
    return {key: sorted(value) for key, value in found.items()}


def trace_tick(time):
    if (time - 5) % 20:
        raise ValueError('report off the trace clock grid')
    return (time - 5) // 20


def parse_sby(log, error=None):
    """Status, first failed assertion and cover results of one SBY console log."""
    done = re.findall(r'DONE \((\w+), rc=\d+\)', log)
    status = done[-1] if len(done) == 1 and not error else 'ERROR'
    failed = re.search(r'failed assertion (\S+) at \S+(?: step (\d+))?', log)
    reached = {m[2]: int(m[1]) for m in re.finditer(r'Reached cover statement in step (\d+) at (\S+): c_antecedent', log)}
    unreached = set(re.findall(r'Unreached cover statement at (\S+): c_antecedent', log))
    return dict(status=status, failed=failed[1] if failed else None, step=int(failed[2]) if failed and failed[2] else None,
                reached=reached, unreached=unreached, induction='successful proof by k-induction' in log)


class Runner:
    def __init__(self, args, evidence):
        self.a, self.e, self.out, self.p = args, evidence, evidence.out, profile(args)
        self.expected = json.loads((HERE / 'expected.json').read_text(encoding='utf-8'))
        self.probe_expected = json.loads((HERE / 'probes/expected.json').read_text(encoding='utf-8'))
        self.pool = ThreadPoolExecutor(max_workers=args.jobs)

    def verilate(self, name, top, sources, extra=()):
        directory = self.out / 'build' / name
        directory.mkdir(parents=True)
        command = [self.a.verilator, '--binary', '--assert', '--timing', '--coverage-user', '-Wno-fatal', '--top-module', top,
                   f'-I{HERE / "sva"}', *extra, '--Mdir', str(directory / 'obj'), '-o', 'sim', *map(str, sources)]
        execution = P.execute(command, directory / 'build.log', self.a.build_timeout, directory)
        return name, execution['returncode'] == 0 and not execution['error'] and (directory / 'obj/sim').is_file(), directory / 'obj/sim'

    def simulate(self, binary, directory, plusargs):
        directory.mkdir(parents=True, exist_ok=True)
        execution = P.execute([str(binary), *plusargs], directory / 'simulation.log', self.a.timeout, directory)
        log = (directory / 'simulation.log').read_text(errors='replace')
        return execution['returncode'] == 0 and not execution['error'], log

    def sby(self, name, mode, depth, files, script, multiclock=False):
        """Run one SBY task; return status, first failed assertion and cover results."""
        directory = self.out / 'formal' / name
        directory.mkdir(parents=True)
        names = []
        for item in files:
            if isinstance(item, tuple):
                (directory / item[0]).write_text(item[1], encoding='utf-8')
                names.append(item[0])
            else:
                shutil.copyfile(item, directory / item.name)
                names.append(item.name)
        reading = 'read_verilog -sv -formal ' + ' '.join(n for n in names if n.endswith('.sv'))
        (directory / 'task.sby').write_text(
            f'[options]\nmode {mode}\ndepth {depth}\n' + ('multiclock on\n' if multiclock else '') +
            '\n[engines]\nsmtbmc z3\n\n[script]\n' + reading + '\n' + script + '\n\n[files]\n' + '\n'.join(names) + '\n', encoding='utf-8')
        execution = P.execute([self.a.sby, '--yosys', self.a.yosys, '--smtbmc', self.a.smtbmc, '--witness', self.a.witness, 'task.sby'],
                              directory / 'console.log', self.a.formal_timeout, directory)
        return dict(name=name, seconds=execution['seconds'], **parse_sby((directory / 'console.log').read_text(errors='replace'), execution['error']))

    # --- stages -------------------------------------------------------------------------------
    def tools(self):
        probes = {}
        for name, command in (('verilator', [self.a.verilator, '--version']), ('yosys', [self.a.yosys, '-V']), ('sby', [self.a.sby, '--version'])):
            probes[name] = P.execute(command, self.out / f'{name}-version.log', self.a.timeout, self.out)
            probes[name]['text'] = (self.out / f'{name}-version.log').read_text(errors='replace').strip()[:200]
        P.write_json(self.out / 'tools.json', probes)
        return self.e.check('tool-versions', all(v['returncode'] == 0 and not v['error'] for v in probes.values()),
                            {k: v['text'] for k, v in probes.items()})

    def build(self):
        jobs = [('trace', 'trace_tb', [HERE / 'tb/trace_tb.sv', HERE / 'tb/trace_harness.sv', *LIBRARY], ())]
        jobs += [(f'dut-m{m}', 'dut_tb', [HERE / 'tb/dut_tb.sv', *RTL.values(), *LIBRARY, BIND], (f'-GMUTATION={m}',)) for m in (0, *MUTANTS)]
        jobs += [(f'eval-{c}', 'eval', [HERE / 'probes/eval.sv'], (f'-D{c}',)) for c in EVAL_CASES]
        results = list(self.pool.map(lambda job: self.verilate(*job), jobs))
        self.binary = {name: path for name, ok, path in results}
        failed = [name for name, ok, _ in results if not ok]
        return self.e.check('build', not failed, dict(builds=len(results), failed=failed))

    def acceptance(self):
        directory = self.out / 'probes'
        directory.mkdir()
        seen = {}
        for case in ACCEPT_CASES:
            source = HERE / f'probes/accept_{case}.sv'
            v = P.execute([self.a.verilator, '--lint-only', '--assert', '--timing', '-Wno-fatal', '--top-module', 'probe', str(source)],
                          directory / f'{case}.verilator.log', self.a.build_timeout, directory)
            script = directory / f'{case}.ys'
            script.write_text(f'read_verilog -sv -formal "{source}"\nhierarchy -top probe\nproc\n', encoding='utf-8')
            y = P.execute([self.a.yosys, '-q', '-s', str(script)], directory / f'{case}.yosys.log', self.a.formal_timeout, directory)
            if v['error'] or y['error']:
                return self.e.check('tool-acceptance', False, dict(case=case, error=v['error'] or y['error']))
            seen[case] = dict(verilator=v['returncode'] == 0, yosys=y['returncode'] == 0)
        expected = self.probe_expected['acceptance']
        return self.e.check('tool-acceptance', seen == expected, dict(observed=seen, differs=[c for c in seen if seen[c] != expected.get(c)]))

    def evaluation(self):
        observed, ok = {}, True
        for case in EVAL_CASES:
            passed, log = self.simulate(self.binary[f'eval-{case}'], self.out / 'probes' / case, [])
            fails = [int(n) for n in re.findall(r'^PROBE_FAIL (\d+)$', log, re.M)]
            spec = self.probe_expected['evaluation'][case]
            verdict = 'correct' if fails == spec['correct'] else 'recorded-difference' if fails == spec.get('recorded') else 'unexpected'
            # A form used by the library must be evaluated correctly; the others may show the recorded difference.
            if not passed or 'PROBE_DONE' not in log or verdict == 'unexpected' or (spec.get('used_by_library') and verdict != 'correct'):
                ok = False
            observed[case] = dict(fails=fails, verdict=verdict)
        return self.e.check('tool-evaluation', ok, observed)

    def trace_run(self, pattern, rows, directory):
        directory.mkdir(parents=True, exist_ok=True)
        (directory / 'trace.hex').write_text(M.encode(rows), encoding='utf-8')
        passed, log = self.simulate(self.binary['trace'], directory, ['+TRACE=trace.hex', f'+SEL={M.SEL[pattern]}'])
        if not passed or 'TRACE_DONE' not in log:
            raise ValueError('trace simulation did not complete')
        found = reports(log, trace_tick)
        if any(key[0] != pattern for key in found):
            raise ValueError('an unselected checker reported')
        return {(form, kind): found.get((pattern, form, kind), []) for form in ('aux', 'sva') for kind in ('FAIL', 'HIT')}

    def traces(self):
        ok, self.trace_seen, order_sva = True, {}, {}
        fixed = M.fixed_traces()
        for pattern in M.PATTERNS:
            for kind in M.KINDS:
                name, want, rows = f'trace-{pattern}-{kind}', self.expected[pattern][kind], fixed[pattern, kind]
                try:
                    seen = self.trace_run(pattern, rows, self.out / 'traces' / f'{pattern}-{kind}')
                    model_fails, model_hits = M.evaluate(pattern, rows)
                    good = (seen['aux', 'FAIL'] == want['fails'] == model_fails and len(seen['aux', 'HIT']) == want['hits'] == len(model_hits) and
                            seen['aux', 'HIT'] == model_hits and (bool(want['fails']), want['hits'] > 0) ==
                            dict(**{'pass': (False, True), 'violation': (True, True), 'vacuous': (False, False)})[kind])
                    if pattern in ASSERTION_FORMS:
                        good = good and seen['sva', 'FAIL'] == seen['aux', 'FAIL'] and seen['sva', 'HIT'] == seen['aux', 'HIT']
                    if pattern == 'order':
                        order_sva[kind] = seen['sva', 'FAIL']
                    self.trace_seen[pattern, kind] = seen
                    detail = dict(expected=want, helper=dict(fails=seen['aux', 'FAIL'], hits=seen['aux', 'HIT']),
                                  assertion=dict(fails=seen['sva', 'FAIL'], hits=seen['sva', 'HIT']) if pattern in ASSERTION_FORMS else 'no bound assertion form')
                except (ValueError, OSError) as exc:
                    good, detail = False, str(exc)
                ok = self.e.check(name, good, detail) and ok
        spec = self.probe_expected['order_local_variable']
        verdict = 'correct' if order_sva == spec['correct'] else 'recorded-difference' if order_sva == spec['recorded'] else 'unexpected'
        ok = self.e.check('diagnose-order-local-variable', verdict != 'unexpected', dict(fails=order_sva, verdict=verdict)) and ok
        return ok

    def random_traces(self):
        """Half of the traces obey the property and half break it; both forms must match the model on all."""
        ok, half = True, self.p['traces'] // 2
        for pattern in M.PATTERNS:
            for seed in self.p['seeds']:
                try:
                    legal = [M.random_trace(pattern, seed * 1000 + index, False) for index in range(half)]
                    candidates = (M.random_trace(pattern, seed * 1000 + index, True) for index in range(400))
                    broken = [rows for rows in candidates if M.evaluate(pattern, rows)[0]][:half]
                    good, hits = len(broken) == half and not any(M.evaluate(pattern, rows)[0] for rows in legal), 0
                    for index, rows in enumerate(legal + broken):
                        seen = self.trace_run(pattern, rows, self.out / 'random' / f'{pattern}-seed{seed}' / str(index))
                        model = M.evaluate(pattern, rows)
                        hits += len(model[1])
                        if (seen['aux', 'FAIL'], seen['aux', 'HIT']) != model:
                            good = False
                        if pattern in ASSERTION_FORMS and (seen['sva', 'FAIL'], seen['sva', 'HIT']) != model:
                            good = False
                    good = good and hits > 0
                    detail = dict(traces_without_violation=len(legal), traces_with_violation=len(broken), antecedents=hits,
                                  forms='helper and assertion' if pattern in ASSERTION_FORMS else 'helper only')
                except (ValueError, OSError) as exc:
                    good, detail = False, str(exc)
                ok = self.e.check(f'random-{pattern}-seed{seed}', good, detail) and ok
        return ok

    def dut_run(self, name, mutation, seed, half_b):
        rows = M.queue_stimulus(seed, self.p['cycles'])
        directory = self.out / 'dut' / name
        directory.mkdir(parents=True)
        (directory / 'vectors.hex').write_text('\n'.join(M.queue_vectors(rows)) + '\n', encoding='utf-8')
        completed, log = self.simulate(self.binary[f'dut-m{mutation}'], directory, ['+VECTORS=vectors.hex', f'+CYCLES={len(rows)}', f'+HALF_B={half_b}'])
        counts = {k: int(v) for k, v in re.findall(r'^COUNT (\w+)=(\d+)$', log, re.M)}
        result = re.findall(r'^RESULT (\w+)$', log, re.M)
        if not completed or result not in (['PASS'], ['FAIL']) or counts.get('checked') != len(rows):
            raise ValueError('queue simulation did not complete')
        found = reports(log)
        return dict(model_pass=result == ['PASS'], labels=sorted(set(re.findall(r'^CHECK_FAIL (\w+)', log, re.M))), counts=counts, found=found)

    def dut(self):
        ok = True
        cases = [('dut-clean-fixed', None, HALF_B[0])] + [(f'dut-clean-seed{s}', s, HALF_B[i % 3]) for i, s in enumerate(self.p['seeds'])]
        for name, seed, half_b in cases:
            try:
                r = self.dut_run(name, 0, seed, half_b)
                hits = {p: len(r['found'].get((p, 'aux', 'HIT'), [])) for p in M.PATTERNS}
                same = all(r['found'].get((p, 'sva', 'HIT'), []) == r['found'].get((p, 'aux', 'HIT'), []) for p in ASSERTION_FORMS)
                failures = sorted({key[:2] for key in r['found'] if key[2] == 'FAIL'})
                good = r['model_pass'] and not failures and all(hits.values()) and same and r['counts'].get('accepted', 0) > 0
                detail = dict(half_period_b=half_b, checked=r['counts'].get('checked'), antecedents=hits, failures=failures, forms_agree=same)
            except (ValueError, OSError) as exc:
                good, detail = False, str(exc)
            ok = self.e.check(name, good, detail) and ok
        for mutation, pattern in MUTANTS.items():
            try:
                r = self.dut_run(f'dut-mutant{mutation}', mutation, self.a.seed, HALF_B[0])
                helper = r['found'].get((pattern, 'aux', 'FAIL'), [])
                good = bool(helper)
                if pattern in ASSERTION_FORMS:
                    good = good and r['found'].get((pattern, 'sva', 'FAIL'), []) == helper
                others = sorted({key[0] for key in r['found'] if key[2] == 'FAIL' and key[0] != pattern})
                detail = dict(pattern=pattern, failures=len(helper), first_time=helper[0] if helper else None, other_patterns=others,
                              model_comparison='noticed' if not r['model_pass'] else 'not noticed', labels=r['labels'])
            except (ValueError, OSError) as exc:
                good, detail = False, str(exc)
            ok = self.e.check(f'dut-mutant{mutation}', good, detail) and ok
        return ok

    def formal(self):
        library = [*LIBRARY, REPORT]
        fixed = M.fixed_traces()
        jobs = {}
        for pattern in M.PATTERNS:
            for kind in M.KINDS:
                top = ('trace_top.sv', f"module trace_top(input logic gclk);\n  trace_harness #(.LEN({M.LEN})) u (.gclk(gclk), .sel(3'd{M.SEL[pattern]}));\nendmodule\n")
                files = [*library, HERE / 'tb/trace_harness.sv', top, ('trace.hex', M.encode(fixed[pattern, kind]))]
                for mode in ('bmc', 'cover'):
                    jobs[f'trace-{pattern}-{kind}-{mode}'] = (mode, 2 * M.LEN, files, 'prep -top trace_top', True)
        rewritten = {}
        for pattern in M.PATTERNS:
            target, top, multiclock = ('event_cross', 'cross_formal', True) if pattern == 'cross' else ('tagged_queue', 'queue_formal', False)
            instance = [f'u_{pattern}_aux']
            proved = pattern in PROVED
            depth = 8 if proved else self.p['depth'][pattern]
            clean, names = rewrite(target, instance, invariants=proved)
            plain, _ = rewrite(target, instance)
            rewritten[pattern] = names
            base = [*library, HERE / f'tb/{top}.sv']
            script = 'hierarchy -top {0} -chparam MUTATION {1}\nprep -top {0}'
            jobs[f'clean-{pattern}'] = ('prove' if proved else 'bmc', depth, [*base, (f'{target}_bound.sv', clean)], script.format(top, 0), multiclock)
            jobs[f'clean-{pattern}-cover'] = ('cover', depth, [*base, (f'{target}_bound.sv', plain)], script.format(top, 0), multiclock)
            mutation = next(m for m, p in MUTANTS.items() if p == pattern)
            jobs[f'mutant{mutation}'] = ('bmc', depth if not proved else 20, [*base, (f'{target}_bound.sv', plain)], script.format(top, mutation), multiclock)
        results = dict(zip(jobs, self.pool.map(lambda item: self.sby(item[0], *item[1]), jobs.items())))
        P.write_json(self.out / 'formal-results.json', {k: {**v, 'unreached': sorted(v['unreached'])} for k, v in results.items()})

        ok = True
        for pattern in M.PATTERNS:
            scope = f'trace_top.u.u_{pattern}_aux'
            for kind in M.KINDS:
                want, seen = self.expected[pattern][kind], self.trace_seen.get((pattern, kind))
                bmc, cover = results[f'trace-{pattern}-{kind}-bmc'], results[f'trace-{pattern}-{kind}-cover']
                if seen is None:
                    good, detail = False, 'no simulation result to compare with'
                else:
                    if want['fails']:
                        good = (bmc['status'] == 'FAIL' and bmc['failed'] == scope + '.a_pattern' and bmc['step'] is not None and
                                (bmc['step'] - 1) // 2 == want['fails'][0] == seen['aux', 'FAIL'][0] and bmc['step'] % 2 == 1)
                    else:
                        good = bmc['status'] == 'PASS' and not seen['aux', 'FAIL']
                    if want['hits']:
                        good = good and scope in cover['reached'] and (cover['reached'][scope] - 1) // 2 == seen['aux', 'HIT'][0]
                    else:
                        good = good and scope in cover['unreached'] and scope not in cover['reached'] and not seen['aux', 'HIT']
                    good = good and cover['status'] in ('PASS', 'FAIL')
                    detail = dict(bmc=bmc['status'], first_failure_step=bmc['step'], first_antecedent_step=cover['reached'].get(scope),
                                  simulation=dict(first_failure=(seen['aux', 'FAIL'] or [None])[0], first_antecedent=(seen['aux', 'HIT'] or [None])[0]))
                ok = self.e.check(f'sby-{pattern}-{kind}', good, detail) and ok
        simulation_only = sorted(name for _, _, name in bindings(False))
        formal_names = sorted(name for _, _, name in bindings(True))
        ok = self.e.check('formal-bind-rewrite',
                          formal_names == sorted(f'u_{p}_aux' for p in M.PATTERNS) and simulation_only == sorted(f'u_{p}_sva' for p in ASSERTION_FORMS) and
                          all(rewritten[p] == [f'u_{p}_aux'] for p in M.PATTERNS),
                          dict(rewritten=formal_names, simulation_only=simulation_only)) and ok
        for pattern in M.PATTERNS:
            top = 'cross_formal.u_cross' if pattern == 'cross' else 'queue_formal.u_queue'
            scope = f'{top}.u_{pattern}_aux'
            clean, cover = results[f'clean-{pattern}'], results[f'clean-{pattern}-cover']
            good = clean['status'] == 'PASS' and (clean['induction'] if pattern in PROVED else True) and cover['status'] == 'PASS' and scope in cover['reached']
            ok = self.e.check(f'formal-clean-{pattern}', good, dict(
                method='k-induction with internal invariants' if pattern in PROVED else f'bounded, depth {self.p["depth"][pattern]}',
                status=clean['status'], antecedent_step=cover['reached'].get(scope), seconds=round(clean['seconds'], 1))) and ok
        for mutation, pattern in MUTANTS.items():
            top = 'cross_formal.u_cross' if pattern == 'cross' else 'queue_formal.u_queue'
            r = results[f'mutant{mutation}']
            ok = self.e.check(f'formal-mutant{mutation}', r['status'] == 'FAIL' and r['failed'] == f'{top}.u_{pattern}_aux.a_pattern',
                              dict(pattern=pattern, status=r['status'], failed=r['failed'], step=r['step'])) and ok
        return ok


def requirements(evidence):
    catalog = json.loads((HERE / 'requirements.json').read_text(encoding='utf-8'))
    planned, used, problems = set(evidence.expected) - {'requirements'}, set(), []
    passed = {r['id'] for r in evidence.results if r['status'] == 'pass'}
    ids = [r['id'] for r in catalog['requirements']]
    if len(ids) != len(set(ids)) or not ids:
        problems.append('empty or duplicate requirement')
    for requirement in catalog['requirements']:
        for goal in requirement['goals']:
            # A goal names a check, or a family of checks with one entry per seed.
            members = {c for c in planned if c == goal or re.fullmatch(re.escape(goal) + r'-seed\d+', c)}
            if not members or members & used:
                problems.append(f'{requirement["id"]}: unknown or repeated goal {goal}')
            elif not members <= passed:
                problems.append(f'{requirement["id"]}: goal {goal} not met')
            used |= members
    if planned - used:
        problems.append('checks without a requirement: ' + ', '.join(sorted(planned - used)))
    return evidence.check('requirements', not problems, dict(requirements=len(ids), goals=sum(len(r['goals']) for r in catalog['requirements']), problems=problems))


def run(args):
    evidence = E.Evidence(NAME, args, INPUTS, dict(profile=profile(args), mutants=MUTANTS, proved=PROVED), plan_ids(args))
    runner = Runner(args, evidence)
    try:
        if runner.tools() and runner.build():
            runner.acceptance()
            runner.evaluation()
            runner.traces()
            runner.random_traces()
            runner.dut()
            runner.formal()
            requirements(evidence)
    finally:
        runner.pool.shutdown()
    return evidence.finish()


def main():
    parser = E.parser(__doc__, NAME)
    parser.add_argument('--verilator', default='verilator')
    for name, default in (('sby', 'yowasp-sby'), ('yosys', 'yowasp-yosys'), ('smtbmc', 'yowasp-yosys-smtbmc'), ('witness', 'yowasp-yosys-witness')):
        parser.add_argument('--' + name, default=default)
    parser.add_argument('--jobs', type=int, default=4)
    parser.add_argument('--build-timeout', type=float, default=180)
    parser.add_argument('--formal-timeout', type=float, default=300)
    args = parser.parse_args()
    E.validate(parser, args)
    if args.jobs < 1 or any(not math.isfinite(value) or value <= 0 for value in (args.build_timeout, args.formal_timeout)):
        parser.error('positive jobs and finite positive timeouts required')
    for name in ('verilator', 'sby', 'yosys', 'smtbmc', 'witness'):   # keep working after the child changes directory
        setattr(args, name, shutil.which(getattr(args, name)) or getattr(args, name))
    try:
        return run(args)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print('RUNNER_ERROR', exc, file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())

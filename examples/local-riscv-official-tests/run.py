#!/usr/bin/env python3
"""Build the rv32ui tests of riscv-tests from pinned sources and run them on the core and on the ISS."""
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import shutil
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
NAME = 'local-riscv-official-tests'
PINS = HERE / 'riscv_tests.json'
REQUIREMENTS = HERE / 'requirements.json'
ENV = HERE / 'env'
BENCH = HERE / 'tb/official_tb.sv'
ISS_PATH = HERE.parent / 'local-riscv-iss/iss.py'
CORE = [HERE.parent / 'local-riscv-iss/rtl/rv32i_core.sv', HERE.parent / 'local-riscv-decoder/rtl/rv32i_decoder.sv',
        HERE.parent / 'local-riscv-pmp/rtl/pmp.sv']
DEFAULT_HOME = ROOT / 'artifacts/toolchains/riscv-tests'
RECORD = 'riscv-tests-source.json'
LLVM = Path('/opt/homebrew/opt/llvm/bin')  # where Homebrew keeps llvm-mc when it is not on PATH
WORDS = 16384                              # memory of the bench, in words
CYCLES, STEPS = 20000, 20000               # limits of the core and of the ISS
# Core configurations. Each one is compared with the ISS mode named by `iss`.
CONFIGS = {'traps': dict(TRAPS=1, PREDICT=0, PRIV=0, WAITS=0, iss='traps'),
           'predict-wait': dict(TRAPS=1, PREDICT=2, PRIV=0, WAITS=1, iss='traps'),
           'priv': dict(TRAPS=1, PREDICT=0, PRIV=1, WAITS=1, iss='priv')}
MUTATION_CONFIG = 'predict-wait'           # every mutation of the core up to 17 is active here
MUTATIONS = {'smoke': (1, 3, 5, 10, 12, 13), 'nightly': tuple(range(1, 18))}
UPSTREAM_TEST = 'add'                      # the test built with the upstream environment as a diagnostic
MHARTID_READ = 0xf1402573                  # csrr a0, mhartid


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


E = load('official_evidence', HERE.parent / 'local-exploration-common/evidence.py')
P = E.P
LINK = load('official_link', HERE / 'link.py')
# A private copy of the ISS module: its data memory is widened to the bench memory, so that the
# same image serves as instruction and as data memory. The shared file is not changed.
ISS = load('official_iss', ISS_PATH)
ISS.DATA_WORDS = WORDS


class BuildError(ValueError):
    pass


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def tool(given, name):
    found = shutil.which(given)
    if found is None and given == name and (LLVM / name).is_file():
        found = str(LLVM / name)
    return found


def test_sources(pins, names):
    """Files of the pinned sources that the build of these tests reads, relative to the home."""
    base = pins['sources']['riscv-tests']['directory']
    files = [f'{base}/isa/macros/scalar/test_macros.h']
    for name in names:
        files += [f'{base}/isa/rv32ui/{name}.S', f'{base}/isa/rv64ui/{name}.S']
    return sorted(files)


def upstream_env(pins):
    env = pins['sources']['riscv-test-env']['directory']
    return [f'{env}/p/riscv_test.h', f'{env}/encoding.h']


def tree_sha256(files):
    """One hash for a set of files: the sorted (path, hash) pairs."""
    return sha256(json.dumps(sorted(files.items())).encode())


def verify_home(home, pins):
    """Check the prepared sources against the pins; return the hashes of the files the build reads."""
    record_path = home / RECORD
    if not record_path.is_file():
        raise ValueError(f'pinned sources not found at {home}; run setup_riscv_tests.py first')
    record = json.loads(record_path.read_text())
    for name, source in pins['sources'].items():
        got = record.get('sources', {}).get(name, {})
        if got.get('commit') != source['commit'] or got.get('sha256') != source['sha256']:
            raise ValueError(f'prepared sources are not the pinned {name}')
    wanted = test_sources(pins, [*pins['tests'], *pins['excluded']]) + upstream_env(pins)
    hashes = {}
    for name in wanted:
        path = home / name
        if not path.is_file() or name not in record['files']:
            raise ValueError('file missing from the prepared sources: ' + name)
        hashes[name] = sha256(path.read_bytes())
        if hashes[name] != record['files'][name]:
            raise ValueError('file changed after it was prepared: ' + name)
    if tree_sha256(hashes) != pins['used_files_sha256']:
        raise ValueError('the files the build reads differ from the pinned set')
    suite = home / pins['sources']['riscv-tests']['directory'] / pins['suite']
    listed = sorted(p.stem for p in suite.glob('*.S'))
    if listed != sorted([*pins['tests'], *pins['excluded']]):
        raise ValueError('the suite holds other tests than the pinned list')
    return hashes


def build(args, home, pins, test, directory, upstream=False, fault=None):
    """Preprocess, assemble and link one test. Returns words, tohost address, symbols and hashes."""
    base = home / pins['sources']['riscv-tests']['directory']
    env = home / pins['sources']['riscv-test-env']['directory']
    includes = [env / 'p', env] if upstream else [ENV]
    directory.mkdir(parents=True, exist_ok=True)
    source, assembly, obj = base / f'isa/rv32ui/{test}.S', directory / f'{test}.s', directory / f'{test}.o'
    command = [args.clang, '-E', '-P', '-x', 'assembler-with-cpp', '-D__riscv_xlen=32',
               *[f'-I{path}' for path in (*includes, base / 'isa/macros/scalar')], '-o', str(assembly), str(source)]
    steps = [P.execute(command, directory / f'{test}-cpp.log', args.timeout, directory)]
    if not steps[0]['error'] and steps[0]['returncode'] == 0:
        steps.append(P.execute([args.llvm_mc, '-triple=riscv32', '-mattr=-relax,-c', '-filetype=obj', '-o', str(obj), str(assembly)],
                               directory / f'{test}-mc.log', args.timeout, directory))
    if any(step['error'] or step['returncode'] != 0 for step in steps) or len(steps) != 2:
        raise BuildError(f'preprocessing or assembly failed; see {directory.name}/{test}-*.log')
    try:
        image, symbols, counts = LINK.link(obj.read_bytes(), limit=4 * WORDS, fault=fault)
    except LINK.LinkError as exc:
        raise BuildError('link: ' + str(exc)) from exc
    if 'tohost' not in symbols or symbols['tohost'] % 4:
        raise BuildError('link: no aligned tohost symbol')
    words = LINK.words(image)
    (directory / f'{test}.hex').write_text(''.join(f'{word:08x}\n' for word in words))
    return dict(test=test, words=words, tohost=symbols['tohost'], symbols=symbols, relocations=counts,
                image_sha256=sha256(image), bytes=len(image), hex=directory / f'{test}.hex')


def write_image(built, path):
    path.write_text(''.join(f'{word:08x}\n' for word in built['words']))
    return path


def compile_bench(args, out, key, parameters, mutation=0):
    target = out / f'{key}.vvp'
    command = [args.iverilog, '-g2012', '-s', 'official_tb', '-o', str(target), f'-Pofficial_tb.MUTATION={mutation}']
    command += [f'-Pofficial_tb.{name}={value}' for name, value in parameters.items() if name != 'iss']
    execution = P.execute(command + [str(p) for p in (*CORE, BENCH)], out / f'{key}-build.log', args.timeout * 3, out)
    if execution['error'] or execution['returncode'] != 0:
        raise BuildError(f'bench did not compile; see {key}-build.log')
    return target


def run_core(args, bench, image, tohost, directory, name):
    """One simulation. status: done (halted after one store to tohost), a check label, or error."""
    log, trace = directory / f'{name}.log', directory / f'{name}.trace'
    execution = P.execute([args.vvp, str(bench), f'+IMAGE={image}', f'+TRACE={trace}', f'+TOHOST={tohost}', f'+LIMIT={CYCLES}'],
                          log, args.timeout, directory)
    output = log.read_text(errors='replace')
    failures = re.findall(r'^CHECK_FAIL (\w+)$', output, re.M)
    done = re.findall(r'^RESULT DONE words=\d+$', output, re.M)
    values = {key: re.findall(rf'^{key} (\w+)$', output, re.M) for key in ('TOHOST', 'RETIRED', 'CYCLES')}
    result = dict(status='error', tohost=None, retired=None, cycles=None, trace=trace, log=log.name)
    if execution['error']:
        result['message'] = execution['error']
    elif execution['returncode'] == 0 and len(done) == 1 and not failures and all(len(v) == 1 for v in values.values()):
        result.update(status='done', tohost=int(values['TOHOST'][0], 16), retired=int(values['RETIRED'][0]),
                      cycles=int(values['CYCLES'][0]))
    elif execution['returncode'] != 0 and len(failures) == 1 and not done:
        result['status'] = failures[0]
    else:
        result['message'] = 'missing or inconsistent completion record'
    return result


def run_iss(words, tohost, mode):
    """The same image on the ISS. Returns the tohost word, the retirement rows and an error text."""
    image = list(words) + [0] * (WORDS - len(words))
    memory = []
    try:
        trace = ISS.execute(image, image, STEPS, traps=True, memory=memory, priv=mode == 'priv')
    except (ValueError, IndexError, KeyError) as exc:
        return dict(tohost=None, rows=None, error=f'{type(exc).__name__}: {exc}')
    stores = sum(r.kind == 2 and r.addr >> 2 == tohost >> 2 for r in trace)
    rows = [(r.pc, r.insn, r.rd, r.wdata, r.kind, r.addr if r.kind else 0, r.data if r.kind else 0) for r in trace]
    return dict(tohost=memory[tohost >> 2], rows=rows, stores=stores, error=None)


def read_trace(path):
    return [tuple(int(field, 16) for field in line.split()) for line in path.read_text().splitlines()]


def judge(core, iss):
    """pass, or why this test did not pass on this configuration."""
    if core['status'] == 'error':
        return 'error'
    if core['status'] == 'OT_TIMEOUT':
        return 'timeout'
    if core['status'] != 'done':
        return 'bench:' + core['status']
    if core['tohost'] != 1:
        return f"self-check:{core['tohost']:#x}"
    if iss['error'] or iss['rows'] != read_trace(core['trace']):
        return 'trace'
    return 'pass'


def classify(outcomes):
    """Class of a mutation from the outcomes of all tests: how the suite sees it."""
    if any(o == 'error' for o in outcomes.values()):
        return 'error'
    if any(o.startswith(('self-check', 'timeout', 'bench')) for o in outcomes.values()):
        return 'self-check'
    return 'trace-only' if any(o == 'trace' for o in outcomes.values()) else 'invisible'


def plan_ids(pins, profile):
    tests = pins['tests']
    ids = ['toolchain', 'sources', 'excluded-tests']
    ids += [f'build-{t}' for t in tests] + [f'iss-{t}' for t in tests]
    ids += [f'core-{c}-{t}' for c in CONFIGS for t in tests]
    ids += ['upstream-env-blocked', 'detect-wrong-data', 'detect-bad-relocation']
    ids += [f'mutation-{m}' for m in MUTATIONS[profile]]
    return ids + ['requirements', 'inputs-unchanged']


def requirement_results(catalog, results):
    passed = {r['id'] for r in results if r['status'] == 'pass'}
    rows = []
    for item in catalog['requirements']:
        matched = [i for i in passed if any(i == p or i.startswith(p) for p in item['checks'])]
        rows.append(dict(id=item['id'], checks=len(matched), passed=len(matched) >= item['minimum']))
    return rows


def run(args):
    pins = json.loads(PINS.read_text())
    catalog = json.loads(REQUIREMENTS.read_text())
    home = args.riscv_tests_home.resolve()
    try:
        used = verify_home(home, pins)
        home_error = None
    except (OSError, ValueError, KeyError) as exc:
        used, home_error = {}, str(exc)
    if home_error and not (home / RECORD).is_file():
        # Without the sources nothing can be checked: say how to get them and stop.
        print(f'RUNNER_ERROR {home_error}\n  python3 examples/{NAME}/setup_riscv_tests.py --out {DEFAULT_HOME.relative_to(ROOT)}',
              file=sys.stderr)
        return 1
    inputs = [Path(__file__), HERE / 'link.py', HERE / 'setup_riscv_tests.py', PINS, REQUIREMENTS, ENV / 'riscv_test.h', BENCH,
              ISS_PATH, HERE.parent / 'local-riscv-decoder/generate.py', *CORE]
    plan = dict(suite=pins['suite'], tests=pins['tests'], excluded=pins['excluded'], configurations=CONFIGS,
                mutations=list(MUTATIONS[args.profile]), mutation_configuration=MUTATION_CONFIG,
                sources={name: dict(commit=s['commit'], sha256=s['sha256']) for name, s in pins['sources'].items()})
    e = E.Evidence(NAME, args, inputs, plan, plan_ids(pins, args.profile))
    out = e.out
    frozen = json.loads((out / 'manifest.json').read_text())['source_sha256']

    versions = {}
    for name, command in (('clang', [args.clang, '--version']), ('llvm-mc', [args.llvm_mc, '--version']),
                          ('iverilog', [args.iverilog, '-V']), ('vvp', [args.vvp, '-V'])):
        log = out / f'{name}-version.log'
        versions[name] = dict(P.execute(command, log, args.timeout, out), output=log.read_text(errors='replace')[:400])
    P.write_json(out / 'tools.json', versions)
    tools_ok = all(not v['error'] and v['returncode'] == 0 and v['output'].strip() for v in versions.values())
    e.check('toolchain', tools_ok, {k: v['output'].splitlines()[:2] for k, v in versions.items()})
    P.write_json(out / 'sources.json', dict(home=str(home), pins=pins['sources'], used_files_sha256=used, error=home_error))
    e.check('sources', home_error is None, home_error or dict(files=len(used), tree_sha256=pins['used_files_sha256']))
    excluded_ok = (home_error is None and len(pins['tests']) == 40 and len(set(pins['tests'])) == 40 and
                   not set(pins['tests']) & set(pins['excluded']) and all(isinstance(r, str) and len(r) > 20 for r in pins['excluded'].values()))
    e.check('excluded-tests', excluded_ok, pins['excluded'])
    if home_error or not tools_ok:
        return e.finish()  # the remaining checks are recorded as not completed

    benches, bench_error = {}, None
    try:
        for name, parameters in CONFIGS.items():
            benches[name] = compile_bench(args, out, name, parameters)
    except BuildError as exc:
        bench_error = str(exc)

    built, images, iss_results = {}, {}, {}
    (out / 'images').mkdir()
    for test in pins['tests']:
        try:
            built[test] = build(args, home, pins, test, out / 'build')
            images[test] = dict(sha256=built[test]['image_sha256'], bytes=built[test]['bytes'], tohost=built[test]['tohost'],
                                relocations=built[test]['relocations'])
            e.check(f'build-{test}', True, images[test])
        except (BuildError, OSError) as exc:
            e.check(f'build-{test}', False, str(exc))
    P.write_json(out / 'images.json', images)

    for test in pins['tests']:
        if test not in built:
            e.check(f'iss-{test}', False, 'not built')
            continue
        iss_results[test] = {mode: run_iss(built[test]['words'], built[test]['tohost'], mode) for mode in ('traps', 'priv')}
        ok = all(r['error'] is None and r['tohost'] == 1 and r['stores'] == 1 for r in iss_results[test].values())
        e.check(f'iss-{test}', ok, {mode: dict(tohost=r['tohost'], retired=r['rows'] and len(r['rows']), error=r['error'])
                                    for mode, r in iss_results[test].items()})

    table = {}
    for name, parameters in CONFIGS.items():
        directory = out / name
        directory.mkdir()
        for test in pins['tests']:
            if test not in built or bench_error:
                e.check(f'core-{name}-{test}', False, bench_error or 'not built')
                continue
            core = run_core(args, benches[name], built[test]['hex'], built[test]['tohost'], directory, test)
            verdict = judge(core, iss_results[test][parameters['iss']])
            table.setdefault(test, {})[name] = dict(verdict=verdict, retired=core['retired'], cycles=core['cycles'])
            e.check(f'core-{name}-{test}', verdict == 'pass', table[test][name])
    P.write_json(out / 'results.json', table)

    # The upstream environment: record that it still stops where README.md says it does.
    directory = out / 'upstream-env'
    try:
        if bench_error:
            raise BuildError(bench_error)
        upstream = build(args, home, pins, UPSTREAM_TEST, directory, upstream=True)
        core = run_core(args, benches['priv'], upstream['hex'], upstream['tohost'], directory, 'core')
        rows = read_trace(core['trace']) if core['trace'].is_file() else []
        traps = [row for row in rows if row[4] == 3]
        first = traps[0] if traps else None
        after = rows[rows.index(first) + 1] if first and rows.index(first) + 1 < len(rows) else None
        blocked = (core['status'] == 'OT_TIMEOUT' and first is not None and first[1] == MHARTID_READ and first[5] == 2 and
                   after is not None and after[0] == 0)
        e.check('upstream-env-blocked', blocked, dict(status=core['status'], first_trap=first and [hex(x) for x in first],
                                                      next_pc=after and hex(after[0]), relocations=upstream['relocations']))
    except (BuildError, OSError, ValueError) as exc:
        e.check('upstream-env-blocked', False, str(exc))

    # A changed data word: the test must report its own failure, on the core and on the ISS.
    directory = out / 'negative'
    directory.mkdir()
    try:
        if bench_error or 'lw' not in built:
            raise BuildError(bench_error or 'lw not built')
        changed = dict(built['lw'], words=list(built['lw']['words']))
        changed['words'][built['lw']['symbols']['tdat'] >> 2] ^= 0x100
        image = write_image(changed, directory / 'lw-wrong-data.hex')
        core = run_core(args, benches['traps'], image, changed['tohost'], directory, 'lw-wrong-data')
        iss = run_iss(changed['words'], changed['tohost'], 'traps')
        ok = core['status'] == 'done' and core['tohost'] == 5 and iss['tohost'] == 5 and iss['rows'] == read_trace(core['trace'])
        e.check('detect-wrong-data', ok, dict(core=core['status'], core_tohost=core['tohost'], iss_tohost=iss['tohost']))
    except (BuildError, OSError, KeyError) as exc:
        e.check('detect-wrong-data', False, str(exc))
    # A linker that computes one low part wrongly: the test must not pass.
    try:
        if bench_error:
            raise BuildError(bench_error)
        broken = build(args, home, pins, 'lw', directory / 'bad-relocation', fault='lo12-off-by-four')
        core = run_core(args, benches['traps'], broken['hex'], broken['tohost'], directory, 'lw-bad-relocation')
        verdict = judge(core, run_iss(broken['words'], broken['tohost'], 'traps'))
        ok = verdict.startswith(('self-check', 'bench:OT_TOHOST_WRITES')) and broken['image_sha256'] != built['lw']['image_sha256']
        e.check('detect-bad-relocation', ok, dict(verdict=verdict))
    except (BuildError, OSError, KeyError) as exc:
        e.check('detect-bad-relocation', False, str(exc))

    # Mutations of the core: which tests notice each one, against the pinned table.
    survey = {}
    parameters = CONFIGS[MUTATION_CONFIG]
    for mutation in MUTATIONS[args.profile]:
        expected = pins['mutations'][str(mutation)]
        try:
            if bench_error or len(built) != len(pins['tests']):
                raise BuildError(bench_error or 'not every test was built')
            bench = compile_bench(args, out, f'mutation{mutation}', parameters, mutation)
            directory = out / f'mutation{mutation}'
            directory.mkdir()
            outcomes = {}
            for test in pins['tests']:
                core = run_core(args, bench, built[test]['hex'], built[test]['tohost'], directory, test)
                outcomes[test] = judge(core, iss_results[test][parameters['iss']])
            noticed = sorted(t for t, o in outcomes.items() if o != 'pass')
            survey[mutation] = dict(observed=classify(outcomes), noticed=noticed, outcomes={t: outcomes[t] for t in noticed})
            ok = survey[mutation]['observed'] == expected['class'] and noticed == sorted(expected['noticed'])
            e.check(f'mutation-{mutation}', ok, dict(survey[mutation], expected=expected))
        except (BuildError, OSError) as exc:
            e.check(f'mutation-{mutation}', False, str(exc))
    P.write_json(out / 'mutations.json', survey)

    rows = requirement_results(catalog, e.results)
    P.write_json(out / 'requirements.json', rows)
    e.check('requirements', all(row['passed'] for row in rows), rows)
    changed = [name for name, digest in frozen.items() if not (ROOT / name).is_file() or sha256((ROOT / name).read_bytes()) != digest]
    try:
        again = verify_home(home, pins)
    except (OSError, ValueError, KeyError) as exc:
        again, changed = None, changed + [str(exc)]
    e.check('inputs-unchanged', not changed and again == used, changed)
    return e.finish()


def main():
    parser = E.parser(__doc__, NAME)
    parser.add_argument('--riscv-tests-home', type=Path, default=DEFAULT_HOME,
                        help='directory made by setup_riscv_tests.py (default: artifacts/toolchains/riscv-tests)')
    parser.add_argument('--clang', default='clang', help='used for preprocessing only')
    parser.add_argument('--llvm-mc', default='llvm-mc')
    args = parser.parse_args()
    E.validate(parser, args)
    # Only the C preprocessor is used: where clang is not installed, the system compiler driver serves.
    args.clang = tool(args.clang, 'clang') or (shutil.which('cc') if args.clang == 'clang' else None) or args.clang
    args.llvm_mc = tool(args.llvm_mc, 'llvm-mc') or args.llvm_mc
    try:
        return run(args)
    except P.RunInterrupted as exc:
        return 128 + exc.signum
    except KeyboardInterrupt:
        return 130
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print('RUNNER_ERROR', exc, file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())

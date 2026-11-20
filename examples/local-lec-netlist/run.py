#!/usr/bin/env python3
"""Equivalence of an RTL block, its synthesized netlist and the netlist after scan insertion and an ECO."""
import importlib.util
import json
from pathlib import Path
import re
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
NAME = 'local-lec-netlist'
TOP = 'event_meter'
NET = 'event_meter_net'
RTL = HERE / 'rtl/event_meter.sv'
INPUTS = ['clk', 'rst_n', 'en', 'clear', 'din']
OUTPUTS = {'busy': 1, 'full': 1, 'level': 4, 'odd': 1, 'warn': 1}
OLD_ALARM, NEW_ALARM = 12, 10
BMC_STEPS = 16
ALL = 'every flop'
SYNTHESIS = (f'read_verilog -sv {RTL.name}; synth -top {TOP} -flatten -nofsm; dfflegalize -cell $_SDFF_PN0_ x; '
             'abc -g AND,NAND,OR,NOR,XOR,XNOR,ANDNOT,ORNOT,MUX; opt_clean; stat; write_json synth.json')
LEGALIZE = 'read_json synth.json; dfflegalize -cell $_DFF_P_ x; opt_clean; stat; write_json plain.json'
# gate: which netlist; gold: ALARM_AT of the RTL; scan: how the wrapper drives scan_en;
# differs: the flops at which the comparison must fail; outputs: the outputs computed from those flops.
# The comparison must fail at these points and nowhere else.
TASKS = [
    dict(id='rtl-vs-synth', kind='equiv', gate='synth', gold=OLD_ALARM, differs=[]),
    dict(id='rtl-vs-scan-functional', kind='equiv', gate='scan', gold=OLD_ALARM, scan='tied', differs=[]),
    dict(id='diagnose-scan-unconstrained', kind='equiv', gate='scan', gold=OLD_ALARM, scan='free', differs=ALL, outputs=['busy', 'full']),
    dict(id='detect-reset-polarity', kind='equiv', gate='reset-polarity', gold=OLD_ALARM, differs=['alarm']),
    dict(id='detect-reset-value', kind='equiv', gate='reset-value', gold=OLD_ALARM, differs=['count[0]']),
    dict(id='detect-scan-miswire', kind='equiv', gate='scan-miswire', gold=OLD_ALARM, scan='tied', differs=['state[1]'],
         outputs=['busy', 'full']),
    dict(id='eco-new-specification', kind='equiv', gate='eco', gold=NEW_ALARM, differs=[]),
    dict(id='eco-changed-range', kind='equiv', gate='eco', gold=OLD_ALARM, differs=['alarm']),
    dict(id='eco-kept-range', kind='equiv', gate='eco', gold=OLD_ALARM, drop=['warn'], differs=[]),
    dict(id='detect-eco-wrong-gate', kind='equiv', gate='eco-wrong', gold=NEW_ALARM, differs=['alarm']),
    dict(id='scan-shift', kind='shift', gate='scan', counterexample=False),
    dict(id='detect-scan-chain-break', kind='shift', gate='scan-break', counterexample=True),
]
BROKEN_AT = 'count[3]'


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


E = load('lec_evidence', HERE.parent / 'local-exploration-common/evidence.py')
N = load('lec_netlist', HERE / 'netlist.py')
P = E.P
SOURCES = [Path(__file__), HERE / 'netlist.py', HERE / 'requirements.json', RTL]


def variants(synth, plain):
    """Every netlist the tasks compare, as JSON with the module called NET, and the order of the scan chain."""
    scan, chain = N.scan_insert(plain, TOP)
    designs = {
        'synth': synth,
        'scan': scan,
        'scan-miswire': N.scan_insert(plain, TOP, miswire='state[1]')[0],
        'scan-break': N.scan_insert(plain, TOP, break_at=BROKEN_AT)[0],
        'reset-polarity': N.mutate_reset(synth, TOP, 'alarm', 'polarity'),
        'reset-value': N.mutate_reset(synth, TOP, 'count[0]', 'value'),
        'eco': N.eco_alarm(synth, TOP),
        'eco-wrong': N.eco_alarm(synth, TOP, wrong_gate=True),
    }
    return {name: N.renamed(design, TOP, NET) for name, design in designs.items()}, chain


def aliases(synth):
    """Flop name -> every public name of the net it drives, e.g. alarm -> {alarm, warn}."""
    module = N.module_of(synth, TOP)
    names = {}
    for name, net in module['netnames'].items():
        if not net.get('hide_name'):
            for index, bit in enumerate(net['bits']):
                if isinstance(bit, int):
                    names.setdefault(bit, set()).add(name if len(net['bits']) == 1 else f'{name}[{index}]')
    return {flop: names[module['cells'][cell]['connections']['Q'][0]] for flop, cell in N.flops(module).items()}


def port_list(task):
    scan = ['scan_en', 'scan_in'] if task.get('scan') else []
    outputs = [name for name in OUTPUTS if name not in task.get('drop', [])]
    lines = [f'input wire {name}' for name in INPUTS + scan]
    lines += [f"output wire {'[%d:0] ' % (OUTPUTS[name] - 1) if OUTPUTS[name] > 1 else ''}{name}" for name in outputs]
    return ', '.join(lines), outputs


def wrappers(task):
    """gold and gate with the same ports, each holding its design as instance u."""
    ports, outputs = port_list(task)
    pins = [f'.{name}({name})' for name in INPUTS] + [f".{name}({name if name in outputs else ''})" for name in OUTPUTS]
    scan_pins = []
    if task.get('scan'):
        enable = 'scan_en' if task['scan'] == 'free' else "1'b0"
        scan_pins = [f'.scan_en({enable})', '.scan_in(scan_in)', '.scan_out()']
    return (f"module gold({ports});\n  {TOP} #(.ALARM_AT({task['gold']})) u({', '.join(pins)});\nendmodule\n",
            f"module gate({ports});\n  {NET} u({', '.join(pins + scan_pins)});\nendmodule\n")


def shift_checker(length):
    """scan_out against scan_in delayed by one clock per flop, with scan_en held at 1."""
    pins = [f'.{name}({name})' for name in INPUTS] + [f'.{name}()' for name in OUTPUTS]
    pins += [".scan_en(1'b1)", '.scan_in(scan_in)', '.scan_out(scan_out)']
    return (f"module shift_check({', '.join('input wire ' + name for name in INPUTS + ['scan_in'])}, output wire bad);\n"
            f"  wire scan_out;\n  reg [{length - 1}:0] line;\n  {NET} u({', '.join(pins)});\n"
            f"  always @(posedge clk) line <= {{line[{length - 2}:0], scan_in}};\n"
            f"  assign bad = scan_out ^ line[{length - 1}];\nendmodule\n")


def equiv_script(task):
    return '\n'.join([
        f'read_verilog -sv {RTL.name} gold.v', 'hierarchy -top gold', 'proc', 'flatten', 'opt_clean',
        'read_json gate.json', 'read_verilog -sv gate.v', 'proc gate', 'flatten gate',
        f'delete {NET}', 'opt_clean', 'design -save compared',
        'equiv_make gold gate equiv', 'equiv_simple equiv', 'equiv_induct equiv', 'equiv_status equiv',
        'write_json equiv.json', 'log LEC_EQUIV_DONE',
        'design -load compared', 'miter -equiv -flatten -make_outputs gold gate miter',
        f'sat -seq {BMC_STEPS} -set-at 1 in_rst_n 0 -prove-skip 1 -prove trigger 0 -show-inputs -show-outputs '
        '-dump_vcd counterexample.vcd miter', 'log LEC_BMC_DONE', ''])


def shift_script(length):
    return '\n'.join([
        'read_json gate.json', 'read_verilog -sv shift_check.v', 'hierarchy -top shift_check', 'proc', 'flatten',
        'opt_clean', f'sat -seq {2 * length + 2} -prove-skip {length} -prove bad 0 -show-inputs -show-outputs '
        '-dump_vcd counterexample.vcd shift_check', 'log LEC_BMC_DONE', ''])


def unproven_points(log):
    """Names from the equiv_status lines `Unproven $equiv <cell>: \\u.count_gold [2] \\u.count_gate [2]`."""
    points = set()
    for name, bit in re.findall(r'^\s*Unproven \$equiv \S+: \\(\S+)_gold(?: \[(\d+)\])? \\\S+_gate', log, re.M):
        points.add(name + (f'[{bit}]' if bit else ''))
    return points


def bmc_verdict(log):
    """True: a counterexample was found. False: none within the bound. None: no single clear answer."""
    found = len(re.findall(r'^SAT proof finished - model found: FAIL!$', log, re.M))
    none = len(re.findall(r'^SAT proof finished - no model found: SUCCESS!$', log, re.M))
    if found + none != 1 or len(re.findall(r'^LEC_BMC_DONE$', log, re.M)) != 1:
        return None
    return bool(found)


def expected_points(differs, outputs, names):
    """The flops, every other name of their nets, and the named outputs; ports appear inside u and at the top."""
    inner = {alias for flop in differs for alias in names[flop]} | set(outputs)
    ports = {name for name in inner if name.split('[')[0] in OUTPUTS}
    return {'u.' + name for name in inner} | ports


def judge_equiv(task, log, compared, names, trace):
    """(ok, message, details). A tool problem or an incomplete log is never a detection."""
    differs = sorted(names) if task['differs'] == ALL else task['differs']
    expected = expected_points(differs, task.get('outputs', []), names)
    required = {'u.' + alias for flop, group in names.items() for alias in group}
    dropped = set()
    for port in task.get('drop', []):
        dropped |= {'u.' + alias for group in names.values() if port in group for alias in group}
    unproven = unproven_points(log)
    counts = re.findall(r'^\s*Of those cells (\d+) are proven and (\d+) are unproven\.$', log, re.M)
    bmc = bmc_verdict(log)
    details = dict(expected_unproven=sorted(expected), unproven=sorted(unproven), compared=sorted(compared),
                   counterexample=bmc, counts=counts)
    if re.search(r'^ERROR', log, re.M) or len(re.findall(r'^LEC_EQUIV_DONE$', log, re.M)) != 1 or len(counts) != 1 or bmc is None:
        return False, 'incomplete or failed tool run', details
    if int(counts[0][1]) != len(unproven):
        return False, 'the list of unproven points does not agree with its count', details
    if not required - dropped <= compared or dropped & compared:
        return False, 'the proof did not compare the flops it should: ' + ', '.join(sorted((required - dropped) - compared | dropped & compared)), details
    if unproven != expected:
        return False, 'unproven points differ from the plan', details
    proven_line = bool(re.search(r'^\s*Equivalence successfully proven!$', log, re.M))
    if expected:
        if proven_line or not bmc or not trace:
            return False, 'no counterexample from reset for a planned difference', details
        return True, 'difference reported at ' + ', '.join(sorted(differs)) + '; counterexample from reset', details
    if not proven_line or bmc:
        return False, 'not proven, or a counterexample from reset exists', details
    return True, f'{counts[0][0]} points proven by induction; no counterexample in {BMC_STEPS} steps from reset', details


def judge_shift(task, log, trace):
    bmc = bmc_verdict(log)
    details = dict(counterexample=bmc)
    if re.search(r'^ERROR', log, re.M) or bmc is None:
        return False, 'incomplete or failed tool run', details
    if bmc != task['counterexample'] or (bmc and not trace):
        return False, 'counterexample expected' if task['counterexample'] else 'scan_out differs from the delayed scan_in', details
    return True, 'broken chain reported with a counterexample' if bmc else 'scan_out follows scan_in for every input', details


def has_trace(path):
    return path.is_file() and '$enddefinitions' in path.read_text(errors='replace')


def yosys(args, directory, name, script, timeout=None):
    """Run one script; return its log, or raise when the tool did not finish cleanly."""
    (directory / f'{name}.ys').write_text(script if script.endswith('\n') else script.replace('; ', '\n') + '\n')
    execution = P.execute([args.yosys, '-s', f'{name}.ys'], directory / f'{name}.log', timeout or args.timeout, directory)
    log = (directory / f'{name}.log').read_text(errors='replace')
    if execution['error'] or execution['returncode'] != 0:
        raise ValueError(f"yosys failed ({execution['error'] or execution['returncode']}); see {directory.name}/{name}.log")
    return log


def build(args, out):
    """Synthesize once, derive every netlist from it, and write each one as Verilog for the record."""
    directory = out / 'netlists'
    directory.mkdir()
    (directory / RTL.name).write_bytes(RTL.read_bytes())
    yosys(args, directory, 'synthesis', SYNTHESIS)
    yosys(args, directory, 'legalize', LEGALIZE)
    synth = json.loads((directory / 'synth.json').read_text())
    plain = json.loads((directory / 'plain.json').read_text())
    designs, chain = variants(synth, plain)
    script = []
    for name, design in designs.items():
        (directory / f'{name}.json').write_text(json.dumps(design, indent=1) + '\n')
        script += ['design -reset', f'read_json {name}.json', f'write_verilog -noattr {name}.v']
    yosys(args, directory, 'export', '\n'.join(script) + '\n')
    module = N.module_of(synth, TOP)
    record = dict(chain=chain, flops={k: sorted(v) for k, v in aliases(synth).items()},
                  cells=len(module['cells']),
                  sha256={p.name: E.hashlib.sha256(p.read_bytes()).hexdigest()
                          for p in sorted(directory.glob('*')) if p.suffix in ('.json', '.v')})
    P.write_json(directory / 'netlists.json', record)
    return designs, chain, aliases(synth)


def run_task(args, out, task, designs, chain, names):
    directory = out / task['id']
    directory.mkdir()
    (directory / RTL.name).write_bytes(RTL.read_bytes())
    (directory / 'gate.json').write_text(json.dumps(designs[task['gate']]) + '\n')
    trace = directory / 'counterexample.vcd'
    try:
        if task['kind'] == 'equiv':
            gold, gate = wrappers(task)
            (directory / 'gold.v').write_text(gold)
            (directory / 'gate.v').write_text(gate)
            log = yosys(args, directory, 'compare', equiv_script(task))
            compared = N.compared_points(json.loads((directory / 'equiv.json').read_text()))
            ok, message, details = judge_equiv(task, log, compared, names, has_trace(trace))
        else:
            (directory / 'shift_check.v').write_text(shift_checker(len(chain)))
            log = yosys(args, directory, 'compare', shift_script(len(chain)))
            ok, message, details = judge_shift(task, log, has_trace(trace))
    except (OSError, ValueError, KeyError) as exc:
        ok, message, details = False, str(exc), {}
    P.write_json(directory / 'result.json', dict(id=task['id'], task=task, ok=ok, message=message, **details))
    return ok, message


def run(args):
    _, goals = E.C.catalog(HERE / 'requirements.json')
    ids = ['toolchain', 'netlists', *[task['id'] for task in TASKS], 'requirements', 'inputs-unchanged']
    evidence = E.Evidence(NAME, args, SOURCES, dict(tasks=TASKS, bmc_steps=BMC_STEPS, synthesis=SYNTHESIS, legalize=LEGALIZE), ids)
    out = evidence.out
    frozen = {p: E.hashlib.sha256(p.read_bytes()).hexdigest() for p in SOURCES}
    version = P.execute([args.yosys, '-V'], out / 'yosys-version.log', args.timeout, out)
    P.write_json(out / 'tools.json', dict(yosys=dict(version, output=(out / 'yosys-version.log').read_text(errors='replace'))))
    tool_ok = not version['error'] and version['returncode'] == 0
    evidence.check('toolchain', tool_ok, version)
    designs = None
    if tool_ok:
        try:
            designs, chain, names = build(args, out)
            evidence.check('netlists', len(chain) == len(names) == 8, dict(chain=chain))
        except (OSError, ValueError, KeyError) as exc:
            designs = None
            evidence.check('netlists', False, str(exc))
    passed = set()
    for task in TASKS:
        if designs is None:
            evidence.check(task['id'], False, 'no netlists to compare')
            continue
        ok, message = run_task(args, out, task, designs, chain, names)
        if evidence.check(task['id'], ok, message):
            passed.add(task['id'])
    evidence.check('requirements', goals == {task['id'] for task in TASKS} == passed,
                   dict(missing=sorted(goals - passed), unplanned=sorted({t['id'] for t in TASKS} - goals)))
    changed = [str(p.relative_to(ROOT)) for p, digest in frozen.items() if E.hashlib.sha256(p.read_bytes()).hexdigest() != digest]
    evidence.check('inputs-unchanged', not changed, changed)
    return evidence.finish()


def main():
    parser = E.parser(__doc__, NAME)
    parser.add_argument('--yosys', default='yowasp-yosys')
    parser.set_defaults(timeout=120)
    args = parser.parse_args()
    E.validate(parser, args)
    try:
        return run(args)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print('RUNNER_ERROR', exc, file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())

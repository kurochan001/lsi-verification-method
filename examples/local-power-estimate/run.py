#!/usr/bin/env python3
"""Estimate power from simulated activity with OpenSTA and compare a register bank with and without a clock gate."""
import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import re
import shutil
import sys
import xml.etree.ElementTree as ET

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
PROCESS = HERE.parent / 'local-irq-cdc/run.py'


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


P = load('power_process', PROCESS)
MODEL = load('power_model', HERE / 'model.py')
CONTRACT = HERE / 'contract.json'
NETLIST, LIBRARY, CELLS, BENCH, SCRIPT = (HERE / name for name in (
    'design/bank.v', 'design/cells.lib', 'design/cells.v', 'tb/power_tb.sv', 'power.tcl'))
SOURCES = [Path(__file__), PROCESS, HERE / 'model.py', CONTRACT, NETLIST, LIBRARY, CELLS, BENCH, SCRIPT]
ACTIVITIES = ('low', 'mid', 'high')
MUTANTS = 4
LABELS = {1: 'POWER_ACTIVITY', 2: 'POWER_SCOPE', 3: 'POWER_VALUE', 4: 'POWER_SAVING'}
# Mutant 3 analyses with a library whose flop clock pin costs twice the energy.
WRONG_LIBRARY = ('pin(CLK) { direction : input; clock : true; capacitance : 0.01; internal_power() '
                 '{ rise_power(scalar) { values("0.004"); } fall_power(scalar) { values("0.004"); } } }',
                 'values("0.004")', 'values("0.008")')
KEYS = ('internal', 'switching', 'leakage')


def load_contract(path=CONTRACT):
    data = json.loads(path.read_text())
    if data.get('schema_version') != 1 or type(data.get('revision')) is not int or data['revision'] < 1:
        raise ValueError('invalid power contract version')
    if tuple(data.get('activities', {})) != ACTIVITIES or set(data.get('cells', {})) != {'BUF', 'MUX2', 'DFF', 'ICG'}:
        raise ValueError('power contract must contain the three activities and the four cells')
    numbers = [data.get('voltage'), data.get('period_ns'), data.get('output_load_pf'), data.get('relative_tolerance')]
    if any(type(v) not in (int, float) or not math.isfinite(v) or v <= 0 for v in numbers) or data['relative_tolerance'] > 0.01:
        raise ValueError('invalid power contract constants')
    if type(data.get('cycles')) is not int or data['cycles'] < 32:
        raise ValueError('too few cycles for an activity estimate')
    for name, item in data['activities'].items():
        saving = item.get('saving', {})
        if type(item.get('load_every')) is not int or item['load_every'] < 1 or len(saving) != 1 or \
                set(saving) - {'max_ratio', 'min_ratio'} or any(type(v) not in (int, float) or not 0 < v < 10 for v in saving.values()):
            raise ValueError(f'invalid activity {name}')
    return data


def expected_label(mutation, activity, contract):
    """Tying the gate open costs nothing where the contract expects no saving anyway."""
    if mutation == 4 and 'min_ratio' in contract['activities'][activity]['saving']:
        return 'PASS'
    return LABELS[mutation]


def parse_report(log):
    """Annotation counts and the power of every instance; complete or an error."""
    if not re.search(r'^RESULT POWER DONE$', log, re.M):
        raise ValueError('incomplete power report')
    annotation = re.search(r'^BEGIN ANNOTATION\n(.*?)^END ANNOTATION$', log, re.M | re.S)
    table = re.search(r'^BEGIN INSTANCES\n(.*?)^END INSTANCES$', log, re.M | re.S)
    if not annotation or not table:
        raise ValueError('report sections missing')
    counts = {name: int(value) for name, value in re.findall(r'^(\w+)\s+(\d+)$', annotation.group(1), re.M)}
    if 'unannotated' not in counts:
        raise ValueError('annotation summary missing')
    power = {}
    for internal, switching, leakage, total, name in re.findall(
            r'^\s*([\d.e+-]+)\s+([\d.e+-]+)\s+([\d.e+-]+)\s+([\d.e+-]+)\s+(\w+)$', table.group(1), re.M):
        values = dict(internal=float(internal), switching=float(switching), leakage=float(leakage))
        if name in power or any(not math.isfinite(v) or v < 0 for v in values.values()):
            raise ValueError('duplicate instance or invalid power value')
        power[name] = values
    if not power:
        raise ValueError('no instance power reported')
    return dict(annotated=counts.get('vcd', 0), unannotated=counts['unannotated'],
                other={k: v for k, v in counts.items() if k not in ('vcd', 'unannotated')}), power


def differing(measured, expected, tolerance):
    """Instances whose measured power is not the expected one, with the direction of the difference."""
    if set(measured) != set(expected):
        raise ValueError('reported instances differ from the netlist')
    rows = {}
    for name in expected:
        for key in KEYS:
            want, got = expected[name][key], measured[name][key]
            if abs(got - want) > tolerance * max(abs(want), 1e-12):
                rows.setdefault(name, {})[key] = 'high' if got > want else 'low'
    return rows


def saving_ok(ratio, requirement):
    return ratio <= requirement['max_ratio'] if 'max_ratio' in requirement else ratio >= requirement['min_ratio']


def derive(annotation, pins, differences, ratio, requirement):
    """The verdict from the report alone. `ratio` is None for the analysis that is the reference."""
    if annotation['annotated'] == 0:
        return 'POWER_ACTIVITY'
    if annotation['unannotated'] or annotation['other'] or annotation['annotated'] != pins:
        return 'POWER_SCOPE'
    if differences:
        return 'POWER_VALUE'
    if ratio is not None and not saving_ok(ratio, requirement):
        return 'POWER_SAVING'
    return 'PASS'


def intended(mutation, annotation, differences, netlist_module):
    """A detection counts only when the report shows the planted mistake."""
    flops = sorted(name for name, (cell, _) in netlist_module['instances'].items() if cell == 'DFF')
    if mutation == 1:
        return annotation['unannotated'] > 0
    if mutation == 2:   # the flops were given the activity of the ungated clock
        return all(differences.get(name, {}).get('internal') == 'high' for name in flops)
    if mutation == 3:   # only the flops, only their internal power
        return sorted(differences) == flops and all(row == {'internal': 'high'} for row in differences.values())
    return not differences


class Campaign:
    def __init__(self, args, out, contract, command):
        self.args, self.out, self.contract, self.command = args, out, contract, command
        self.modules = MODEL.parse_netlist(NETLIST.read_text())
        self.results = []

    def record(self, case, status, message, **detail):
        result = dict(**case, status=status, message=message, **detail)
        directory = self.out / case['id']
        directory.mkdir(exist_ok=True)
        P.write_json(directory / 'result.json', result)
        self.results.append(result)
        print(status.upper(), case['id'], message, flush=True)
        return result

    def simulate(self, case, build):
        activity = case['configuration']
        directory = self.out / case['id']
        directory.mkdir()
        rows = MODEL.stimulus(self.args.seed, self.contract['cycles'], self.contract['activities'][activity]['load_every'])
        (directory / 'vectors.txt').write_text(''.join(' '.join(format(v, 'x') for v in row) + '\n' for row in rows))
        loads = sum(row[0] for row in rows)
        if build['error'] or build['returncode'] != 0:
            return self.record(case, 'error', 'build failed; see build.log'), None
        execution = P.execute([self.args.vvp, str(self.out / 'bench.vvp'), f"+VECTORS={directory / 'vectors.txt'}",
                               f"+WAVE={directory / 'wave.vcd'}"], directory / 'simulation.log', self.args.timeout, directory)
        log = (directory / 'simulation.log').read_text(errors='replace')
        passed = re.findall(r'^RESULT PASS checks=(\d+)$', log, re.M)
        counted = re.findall(r'^COUNT loads=(\d+)$', log, re.M)
        if execution['error'] or execution['returncode'] != 0 or re.search(r'^CHECK_FAIL', log, re.M):
            return self.record(case, 'error' if execution['error'] else 'fail', execution['error'] or 'register values differ', execution=execution), None
        if passed != [str(len(rows))] or counted != [str(loads)]:
            return self.record(case, 'error', 'missing or incorrect completion counts', execution=execution), None
        try:
            text = (directory / 'wave.vcd').read_text()
            activity_of = {name: MODEL.transitions(text, f'power_tb/{name}') for name in ('plain', 'gated', 'stuck')}
            clock = {name: counts['clk'] for name, (counts, _) in activity_of.items()}
            # Independent of the netlists: the bench clock toggles twice per cycle, the gated clock twice per load.
            if len(set(clock.values())) != 1 or activity_of['gated'][0]['gclk'] != 2 * loads:
                raise ValueError('clock activity differs from the stimulus')
        except (OSError, ValueError, KeyError) as exc:
            return self.record(case, 'error', f'invalid activity file: {exc}', execution=execution), None
        self.record(case, 'pass', f'{len(rows)} cycles, {loads} loads, register values agree in the three netlists',
                    loads=loads, clock_transitions=clock['plain'], gated_clock_transitions=2 * loads, execution=execution)
        return directory / 'wave.vcd', activity_of

    def analyse(self, case, top, mutation, wave, activity_of, reference):
        """One OpenSTA run. `reference` is the total of the ungated bank, or None when this run is that bank."""
        directory = self.out / case['id']
        directory.mkdir()
        if mutation == 4 and reference is not None:
            top = 'stuck'
        scope = 'plain' if (mutation == 2 and top != 'plain') else 'gated' if mutation == 2 else top
        library = LIBRARY.read_text()
        if mutation == 3:
            pin, old, new = WRONG_LIBRARY
            if library.count(pin) != 1:
                raise ValueError('the clock pin of the flop is not where the mutant expects it')
            library = library.replace(pin, pin.replace(old, new))
        (directory / 'cells.lib').write_text(library)
        shutil.copy2(NETLIST, directory / 'bank.v')
        shutil.copy2(SCRIPT, directory / 'power.tcl')
        shutil.copy2(wave, directory / 'wave.vcd')
        (directory / 'run.tcl').write_text(f'set top bank_{top}\nset scope power_tb/{scope}\n'
                                           f'set use_vcd {int(mutation != 1)}\nsource power.tcl\n')
        execution = P.execute([self.command, '-no_init', '-exit', 'run.tcl'], directory / 'console.log', self.args.timeout, directory)
        log = (directory / 'console.log').read_text(errors='replace')
        if execution['error']:
            return self.record(case, 'error', execution['error'], execution=execution), None
        if execution['returncode'] != 0 or re.search(r'^(?:Error:|TOOL_ERROR)', log, re.M):
            return self.record(case, 'error', 'tool reported an error', execution=execution), None
        module = self.modules[f'bank_{top}']
        try:
            annotation, measured = parse_report(log)
            counts, duration = activity_of[top]
            expected = MODEL.expected_power(module, counts, duration, self.contract)
            differences = differing(measured, expected, self.contract['relative_tolerance'])
        except (ValueError, KeyError) as exc:
            return self.record(case, 'error', f'invalid power evidence: {exc}', execution=execution), None
        measured_total = MODEL.total(measured)
        ratio = None if reference is None else measured_total / reference
        requirement = self.contract['activities'][case['configuration']]['saving']
        label = derive(annotation, MODEL.pin_count(module), differences, ratio, requirement)
        detail = dict(top=f'bank_{top}', scope=f'power_tb/{scope}', annotation=annotation, pins=MODEL.pin_count(module),
                      measured_total_w=measured_total, expected_total_w=MODEL.total(expected), ratio_to_plain=ratio,
                      differences=differences, measured=measured, expected=expected, execution=execution)
        if label != case['expect']:
            return self.record(case, 'fail', f"expected {case['expect']}, got {label}", label=label, **detail), None
        if case['category'] == 'mutation':
            if not intended(case['mutation'], annotation, differences, module):
                return self.record(case, 'error', 'the report does not show the planted mistake', label=label, **detail), None
            return self.record(case, 'detected', f'confirmed {label}', label=label, **detail), None
        message = (f'{len(measured)} instances agree, total {measured_total * 1e6:.3f} uW' if ratio is None else
                   f'{len(measured)} instances agree, total {measured_total * 1e6:.3f} uW, {ratio:.3f} of the ungated bank')
        if case['category'] == 'diagnostic':
            message = 'no saving is expected at this activity; ' + message
        return self.record(case, 'pass', message, label=label, **detail), measured_total


def make_cases(activities, demo_bug, contract):
    cases = []
    for activity in activities:
        base = dict(configuration=activity)
        cases.append(dict(base, id=f'{activity}-simulation', category='simulation', mutation=0, expect='PASS'))
        cases.append(dict(base, id=f'{activity}-plain', category='normal', mutation=0, expect='PASS'))
        cases.append(dict(base, id=f'{activity}-gated', category='normal', mutation=demo_bug, expect='PASS'))
        for mutation in range(1, MUTANTS + 1):
            label = expected_label(mutation, activity, contract)
            cases.append(dict(base, id=f"{activity}-{'unseen' if label == 'PASS' else 'detect'}-mutation{mutation}",
                              category='diagnostic' if label == 'PASS' else 'mutation', mutation=mutation, expect=label))
    return cases


def order_verdict(ratios):
    """The more often the register loads, the less the gate saves."""
    if set(ratios) != set(ACTIVITIES):
        return 'error', 'every activity must have passed'
    ordered = [ratios[name] for name in ACTIVITIES]
    if not ordered[0] < ordered[1] < ordered[2]:
        return 'fail', 'ratio does not grow with the activity: ' + ', '.join(f'{v:.3f}' for v in ordered)
    return 'pass', 'gated/ungated total: ' + ', '.join(f'{name} {ratios[name]:.3f}' for name in ACTIVITIES)


def run(args):
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=False)
    contract = load_contract()
    activities = list(ACTIVITIES) if args.configuration == 'all' else [args.configuration]
    cases = make_cases(activities, args.demo_bug, contract)
    planned = [c['id'] for c in cases] + (['activity-order'] if args.configuration == 'all' else [])
    binary = shutil.which(args.sta)
    if binary:
        binary = str(Path(binary).resolve())
    command = binary or args.sta
    tools = dict(sta=P.execute([command, '-version'], out / 'sta-version.log', args.timeout, out),
                 iverilog=P.execute([args.iverilog, '-V'], out / 'iverilog-version.log', args.timeout, out),
                 vvp=P.execute([args.vvp, '-V'], out / 'vvp-version.log', args.timeout, out))
    hashes = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in SOURCES}
    P.write_json(out / 'manifest.json', dict(
        schema_version=1, created_at=datetime.now(timezone.utc).isoformat(), configurations=activities, seed=args.seed,
        demo_bug=args.demo_bug, cases=cases, check_ids=planned, source_sha256=hashes,
        tool=dict(path=binary, sha256=hashlib.sha256(Path(binary).read_bytes()).hexdigest() if binary else None,
                  version=(out / 'sta-version.log').read_text(), executions=tools)))
    build = P.execute([args.iverilog, '-g2012', '-s', 'power_tb', '-o', str(out / 'bench.vvp'), str(BENCH), str(NETLIST), str(CELLS)],
                      out / 'build.log', args.timeout, out)
    campaign = Campaign(args, out, contract, command)
    ratios = {}
    by_id = {c['id']: c for c in cases}
    for activity in activities:
        simulated = campaign.simulate(by_id[f'{activity}-simulation'], build)
        rest = [c for c in cases if c['configuration'] == activity and c['category'] != 'simulation']
        if simulated[1] is None:
            for case in rest:
                campaign.record(case, 'error', 'no activity file: the simulation did not pass')
            continue
        wave, activity_of = simulated
        _, reference = campaign.analyse(rest[0], 'plain', 0, wave, activity_of, None)
        for case in rest[1:]:
            if reference is None:
                campaign.record(case, 'error', 'no reference: the ungated analysis did not pass')
                continue
            result, _ = campaign.analyse(case, 'gated', case['mutation'], wave, activity_of, reference)
            if case['id'] == f'{activity}-gated' and result['status'] == 'pass':
                ratios[activity] = result['ratio_to_plain']
    results = campaign.results
    if args.configuration == 'all':
        status, message = order_verdict(ratios)
        results.append(dict(id='activity-order', configuration='all', category='comparison', status=status, message=message, ratios=ratios))
        print(status.upper(), 'activity-order', message, flush=True)
    evidence_ok = (all(not t['error'] and t['returncode'] == 0 for t in tools.values()) and
                   bool((out / 'sta-version.log').read_text().strip()) and
                   all(hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == digest for name, digest in hashes.items()))
    complete = [r['id'] for r in results] == planned
    success = evidence_ok and complete and all(r['status'] in ('pass', 'detected') for r in results)
    P.write_json(out / 'summary.json', dict(
        success=success, complete=complete, evidence_ok=evidence_ok, planned=len(planned),
        detected=sum(r['status'] == 'detected' for r in results),
        unseen=sum(r['category'] == 'diagnostic' and r['status'] == 'pass' for r in results), ratios=ratios,
        results=[{k: v for k, v in r.items() if k not in ('measured', 'expected', 'execution')} for r in results]))
    suite = ET.Element('testsuite', name='power-estimate', tests=str(len(results) + 1),
                       failures=str(sum(r['status'] == 'fail' for r in results)),
                       errors=str(sum(r['status'] == 'error' for r in results) + (not evidence_ok)))
    for r in results:
        node = ET.SubElement(suite, 'testcase', name=r['id'], classname='power-estimate.' + r['configuration'])
        if r['status'] in ('fail', 'error'):
            ET.SubElement(node, 'failure' if r['status'] == 'fail' else 'error', message=r['message'])
    gate = ET.SubElement(suite, 'testcase', name='evidence', classname='power-estimate')
    if not evidence_ok:
        ET.SubElement(gate, 'error', message='version acquisition failed or source hashes changed')
    ET.indent(suite)
    ET.ElementTree(suite).write(out / 'junit.xml', encoding='utf-8', xml_declaration=True)
    print('Artifacts:', out, '\nPower:', 'PASS' if success else 'FAIL')
    return 0 if success else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    default = ROOT / 'artifacts/toolchains/opensta-build/sta'
    parser.add_argument('--sta', default=str(default) if default.exists() else 'sta')
    parser.add_argument('--iverilog', default='iverilog')
    parser.add_argument('--vvp', default='vvp')
    parser.add_argument('--configuration', choices=('all', *ACTIVITIES), default='all')
    parser.add_argument('--seed', type=int, default=17)
    parser.add_argument('--demo-bug', type=int, choices=range(MUTANTS + 1), default=0)
    parser.add_argument('--timeout', type=float, default=30)
    parser.add_argument('--out', type=Path, default=ROOT / 'artifacts' / datetime.now(timezone.utc).strftime('power-estimate-%Y%m%dT%H%M%S%fZ'))
    args = parser.parse_args()
    P.resolve_tools(args)
    if args.out.exists() or args.seed < 0 or not math.isfinite(args.timeout) or args.timeout <= 0:
        parser.error('requires a new output directory, a nonnegative seed and a finite positive timeout')
    try:
        return run(args)
    except (OSError, ValueError, KeyError) as exc:
        print('RUNNER_ERROR', exc, file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())

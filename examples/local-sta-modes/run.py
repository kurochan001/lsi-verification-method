#!/usr/bin/env python3
"""Run real OpenSTA per mode and corner: mixed modes, vanished paths, one-corner checks and half-cut clock crossings."""
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
spec = importlib.util.spec_from_file_location('sta_modes_process', PROCESS)
P = importlib.util.module_from_spec(spec)
spec.loader.exec_module(P)
CONTRACT = HERE / 'contract.json'
NETLIST = HERE / 'design/scan_core.v'
SOURCES = [Path(__file__), PROCESS, CONTRACT, HERE / 'check.tcl', HERE / 'constraints.tcl',
           *sorted((HERE / 'design').glob('*'))]
MODES, CORNERS = ('func', 'scan'), ('slow', 'fast')
CONFIGS = [f'{mode}-{corner}' for mode in MODES for corner in CORNERS]
MUTANTS = 6
TOLERANCE = 0.00005
HOLD_BUFFER = ('.B(h1)', '.B(q0)')   # mutant 2 feeds the scan input of f1 straight from f0


def expected_label(mutation, mode, corner):
    """What each mistake must look like in each analysis; PASS means this analysis cannot see it."""
    if mutation == 1:
        return 'STA_SETUP' if corner == 'slow' else 'PASS'
    if mutation == 2:
        return 'STA_HOLD' if (mode, corner) == ('scan', 'fast') else 'PASS'
    if mutation == 5:
        return 'STA_ASYNC' if mode == 'func' else 'PASS'
    return {3: 'STA_MODE', 4: 'STA_PATH', 6: 'STA_ASYNC'}[mutation]


def slack_pair(contract, mode, corner, name):
    """Setup and hold slack of one path from the cell delays, written without the tool."""
    path, delay, margin = contract['paths'][name], contract['corners'][corner], contract['uncertainty']
    period = contract['clocks'][path['clock']] if 'clock' in path else contract['modes'][mode]['period']
    through = sum(delay[cell] for cell in path['cells'])
    launch_max = launch_min = delay['clk_to_q']
    if path['from'] in contract['ports']:
        launch_max, launch_min = (contract['ports'][path['from']][key] for key in ('max', 'min'))
    if path['to'] in contract['ports']:
        setup = period - margin['setup'] - launch_max - through - contract['ports'][path['to']]['max']
        hold = launch_min + through + contract['ports'][path['to']]['min'] - margin['hold']
    else:
        setup = period - margin['setup'] - launch_max - through - delay['setup']
        hold = launch_min + through - delay['hold'] - margin['hold']
    return [round(setup, 6), round(hold, 6)]


def load_contract(path=CONTRACT):
    data = json.loads(path.read_text())
    if data.get('schema_version') != 1 or type(data.get('revision')) is not int or data['revision'] < 1:
        raise ValueError('invalid timing contract version')
    if tuple(data.get('modes', {})) != MODES or set(data.get('corners', {})) != set(CORNERS):
        raise ValueError('timing contract must contain both modes and both corners')
    paths = data.get('paths')
    if not isinstance(paths, dict) or not paths:
        raise ValueError('timing contract has no paths')
    for name, item in paths.items():
        if (not re.fullmatch(r'[a-z0-9_]+', name) or item.get('kind') not in ('mode', 'async') or
                not set(item.get('timed_in', ['?'])) <= set(MODES) or
                any(not isinstance(item.get(key), str) or not item[key] for key in ('from', 'through', 'to'))):
            raise ValueError(f'invalid path {name}')
    if set(data.get('crossings', {})) != {n for n, item in paths.items() if item['kind'] == 'async'}:
        raise ValueError('every asynchronous path needs a structural crossing record')
    for mode in MODES:
        if not any(mode in item['timed_in'] and other not in item['timed_in'] for item in paths.values()
                   for other in MODES if other != mode):
            raise ValueError(f'mode {mode} has no path of its own')
        for corner in CORNERS:
            table = data.get('expected', {}).get(f'{mode}-{corner}')
            timed = {name for name, item in paths.items() if mode in item['timed_in']}
            if not isinstance(table, dict) or set(table) != timed:
                raise ValueError(f'expected slacks of {mode}-{corner} do not cover its timed paths')
            for values in table.values():
                if (not isinstance(values, list) or len(values) != 2 or
                        any(type(v) not in (int, float) or not math.isfinite(v) or v < 0 for v in values)):
                    raise ValueError('expected slacks must be two finite nonnegative numbers')
    return data


def parse(log, contract):
    """Slacks, missing paths, audit and crossings; complete and unambiguous or an error."""
    slacks, missing = {}, set()
    for name, kind, value in re.findall(r'^MEASURE (\w+) (min|max) (\S+)$', log, re.M):
        key, value = f'{name}/{kind}', float(value)
        if key in slacks or not math.isfinite(value):
            raise ValueError('duplicate/nonfinite measurement')
        slacks[key] = value
    for name, kind in re.findall(r'^MISSING (\w+) (min|max)$', log, re.M):
        key = f'{name}/{kind}'
        if key in missing or key in slacks:
            raise ValueError('duplicate path record')
        missing.add(key)
    wanted = {f'{name}/{kind}' for name in contract['paths'] for kind in ('min', 'max')}
    audits = re.findall(r'^AUDIT constraints ([01])$', log, re.M)
    done = re.findall(r'^RESULT STA DONE records=(\d+)$', log, re.M)
    found = re.findall(r'^CROSSING (\w+) ([01])$', log, re.M)
    crossings = {name: int(value) for name, value in found}
    if (set(slacks) | missing != wanted or len(audits) != 1 or done != [str(len(wanted))] or
            len(found) != len(crossings) or set(crossings) != set(contract['crossings'])):
        raise ValueError('incomplete or unexpected timing evidence')
    return slacks, missing, int(audits[0]), crossings


def derive(contract, mode, slacks, missing, audit):
    """The verdict from the measurements alone, with the paths that explain it."""
    timed = {name for name, item in contract['paths'].items() if mode in item['timed_in']}
    present = {key.split('/')[0] for key in slacks}
    gone = sorted({key.split('/')[0] for key in missing} & timed)
    leaked = {kind: sorted(name for name in present - timed if contract['paths'][name]['kind'] == kind)
              for kind in ('mode', 'async')}
    negative = {kind: sorted(key.split('/')[0] for key, value in slacks.items() if key.endswith('/' + kind) and value < 0)
                for kind in ('max', 'min')}
    label = ('STA_CONSTRAINT' if not audit else 'STA_PATH' if gone else 'STA_MODE' if leaked['mode'] else
             'STA_ASYNC' if leaked['async'] else 'STA_SETUP' if negative['max'] else
             'STA_HOLD' if negative['min'] else 'PASS')
    return label, dict(gone=gone, leaked_mode=leaked['mode'], leaked_async=leaked['async'],
                       setup_violations=negative['max'], hold_violations=negative['min'])


def intended(case, contract, detail, slacks):
    """A detection counts only when it is the mistake that was planted."""
    mode, mutation = case['mode'], case['mutation']
    own = sorted(n for n, item in contract['paths'].items() if item['timed_in'] == [mode])
    if mutation == 1:
        return ('logic' if mode == 'func' else 'link01') in detail['setup_violations'] and not detail['hold_violations']
    if mutation == 2:
        return detail['hold_violations'] == ['link01'] and not detail['setup_violations']
    if mutation == 3:  # in the functional mode the leaked enable path is also a violation that does not exist
        return 'enable' in detail['leaked_mode'] and (mode == 'scan' or slacks['enable/max'] < 0)
    if mutation == 4:
        return detail['gone'] == own
    if mutation == 5:
        return detail['leaked_async'] == ['cross_in']
    return detail['leaked_async'] == (['cross_in', 'cross_out'] if mode == 'func' else ['cross_out'])


def judge(case, execution, log, contract):
    if execution['error']:
        return 'error', execution['error'], {}, {}
    if execution['returncode'] != 0 or re.search(r'^(?:Error:|TOOL_ERROR)', log, re.M):
        return 'error', 'tool reported an error', {}, {}
    try:
        slacks, missing, audit, crossings = parse(log, contract)
    except ValueError as exc:
        return 'error', str(exc), {}, {}
    mode = case['mode']
    label, detail = derive(contract, mode, slacks, missing, audit)
    detail['crossings'] = crossings
    if label != case['expect']:
        return 'fail', f"expected {case['expect']}, got {label}", slacks, detail
    if case['category'] == 'mutation':
        if not intended(case, contract, detail, slacks):
            return 'error', 'a different path explains the label', slacks, detail
        return 'detected', f'confirmed {label}', slacks, detail
    if case['category'] == 'diagnostic':
        return 'pass', 'this mode and corner cannot see the mistake', slacks, detail
    if crossings != {name: int(mode in item['exists_in']) for name, item in contract['crossings'].items()}:
        return 'fail', 'clock crossings in the netlist differ from the contract', slacks, detail
    table = contract['expected'][case['configuration']]
    for name, (setup, hold) in table.items():
        if abs(slacks[f'{name}/max'] - setup) > TOLERANCE or abs(slacks[f'{name}/min'] - hold) > TOLERANCE:
            return 'fail', f'slack of {name} differs from the independently calculated contract', slacks, detail
    return 'pass', f'{2 * len(table)} slacks agree; {len(contract["paths"]) - len(table)} paths are not timed', slacks, detail


def corner_verdict(mode, by_corner):
    """Setup is decided by the slow corner and hold by the fast one, for every path timed in both."""
    slow, fast = by_corner.get('slow'), by_corner.get('fast')
    if not slow or not fast or set(slow) != set(fast):
        return 'error', 'both corners must have passed with the same paths'
    setup = [key for key in slow if key.endswith('/max') and not slow[key] < fast[key]]
    hold = [key for key in slow if key.endswith('/min') and not fast[key] < slow[key]]
    if setup or hold:
        return 'fail', 'not decided by the expected corner: ' + ', '.join(setup + hold)
    worst = lambda values, kind: min(v for k, v in values.items() if k.endswith(kind))
    return 'pass', (f"{mode}: worst setup {worst(slow, '/max'):.3f} at slow ({worst(fast, '/max'):.3f} at fast), "
                    f"worst hold {worst(fast, '/min'):.3f} at fast ({worst(slow, '/min'):.3f} at slow)")


def make_cases(configurations, demo_bug):
    cases = []
    for configuration in configurations:
        mode, corner = configuration.split('-')
        base = dict(configuration=configuration, mode=mode, corner=corner)
        cases.append(dict(base, id=configuration + '-normal', category='normal', mutation=demo_bug, expect='PASS'))
        for mutation in range(1, MUTANTS + 1):
            label = expected_label(mutation, mode, corner)
            cases.append(dict(base, id=f"{configuration}-{'unseen' if label == 'PASS' else 'detect'}-mutation{mutation}",
                              category='diagnostic' if label == 'PASS' else 'mutation', mutation=mutation, expect=label))
    return cases


def run(args):
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=False)
    contract = load_contract()
    configurations = CONFIGS if args.configuration == 'all' else [args.configuration]
    cases = make_cases(configurations, args.demo_bug)
    comparisons = [mode for mode in MODES if all(f'{mode}-{corner}' in configurations for corner in CORNERS)]
    binary = shutil.which(args.sta)
    if binary:
        binary = str(Path(binary).resolve())
    command = binary or args.sta
    tool = P.execute([command, '-version'], out / 'version.log', args.timeout, out)
    hashes = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in SOURCES}
    planned = [dict(id=c['id']) for c in cases] + [dict(id=f'{mode}-corners') for mode in comparisons]
    P.write_json(out / 'manifest.json', dict(
        schema_version=1, created_at=datetime.now(timezone.utc).isoformat(), configurations=configurations,
        demo_bug=args.demo_bug, cases=cases, comparisons=comparisons, check_ids=[c['id'] for c in planned],
        source_sha256=hashes,
        tool=dict(path=binary, sha256=hashlib.sha256(Path(binary).read_bytes()).hexdigest() if binary else None,
                  version=(out / 'version.log').read_text(), execution=tool)))
    paths = ''.join(f"    {name} {item['from']} {item['through']} {item['to']}\n" for name, item in contract['paths'].items())
    crossings = ''.join(f"    {name} {item['from']} {item['to']}\n" for name, item in contract['crossings'].items())
    results, normal = [], {}
    for case in cases:
        directory = out / case['id']
        directory.mkdir()
        mode, corner, mutation = case['mode'], case['corner'], case['mutation']
        shutil.copy2(HERE / 'design' / f'{corner}.lib', directory / 'cells.lib')
        for name in ('check.tcl', 'constraints.tcl'):
            shutil.copy2(HERE / name, directory / name)
        netlist = NETLIST.read_text()
        if mutation == 2:
            if netlist.count(HOLD_BUFFER[0]) != 1:
                raise ValueError('the hold buffer of the first scan link is not where the mutant expects it')
            netlist = netlist.replace(*HOLD_BUFFER)
        (directory / 'scan_core.v').write_text(netlist)
        (directory / 'paths.tcl').write_text(f'set paths {{\n{paths}}}\nset crossings {{\n{crossings}}}\n')
        period = contract['modes'][mode]['short_period' if mutation == 1 else 'period']
        (directory / 'run.tcl').write_text(f'set mode {mode}\nset period {period}\nset mutation {mutation}\nsource check.tcl\n')
        execution = P.execute([command, '-no_init', '-exit', 'run.tcl'], directory / 'console.log', args.timeout, directory)
        status, message, slacks, detail = judge(case, execution, (directory / 'console.log').read_text(errors='replace'), contract)
        result = dict(**case, status=status, message=message, slacks=slacks, detail=detail, execution=execution)
        P.write_json(directory / 'result.json', result)
        results.append(result)
        if case['category'] == 'normal' and status == 'pass':
            normal.setdefault(mode, {})[corner] = slacks
        print(status.upper(), case['id'], message, flush=True)
    for mode in comparisons:
        status, message = corner_verdict(mode, normal.get(mode, {}))
        result = dict(id=f'{mode}-corners', configuration=mode, mode=mode, category='comparison', status=status, message=message)
        results.append(result)
        print(status.upper(), result['id'], message, flush=True)
    evidence_ok = (not tool['error'] and tool['returncode'] == 0 and bool((out / 'version.log').read_text().strip()) and
                   all(hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == digest for name, digest in hashes.items()))
    complete = [r['id'] for r in results] == [c['id'] for c in planned]
    success = evidence_ok and complete and all(r['status'] in ('pass', 'detected') for r in results)
    P.write_json(out / 'summary.json', dict(
        success=success, complete=complete, evidence_ok=evidence_ok, planned=len(planned),
        detected=sum(r['status'] == 'detected' for r in results),
        unseen=sum(r['category'] == 'diagnostic' and r['status'] == 'pass' for r in results), results=results))
    suite = ET.Element('testsuite', name='opensta-modes', tests=str(len(results) + 1),
                       failures=str(sum(r['status'] == 'fail' for r in results)),
                       errors=str(sum(r['status'] == 'error' for r in results) + (not evidence_ok)))
    for r in results:
        node = ET.SubElement(suite, 'testcase', name=r['id'], classname='opensta-modes.' + r['configuration'])
        if r['status'] in ('fail', 'error'):
            ET.SubElement(node, 'failure' if r['status'] == 'fail' else 'error', message=r['message'])
    gate = ET.SubElement(suite, 'testcase', name='evidence', classname='opensta-modes')
    if not evidence_ok:
        ET.SubElement(gate, 'error', message='version acquisition or source hashes changed')
    ET.indent(suite)
    ET.ElementTree(suite).write(out / 'junit.xml', encoding='utf-8', xml_declaration=True)
    print('Artifacts:', out, '\nSTA:', 'PASS' if success else 'FAIL')
    return 0 if success else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    default = ROOT / 'artifacts/toolchains/opensta-build/sta'
    parser.add_argument('--sta', default=str(default) if default.exists() else 'sta')
    parser.add_argument('--configuration', choices=('all', *CONFIGS), default='all')
    parser.add_argument('--demo-bug', type=int, choices=range(MUTANTS + 1), default=0)
    parser.add_argument('--timeout', type=float, default=30)
    parser.add_argument('--out', type=Path, default=ROOT / 'artifacts' / datetime.now(timezone.utc).strftime('sta-modes-%Y%m%dT%H%M%S%fZ'))
    args = parser.parse_args()
    P.resolve_tools(args)
    if args.out.exists() or not math.isfinite(args.timeout) or args.timeout <= 0:
        parser.error('requires a new output directory and finite positive timeout')
    try:
        return run(args)
    except (OSError, ValueError, KeyError) as exc:
        print('RUNNER_ERROR', exc, file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())

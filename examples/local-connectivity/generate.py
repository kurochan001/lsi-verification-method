#!/usr/bin/env python3
"""Generate the formal connectivity checker from the connection table.

The block and SoC port lists come from Yosys, so every width in the checker is the
compiled one. Generation stops when the table leaves a destination bit unspecified,
specifies it twice, compares values of different widths or never uses a block output.
"""
import argparse
import csv
import json
from pathlib import Path
import re
import subprocess
import sys

HERE = Path(__file__).resolve().parent
TABLE = HERE / 'connectivity.csv'
CHECKER = HERE / 'conn_check.sv'
RTL = [HERE / 'rtl/soc_top.sv', HERE / 'ip_blackbox.sv']
TOP = 'soc_top'
ELEMENT = re.compile(r"(\d+)'b([01_]+)|(u_\w+\.\w+|[a-z]\w*)(?:\[(\d+)(?::(\d+))?\])?")
PROBE = re.compile(r'\bu_\w+\.\w+')


class TableError(ValueError):
    pass


def rows(path=TABLE):
    with path.open(newline='', encoding='utf-8') as f:
        return list(csv.DictReader(f))


def assert_name(row):
    return 'ap_' + row['id'].lower()


def cover_rows(table):
    """One cover per distinct condition, named after its first row, and one per delayed row."""
    seen, chosen = set(), []
    for row in table:
        if row['when'] and row['when'] not in seen:
            seen.add(row['when'])
            chosen.append(row)
        elif row['delay'] != '0':
            chosen.append(row)
    return chosen


def names(table):
    return {'assert': {assert_name(r) for r in table}, 'assume': set(),
            'cover': {'cp_' + r['id'].lower() for r in cover_rows(table)}}


def probes(table):
    """Block ports the table refers to, in order of first use."""
    found = []
    for row in table:
        for field in ('to', 'from', 'when', 'reset'):
            for probe in PROBE.findall(row[field]):
                if probe not in found:
                    found.append(probe)
    return found


def netlist(yosys):
    script = f"read_verilog -sv {' '.join(map(str, RTL))}; hierarchy -top {TOP}; proc; write_json"
    result = subprocess.run([yosys, '-q', '-p', script], capture_output=True, text=True, timeout=120)
    if result.returncode:
        raise TableError('Yosys could not read the design: ' + (result.stderr or result.stdout).strip())
    modules = json.loads(result.stdout)['modules']
    ports = {name: {p: (v['direction'], len(v['bits'])) for p, v in m['ports'].items()}
             for name, m in modules.items()}
    instances = {cell: c['type'] for cell, c in modules[TOP]['cells'].items() if c['type'] in modules}
    return ports, instances


class Design:
    def __init__(self, ports, instances):
        self.top = ports[TOP]
        self.blocks = {inst: ports[kind] for inst, kind in instances.items()}

    def port(self, name):
        if '.' in name:
            inst, port = name.split('.')
            if inst not in self.blocks or port not in self.blocks[inst]:
                raise TableError(f'unknown block port {name}')
            return self.blocks[inst][port]
        if name not in self.top:
            raise TableError(f'unknown SoC port {name}')
        return self.top[name]

    def bits(self, text):
        """Width and (signal, bit) set of a name, slice, sized literal or concatenation."""
        body = text[1:-1] if text.startswith('{') and text.endswith('}') else text
        width, bits = 0, set()
        for part in body.split(','):
            m = ELEMENT.fullmatch(part.strip())
            if not m:
                raise TableError(f'unsupported expression {text!r}')
            if m.group(1):
                if len(m.group(2).replace('_', '')) != int(m.group(1)):
                    raise TableError(f'literal width differs in {part}')
                width += int(m.group(1))
                continue
            name, full = m.group(3), self.port(m.group(3))[1]
            if m.group(4) is None:
                high, low = full - 1, 0
            elif m.group(5) is None:
                high = low = int(m.group(4))
            else:
                high, low = int(m.group(4)), int(m.group(5))
            if not 0 <= low <= high < full:
                raise TableError(f'{part} is outside {name}[{full-1}:0]')
            width += high - low + 1
            bits |= {(name, b) for b in range(low, high + 1)}
        return width, bits


def check(table, design):
    """Every block input bit and SoC output bit is specified exactly once per condition."""
    specified = {}
    for row in table:
        width, _ = design.bits(row['from'])
        for target in row['to'].split():
            tw, tbits = design.bits(target)
            if tw != width:
                raise TableError(f"{row['id']}: {target} has {tw} bits, {row['from']} has {width}")
            for bit in tbits:
                specified.setdefault(bit, []).append(row['when'])
        for field in ('when', 'reset'):
            if row[field] and design.bits(row[field].lstrip('!'))[0] != 1:
                raise TableError(f"{row['id']}: {field} must be one bit")
        if row['delay'] not in ('0', '1') or (row['delay'] == '1') != bool(row['reset']):
            raise TableError(f"{row['id']}: delay is 0, or 1 with a reset")
        if row['delay'] == '1' and (row['when'] or len(row['to'].split()) != 1):
            raise TableError(f"{row['id']}: a delayed row has one target and no condition")
    required = {(f'{inst}.{p}', b) for inst, ports in design.blocks.items()
                for p, (direction, w) in ports.items() if direction == 'input' for b in range(w)}
    required |= {(p, b) for p, (direction, w) in design.top.items() if direction == 'output' for b in range(w)}
    for bit in sorted(required | set(specified)):
        conditions = sorted(specified.get(bit, []))
        if bit not in required:
            raise TableError(f'{bit[0]}[{bit[1]}] is not a block input or SoC output')
        if conditions != [''] and not (len(conditions) == 2 and conditions[0] == '!' + conditions[1]):
            raise TableError(f'{bit[0]}[{bit[1]}] needs one unconditional row or a pair c / !c, got {conditions}')
    used = set(probes(table))
    for inst, ports in design.blocks.items():
        for p, (direction, _) in ports.items():
            if direction == 'output' and f'{inst}.{p}' not in used:
                raise TableError(f'{inst}.{p} is never used by the table')


def local(expr):
    return PROBE.sub(lambda m: m.group(0).replace('.', '__'), expr)


def declare(width, name):
    return f'wire {name};' if width == 1 else f'wire [{width-1}:0] {name};'


def render(table, design):
    check(table, design)
    inputs = [(p, w) for p, (d, w) in design.top.items() if d == 'input']
    outputs = [(p, w) for p, (d, w) in design.top.items() if d == 'output']
    ports = ', '.join(f'input wire {p}' if w == 1 else f'input wire [{w-1}:0] {p}' for p, w in inputs)
    lines = ['// Generated by generate.py from connectivity.csv. Do not edit by hand.',
             '// soc_probe is soc_top after Yosys flattens it and exposes the block ports below.',
             f'module conn_check({ports});']
    lines += ['    ' + declare(w, p) for p, w in outputs]
    found = probes(table)
    lines += ['    ' + declare(design.port(p)[1], local(p)) for p in found]
    connections = [f'.{p}({p})' for p, _ in inputs + outputs] + [f'.\\{p} ({local(p)})' for p in found]
    lines.append('    soc_probe dut(' + (',\n' + ' ' * 18).join(connections) + ');')
    lines += ['    reg past_valid = 0;', '    always @(posedge clk) past_valid <= 1;']
    for row in table:
        targets = row['to'].split()
        lines.append(f"    // {row['id']}: {row['note']}")
        if row['delay'] == '1':
            width = design.bits(row['from'])[0]
            expected = f"($past({local(row['reset'])}) ? $past({local(row['from'])}) : {width}'d0)"
            lines.append(f"    always @(posedge clk) if (past_valid) {assert_name(row)}: "
                         f"assert({local(targets[0])} == {expected});")
            continue
        guard = f"if ({local(row['when'])}) " if row['when'] else ''
        head = f'    always @* {guard}{assert_name(row)}: assert('
        relation = (' &&\n' + ' ' * len(head)).join(f"{local(t)} == {local(row['from'])}" for t in targets)
        lines.append(f'{head}{relation});')
    lines.append('    // Covers: each condition of the table can hold, and the delayed path carries a 1.')
    for row in cover_rows(table):
        if row['delay'] == '1':
            lines.append(f"    always @(posedge clk) if (past_valid) cp_{row['id'].lower()}: "
                         f"cover({local(row['to'])});")
        else:
            lines.append(f"    always @* cp_{row['id'].lower()}: cover({local(row['when'])});")
    lines.append('endmodule')
    return '\n'.join(lines) + '\n'


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--yosys', default='yowasp-yosys')
    p.add_argument('--check', action='store_true', help='fail when conn_check.sv is out of date')
    args = p.parse_args()
    try:
        text = render(rows(), Design(*netlist(args.yosys)))
    except TableError as exc:
        print('TABLE_ERROR', exc, file=sys.stderr)
        return 1
    if args.check:
        current = CHECKER.read_text() == text
        print('conn_check.sv is', 'current' if current else 'out of date')
        return 0 if current else 1
    CHECKER.write_text(text)
    print('wrote', CHECKER.relative_to(HERE))
    return 0


if __name__ == '__main__':
    sys.exit(main())

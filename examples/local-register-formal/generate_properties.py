#!/usr/bin/env python3
"""Generate formal properties for a register block from elaborated SystemRDL, one group per field attribute."""
import argparse
import json
from pathlib import Path

from systemrdl import RDLCompiler

# Deliberate generator errors, for the checks that must notice them (see README).
DEMO_BUGS = {
    1: 'no property for the reserved bits',
    2: 'onwrite=woclr is ignored, so a W1C field is treated as plain RW',
    3: 'the reset value of every field is taken as zero',
    4: 'no property for unmapped addresses',
    5: 'only the bits above the highest field count as reserved',
}


def fields_of(path):
    """The supported subset: a flat map of 32-bit registers with RW, RO and sticky W1C fields."""
    compiler = RDLCompiler()
    compiler.compile_file(str(path))
    top = compiler.elaborate().top
    if top.list_properties() or any(type(node).__name__ != 'RegNode' for node in top.children()):
        raise ValueError('only a flat address map without further properties is supported')
    registers = []
    for reg in top.registers():
        if set(reg.list_properties()) - {'regwidth'} or reg.is_array or reg.get_property('regwidth') != 32:
            raise ValueError('only scalar 32-bit registers are supported')
        if reg.absolute_address % 4 or reg.absolute_address > 252:
            raise ValueError('word-aligned addresses below 256 are required')
        fields = []
        for field in reg.fields():
            sw, hw = field.get_property('sw').name, field.get_property('hw').name
            onwrite = field.get_property('onwrite')
            onwrite = onwrite.name if onwrite else None
            reset = field.get_property('reset')
            if not isinstance(reset, int) or field.get_property('onread') is not None:
                raise ValueError('an explicit integer reset and no read side effect are required')
            names = set(field.list_properties())
            if sw == 'rw' and hw == 'r' and onwrite is None and names <= {'sw', 'hw', 'reset'}:
                access = 'RW'
            elif sw == 'r' and hw == 'r' and names <= {'sw', 'hw', 'reset'}:
                access = 'RO'
            elif (sw == 'rw' and hw == 'w' and onwrite == 'woclr' and field.get_property('stickybit')
                  and field.get_property('precedence').name == 'hw'
                  and names <= {'sw', 'hw', 'reset', 'onwrite', 'stickybit', 'precedence'}):
                access = 'W1C'
            else:
                raise ValueError(f'unsupported field semantics: {reg.inst_name}.{field.inst_name}')
            fields.append(dict(name=field.inst_name, lsb=field.low, width=field.width, access=access, reset=reset))
        if not fields:
            raise ValueError('a register needs a field')
        registers.append(dict(name=reg.inst_name, address=reg.absolute_address, fields=fields))
    if len({r['address'] for r in registers}) != len(registers):
        raise ValueError('two registers share an address')
    return registers


def reserved_mask(register, demo_bug):
    used = 0
    for field in register['fields']:
        used |= ((1 << field['width']) - 1) << field['lsb']
    if demo_bug == 5:
        top = max(f['lsb'] + f['width'] for f in register['fields'])
        return 0xffffffff & ~((1 << top) - 1)
    return 0xffffffff & ~used


def build(registers, binding, demo_bug=0):
    """The property table: every row becomes exactly one assertion or cover of the same name."""
    asserts, covers = [], []

    def row(kind, register, field=None, value=None):
        name = '_'.join(x for x in ('ap', register and register['name'], field and field['name'], kind) if x)
        asserts.append(dict(name=name, kind=kind, register=register and register['name'], field=field and field['name'],
                            address=register and register['address'], lsb=field and field['lsb'],
                            width=field and field['width'], value=value))

    def goal(kind, register=None, field=None):
        covers.append('_'.join(x for x in ('cp', register and register['name'], field and field['name'], kind) if x))

    for register in registers:
        for field in register['fields']:
            access = 'RW' if demo_bug == 2 and field['access'] == 'W1C' else field['access']
            row('reset', register, field, 0 if demo_bug == 3 else field['reset'])
            if access == 'RW':
                row('write', register, field)
                row('hold', register, field)
                goal('write', register, field)
            elif access == 'RO':
                row('const', register, field, 0 if demo_bug == 3 else field['reset'])
            else:
                row('event', register, field)
                row('w1c', register, field)
                goal('event', register, field)
                goal('clear', register, field)
            row('read', register, field)
            goal('read', register, field)
        mask = reserved_mask(register, demo_bug)
        if mask and demo_bug != 1:
            row('reserved', register, value=mask)
        if all(f['access'] == 'RO' for f in register['fields']):
            row('ro_write', register, value='error' if binding['ro_write_error'] else 'ignored')
            goal('ro_write', register)
    if demo_bug != 4:
        row('unmapped_error', None)
        row('unmapped_read', None)
        goal('unmapped')
    row('mapped_ok', None)
    return dict(asserts=asserts, covers=covers, assumes=['as_reset', 'as_select', 'as_phase', 'as_stable'])


def storage(binding, register, field):
    return binding['storage'].format(reg=register['name'], field=field['name'])


def text(registers, table, binding, idle=False):
    """SystemVerilog to be placed inside the register module, where it can see the storage."""
    by_name = {r['name']: r for r in registers}
    kinds = {a['name']: a for a in table['asserts']}
    out = ['// Generated by generate_properties.py. Do not edit.',
           "reg f_past;", "initial f_past = 1'b0;", "always @(posedge clk) f_past <= 1'b1;",
           'wire f_access = psel && penable;', 'wire f_done = f_access && pready;']
    for register in registers:
        out.append(f"wire f_sel_{register['name']} = paddr == 8'd{register['address']};")
    out.append('wire f_mapped = ' + ' || '.join(f"f_sel_{r['name']}" for r in registers) + ';')
    read_only = [r for r in registers if all(f['access'] == 'RO' for f in r['fields'])]
    refused = ' || '.join(f"f_sel_{r['name']}" for r in read_only) if binding['ro_write_error'] and read_only else "1'b0"
    out += [f'wire f_refused = pwrite && ({refused});', 'wire f_wr = f_done && pwrite && f_mapped && !f_refused;']
    lines = []      # body of the clocked block

    def emit(name, condition, expression):
        if name in kinds or name.startswith('cp_'):
            verb = 'cover' if name.startswith('cp_') else 'assert'
            lines.append(f'    if ({condition}) {name}: {verb}({expression});')

    def want(name):
        return name in table['covers']

    for register in registers:
        reg = register['name']
        sel = f'f_sel_{reg}'
        for field in register['fields']:
            base = f"{reg}_{field['name']}"
            keep = storage(binding, register, field)
            width, lsb = field['width'], field['lsb']
            data = f"pwdata[{lsb + width - 1}:{lsb}]"
            row = kinds.get(f'ap_{base}_reset')
            if row:
                emit(f'ap_{base}_reset', 'f_past && !$past(rst_n)', f"{keep} == {width}'h{row['value']:x}")
            if f'ap_{base}_write' in kinds:
                emit(f'ap_{base}_write', f'f_past && $past(rst_n) && $past(f_wr && {sel})', f'{keep} == $past({data})')
                emit(f'ap_{base}_hold', f'f_past && $past(rst_n) && !$past(f_wr && {sel})', f'{keep} == $past({keep})')
                if want(f'cp_{base}_write'):
                    emit(f'cp_{base}_write', f'f_past && $past(rst_n) && $past(f_wr && {sel})',
                         f"{keep} != {width}'h{field['reset']:x}")
            if f'ap_{base}_const' in kinds:
                emit(f'ap_{base}_const', 'f_past', f"{keep} == {width}'h{kinds[f'ap_{base}_const']['value']:x}")
            if f'ap_{base}_event' in kinds:
                low, high = binding['events'][f"{reg}.{field['name']}"]
                out.append(f'wire [{width - 1}:0] f_{base}_event = events[{high}:{low}];')
                out.append(f"wire [{width - 1}:0] f_{base}_clear = f_wr && {sel} ? {data} : {width}'d0;")
                emit(f'ap_{base}_event', 'f_past && $past(rst_n)', f"($past(f_{base}_event) & ~{keep}) == {width}'d0")
                emit(f'ap_{base}_w1c', 'f_past && $past(rst_n)',
                     f'({keep} & ~$past(f_{base}_event)) == ($past({keep}) & ~$past(f_{base}_clear) & ~$past(f_{base}_event))')
                if want(f'cp_{base}_event'):
                    emit(f'cp_{base}_event', 'f_past && $past(rst_n)', f"$past({keep}) == {width}'d0 && {keep} != {width}'d0")
                    emit(f'cp_{base}_clear', 'f_past && $past(rst_n)',
                         f"$past({keep}) != {width}'d0 && $past(f_{base}_clear) != {width}'d0 && {keep} == {width}'d0")
            emit(f'ap_{base}_read', f'f_access && !pwrite && {sel}', f'prdata[{lsb + width - 1}:{lsb}] == {keep}')
            if want(f'cp_{base}_read'):
                emit(f'cp_{base}_read', f'f_done && !pwrite && {sel}', "1'b1")
        row = kinds.get(f'ap_{reg}_reserved')
        if row:
            emit(f'ap_{reg}_reserved', f'f_access && !pwrite && {sel}', f"(prdata & 32'h{row['value']:x}) == 32'd0")
        row = kinds.get(f'ap_{reg}_ro_write')
        if row:
            emit(f'ap_{reg}_ro_write', f'f_done && pwrite && {sel}', 'pslverr' if row['value'] == 'error' else '!pslverr')
            if want(f'cp_{reg}_ro_write'):
                emit(f'cp_{reg}_ro_write', f'f_done && pwrite && {sel}', "1'b1")
    emit('ap_unmapped_error', 'f_done && !f_mapped', 'pslverr')
    emit('ap_unmapped_read', 'f_access && !f_mapped', "prdata == 32'd0")
    if want('cp_unmapped'):
        emit('cp_unmapped', 'f_done && !f_mapped', "1'b1")
    emit('ap_mapped_ok', 'f_done && f_mapped && !f_refused', '!pslverr')
    assert by_name and len(lines) == len(table['asserts']) + len(table['covers']), 'a row without a statement'
    out += ['always @(posedge clk) begin',
            '    // The environment: one reset first, then APB transfers of a setup and an access phase.',
            '    if (!f_past) as_reset: assume(!rst_n);',
            '    as_select: assume(psel || !penable);',
            '    as_phase: assume(penable == (f_past && $past(psel) && !$past(f_done)));',
            '    if (f_past && $past(psel) && !$past(f_done)) as_stable: assume(psel && paddr == $past(paddr) '
            '&& pwrite == $past(pwrite) && pwdata == $past(pwdata));']
    if idle:
        out.append('    as_idle: assume(!psel);')
    out += lines + ['end', '']
    return '\n'.join(out)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('--bindings', type=Path, required=True, help='JSON: how each block stores fields and answers')
    parser.add_argument('--configuration', required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--demo-bug', type=int, choices=range(len(DEMO_BUGS) + 1), default=0)
    parser.add_argument('--idle', action='store_true', help='diagnostic: also assume that no transfer ever starts')
    args = parser.parse_args()
    binding = json.loads(args.bindings.read_text())[args.configuration]
    registers = fields_of(args.source)
    table = build(registers, binding, args.demo_bug)
    if args.idle:
        table['assumes'].append('as_idle')
    args.out.mkdir(parents=True, exist_ok=False)
    (args.out / 'model.json').write_text(json.dumps(registers, indent=2) + '\n')
    (args.out / 'properties.json').write_text(json.dumps(table, indent=2) + '\n')
    (args.out / 'properties.svh').write_text(text(registers, table, binding, args.idle))


if __name__ == '__main__':
    main()

"""Edits of a Yosys JSON netlist: scan insertion, ECO patches and the deliberate errors of this example.

Every function takes the parsed JSON of one design and returns a new one. Nothing here runs a tool.
"""
import copy

FLOP_TYPES = {'$_DFF_P_', '$_SDFF_PN0_', '$_SDFF_PN1_', '$_SDFF_PP0_', '$_SDFF_PP1_'}
DIRECTIONS = {'$_MUX_': dict(A='input', B='input', S='input', Y='output'),
              '$_AND_': dict(A='input', B='input', Y='output'),
              '$_OR_': dict(A='input', B='input', Y='output')}


def module_of(netlist, name):
    try:
        return netlist['modules'][name]
    except KeyError:
        raise ValueError(f'module {name} is not in the netlist') from None


def renamed(netlist, old, new):
    """The same design with its module called `new`, so that it can sit next to the RTL of the same name."""
    result = copy.deepcopy(netlist)
    result['modules'] = {new if key == old else key: value for key, value in result['modules'].items()}
    module_of(result, new)
    return result


def bit_names(module):
    """Net number -> public name such as `count[2]`. Of two public names, the one that is not a port is used."""
    names = {}
    for name, net in sorted(module['netnames'].items(), key=lambda item: (item[0] in module['ports'], item[0])):
        if net.get('hide_name'):
            continue
        for index, bit in enumerate(net['bits']):
            if isinstance(bit, int):
                names.setdefault(bit, name if len(net['bits']) == 1 else f'{name}[{index}]')
    return names


def flops(module):
    """Flop name -> cell name, the flop being called after the public net it drives."""
    names = bit_names(module)
    result = {}
    for cell_name, cell in module['cells'].items():
        if cell['type'] not in FLOP_TYPES:
            continue
        q = cell['connections']['Q'][0]
        if q not in names or names[q] in result:
            raise ValueError(f'flop {cell_name} cannot be named after its output')
        result[names[q]] = cell_name
    if not result:
        raise ValueError('the netlist has no flop')
    return dict(sorted(result.items()))


def _next_bit(module):
    used = [bit for net in module['netnames'].values() for bit in net['bits'] if isinstance(bit, int)]
    used += [bit for cell in module['cells'].values() for bits in cell['connections'].values()
             for bit in bits if isinstance(bit, int)]
    return max(used) + 1


def _add_net(module, name):
    if name in module['netnames']:
        raise ValueError(f'net {name} already exists')
    bit = _next_bit(module)
    module['netnames'][name] = dict(hide_name=0, bits=[bit], attributes={})
    return bit


def _add_port(module, name, direction, bit=None):
    if name in module['ports']:
        raise ValueError(f'port {name} already exists')
    if bit is None:
        bit = _add_net(module, name)
    else:
        module['netnames'][name] = dict(hide_name=0, bits=[bit], attributes={})
    module['ports'][name] = dict(direction=direction, bits=[bit])
    return bit


def _add_cell(module, name, kind, **connections):
    if name in module['cells']:
        raise ValueError(f'cell {name} already exists')
    module['cells'][name] = dict(hide_name=0, type=kind, parameters={}, attributes={},
                                 port_directions=dict(DIRECTIONS[kind]),
                                 connections={port: [bit] for port, bit in connections.items()})


def scan_insert(netlist, top, miswire=None, break_at=None):
    """Put a multiplexer in front of every plain D flop and chain the flops in the order of their names.

    scan_en=0 selects the functional data, scan_en=1 the previous flop of the chain (scan_in for the first).
    scan_out is the output of the last flop. Two deliberate errors:
    miswire  -- the two data inputs of the multiplexer of this flop are exchanged
    break_at -- this flop takes scan_in instead of the previous flop, which cuts the chain in two
    """
    result = copy.deepcopy(netlist)
    module = module_of(result, top)
    chain = flops(module)
    for option in (miswire, break_at):
        if option is not None and option not in chain:
            raise ValueError(f'no flop called {option}')
    if any(module['cells'][cell]['type'] != '$_DFF_P_' for cell in chain.values()):
        raise ValueError('scan insertion expects plain D flops; legalize the netlist first')
    if break_at is not None and break_at == next(iter(chain)):
        raise ValueError('the first flop already takes scan_in')
    scan_en = _add_port(module, 'scan_en', 'input')
    scan_in = _add_port(module, 'scan_in', 'input')
    previous = scan_in
    for index, (name, cell_name) in enumerate(chain.items()):
        cell = module['cells'][cell_name]
        functional = cell['connections']['D'][0]
        shifted = scan_in if name == break_at else previous
        mux_out = _add_net(module, f'scan_d{index}')
        a, b = (shifted, functional) if name == miswire else (functional, shifted)
        _add_cell(module, f'scan_mux{index}', '$_MUX_', A=a, B=b, S=scan_en, Y=mux_out)
        cell['connections']['D'] = [mux_out]
        previous = cell['connections']['Q'][0]
    _add_port(module, 'scan_out', 'output', previous)
    return result, list(chain)


def mutate_reset(netlist, top, flop, kind):
    """Change the synchronous reset of one flop: `polarity` makes it active high, `value` makes it reset to 1."""
    result = copy.deepcopy(netlist)
    module = module_of(result, top)
    cell = module['cells'][flops(module)[flop]]
    if cell['type'] != '$_SDFF_PN0_' or kind not in ('polarity', 'value'):
        raise ValueError('expected a flop with an active-low reset to 0, and polarity or value')
    cell['type'] = '$_SDFF_PP0_' if kind == 'polarity' else '$_SDFF_PN1_'
    return result


def eco_alarm(netlist, top, wrong_gate=False):
    """ECO for the changed specification: the alarm flop takes `count >= 10` instead of `count >= 12`.

    count >= 10 is count[3] & (count[2] | count[1]): two added gates. The old gates stay in the netlist
    without a load, as after a metal ECO. wrong_gate uses AND for the OR, which gives count >= 14.
    """
    result = copy.deepcopy(netlist)
    module = module_of(result, top)
    cells = flops(module)
    q = {name: module['cells'][cells[name]]['connections']['Q'][0] for name in ('count[1]', 'count[2]', 'count[3]')}
    inner = _add_net(module, 'eco_n1')
    _add_cell(module, 'eco_g1', '$_AND_' if wrong_gate else '$_OR_', A=q['count[2]'], B=q['count[1]'], Y=inner)
    outer = _add_net(module, 'eco_n2')
    _add_cell(module, 'eco_g2', '$_AND_', A=q['count[3]'], B=inner, Y=outer)
    module['cells'][cells['alarm']]['connections']['D'] = [outer]
    return result


def compared_points(equiv_json, top='equiv'):
    """Names of the gold nets that feed a $equiv cell, e.g. `u.count[2]`: what the proof actually compared."""
    module = module_of(equiv_json, top)
    names = {}
    for name, net in module['netnames'].items():
        if name.endswith('_gold'):
            for index, bit in enumerate(net['bits']):
                if isinstance(bit, int):
                    names.setdefault(bit, []).append(name[:-5] if len(net['bits']) == 1 else f'{name[:-5]}[{index}]')
    points = set()
    for cell in module['cells'].values():
        if cell['type'] == '$equiv':
            points.update(names.get(cell['connections']['A'][0], []))
    return points

"""Expected power of a cell netlist from its activity file, written without the timing tool."""
import random
import re

MODULE = re.compile(r'^module (\w+)\((.*?)\);(.*?)^endmodule', re.M | re.S)
INSTANCE = re.compile(r'^\s*(\w+) (\w+)\((.*?)\);', re.M)
PIN = re.compile(r'\.(\w+)\(([^()]*)\)')


def stimulus(seed, cycles, load_every):
    """Rows of enable, data and the register value after the clock edge."""
    rng, value, rows = random.Random(seed), 0, []
    for cycle in range(cycles):
        enable = int(cycle % load_every == load_every - 1)
        data = rng.randrange(256)
        value = data if enable else value
        rows.append([enable, data, value])
    return rows


def parse_netlist(text):
    """Per module: the bits of its ports with their direction, and its instances with pin-to-net maps."""
    modules = {}
    for name, header, body in MODULE.findall(text):
        ports = {}
        for direction, high, port in re.findall(r'(input|output)\s*(?:\[(\d+):0\])?\s*(\w+)', header):
            for bit in ([f'{port}[{i}]' for i in range(int(high) + 1)] if high else [port]):
                ports[bit] = direction
        instances = {}
        for cell, instance, pins in INSTANCE.findall(body):
            if cell == 'wire':
                continue
            if instance in instances:
                raise ValueError(f'duplicate instance {instance}')
            instances[instance] = (cell, dict(PIN.findall(pins)))
        if not ports or not instances:
            raise ValueError(f'module {name} has no ports or no instances')
        modules[name] = dict(ports=ports, instances=instances)
    if not modules:
        raise ValueError('no module found')
    return modules


def pin_count(module):
    """What a complete annotation covers: every pin of every cell and every port bit."""
    return len(module['ports']) + sum(len(pins) for _, pins in module['instances'].values())


def transitions(text, scope):
    """Value changes per net bit directly inside `scope`, and the length of the file in ns.

    The first value of a variable is not a change. A change to or from an unknown value is an error:
    the estimate would silently depend on how the tool counts it.
    """
    unit = re.search(r'\$timescale\s+(\d+)\s*(\w+)\s+\$end', text)
    if not unit:
        raise ValueError('activity file has no timescale')
    scale = int(unit.group(1)) * {'ps': 0.001, 'ns': 1.0}[unit.group(2)]
    header, _, body = text.partition('$enddefinitions')
    if not body:
        raise ValueError('activity file has no end of definitions')
    names, path, wanted = {}, [], scope.split('/')
    for kind, rest in re.findall(r'\$(scope|upscope|var)\s+(.*?)\s*\$end', header, re.S):
        if kind == 'scope':
            path.append(rest.split()[1])
        elif kind == 'upscope':
            path.pop()
        elif path == wanted:
            _, width, code, name, *select = rest.split()
            bits = [f'{name}[{i}]' for i in range(int(width) - 1, -1, -1)] if int(width) > 1 else [name]
            if int(width) > 1 and select != [f'[{int(width) - 1}:0]']:
                raise ValueError(f'unexpected range of {name}')
            names.setdefault(code, []).append(bits)
    if not names:
        raise ValueError(f'scope {scope} not found in the activity file')
    last, counts, now = {}, {}, 0
    for line in body.split('\n'):
        line = line.strip()
        if not line or line.startswith('$'):
            continue
        if line[0] == '#':
            now = int(line[1:])
            continue
        if line[0] in 'bB':
            value, code = line[1:].split()
        else:
            value, code = line[0], line[1:]
        for bits in names.get(code, []):
            value_bits = value.rjust(len(bits), '0' if value[0] in '01' else value[0])
            for bit, new in zip(bits, value_bits):
                if new not in '01':
                    raise ValueError(f'unknown value on {bit}')
                if bit in last and last[bit] != new:
                    counts[bit] = counts.get(bit, 0) + 1
                last[bit] = new
                counts.setdefault(bit, 0)
    if now <= 0:
        raise ValueError('activity file covers no time')
    return counts, now * scale


def expected_power(module, counts, duration_ns, contract):
    """Internal, switching and leakage power in watts for every instance."""
    cells, voltage = contract['cells'], contract['voltage']

    def density(net):                      # transitions per ns
        if net not in counts:
            raise ValueError(f'net {net} has no activity')
        return counts[net] / duration_ns

    load = {}
    for cell, pins in module['instances'].values():
        for pin, net in pins.items():
            if pin in cells[cell]['inputs']:
                load[net] = load.get(net, 0.0) + cells[cell]['inputs'][pin]['cap_pf']
    for port, direction in module['ports'].items():
        if direction == 'output':
            load[port] = load.get(port, 0.0) + contract['output_load_pf']
    result = {}
    for instance, (cell, pins) in module['instances'].items():
        if set(pins) != set(cells[cell]['inputs']) | set(cells[cell]['outputs']):
            raise ValueError(f'pins of {instance} differ from the cell {cell}')
        internal = sum(item.get('energy_pj', 0.0) * density(pins[pin]) for pin, item in cells[cell]['inputs'].items())
        internal += sum(item['energy_pj'] * density(pins[pin]) for pin, item in cells[cell]['outputs'].items())
        switching = sum(0.5 * load.get(pins[pin], 0.0) * voltage ** 2 * density(pins[pin]) for pin in cells[cell]['outputs'])
        # pJ/ns is mW; leakage is given in nW.
        result[instance] = dict(internal=internal * 1e-3, switching=switching * 1e-3, leakage=cells[cell]['leakage_nw'] * 1e-9)
    return result


def total(power):
    return sum(sum(row[key] for key in ('internal', 'switching', 'leakage')) for row in power.values())

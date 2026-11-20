"""Structural clock and reset domain crossings of a flattened Yosys netlist (JSON).

A teaching checker: it reads flops, their clocks and asynchronous resets, lists every crossing
and classifies it with six rules. It is not a replacement for a static CDC/RDC sign-off tool.
"""
from collections import defaultdict
import hashlib
import re

RULES = ('NO_SYNC', 'COMB_BEFORE_SYNC', 'FANOUT_BEFORE_SYNC', 'RECONVERGENCE', 'MULTIBIT_SEPARATE_SYNC',
         'RESET_RELEASE')
FLOP = re.compile(r'^\$_(DFF|DFFE|SDFF|SDFFE|SDFFCE)_[NP01]+_$')
SEQUENTIAL = re.compile(r'DFF|LATCH|\$_SR_|\$sr|\$mem|\$ff|\$_FF_', re.I)
TRANSPARENT = ('$_NOT_', '$_BUF_')
SYNTHESIS = ('read_verilog -sv {source}; {parameters}hierarchy -check -top {top}; proc; flatten; opt_expr; opt_clean; '
             'memory_map; opt_expr; opt_dff; opt_clean; simplemap; opt_expr; opt_clean; write_json {json}')


class Unsupported(ValueError):
    """The netlist or its description has something this checker does not understand."""


def base_name(name):
    """`rsync[1][2]` and `rsync[0]` belong to `rsync`."""
    return re.sub(r'(\[\d+\])+$', '', name)


def synthesis_script(source, top, parameters, json_name):
    chosen = ''.join(f'chparam -set {key} {value} {top}; ' for key, value in sorted(parameters.items()))
    return SYNTHESIS.format(source=source, top=top, parameters=chosen, json=json_name)


class Netlist:
    def __init__(self, data, top, target):
        if top not in data.get('modules', {}):
            raise Unsupported(f'top module {top} is not in the netlist')
        if len(data['modules']) != 1:
            raise Unsupported('the netlist is not flat')
        module = data['modules'][top]
        self.cells = module['cells']
        self.target = target
        self.clocks = list(target['clocks'])
        self.resets = dict(target.get('resets', {}))
        self.inputs = dict(target.get('inputs', {}))
        self.outputs = dict(target.get('outputs', {}))
        self.port_in, self.port_out, self.driver, self.loads = {}, {}, {}, defaultdict(list)
        declared = set(self.clocks) | set(self.resets) | set(self.inputs)
        for name, port in module['ports'].items():
            wide = len(port['bits']) > 1
            for index, bit in enumerate(port['bits']):
                label = f'{name}[{index}]' if wide else name
                if port['direction'] == 'input':
                    if name not in declared:
                        raise Unsupported(f'input port {name} has no declared domain')
                    self.port_in[bit] = (name, label)
                elif port['direction'] == 'output':
                    if name not in self.outputs:
                        raise Unsupported(f'output port {name} has no declared domain')
                    self.port_out[label] = (name, bit)
                    if not isinstance(bit, str):
                        self.loads[bit].append(('port', label))
                else:
                    raise Unsupported(f'port {name} is neither an input nor an output')
        missing = (declared | set(self.outputs)) - set(module['ports'])
        if missing:
            raise Unsupported('declared ports are not in the netlist: ' + ', '.join(sorted(missing)))
        ports = set(module['ports'])
        names = {}
        for name, net in module['netnames'].items():
            if net['hide_name']:
                continue
            wide = len(net['bits']) > 1
            for index, bit in enumerate(net['bits']):
                label = f'{name}[{index}]' if wide else name
                rank = (name in ports, len(label), label)
                if bit not in names or rank < names[bit][0]:
                    names[bit] = (rank, label)
        self.names = {bit: label for bit, (_, label) in names.items()}
        self.flops = {}
        for name, cell in self.cells.items():
            kind = FLOP.match(cell['type'])
            if not kind and SEQUENTIAL.search(cell['type']):
                raise Unsupported(f"sequential cell {cell['type']} is not supported")
            for port, bits in cell['connections'].items():
                direction = cell['port_directions'][port]
                for bit in bits:
                    if isinstance(bit, str):
                        continue
                    if direction == 'output':
                        if bit in self.driver or bit in self.port_in:
                            raise Unsupported('a net has more than one driver')
                        self.driver[bit] = name
                    else:
                        self.loads[bit].append((name, port))
            if kind:
                pins = {port: bits[0] for port, bits in cell['connections'].items()}
                self.flops[name] = dict(pins=pins, asynchronous=kind.group(1) in ('DFF', 'DFFE') and 'R' in pins)
        for name, flop in self.flops.items():
            root = self.through(flop['pins']['C'])
            port = self.port_in.get(root)
            if port is None or port[0] not in self.clocks:
                raise Unsupported(f'clock of {self.flop_name(name)} is not a declared clock port')
            flop['domain'] = port[0]
            flop['name'] = self.flop_name(name)
        if len({flop['name'] for flop in self.flops.values()}) != len(self.flops):
            raise Unsupported('two flops share one name')
        self._cones = {}

    def flop_name(self, cell):
        bit = self.cells[cell]['connections']['Q'][0]
        return self.names.get(bit, cell)

    def through(self, bit):
        """Follow inverters and buffers back to what really drives the net."""
        while not isinstance(bit, str) and bit in self.driver and self.cells[self.driver[bit]]['type'] in TRANSPARENT:
            bit = self.cells[self.driver[bit]]['connections']['A'][0]
        return bit

    def final_loads(self, bit):
        """Loads of a net, looking through inverters and buffers."""
        found = []
        for cell, port in self.loads.get(bit, []):
            if cell != 'port' and self.cells[cell]['type'] in TRANSPARENT:
                found += self.final_loads(self.cells[cell]['connections']['Y'][0])
            else:
                found.append((cell, port))
        return found

    def cone(self, bit):
        """Sources (flops and input ports) of the combinational cone of a net, and its number of gates."""
        if bit in self._cones:
            return self._cones[bit]
        sources, gates, seen, stack = set(), 0, set(), [bit]
        while stack:
            current = stack.pop()
            if isinstance(current, str) or current in seen:
                continue
            seen.add(current)
            if current in self.port_in:
                sources.add(('port', self.port_in[current][1]))
                continue
            cell = self.driver.get(current)
            if cell is None:
                raise Unsupported('a net in a cone has no driver')
            if cell in self.flops:
                sources.add(('flop', cell))
                continue
            gates += self.cells[cell]['type'] not in TRANSPARENT
            for port, bits in self.cells[cell]['connections'].items():
                if self.cells[cell]['port_directions'][port] == 'input':
                    stack.extend(bits)
        self._cones[bit] = (frozenset(sources), gates)
        return self._cones[bit]

    def describe(self, source):
        """Name, domain and synchronised-from domain of a source."""
        if source[0] == 'flop':
            flop = self.flops[source[1]]
            return flop['name'], flop['domain'], None
        port = re.sub(r'\[\d+\]$', '', source[1])
        where = self.resets.get(port, self.inputs.get(port))
        if port in self.clocks:
            raise Unsupported(f'clock {port} is used as data')
        if isinstance(where, dict):  # already synchronised outside this module
            return source[1], where['synchronized_into'], where['from']
        if where != 'async' and where != 'static' and where not in self.clocks:
            raise Unsupported(f'port {port} is declared in unknown domain {where}')
        return source[1], where, None


def analyze(data, top, target, disabled=()):
    """Flops, synchronisers, crossings and findings. `disabled` switches rules off (to test the checker)."""
    unknown = set(disabled) - set(RULES)
    if unknown:
        raise Unsupported('unknown rules: ' + ', '.join(sorted(unknown)))
    net = Netlist(data, top, target)
    flops = net.flops
    findings = defaultdict(lambda: dict(sources=set(), sinks=set(), bits=0))

    def report(rule, sources, sinks, bits=1):
        if rule in disabled:
            return
        key = (rule, tuple(sorted({base_name(s) for s in sources})), tuple(sorted({base_name(s) for s in sinks})))
        findings[key]['bits'] += bits

    # What each flop takes in: data cone, and the cones of enable and synchronous reset.
    for name, flop in flops.items():
        pins = flop['pins']
        data_sources, gates = net.cone(pins['D'])
        control = set()
        for pin in ('E',) + (() if flop['asynchronous'] else ('R',)):
            if pin in pins:
                control |= net.cone(pins[pin])[0]
        flop.update(data=data_sources, gates=gates, control=control)
        flop['foreign'] = {s for s in data_sources | control
                           if net.describe(s)[1] not in (flop['domain'], 'static')}

    def next_stage(name):
        loads = net.final_loads(flops[name]['pins']['Q'])
        if len(loads) != 1 or loads[0][0] not in flops or loads[0][1] != 'D':
            return None
        following = flops[loads[0][0]]
        if following['domain'] != flops[name]['domain'] or following['gates'] or following['foreign']:
            return None
        return loads[0][0]

    crossings = defaultdict(int)
    chains = []       # (source, [stage flops])
    receivers = defaultdict(set)   # source -> receiving flops
    for name, flop in sorted(flops.items(), key=lambda item: item[1]['name']):
        if not flop['foreign']:
            continue
        following = next_stage(name)
        direct = (len(flop['foreign']) == 1 and flop['data'] == flop['foreign'] and not flop['gates'] and
                  not (flop['control'] & flop['foreign']))
        kind = 'synchronized' if direct and following else 'unsynchronized'
        for source in flop['foreign']:
            source_name, source_domain, _ = net.describe(source)
            crossings[(base_name(source_name), source_domain, base_name(flop['name']), flop['domain'], kind)] += 1
            receivers[(source, flop['domain'])].add(name)
        if direct and following:
            stages = [name]
            while following and following not in stages:
                stages.append(following)
                following = next_stage(following)
            chains.append((next(iter(flop['foreign'])), stages))
        else:
            names = [net.describe(s)[0] for s in flop['foreign']]
            report('COMB_BEFORE_SYNC' if following else 'NO_SYNC', names, [flop['name']])
    # Output ports that take a signal of another domain without any flop.
    for label, (port, bit) in sorted(net.port_out.items()):
        domain = net.outputs[port]
        if domain not in net.clocks:
            raise Unsupported(f'output port {port} is declared in unknown domain {domain}')
        foreign = [] if isinstance(bit, str) else [s for s in net.cone(bit)[0] if net.describe(s)[1] not in (domain, 'static')]
        for source in foreign:
            source_name, source_domain, _ = net.describe(source)
            crossings[(base_name(source_name), source_domain, base_name(label), domain, 'unsynchronized')] += 1
        if foreign:
            report('NO_SYNC', [net.describe(s)[0] for s in foreign], [label])
    # One source bit that goes to several receiving flops of one domain.
    # A declared reset port fans out by nature: its release is judged by RESET_RELEASE and NO_SYNC.
    for (source, _), sinks in sorted(receivers.items(), key=lambda item: (net.describe(item[0][0])[0], item[0][1])):
        is_reset = source[0] == 'port' and re.sub(r'\[\d+\]$', '', source[1]) in net.resets
        if len(sinks) > 1 and not is_reset:
            report('FANOUT_BEFORE_SYNC', [net.describe(source)[0]], [flops[s]['name'] for s in sinks])
    # Bits of one bus, each with its own synchroniser.
    buses = defaultdict(dict)
    for source, stages in chains:
        source_name, source_domain, _ = net.describe(source)
        buses[(base_name(source_name), source_domain, flops[stages[0]]['domain'])].setdefault(source, []).append(stages)
    for (source_name, _, _), group in sorted(buses.items()):
        if len(group) > 1:    # distinct bits of the bus; one bit sent twice is FANOUT_BEFORE_SYNC
            report('MULTIBIT_SEPARATE_SYNC', [source_name],
                   [flops[stages[0]]['name'] for chains_of_bit in group.values() for stages in chains_of_bit], len(group))
    # Synchronised signals that meet again in one cone.
    synchronized = {('flop', stages[-1]): net.describe(source)[1] for source, stages in chains}

    def meeting(sources, domain):
        groups = defaultdict(set)
        for source in sources:
            name, where, origin = net.describe(source)
            if source in synchronized and where == domain:
                groups[synchronized[source]].add(name)
            elif origin is not None and where == domain:
                groups[origin].add(name)
        return [names for names in groups.values() if len(names) > 1]
    for name, flop in sorted(flops.items(), key=lambda item: item[1]['name']):
        for names in meeting(flop['data'] | flop['control'], flop['domain']):
            report('RECONVERGENCE', names, [flop['name']])
    for label, (port, bit) in sorted(net.port_out.items()):
        if not isinstance(bit, str):
            for names in meeting(net.cone(bit)[0], net.outputs[port]):
                report('RECONVERGENCE', names, [label])
    # Asynchronous resets: the release must come from the flop's own domain, through two stages.
    reset_cones = {name: net.cone(flop['pins']['R'])[0] for name, flop in flops.items() if flop['asynchronous']}

    def reset_stage(name, depth=0):
        """How many stages of a reset synchroniser end in this flop: 0 when it is not one."""
        flop = flops[name]
        if not flop['asynchronous'] or flop['gates'] or flop['control'] or depth > len(flops):
            return 0
        if not flop['data']:
            return 1 if net.through(flop['pins']['D']) in ('0', '1') else 0
        if len(flop['data']) != 1:
            return 0
        kind, previous = next(iter(flop['data']))
        if kind != 'flop' or flops[previous]['domain'] != flop['domain'] or \
                reset_cones.get(previous) != reset_cones[name]:
            return 0
        before = reset_stage(previous, depth + 1)
        return before + 1 if before else 0
    for name, flop in sorted(flops.items(), key=lambda item: item[1]['name']):
        if not flop['asynchronous']:
            continue
        for source in reset_cones[name]:
            source_name, source_domain, _ = net.describe(source)
            if source[0] == 'flop':
                same = source_domain == flop['domain']
                stages = reset_stage(source[1])
                ok = same and stages != 1    # a single stage can still pass on a metastable release
            else:
                ok = source_domain == flop['domain'] or (source_domain == 'async' and reset_stage(name))
            if not ok:
                report('RESET_RELEASE', [source_name], [flop['name']])
    domains = defaultdict(int)
    for flop in flops.values():
        domains[flop['domain']] += 1
    return dict(
        flops=dict(sorted(domains.items())),
        asynchronous_reset_flops=sum(flop['asynchronous'] for flop in flops.values()),
        synchronizers=sorted(
            (dict(source=name, source_domain=source_domain, sink=sink, sink_domain=sink_domain,
                  bits=sum(1 for _ in group), stages=stages)
             for (name, source_domain, sink, sink_domain, stages), group in _grouped(net, chains).items()),
            key=lambda row: (row['source'], row['sink'])),
        crossings=[dict(source=s, source_domain=sd, sink=t, sink_domain=td, kind=kind, paths=count)
                   for (s, sd, t, td, kind), count in sorted(crossings.items())],
        findings=[dict(rule=rule, sources=list(sources), sinks=list(sinks), bits=value['bits'])
                  for (rule, sources, sinks), value in sorted(findings.items())])


def _grouped(net, chains):
    groups = defaultdict(list)
    for source, stages in chains:
        name, domain, _ = net.describe(source)
        first = net.flops[stages[0]]
        groups[(base_name(name), domain, base_name(first['name']), first['domain'], len(stages))].append(stages)
    return groups


def finding_key(finding):
    return f"{finding['rule']} {','.join(finding['sources'])}->{','.join(finding['sinks'])}"


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


DISPOSITIONS = ('waived', 'known-debt')


def apply_waivers(target_id, findings, waivers, hashes):
    """Split the findings of one target into excused and open ones.

    A waiver names its targets and findings, a reason, how it was reviewed, and the files whose
    SHA-256 it was reviewed against (`hashes` holds the current values). A waiver that is stale,
    incomplete, or lists a finding the target does not have, is an error."""
    errors, by_key = [], {}
    for waiver in waivers:
        if target_id not in waiver.get('targets', []):
            continue
        name = waiver.get('id', '?')
        missing = [field for field in ('id', 'findings', 'reason', 'review', 'expires', 'disposition')
                   if not waiver.get(field) or (isinstance(waiver[field], str) and not waiver[field].strip())]
        if missing:
            errors.append(f"waiver {name} lacks {', '.join(missing)}")
            continue
        if waiver['disposition'] not in DISPOSITIONS:
            errors.append(f"waiver {name} has unknown disposition {waiver['disposition']}")
            continue
        pinned = waiver['expires'].get('source_sha256') if isinstance(waiver['expires'], dict) else None
        if not isinstance(pinned, dict) or not pinned or not waiver['expires'].get('condition'):
            errors.append(f"waiver {name} has no expiry condition")
            continue
        stale = sorted(path for path, value in pinned.items() if hashes.get(path) != value)
        if stale:
            errors.append(f"waiver {name} expired: {', '.join(stale)} changed")
            continue
        for key in waiver['findings']:
            if key in by_key:
                errors.append(f"waivers {by_key[key][0]} and {name} both list {key}")
            by_key[key] = (name, waiver['disposition'])
    excused, remaining, used = [], [], set()
    for finding in findings:
        key = finding_key(finding)
        if key in by_key:
            excused.append(dict(finding, waiver=by_key[key][0], disposition=by_key[key][1]))
            used.add(key)
        else:
            remaining.append(finding)
    for key in sorted(set(by_key) - used):
        errors.append(f"waiver {by_key[key][0]} lists a finding the target does not have: {key}")
    return excused, remaining, errors

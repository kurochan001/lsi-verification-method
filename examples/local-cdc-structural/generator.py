"""Random designs built from crossing patterns whose findings are known by construction.

The expected flops, synchronisers and findings come from the pattern that was instantiated,
not from the checker. The checker reads the netlist Yosys makes from the generated Verilog."""
from collections import Counter
import random

CLOCKS = ('a_clk', 'b_clk', 'c_clk')
KINDS = ('good', 'local', 'no_sync', 'port', 'comb', 'fanout', 'reconverge', 'multibit', 'reset')
OPERATORS = ('&', '|', '^')


def generate(seed, blocks, top='cdc_random'):
    """Verilog text, the description the checker needs, and what it must report."""
    rng = random.Random(seed)
    ports, body = [], []
    inputs, outputs = {}, {}
    flops, findings, synchronizers = Counter(), [], []
    asynchronous = 0
    kinds = list(KINDS) + [rng.choice(KINDS) for _ in range(max(0, blocks - len(KINDS)))]
    rng.shuffle(kinds)
    kinds = kinds[:blocks]

    def port(direction, name, domain, width=1):
        ports.append(f"    {direction} wire {'[%d:0] ' % (width - 1) if width > 1 else ''}{name}")
        (inputs if direction == 'input' else outputs)[name] = domain

    def chain(name, stages, source, clock):
        """A synchroniser of `stages` flops called `name`, taking `source` directly."""
        body.append(f'    reg [{stages - 1}:0] {name};')
        shifted = f'{name}[{stages - 2}:0]' if stages > 2 else f'{name}[0]'
        body.append(f'    always @(posedge {clock}) {name} <= {{{shifted}, {source}}};')
        flops[clock] += stages

    for index, kind in enumerate(kinds):
        x, y = rng.sample(CLOCKS, 2)
        stages = rng.choice((2, 2, 3))
        # The first plain synchroniser always sits behind an inverter, so every design has such a path.
        invert = '~' if rng.random() < 0.3 or (kind == 'good' and 'good' not in kinds[:index]) else ''
        operator = rng.choice(OPERATORS)
        s, o = f's{index}', f'o{index}'
        body.append(f'    // block {index}: {kind}, {x} to {y}')
        if kind == 'good':
            port('input', f'i{index}', x)
            port('output', o, y)
            body.append(f'    reg {s};')
            body.append(f'    always @(posedge {x}) {s} <= i{index};')
            flops[x] += 1
            chain(f'g{index}', stages, invert + s, y)
            body.append(f'    assign {o} = g{index}[{stages - 1}];')
            synchronizers.append(dict(source=s, sink=f'g{index}', bits=1, stages=stages))
        elif kind == 'local':
            port('input', f'i{index}', x)
            port('output', o, x)
            body.append(f'    reg [1:0] l{index};')
            body.append(f'    always @(posedge {x}) l{index} <= {{l{index}[0] {operator} i{index}, i{index}}};')
            body.append(f'    assign {o} = l{index}[1];')
            flops[x] += 2
        elif kind == 'no_sync':
            port('input', f'i{index}', x)
            port('output', o, y)
            body.append(f'    reg {s}, r{index};')
            body.append(f'    always @(posedge {x}) {s} <= i{index};')
            body.append(f'    always @(posedge {y}) r{index} <= {invert}{s};')
            body.append(f'    assign {o} = r{index};')
            flops[x] += 1
            flops[y] += 1
            findings.append(dict(rule='NO_SYNC', sources=[s], sinks=[f'r{index}'], bits=1))
        elif kind == 'port':
            port('input', f'i{index}', x)
            port('output', o, y)
            body.append(f'    reg {s};')
            body.append(f'    always @(posedge {x}) {s} <= i{index};')
            body.append(f'    assign {o} = {invert}{s};')
            flops[x] += 1
            findings.append(dict(rule='NO_SYNC', sources=[s], sinks=[o], bits=1))
        elif kind == 'comb':
            port('input', f'i{index}', x, 2)
            port('output', o, y)
            body.append(f'    reg {s}a, {s}b;')
            body.append(f'    always @(posedge {x}) {{{s}a, {s}b}} <= i{index};')
            flops[x] += 2
            chain(f'm{index}', stages, f'({s}a {operator} {s}b)', y)
            body.append(f'    assign {o} = m{index}[{stages - 1}];')
            findings.append(dict(rule='COMB_BEFORE_SYNC', sources=[f'{s}a', f'{s}b'], sinks=[f'm{index}'], bits=1))
        elif kind == 'fanout':
            port('input', f'i{index}', x)
            port('output', o, y, 2)
            body.append(f'    reg {s};')
            body.append(f'    always @(posedge {x}) {s} <= i{index};')
            flops[x] += 1
            chain(f'p{index}', stages, s, y)
            chain(f'q{index}', 2, invert + s, y)
            body.append(f'    assign {o} = {{p{index}[{stages - 1}], q{index}[1]}};')
            synchronizers += [dict(source=s, sink=f'p{index}', bits=1, stages=stages),
                              dict(source=s, sink=f'q{index}', bits=1, stages=2)]
            findings.append(dict(rule='FANOUT_BEFORE_SYNC', sources=[s], sinks=[f'p{index}', f'q{index}'], bits=1))
        elif kind == 'reconverge':
            port('input', f'i{index}', x, 2)
            port('output', o, y)
            body.append(f'    reg {s}a, {s}b, v{index};')
            body.append(f'    always @(posedge {x}) {{{s}a, {s}b}} <= i{index};')
            flops[x] += 2
            chain(f'p{index}', stages, f'{s}a', y)
            chain(f'q{index}', 2, f'{invert}{s}b', y)
            body.append(f'    always @(posedge {y}) v{index} <= p{index}[{stages - 1}] {operator} q{index}[1];')
            body.append(f'    assign {o} = v{index};')
            flops[y] += 1
            synchronizers += [dict(source=f'{s}a', sink=f'p{index}', bits=1, stages=stages),
                              dict(source=f'{s}b', sink=f'q{index}', bits=1, stages=2)]
            findings.append(dict(rule='RECONVERGENCE', sources=[f'p{index}', f'q{index}'], sinks=[f'v{index}'], bits=1))
        elif kind == 'multibit':
            width = rng.randrange(2, 5)
            port('input', f'i{index}', x, width)
            port('output', o, y, width)
            body.append(f'    reg [{width - 1}:0] {s}, m{index}, n{index};')
            body.append(f'    always @(posedge {x}) {s} <= i{index};')
            body.append(f'    always @(posedge {y}) begin m{index} <= {invert}{s}; n{index} <= m{index}; end')
            body.append(f'    assign {o} = n{index};')
            flops[x] += width
            flops[y] += 2 * width
            synchronizers.append(dict(source=s, sink=f'm{index}', bits=width, stages=2))
            findings.append(dict(rule='MULTIBIT_SEPARATE_SYNC', sources=[s], sinks=[f'm{index}'], bits=width))
        elif kind == 'reset':
            port('input', f'i{index}', y)
            port('output', o, y)
            body.append(f'    reg z{index};')
            body.append(f'    always @(posedge {y} or negedge arst_n) if (!arst_n) z{index} <= 1\'b0; else z{index} <= i{index};')
            body.append(f'    assign {o} = z{index};')
            flops[y] += 1
            asynchronous += 1
            findings.append(dict(rule='RESET_RELEASE', sources=['arst_n'], sinks=[f'z{index}'], bits=1))
        else:
            raise ValueError(kind)
    resets = {'arst_n': 'async'} if asynchronous else {}
    head = [f'    input wire {clock}' for clock in CLOCKS] + [f'    input wire {name}' for name in resets]
    source = (f'// Generated by generator.py: seed {seed}, {blocks} blocks.\nmodule {top} (\n' + ',\n'.join(head + ports) +
              '\n);\n' + '\n'.join(body) + '\nendmodule\n')
    key = lambda row: (row['rule'], row['sources'], row['sinks'])
    return dict(
        source=source, kinds=dict(sorted(Counter(kinds).items())),
        target=dict(id=f'random-seed{seed}', top=top, parameters={}, clocks=list(CLOCKS), resets=resets,
                    inputs=inputs, outputs=outputs),
        expected=dict(flops={clock: flops[clock] for clock in sorted(flops) if flops[clock]},
                      asynchronous_reset_flops=asynchronous,
                      synchronizers=sorted(synchronizers, key=lambda row: (row['source'], row['sink'])),
                      findings=sorted(findings, key=key)))

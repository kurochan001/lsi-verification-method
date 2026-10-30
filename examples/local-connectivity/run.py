#!/usr/bin/env python3
"""SoC connectivity proved against a connection table, with black-box blocks and four wiring mutants."""
import importlib.util
from pathlib import Path
import sys
HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('connectivity_generate', HERE / 'generate.py')
G = importlib.util.module_from_spec(spec)
spec.loader.exec_module(G)
TOP = 'conn_check'
PARAMETER_MODULE = 'soc_probe'  # soc_top after flattening; it carries MUTATION
CONFIGS = {'soc': {}}
BOUND = 8
PROOF_DEPTH = 2  # one step of history for the registered CPU interrupt; depth 1 leaves its induction open
SOURCES = [HERE / 'rtl/soc_top.sv', HERE / 'ip_blackbox.sv', HERE / 'conn_check.sv', G.TABLE, HERE / 'generate.py']
SCOPE = ('Unbounded proof that every row of connectivity.csv holds for any behaviour of the eight '
         'black-box blocks. Block internals, clock quality and reset timing are out of scope.')
TABLE = G.rows()
FAILURES = {1: 'ap_irq1_timer', 2: 'ap_uart_rx_idle', 3: 'ap_pad3_gpio', 4: 'ap_rst'}


def properties(parameters, case):
    return G.names(TABLE)


def prepare(parameters, case):
    """Flatten soc_top over the black boxes, expose the block ports the table names, then read the checker."""
    settings = ''.join(f'chparam -set {k} {v} soc_top\n' for k, v in {**parameters, **case['parameters']}.items())
    exposed = ' '.join('w:' + p for p in G.probes(TABLE))
    return (f'read -formal -sv soc_top.sv ip_blackbox.sv\n{settings}hierarchy -top soc_top\nproc\nflatten\n'
            f'expose {exposed}\nrename soc_top {PARAMETER_MODULE}\nread -formal -sv conn_check.sv\n')


def plan(bound, demo_bug):
    def case(name, mode='prove', expect='PASS', mutation=0, category='normal', failure=None):
        return dict(id=name, mode=mode, expect=expect, depth=PROOF_DEPTH if mode == 'prove' else bound,
                    category=category, failure=failure, parameters=dict(MUTATION=mutation))
    return [case('connectivity-proof', mutation=demo_bug), case('scenario-cover', 'cover')] + [
        case(f'detect-mutation{m}', 'bmc', 'FAIL', m, 'mutation', FAILURES[m]) for m in range(1, 5)]


if __name__ == '__main__':
    spec = importlib.util.spec_from_file_location('formal_runner', HERE.parent / 'local-formal-common/runner.py')
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    sys.exit(m.main(sys.modules[__name__]))

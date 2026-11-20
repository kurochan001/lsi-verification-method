#!/usr/bin/env python3
"""Stuck-at and transition faults of six named nodes: exhaustive pattern search for a scan circuit.

A pattern is a scan-loaded state q (4 bits) and the primary input x (1 bit), 32 assignments.
  stuck-at:    one capture clock. The fault holds the node at 0 or 1.
  transition:  launch-on-capture, two clocks. The first clock moves the state from q to f(q);
               a slow node still shows its old value when the second clock captures.
"""
import json

SITES = 6
STUCK = tuple((site, value) for site in range(SITES) for value in (0, 1))
# (site, 1): slow to rise, the node is late when it goes from 0 to 1. (site, 0): slow to fall.
TRANSITION = tuple((site, to) for site in range(SITES) for to in (1, 0))
PATTERNS = tuple((q, x) for q in range(16) for x in range(2))
# State bits that each node depends on, directly or through other nodes.
CONE = {0: {0, 1}, 1: {2}, 2: {0, 1, 2}, 3: {1, 3}, 4: {0, 1, 2, 3}, 5: {0, 1, 3}}


def functional(q, x):
    """Next state without a fault, written from the specification and not from the node list."""
    q0, q1, q2, q3 = ((q >> i) & 1 for i in range(4))
    differ = q0 != q1
    gated = differ and (q2 or x)
    d0 = not (q1 and q3)
    d1 = differ
    d2 = gated != bool(q3)
    d3 = gated or (q3 and not q0 and not q1)
    return int(d0) | int(d1) << 1 | int(d2) << 2 | int(d3) << 3


def nodes(q, x, held=None):
    """Values of n0..n5. `held` = (site, value) keeps one node at a value, whatever its inputs."""
    def node(site, value):
        return held[1] if held and held[0] == site else value
    b = [(q >> i) & 1 for i in range(4)]
    n = [0] * SITES
    n[0] = node(0, b[0] ^ b[1])
    n[1] = node(1, b[2] | x)
    n[2] = node(2, n[0] & n[1])
    n[3] = node(3, 1 - (b[1] & b[3]))
    n[4] = node(4, n[2] ^ b[3])
    n[5] = node(5, (1 - b[0]) & (1 - b[1]) & b[3])
    return n


def capture(q, x, held=None):
    n = nodes(q, x, held)
    return n[3] | n[0] << 1 | n[4] << 2 | (n[2] | n[5]) << 3


def stuck_detects(q, x, fault):
    return capture(q, x, fault) != functional(q, x)


def launches(q, x, fault):
    """True when the launch clock moves the node in the direction that the fault slows down."""
    site, to = fault
    return nodes(q, x)[site] == 1 - to and nodes(functional(q, x), x)[site] == to


def transition_response(q, x, fault):
    """State after launch and capture when the slow node still shows its old value at the capture."""
    site, to = fault
    second = functional(q, x)
    return capture(second, x, (site, 1 - to)) if launches(q, x, fault) else functional(second, x)


def transition_detects(q, x, fault):
    return transition_response(q, x, fault) != functional(functional(q, x), x)


def hazard_free(q, x, fault):
    """False when the outcome depends on a glitch: the node keeps the value that the fault makes
    late, while state bits in its cone change. A pulse the other way would then come back late."""
    site, to = fault
    first, second = nodes(q, x)[site], nodes(functional(q, x), x)[site]
    changed = {i for i in range(4) if (q ^ functional(q, x)) >> i & 1}
    return not (first == second == to and changed & CONE[site])


def select(faults, detects):
    """Greedy cover: the pattern that detects most of the remaining faults, until none is left."""
    table = {p: {f for f in faults if detects(*p, f)} for p in PATTERNS}
    detectable = set().union(*table.values())
    remaining, chosen = set(detectable), []
    while remaining:
        best = max(PATTERNS, key=lambda p: len(table[p] & remaining))
        chosen.append(best)
        remaining -= table[best]
    return chosen, detectable


def untestable_reason(fault):
    """Why no launch-on-capture pattern detects a transition fault."""
    if not any(launches(*p, fault) for p in PATTERNS):
        return 'no-launch'       # no state q whose successor f(q) moves the node this way
    return 'not-observed'        # the node moves, but the old value gives the same captured state


def report():
    stuck_patterns, stuck_ok = select(STUCK, stuck_detects)
    robust = lambda q, x, f: transition_detects(q, x, f) and hazard_free(q, x, f)
    transition_patterns, transition_ok = select(TRANSITION, robust)
    return dict(
        assignments=len(PATTERNS),
        stuck=dict(faults=len(STUCK), detectable=len(stuck_ok), patterns=[list(p) for p in stuck_patterns],
                   undetectable=[list(f) for f in STUCK if f not in stuck_ok]),
        transition=dict(faults=len(TRANSITION), detectable=len(transition_ok),
                        patterns=[list(p) for p in transition_patterns],
                        undetectable=[dict(fault=list(f), reason=untestable_reason(f),
                                           stuck_at_detectable=(f[0], 1 - f[1]) in stuck_ok)
                                      for f in TRANSITION if f not in transition_ok]))


if __name__ == '__main__':
    print(json.dumps(report(), indent=2))
